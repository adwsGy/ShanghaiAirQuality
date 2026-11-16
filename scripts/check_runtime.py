"""Check installation prerequisites without importing application dependencies."""
import re
import shutil
import subprocess
import sys


def check_runtime():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(
            f'Python 3.12 is required; this interpreter is {sys.version.split()[0]}. '
            'Select Python 3.12 with --python (Bash) or -Python (PowerShell). '
            'If .venv already exists, recreate it with Python 3.12.'
        )
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js 24 or newer is required. Install it and reopen your terminal.')
    try:
        result = subprocess.run([node, '--version'], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError('Cannot run Node.js. Check its installation and PATH.') from error
    version = result.stdout.strip()
    match = re.match(r'^v(\d+)\.', version)
    if not match or int(match[1]) < 24:
        raise RuntimeError(f'Node.js 24 or newer is required; found {version or "an unknown version"}.')
    if not (shutil.which('npm') or shutil.which('npm.cmd')):
        raise RuntimeError('npm is missing. Install Node.js with npm and reopen your terminal.')
    return f'Runtime ready: Python {sys.version.split()[0]}, Node.js {version}.'


if __name__ == '__main__':
    try:
        print(check_runtime())
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
