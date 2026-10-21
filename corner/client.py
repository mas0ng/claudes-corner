"""Shared localhost client for CLI and MCP. Never log the local control token."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from .runner import ROOT, RUNTIME, OUTPUTS


class Client:
    def __init__(self, autostart=True):
        self.connection = None
        self.autostart = autostart

    def connect(self):
        try:
            connection = json.loads((RUNTIME / 'server.json').read_text(encoding='utf-8'))
            # Descriptor is local state, but validate before forwarding a control token.
            from urllib.parse import urlparse
            url = urlparse(connection['url'])
            if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port:
                raise ValueError('Invalid local server address.')
            with urllib.request.urlopen(connection['url'] + '/api/health', timeout=2) as response:
                health = json.load(response)
            if health.get('instance') != connection['instance'] or health.get('service') != 'claudes-corner':
                raise ValueError('Stale server connection.')
            self.connection = connection
            return
        except (OSError, ValueError, KeyError):
            if not self.autostart:
                raise RuntimeError('Claude’s Corner is not running.') from None
        RUNTIME.mkdir(exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with (RUNTIME / 'server.log').open('a', encoding='utf-8') as log:
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
            subprocess.Popen([sys.executable, str(ROOT / 'watch.py'), '--port', str(port), '--no-open'],
                cwd=ROOT, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                creationflags=flags, start_new_session=os.name != 'nt')
        self.autostart = False
        for _ in range(60):
            try:
                self.connect()
                return
            except RuntimeError:
                time.sleep(.25)
        raise RuntimeError('Server did not start. Check .runtime/server.log.')

    def request(self, path, data=None):
        if not self.connection:
            self.connect()
        headers = {'X-Corner-Token': self.connection['token']}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.connection['url'] + path,
                    data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                message = json.load(exc).get('error', str(exc))
            except ValueError:
                message = str(exc)
            raise RuntimeError(message) from None

    def start(self, browser='chromium', model='base', auto_like=True):
        state = self.request('/api/state')
        if state['running']:
            if not state.get('config', {}).get('agent_mode'):
                raise RuntimeError('A manual session is running. Stop it before starting agent watching.')
        else:
            self.request('/api/start', {'browser': browser, 'model': model, 'agent_mode': True, 'auto_like': auto_like})
        return {'status': 'watching', 'dashboard': self.connection['url'],
                'auto_like': state.get('config', {}).get('auto_like', True) if state['running'] else auto_like,
                'instruction': 'Call next, inspect all five images and transcript, react in chat, then acknowledge with that reaction and feedback: rating 1–5, would_like, would_comment, and suggested comment. Repeat until stopped.'}

    def next(self, wait=25):
        until = time.monotonic() + max(0, min(float(wait), 50))
        while True:
            state = self.request('/api/state')
            if state.get('blocker'):
                return {'status': 'needs_attention', 'blocker': state['blocker'], 'dashboard': self.connection['url']}
            if not state['running']:
                return {'status': 'stopped', 'message': state['status']}
            key = state.get('pending_reaction')
            if key:
                result = next(r for r in state['results'] if r['folder'] == key)
                folder = (OUTPUTS / key).resolve()
                if not folder.is_relative_to(OUTPUTS.resolve()):
                    raise RuntimeError('Invalid result folder.')
                images = []
                for frame in result['frames']:
                    path = (folder / frame['file']).resolve()
                    if not path.is_relative_to(folder):
                        raise RuntimeError('Invalid frame path.')
                    images.append({'path': str(path), 'time': frame['time']})
                return {'status': 'video', 'key': key, 'video': result, 'images': images,
                        'instruction': 'Read the transcript and inspect all five images. React in chat, then acknowledge with the same text and feedback: {rating: integer 1–5, would_like: boolean, would_comment: boolean, comment: string}. Comment must be nonempty only when would_comment is true. When automatic likes are enabled, would_like=true triggers a real YouTube like in the watching browser. Comments stay drafts and are never posted.'}
            if time.monotonic() >= until:
                return {'status': 'waiting', 'message': state['status'], 'instruction': 'Call next again. Keep the watching turn active until the user stops.'}
            time.sleep(.5)

    def react(self, key, reaction, feedback=None):
        return self.request('/api/react', {'key': key, 'reaction': reaction, 'feedback': feedback})
