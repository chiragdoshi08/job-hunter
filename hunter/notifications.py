"""Optional private phone alerts with durable delivery, deduplication and retry."""
import json
import os
import secrets
import re
import smtplib
import ssl
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
def configuration():return db.unpack(secret_path().read_text(),{}) if secret_path().exists() else {}

def status():
    value=configuration();email=value.get('email',{})
    return {'enabled':bool(value.get('enabled')), 'topic':value.get('topic',''),
            'channel':value.get('channel','ntfy'),
            'email':{k:email.get(k,'') for k in ('host','port','security','username','recipient')},
            'email_configured':bool(email.get('password')),
            'subscribe_url':'https://ntfy.sh/'+value['topic'] if value.get('topic') else '',
            'pending':db.one("SELECT count(*) n FROM notification_outbox WHERE state='pending'")['n'],
            'failed':db.one("SELECT count(*) n FROM notification_outbox WHERE state='failed'")['n'],
            'last_error':(db.one("SELECT error FROM notification_outbox WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 1") or {}).get('error')}

def configure(enabled,channel=None,email=None):
    value=configuration();channel=channel or value.get('channel','ntfy')
    if channel not in ('ntfy','email'):raise ValueError('Choose email or ntfy alerts')
    if channel=='email':
        old=value.get('email',{});email=email or {};settings={k:email.get(k,old.get(k,default)) for k,default in [('host','smtp.gmail.com'),('port',465),('security','ssl'),('username',''),('recipient','')]}
        settings={k:(str(v).strip() if k!='port' else int(v)) for k,v in settings.items()}
        if settings['security'] not in ('ssl','starttls') or settings['port'] not in (465,587):raise ValueError('Email alerts require TLS on port 465 or 587')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+',settings['host']):raise ValueError('Enter the mail provider’s SMTP hostname')
        for key in ('username','recipient'):
            if settings[key] and not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+',settings[key]):raise ValueError('Enter a valid '+('sender' if key=='username' else 'recipient')+' email address')
        same_account=all(settings[k]==old.get(k) for k in ('host','port','security','username'))
        password=email.get('password') or (old.get('password') if same_account else '') or ''
        if settings['host']=='smtp.gmail.com':password=''.join(password.split())
        if len(password)>1000 or '\r' in password or '\n' in password:raise ValueError('Enter the provider’s app password in the app password field')
        settings['password']=password
        if enabled and not all(settings[k] for k in ('username','recipient','password')):raise ValueError('Add the sender, recipient and app password before enabling email alerts')
        value['email']=settings
    if enabled and channel=='ntfy' and not value.get('topic'):value['topic']='job-hunter-'+secrets.token_hex(20)
    value['channel']=channel
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

def send_email(config,item,smtp_factory=None):
    from email.message import EmailMessage
    email=config['email'];context=ssl.create_default_context();factory=smtp_factory or (smtplib.SMTP_SSL if email['security']=='ssl' else smtplib.SMTP)
    kwargs={'timeout':15}
    if email['security']=='ssl':kwargs['context']=context
    message=EmailMessage();message['From']=email['username'];message['To']=email['recipient'];message['Subject']=item['title'];message['Message-ID']='<job-hunter-'+item['id']+'@'+email['username'].rsplit('@',1)[-1]+'>'
    message.set_content(item['message']+'\n\nOpen Job Hunter on your computer, or use remote desktop from your phone to continue.\n')
    with factory(email['host'],email['port'],**kwargs) as client:
        if email['security']=='starttls':client.ehlo();client.starttls(context=context);client.ehlo()
        client.login(email['username'],email['password'])
        if client.send_message(message):raise OSError('Email server refused the recipient')

def deliver_once(opener=None,clock=time.time,smtp_factory=None):
    config=configuration()
    if not config.get('enabled'):return False
    item=db.one("SELECT * FROM notification_outbox WHERE state='pending' AND next_at<=? ORDER BY created_at LIMIT 1",(clock(),))
    if not item:return False
    try:
        if config.get('channel')=='email':send_email(config,item,smtp_factory)
        else:
            request=urllib.request.Request('https://ntfy.sh/'+config['topic'],data=item['message'].encode(),method='POST',
               headers={'Title':item['title'],'Content-Type':'text/plain; charset=utf-8','Cache':'no','Priority':'default'})
            if opener is None:opener=urllib.request.build_opener(urllib.request.ProxyHandler({})).open
            with opener(request,timeout=15) as response:
                if response.status!=200:raise OSError('Notification service refused the alert')
                result=json.load(response)
                if result.get('event')!='message' or result.get('topic')!=config['topic']:raise OSError('Notification delivery was not acknowledged')
        with db.tx() as c:c.execute("UPDATE notification_outbox SET state='sent',error=NULL,attempts=attempts+1 WHERE id=?",(item['id'],))
    except Exception as error:
        attempts=item['attempts']+1
        rejected=isinstance(error,(smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused))
        with db.tx() as c:c.execute('UPDATE notification_outbox SET state=?,attempts=?,next_at=?,error=? WHERE id=?',
             ('failed' if attempts>=6 or rejected else 'pending',attempts,clock()+min(3600,30*2**(attempts-1)),
              'Review your email account and app password in Agent setup. Your saved work is unaffected.' if rejected else 'Alert could not be delivered. Your saved work is unaffected.',item['id']))
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
