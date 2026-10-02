"""Build a bundled Windows application and a per-user Inno Setup installer."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

RUNTIMES={
 'codex-x86_64-pc-windows-msvc.exe':'fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d',
 'codex-windows-sandbox-service-x86_64-pc-windows-msvc.exe':'e74be3680418fad7deea5ef972cb04d058ccd165d0883622376a0c549fb044e5',
 'codex-windows-sandbox-setup-x86_64-pc-windows-msvc.exe':'8f91d62aca2aca87b0ebf446848b817720415dd3080905ffc3085c17b70bd57a'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--browsers',required=True);p.add_argument('--dist',required=True);p.add_argument('--work',required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--console','--name','Job Hunter',
       '--distpath',a.dist,'--workpath',str(work),'--specpath',str(work),
       '--add-data',str(root/'static')+';static','--add-data',str(root/'workflows')+';workflows',
       '--add-data',str(root/'docs')+';docs','--add-data',str(root/'THIRD-PARTY-NOTICES.md')+';.',
       '--collect-all','playwright','--collect-all','pypdf','--collect-all','pypdfium2','--collect-submodules','hunter',str(root/'launch.py')],check=True,cwd=root)
    bundle=Path(a.dist).resolve()/'Job Hunter';runtime=bundle/'_internal';(runtime/'bin').mkdir(exist_ok=True)
    # Auth and browser data are created on the user's computer, never bundled.
    for filename,expected in RUNTIMES.items():
        raw=urllib.request.urlopen('https://github.com/openai/codex/releases/download/rust-v0.160.0/'+filename,timeout=90).read()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Official runtime checksum mismatch: '+filename)
        destination='codex.exe' if filename.startswith('codex-x86') else filename.replace('-x86_64-pc-windows-msvc','')
        (runtime/'bin'/destination).write_bytes(raw)
    shutil.copytree(a.browsers,runtime/'browsers',dirs_exist_ok=True,ignore=shutil.ignore_patterns('.links'))
    shutil.copy2(root/'LICENSE',bundle/'LICENSE');shutil.copy2(root/'THIRD-PARTY-NOTICES.md',bundle/'THIRD-PARTY-NOTICES.md')
    compiler=Path(r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe')
    subprocess.run([str(compiler),'/DAppSource='+str(bundle),'/DAppOutput='+str(Path(a.dist).resolve()),str(root/'scripts'/'windows-installer.iss')],check=True)
    print(bundle)
if __name__=='__main__':main()
