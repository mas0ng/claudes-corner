"""Portable stdlib-only installer. Run with Python 3.12+ after cloning."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Install Claude’s Corner and its browser.')
    parser.add_argument('--skip-browser', action='store_true', help='Use an existing Chrome/Edge installation instead.')
    parser.add_argument('--no-update', action='store_true', help='Install this checkout without checking GitHub.')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit('Python 3.12 or newer is required.')
    from corner.updater import installed_version, update
    print(f'Claude’s Corner {installed_version()}', flush=True)
    if not args.no_update:
        try:
            print('Checking GitHub for a newer version…', flush=True)
            result = update()
            print(result['message'], flush=True)
            if result['status'] == 'updated':
                raise SystemExit(subprocess.call([sys.executable, str(ROOT / 'install.py'), '--no-update', *(['--skip-browser'] if args.skip_browser else [])]))
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f'Could not check for updates: {exc}\nKeeping this version and reusing installed files.', flush=True)
    env = ROOT / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    else:
        print('Reusing the existing environment. Already satisfied packages are not downloaded again.', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    if not args.skip_browser:
        print('Checking the browser installation; an existing matching browser is reused.', flush=True)
        subprocess.run([str(python), '-m', 'playwright', 'install', 'chromium'], check=True)
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    config = {'mcpServers': {'claudes-corner': {'command': str(python), 'args': [str(ROOT / 'mcp_server.py')]}}}
    (runtime / 'mcp-config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    print('\nInstalled. Open the app: python watch.py')
    print('Agent instructions: skills/claudes-corner/SKILL.md')
    print('Start with an agent: python corner_cli.py start')
    print('Optional MCP config: .runtime/mcp-config.json')


if __name__ == '__main__':
    main()
