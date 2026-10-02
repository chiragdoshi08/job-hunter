"""Sign and notarize a reviewed bundle with the owner's Apple credentials."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--identity',required=True);p.add_argument('--keychain-profile',required=True);a=p.parse_args()
    app=Path(a.app).resolve()
    if not app.is_dir() or app.suffix!='.app':raise ValueError('Choose the built Job Hunter.app')
    identities=subprocess.run(['security','find-identity','-v','-p','codesigning'],capture_output=True,text=True,check=True).stdout
    if a.identity not in identities or 'Developer ID Application' not in a.identity:raise ValueError('Install your Developer ID Application certificate in Keychain first')
    with tempfile.TemporaryDirectory() as tmp:
        entitlements=Path(tmp)/'entitlements.plist';entitlements.write_text('''<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>com.apple.security.cs.allow-jit</key><true/><key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/><key>com.apple.security.cs.disable-library-validation</key><true/></dict></plist>''')
        subprocess.run(['codesign','--force','--deep','--options','runtime','--timestamp','--entitlements',str(entitlements),'--sign',a.identity,str(app)],check=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        archive=Path(tmp)/'Job Hunter.zip';subprocess.run(['ditto','-c','-k','--keepParent',str(app),str(archive)],check=True)
        subprocess.run(['xcrun','notarytool','submit',str(archive),'--keychain-profile',a.keychain_profile,'--wait'],check=True)
        subprocess.run(['xcrun','stapler','staple',str(app)],check=True)
        subprocess.run(['xcrun','stapler','validate',str(app)],check=True)
        subprocess.run(['spctl','--assess','--type','execute',str(app)],check=True)
    print('Apple signature, notarization ticket and Gatekeeper assessment verified.')
if __name__=='__main__':main()
