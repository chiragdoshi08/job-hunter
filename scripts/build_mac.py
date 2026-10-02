"""Build from reviewed source plus independently downloaded official runtimes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

p=argparse.ArgumentParser();p.add_argument('--codex',required=True);p.add_argument('--browsers',required=True);p.add_argument('--dist',required=True);p.add_argument('--work',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name','Job Hunter','--osx-bundle-identifier','com.jobhunter.local',
 '--distpath',a.dist,'--workpath',a.work,'--specpath',a.work,
 '--add-data',str(root/'static')+':static','--add-data',str(root/'workflows')+':workflows',
 '--add-data',str(root/'THIRD-PARTY-NOTICES.md')+':.','--add-data',str(root/'docs')+':docs',
 '--collect-all','playwright','--collect-all','pypdf','--collect-submodules','hunter',str(root/'launch.py')]
env=os.environ.copy();env['PYINSTALLER_CONFIG_DIR']=str(Path(a.work).resolve()/'cache')
subprocess.run(command,cwd=root,check=True,env=env)
# Copy browser bundles intact after PyInstaller collection; preserve framework symlinks/signatures.
app=Path(a.dist)/'Job Hunter.app';frameworks=app/'Contents'/'Frameworks'
import shutil
resources=app/'Contents'/'Resources'
shutil.copytree(Path(a.browsers).resolve(),resources/'browsers',symlinks=True,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.links'))
(frameworks/'browsers').symlink_to('../Resources/browsers')
(frameworks/'bin').mkdir(exist_ok=True)
shutil.copy2(Path(a.codex).resolve(),frameworks/'bin'/'codex')
subprocess.run(['codesign','--force','--sign','-',str(frameworks/'bin'/'codex')],check=True)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
import plistlib
info=app/'Contents'/'Info.plist'
metadata=plistlib.loads(info.read_bytes());metadata['CFBundleShortVersionString']='0.2.0';metadata['CFBundleVersion']='2'
info.write_bytes(plistlib.dumps(metadata))
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
print(app)
