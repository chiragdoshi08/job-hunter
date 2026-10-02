#!/usr/bin/env python3
import argparse,os,secrets,signal,subprocess,sys,time,urllib.request,json
from pathlib import Path
ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
if getattr(sys,'frozen',False):os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'browsers'))
os.chdir(ROOT);os.umask(0o077)
from hunter import db

def running():
    try:
        port=int((db.DATA/'port').read_text());pid=int((db.DATA/'server.pid').read_text())
        if os.name!='nt':os.kill(pid,0)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/health',timeout=1) as r:return port if json.load(r).get('service')=='job-hunter' else None
    except Exception:return None

def launch(open_browser=True):
    db.DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    port=running()
    if not port:
        child_env=os.environ.copy()
        if getattr(sys,'frozen',False):child_env['PYINSTALLER_RESET_ENVIRONMENT']='1'
        with (db.DATA/'server.log').open('a') as out:
            child=subprocess.Popen([sys.executable,'--serve'] if getattr(sys,'frozen',False) else [sys.executable,str(ROOT/'launch.py'),'--serve'],cwd=ROOT,env=child_env,stdout=out,stderr=out,start_new_session=os.name!='nt')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            time.sleep(.1);port=running()
            if port:break
            if child.poll() is not None:break
        if not port:raise RuntimeError('Job Hunter could not start. See data/server.log.')
    token=secrets.token_urlsafe(32);(db.DATA/'connect.request').write_text(token)
    for _ in range(40):
        if not (db.DATA/'connect.request').exists():break
        time.sleep(.1)
    url=f'http://127.0.0.1:{port}/connect?token={token}'
    if open_browser:__import__('webbrowser').open(url)
    else:return url
    print(f'Job Hunter is running at http://127.0.0.1:{port}. Closing this window does not stop it.')

def stop():
    if running():
        (db.DATA/'stop.request').write_text(secrets.token_urlsafe(32))
        for _ in range(1000):
            if not running():break
            time.sleep(.1)
        if running():raise RuntimeError('Job Hunter is still restoring a saved résumé or closing its browser. Wait before restarting or restoring a backup.')
        print('Job Hunter stopped. Your progress is saved.')
    else:print('Job Hunter is already stopped.')

if __name__=='__main__':
    if sys.argv[1:2]==['--cli']:
        sys.argv=[sys.argv[0],*sys.argv[2:]]
        try:
            from hunter.cli import main
            main()
        except Exception as e:
            print(db.dump({'error':str(e)}),file=sys.stderr);sys.exit(1)
        sys.exit(0)
    p=argparse.ArgumentParser();p.add_argument('--serve',action='store_true');p.add_argument('--stop',action='store_true');p.add_argument('--link',action='store_true');a=p.parse_args()
    if a.serve:
        from hunter.server import serve
        serve()
    elif a.stop:stop()
    elif a.link:print(launch(False))
    else:launch()
