"""Private runtime storage is separate from the distributable application."""
import os
import sys
from pathlib import Path

_WINDOWS_SID=None

def secure_data(path):
    """Use OS-native access controls; chmod does not create a private Windows ACL."""
    global _WINDOWS_SID
    if os.name!='nt':
        path.chmod(0o700);return
    import csv,re,subprocess
    if _WINDOWS_SID is None:
        result=subprocess.run(['whoami','/user','/fo','csv','/nh'],capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        sid=next(csv.reader([result.stdout.strip()]))[-1]
        if not re.fullmatch(r'S-1-\d+(?:-\d+)+',sid):raise ValueError('Could not determine the private Windows account')
        _WINDOWS_SID=sid
    subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r','*'+_WINDOWS_SID+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],
       capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)


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
