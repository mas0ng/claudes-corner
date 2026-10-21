"""Open Claude's Corner. development.py remains a compatible entry point."""
import os
import sys
import subprocess
from pathlib import Path

if __name__ == '__main__':
    env = Path(__file__).resolve().parent / '.venv'
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if python.exists() and Path(sys.prefix).resolve() != env.resolve():
        raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]]))
    from development import main
    main()
