"""Fresh packaged launch, connection, browser upload and graceful stop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',required=True);a=p.parse_args();exe=str(Path(a.executable).resolve())
    with tempfile.TemporaryDirectory() as tmp:
        data=Path(tmp)/'data';env={**os.environ,'JOB_HUNTER_DATA':str(data)}
        try:
            r=subprocess.run([exe,'--link'],env=env,capture_output=True,text=True,timeout=90,check=True)
            url=next(line for line in r.stdout.splitlines() if line.startswith('http://127.0.0.1:'))
            import http.cookiejar
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),urllib.request.ProxyHandler({}))
            with opener.open(url,timeout=10) as response:assert response.status==200
            base=url.split('/connect?')[0]
            with opener.open(base+'/api/bootstrap') as response:boot=json.load(response)
            assert len(boot['identities'])==2
            request=urllib.request.Request(base+'/api/agent',data=json.dumps({'action':'browser-check','identity':'strategy'}).encode(),
              headers={'Content-Type':'application/json','Origin':base,'X-Hunter-CSRF':boot['csrf']},method='POST')
            opener.open(request,timeout=10).close()
            deadline=time.time()+60
            while time.time()<deadline:
                with opener.open(base+'/api/strategy/agent') as response:status=json.load(response)
                if status['browser_check'].get('ok'):break
                if status['browser_check'].get('message'):raise ValueError(status['browser_check']['message'])
                time.sleep(.5)
            else:raise ValueError('Bundled browser upload did not complete')
            assert status['browser_check']['upload'] is True
        finally:
            subprocess.run([exe,'--stop'],env=env,capture_output=True,timeout=120,check=True)
            deadline=time.time()+15
            while (data/'server.pid').exists() and time.time()<deadline:time.sleep(.1)
            assert not (data/'server.pid').exists(),'Packaged service did not stop'
    print('Packaged application launch, connection, browser upload and stop passed.')
if __name__=='__main__':main()
