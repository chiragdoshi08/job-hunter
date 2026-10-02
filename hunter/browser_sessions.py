"""Persistent local browser sessions. Only token hashes live on disk, outside trackers/backups."""
import hashlib,json,os,re,secrets,threading,time
from . import db

LOCK=threading.RLock()
LIFETIME=7*86400

def _path():return db.DATA/'browser-sessions.json'
def cookie_name():
    # Cookies are shared across ports. Give each local installation its own name.
    return 'hunter_'+hashlib.sha256(str(db.DATA.resolve()).encode()).hexdigest()[:16]
def _read():
    try:return json.loads(_path().read_text())
    except (OSError,ValueError):return {}
def _write(values):
    db.DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=_path();temp=target.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(values,f)
    os.chmod(temp,0o600);os.replace(temp,target)
def register(token,expires=None):
    with LOCK:
        values={k:v for k,v in _read().items() if isinstance(v,(int,float)) and v>time.time()}
        values[hashlib.sha256(token.encode()).hexdigest()]=expires or time.time()+LIFETIME
        _write(values)
def issue():
    token=secrets.token_urlsafe(32);register(token);return token
def valid(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{12,128}',token):return False
    with LOCK:
        expiry=_read().get(hashlib.sha256(token.encode()).hexdigest(),0)
        return isinstance(expiry,(int,float)) and expiry>time.time()
