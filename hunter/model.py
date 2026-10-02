"""Subscription-backed structured decisions; model output cannot execute shell code."""
import json
import os
import signal
import subprocess
import time
from . import db
from .worker import codex_binary, clean_env, auth_status


class Cancelled(Exception):pass


def decide(prompt,schema,folder,cancelled=lambda:False,event_callback=lambda event:None,timeout=180):
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    schema_file=folder/'schema.json';schema_file.write_text(db.dump(schema));output=folder/'result.json'
    command=[codex_binary(),'exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only',
       '-c','forced_login_method="chatgpt"','-c','web_search="disabled"','-c','features.shell_tool=false',
       '-c','features.apps=false','-c','features.plugins=false',
       '-c','features.multi_agent=false','-m',db.get_setting('model'),'--json','--output-schema',str(schema_file),'-o',str(output),'-']
    if not auth_status()['ok']:raise RuntimeError('Sign in with ChatGPT in Setup before starting the agent.')
    with (folder/'stderr.log').open('w') as err,(folder/'events.jsonl').open('w') as events:
        import selectors
        p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,cwd=folder,env=clean_env(),start_new_session=os.name!='nt')
        p.stdin.write(prompt);p.stdin.close();sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
        started=time.monotonic();complete=False
        try:
            while True:
                if cancelled():raise Cancelled()
                if time.monotonic()-started>timeout:raise RuntimeError('The model timed out. Your checkpoint is saved; resume to re-check the page.')
                if sel.select(.2):
                    line=p.stdout.readline()
                    if not line:
                        if p.poll() is not None:break
                        continue
                    events.write(line);events.flush()
                    try:event=json.loads(line)
                    except ValueError:continue
                    event_callback(event)
                    if event.get('type')=='turn.completed':complete=True
                elif p.poll() is not None:break
            if p.wait()!=0 or not complete or not output.exists():
                raise RuntimeError('ChatGPT could not complete this step. Check the account connection and usage in Setup; the saved page can be resumed.')
            result=json.loads(output.read_text())
            return result
        finally:
            sel.close()
            if p.poll() is None:
                if os.name=='nt':p.terminate()
                else:os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
