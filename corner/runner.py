"""Continuous browser capture with optional per-video agent handoff."""
import copy
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from .media import short_id

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / 'outputs'
RUNTIME = ROOT / '.runtime'
FEED = 'https://www.youtube.com/shorts'

class Cancelled(Exception):
    pass

def browser_blocker(url):
    parsed = urlparse(url)
    if not parsed.hostname or (parsed.hostname in ('www.youtube.com', 'youtube.com', 'm.youtube.com') and (parsed.path.rstrip('/') == '/shorts' or short_id(url))):
        return None
    consent = parsed.hostname in ('consent.youtube.com', 'consent.google.com')
    return {'kind': 'consent' if consent else 'redirect', 'url': url,
            'title': 'YouTube needs your consent' if consent else 'YouTube needs your attention',
            'message': 'Review YouTube’s policies and choose your consent settings in the YouTube browser window. Complete any sign-in or verification there. Watching will resume when you return to Shorts.'}

def library():
    results = []
    for path in OUTPUTS.glob('*/session.json'):
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            results.extend({**r, 'run_id': path.parent.name} for r in saved.get('results', []))
        except (OSError, ValueError):
            continue
    return sorted(results, key=lambda r: (r.get('captured_at', r['run_id']), r.get('folder', '')), reverse=True)

