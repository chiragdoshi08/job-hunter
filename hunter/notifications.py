"""Optional private phone alerts with durable delivery, deduplication and retry."""
import json
import os
import secrets
import threading
import time
import urllib.request
from . import db

SCHEMA='''CREATE TABLE IF NOT EXISTS notification_outbox(
 id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
 title TEXT NOT NULL, message TEXT NOT NULL, error TEXT);'''

def init():
    with db.tx() as c:c.executescript(SCHEMA)

def secret_path():return db.DATA/'phone-alerts.json'

def status():
    value=db.unpack(secret_path().read_text(),{}) if secret_path().exists() else {}
    return {'enabled':bool(value.get('enabled')), 'topic':value.get('topic',''),
            'subscribe_url':'https://ntfy.sh/'+value['topic'] if value.get('topic') else '',
            'pending':db.one("SELECT count(*) n FROM notification_outbox WHERE state='pending'")['n'],
            'failed':db.one("SELECT count(*) n FROM notification_outbox WHERE state='failed'")['n']}

def configure(enabled):
    value=db.unpack(secret_path().read_text(),{}) if secret_path().exists() else {}
    if enabled and not value.get('topic'):value['topic']='job-hunter-'+secrets.token_hex(20)
    value['enabled']=bool(enabled)
    path=secret_path();path.write_text(db.dump(value));os.chmod(path,0o600)
    # Never send historical alerts after the user changes the setting.
    with db.tx() as c:c.execute("UPDATE notification_outbox SET state='cancelled' WHERE state='pending'")
    return status()

def enqueue(key,title,message):
    if not status()['enabled']:return
    with db.tx() as c:
        c.execute('INSERT OR IGNORE INTO notification_outbox(id,event_key,created_at,state,title,message) VALUES(?,?,?,\'pending\',?,?)',
                  (db.uid(),key,db.now(),title,message))

def task_changed(identity,task):
    state=task['state'];kind=task['kind']
    if state=='waiting_user':title='Job Hunter needs your help';message='Open Job Hunter to resolve a saved step. Other eligible applications can continue.'
    elif state=='completed' and kind in ('prepare','fill','submit'):title='Job Hunter finished a step';message='Open Job Hunter to review the result and the next application step.'
    else:return
    # Deliberately omit names, employers, answers, documents and local addresses.
    key=db.digest([identity,task['id'],state,task.get('checkpoint') if state=='waiting_user' else kind])
    enqueue(key,title,message)

def deliver_once(opener=None,clock=time.time):
    config=db.unpack(secret_path().read_text(),{}) if secret_path().exists() else {}
    if not config.get('enabled'):return False
    item=db.one("SELECT * FROM notification_outbox WHERE state='pending' AND next_at<=? ORDER BY created_at LIMIT 1",(clock(),))
    if not item:return False
    request=urllib.request.Request('https://ntfy.sh/'+config['topic'],data=item['message'].encode(),method='POST',
       headers={'Title':item['title'],'Content-Type':'text/plain; charset=utf-8','Cache':'no','Priority':'default'})
    try:
        if opener is None:opener=urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        with opener(request,timeout=15) as response:
            if response.status!=200:raise OSError('Notification service refused the alert')
            result=json.load(response)
            if result.get('event')!='message' or result.get('topic')!=config['topic']:raise OSError('Notification delivery was not acknowledged')
        with db.tx() as c:c.execute("UPDATE notification_outbox SET state='sent',error=NULL,attempts=attempts+1 WHERE id=?",(item['id'],))
    except Exception:
        attempts=item['attempts']+1
        with db.tx() as c:c.execute('UPDATE notification_outbox SET state=?,attempts=?,next_at=?,error=? WHERE id=?',
             ('failed' if attempts>=6 else 'pending',attempts,clock()+min(3600,30*2**(attempts-1)),'Phone alert could not be delivered. Your saved work is unaffected.',item['id']))
    return True

class Notifier:
    def __init__(self):self.stopped=threading.Event()
    def start(self):threading.Thread(target=self.run,daemon=True,name='job-hunter-alerts').start()
    def stop(self):self.stopped.set()
    def run(self):
        while not self.stopped.is_set():
            try:deliver_once()
            except Exception:pass
            self.stopped.wait(2)
