"""Exercise real Git fast-forward updates against a local fixture remote."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from corner.updater import update, version_tuple


class UpdateTests(unittest.TestCase):
    def test_numeric_versions(self):
        self.assertGreater(version_tuple('1.10.0'), version_tuple('1.9.9'))
        with self.assertRaises(ValueError):
            version_tuple('not-a-version')

    def test_update_reuses_files_and_preserves_local_changes(self):
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, checkout = root / 'source', root / 'checkout'
            source.mkdir()
            def git(cwd, *args):
                return real_run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True)
            git(source, 'init', '-b', 'main')
            (source / 'VERSION').write_text('1.0.0\n')
            (source / '.gitignore').write_text('outputs/\n')
            git(source, 'add', '.')
            git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Initial')
            git(root, 'clone', str(source), str(checkout))
            (checkout / 'outputs').mkdir()
            cached = checkout / 'outputs' / 'keep.txt'
            cached.write_text('saved video fixture')
            (source / 'VERSION').write_text('1.1.0\n')
            git(source, 'add', 'VERSION')
            git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Update')
            def run(args, **kwargs):
                if args == ['git', 'remote', 'get-url', 'origin']:
                    return subprocess.CompletedProcess(args, 0, 'https://github.com/mas0ng/claudes-corner.git\n', '')
                return real_run(args, **kwargs)
            with patch('corner.updater.subprocess.run', side_effect=run):
                result = update(checkout)
                self.assertEqual(result['status'], 'updated')
                self.assertEqual(result['version'], '1.1.0')
                self.assertEqual(cached.read_text(), 'saved video fixture')
                self.assertEqual(update(checkout)['status'], 'current')
                (source / 'VERSION').write_text('1.2.0\n')
                git(source, 'add', 'VERSION')
                git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Next update')
                (checkout / '.gitignore').write_text('outputs/\nlocal/\n')
                self.assertEqual(update(checkout)['status'], 'local_changes')
                self.assertEqual((checkout / 'VERSION').read_text(), '1.1.0\n')

    def test_zip_install_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'VERSION').write_text('1.1.0')
            self.assertEqual(update(temp)['status'], 'manual')
