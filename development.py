"""Run `python development.py` to open the local development dashboard."""
import argparse
import json
import os
import secrets
import sys
import subprocess
import threading
import webbrowser
from pathlib import Path

# Once installed, `python development.py` also works without activation.
if __name__ == '__main__':
    environment = Path(__file__).resolve().parent / '.venv'
    interpreter = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if interpreter.exists() and Path(sys.prefix).resolve() != environment.resolve():
        raise SystemExit(subprocess.call([str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]]))

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from corner.runner import OUTPUTS, RUNTIME, Runner, library
from corner.updater import installed_version

ROOT = Path(__file__).resolve().parent


def create_app(runner=None):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    runner = runner or Runner()
    token = secrets.token_urlsafe(32)
    app.config['RUNNER'] = runner
    app.config['CORNER_TOKEN'] = token
    app.config['INSTANCE'] = secrets.token_hex(12)

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            abort(403)
        if request.method == 'POST' and not secrets.compare_digest(request.headers.get('X-Corner-Token', ''), token):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; media-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/')
    def index():
        return render_template('index.html', token=token, version=installed_version())

    @app.get('/api/state')
    def state():
        return jsonify(runner.snapshot())

    @app.get('/api/health')
    def health():
        return jsonify(service='claudes-corner', version=installed_version(), instance=app.config['INSTANCE'])

    @app.get('/api/library')
    def videos():
        return jsonify([r for r in library() if not r.get('demo')])

    @app.post('/api/start')
    def start():
        data = request.get_json(silent=True) or {}
        try:
            browser, model = data.get('browser', 'chrome'), data.get('model', 'base')
            if browser not in ('chrome', 'msedge', 'chromium') or model not in ('tiny', 'base', 'small'):
                raise ValueError('Invalid browser or model.')
            if not isinstance(data.get('agent_mode', False), bool):
                raise ValueError('Invalid agent mode.')
            runner.start({'browser': browser, 'model': model, 'agent_mode': data.get('agent_mode', False)})
        except (ValueError, TypeError, OverflowError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True)

    @app.post('/api/stop')
    def stop():
        runner.stop_event.set()
        return jsonify(ok=True)

    @app.post('/api/retry')
    def retry():
        runner.retry_event.set()
        return jsonify(ok=True)

    @app.post('/api/react')
    def react():
        data = request.get_json(silent=True) or {}
        try:
            runner.acknowledge(data.get('key'), data.get('reaction', ''), data.get('feedback'))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True)

    @app.get('/api/sessions')
    def sessions():
        found = []
        for path in sorted(OUTPUTS.glob('*/session.json'), reverse=True):
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                found.append({'id': path.parent.name, 'count': len(saved['results']), 'demo': saved['config']['demo']})
            except (ValueError, KeyError, OSError):
                continue
        return jsonify(found)

    @app.get('/api/sessions/<run_id>')
    def session(run_id):
        if Path(run_id).name != run_id:
            abort(404)
        return send_from_directory(OUTPUTS / run_id, 'session.json')

    @app.get('/outputs/<path:filename>')
    def output(filename):
        return send_from_directory(OUTPUTS, filename)

    return app


def main():
    parser = argparse.ArgumentParser(description="Claude's Corner")
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    print(f"Claude's Corner: {url}\nPress Ctrl+C to shut down.")
    app = create_app()
    RUNTIME.mkdir(exist_ok=True)
    (RUNTIME / 'server.json').write_text(json.dumps({'url': url, 'token': app.config['CORNER_TOKEN'],
        'instance': app.config['INSTANCE'], 'pid': os.getpid()}), encoding='utf-8')
    if not args.no_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host='127.0.0.1', port=args.port, threads=4)
    finally:
        app.config['RUNNER'].stop_event.set()


if __name__ == '__main__':
    main()
