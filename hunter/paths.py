"""Private runtime storage is separate from the distributable application."""
import os
import sys
from pathlib import Path


def data_directory(root):
    if os.environ.get('JOB_HUNTER_DATA'):
        return Path(os.environ['JOB_HUNTER_DATA']).expanduser().resolve()
    if (root / 'data' / 'shared.sqlite').exists():
        return root / 'data'
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return base / 'Job Hunter' / 'data'
