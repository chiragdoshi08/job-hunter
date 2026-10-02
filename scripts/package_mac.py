"""Package a built Mac app with working stop/restore launchers."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--output',required=True);p.add_argument('--work',required=True);a=p.parse_args()
app=Path(a.app).resolve();output=Path(a.output).resolve();work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=work) as tmp:
    folder=Path(tmp)/'Job Hunter';folder.mkdir()
    shutil.copytree(app,folder/'Job Hunter.app',symlinks=True)
    stop='''#!/bin/zsh
set -eu
cd "${0:A:h}"
'./Job Hunter.app/Contents/MacOS/Job Hunter' --stop
read '?Press Enter to close…'
'''
    restore='''#!/bin/zsh
set -eu
cd "${0:A:h}"
'./Job Hunter.app/Contents/MacOS/Job Hunter' --stop
print 'Existing data will be retained as a safety copy.'
read 'hunter_backup?Drag a Job Hunter backup ZIP here, then press Enter: '
hunter_backup=${(Q)hunter_backup}
hunter_backup=${hunter_backup% }
'./Job Hunter.app/Contents/MacOS/Job Hunter' --cli restore --file "$hunter_backup"
read '?Press Enter to close…'
'''
    for name,text in (('Stop Job Hunter.command',stop),('Restore Job Hunter.command',restore)):
        f=folder/name;f.write_text(text);f.chmod(0o755)
    (folder/'START HERE.txt').write_text('''Job Hunter 0.3.0 — Apple Silicon Mac

Open Job Hunter.app. In Agent setup, sign in with ChatGPT, check the connection,
upload your reviewed résumé PDF, save job preferences, and check browser/upload.
Then Start agent. Resolve login/MFA/CAPTCHA in its dedicated browser and Resume.
Review each application before filling and before submitting.

Keep your Mac awake and online. Closing the browser page does not stop the agent.
Use Pause all work in the app or Stop Job Hunter.command here.

This is an unsigned-by-Apple preview with an ad hoc verified signature.
If blocked, use macOS Privacy & Security > Open Anyway after verifying the
published checksum. Do not disable system security globally.

Individual employer workflows still require testing. Native Google Docs CVs
run automatically after you connect Drive and select a master and template.
Uploaded baseline PDFs stay unchanged. Optional Android ntfy alerts can be
enabled in Agent setup; keep your private topic secret.
No candidate data is included. Private data stays in your Application Support
folder. Back up from Settings before changing computers or upgrading.

Source, instructions and limitations: https://github.com/chiragdoshi08/job-hunter
''')
    shutil.copy2(Path(__file__).resolve().parents[1]/'THIRD-PARTY-NOTICES.md',folder/'THIRD-PARTY-NOTICES.md')
    shutil.copy2(Path(__file__).resolve().parents[1]/'LICENSE',folder/'LICENSE')
    subprocess.run(['codesign','--verify','--deep','--strict',str(folder/'Job Hunter.app')],check=True)
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(folder),str(output)],check=True)
print(output)