class Runner:
    def __init__(self):
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.retry_event = threading.Event()
        self.reaction_event = threading.Event()
        self.state = {'running': False, 'status': 'Ready to watch.', 'results': [], 'events': [], 'run_id': None, 'blocker': None, 'pending_reaction': None}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, message):
        with self.lock:
            self.state['status'] = message
            self.state['events'].append({'time': datetime.now().strftime('%H:%M:%S'), 'message': message})
            self.state['events'] = self.state['events'][-50:]
        self.persist()

    def persist(self):
        with self.lock:
            if self.state['run_id']:
                path = OUTPUTS / self.state['run_id'] / 'session.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding='utf-8')
                temp.replace(path)

    def start(self, config):
        with self.lock:
            if self.state['running']:
                raise ValueError('Already watching. Stop the current session first.')
            self.stop_event.clear()
            self.retry_event.clear()
            self.reaction_event.clear()
            run_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
            self.state = {'running': True, 'status': 'Opening YouTube…', 'run_id': run_id, 'results': [], 'events': [], 'config': config, 'blocker': None, 'pending_reaction': None}
            threading.Thread(target=self.run, args=(config,), daemon=True).start()

    def check(self):
        if self.stop_event.is_set():
            raise Cancelled('Stopped.')

    def run_process(self, args, folder):
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'processing.log').open('w', encoding='utf-8') as log:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            process = subprocess.Popen([sys.executable, '-u', '-m', 'corner.process', *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=sys.platform != 'win32')
            try:
                while process.poll() is None:
                    self.check()
                    self.stop_event.wait(.25)
                self.check()
                if process.returncode:
                    tail = (folder / 'processing.log').read_text(encoding='utf-8', errors='replace')[-1200:]
                    raise RuntimeError('Could not process this video. ' + tail)
            finally:
                if process.poll() is None:
                    if sys.platform == 'win32':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=flags)
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        return json.loads((folder / 'result.json').read_text(encoding='utf-8'))

    def set_blocker(self, blocker):
        with self.lock:
            changed = self.state['blocker'] != blocker
            self.state['blocker'] = blocker
        if changed:
            self.update(blocker['title'] if blocker else 'Waiting for a Short…')

    def wait_for_short(self, page, seen):
        self.update('Waiting for a Short…')
        candidate, since, last_skip = None, 0, 0
        while True:
            self.check()
            if page.is_closed():
                raise RuntimeError('The YouTube window was closed. Press Stop, then Watch to reopen it.')
            if self.retry_event.is_set():
                self.retry_event.clear()
                page.goto(FEED, wait_until='domcontentloaded', timeout=30000)
            blocker = browser_blocker(page.url)
            self.set_blocker(blocker)
            video_id = short_id(page.url)
            if blocker:
                candidate = None
            elif video_id in seen and time.monotonic() - last_skip > 2:
                page.keyboard.press('ArrowDown')
                last_skip = time.monotonic()
            elif video_id and video_id not in seen:
                if candidate != video_id:
                    candidate, since = video_id, time.monotonic()
                elif time.monotonic() - since >= 1.5:
                    return f'https://www.youtube.com/shorts/{video_id}'
            else:
                candidate = None
            page.wait_for_timeout(250)

    def record(self, result, folder):
        result['folder'] = folder.relative_to(OUTPUTS).as_posix()
        result['captured_at'] = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.state['results'].append(result)
            if self.state['config'].get('agent_mode'):
                self.reaction_event.clear()
                self.state['pending_reaction'] = result['folder']
        self.update('Ready: ' + result['title'])

    def acknowledge(self, key, reaction):
        with self.lock:
            if not key or key != self.state['pending_reaction']:
                raise ValueError('This video is not waiting for a reaction.')
            if not isinstance(reaction, str) or not reaction.strip():
                raise ValueError('Write a reaction in chat, then provide the same text here.')
            result = next(r for r in self.state['results'] if r['folder'] == key)
            result['reaction'] = reaction.strip()
            (OUTPUTS / key / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
            self.state['pending_reaction'] = None
            self.persist()
            self.reaction_event.set()

    def run(self, config):
        session = OUTPUTS / self.state['run_id']
        cookies = RUNTIME / 'capture-cookies.txt'
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                RUNTIME.mkdir(exist_ok=True)
                browser_args = {'headless': False, 'viewport': None, 'args': ['--autoplay-policy=no-user-gesture-required'], 'timeout': 20000}
                context = None
                launch_errors = []
                for browser in dict.fromkeys([config['browser'], 'chrome', 'msedge', 'chromium']):
                    options = dict(browser_args)
                    if browser != 'chromium':
                        options['channel'] = browser
                    try:
                        context = playwright.chromium.launch_persistent_context(str(RUNTIME / 'browser-profile'), **options)
                        break
                    except Exception as exc:
                        self.check()
                        launch_errors.append(str(exc).split('Call log:')[0].strip())
                if context is None:
                    raise RuntimeError('No supported browser could open. Install Chrome or rerun python install.py. ' + ' / '.join(launch_errors))
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    seen = {r['id'] for r in library() if not r.get('demo')}
                    attempts = failures = 0
                    while True:
                        self.check()
                        attempts += 1
                        try:
                            self.update('Opening Shorts…')
                            page.goto(FEED, wait_until='domcontentloaded', timeout=30000)
                            url = self.wait_for_short(page, seen)
                            video_id = short_id(url)
                            seen.add(video_id)
                            folder = session / f'{attempts:04d}-{video_id}'
                            folder.mkdir(parents=True, exist_ok=True)
                            self.export_cookies(context, cookies)
                            self.update('Downloading and transcribing…')
                            result = self.run_process(['--url', url, '--folder', str(folder), '--model', config['model'], '--cookies', str(cookies)], folder)
                            self.record(result, folder)
                            failures = 0
                            if config.get('agent_mode'):
                                self.update('Waiting for your agent’s reaction…')
                                while not self.reaction_event.wait(.25):
                                    self.check()
                        except Cancelled:
                            raise
                        except Exception as exc:
                            if page.is_closed():
                                raise RuntimeError('The YouTube window was closed.') from exc
                            failures += 1
                            self.update(str(exc))
                            if self.stop_event.wait(min(60, 2 ** min(failures, 6))):
                                self.check()
                        finally:
                            cookies.unlink(missing_ok=True)
                finally:
                    context.close()
        except Cancelled as exc:
            self.update(str(exc))
        except Exception as exc:
            self.update(f'Unable to watch: {exc}')
        finally:
            cookies.unlink(missing_ok=True)
            with self.lock:
                self.state['running'] = False
                self.state['blocker'] = None
            self.persist()

    @staticmethod
    def export_cookies(context, path):
        rows = ['# Netscape HTTP Cookie File']
        for c in context.cookies(['https://www.youtube.com', 'https://youtube.com']):
            rows.append('\t'.join([c['domain'], 'TRUE' if c['domain'].startswith('.') else 'FALSE', c['path'], 'TRUE' if c['secure'] else 'FALSE', str(max(0, int(c.get('expires', 0)))), c['name'], c['value']]))
        path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
