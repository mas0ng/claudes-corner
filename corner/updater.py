"""Fast-forward updates from GitHub, preserving local work and captured media."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent

def version_tuple(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+', value.strip()):
        raise ValueError('Invalid version number: ' + value)
    return tuple(map(int, value.strip().split('.')))

def installed_version(root=ROOT):
    try:
        return (Path(root) / 'VERSION').read_text(encoding='utf-8-sig').strip()
    except FileNotFoundError:
        return '0.0.0'

def update(root=ROOT):
    root = Path(root)
    current = installed_version(root)
    def git(*args, check=True):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=60)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Git command failed.')
        return result
    if not (root / '.git').exists():
        return {'status': 'manual', 'version': current, 'message': 'Source ZIP detected. Use a Git clone for automatic updates; your installed files were kept.'}
    remote = git('remote', 'get-url', 'origin').stdout.strip().rstrip('/').removesuffix('.git').lower()
    if remote not in ('https://github.com/mas0ng/claudes-corner', 'git@github.com:mas0ng/claudes-corner', 'ssh://git@github.com/mas0ng/claudes-corner'):
        raise RuntimeError('Automatic updates require origin to point to mas0ng/claudes-corner on GitHub.')
    git('fetch', '--quiet', 'origin', 'main')
    marker = git('show', 'FETCH_HEAD:VERSION', check=False)
    if marker.returncode:
        return {'status': 'current', 'version': current, 'message': 'No versioned update is published yet.'}
    latest = marker.stdout.strip()
    if version_tuple(latest) <= version_tuple(current):
        return {'status': 'current', 'version': current, 'message': f'Version {current} is already up to date. Reusing installed files.'}
    if git('status', '--porcelain').stdout.strip():
        return {'status': 'local_changes', 'version': current, 'latest': latest,
                'message': f'Version {latest} is available. Commit or move your local changes, then run python install.py again. No files were overwritten.'}
    if git('merge-base', '--is-ancestor', 'HEAD', 'FETCH_HEAD', check=False).returncode:
        return {'status': 'diverged', 'version': current, 'latest': latest,
                'message': f'Version {latest} is available, but this checkout has separate history. Resolve it before updating; no files were overwritten.'}
    git('merge', '--ff-only', 'FETCH_HEAD')
    return {'status': 'updated', 'version': installed_version(root), 'previous': current,
            'message': f'Updated {current} to {latest}. Saved videos, browser state and cached models are kept.'}
