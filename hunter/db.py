from __future__ import annotations
import contextlib, hashlib, json, os, re, sqlite3, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[1]
from .paths import data_directory
DATA = data_directory(ROOT)
DEFAULT_IDENTITIES = {'strategy': 'Strategy, Operations & Business', 'ai': 'AI Product'}
IDENTITIES = dict(DEFAULT_IDENTITIES)
DEFAULT_MASTER_IDS = {'strategy':None,'ai':None}
MASTER_IDS = dict(DEFAULT_MASTER_IDS)
LOCK = threading.RLock()
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid(): return uuid.uuid4().hex[:16]
def dump(v): return json.dumps(v, ensure_ascii=False, sort_keys=True)
def digest(v): return hashlib.sha256((v if isinstance(v,str) else dump(v)).encode()).hexdigest()
def unpack(v, fallback=None):
    try: return json.loads(v)
    except (TypeError, ValueError): return fallback

def identity_path(identity):
    if not isinstance(identity,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',identity):raise ValueError('Choose a valid role')
    if identity not in IDENTITIES and not one('SELECT id FROM identities WHERE id=?',(identity,)):raise ValueError('Choose a valid role')
    return DATA / identity / 'tracker.sqlite'

def connect(identity=None):
    path = identity_path(identity) if identity else DATA/'shared.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c=sqlite3.connect(path, timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA busy_timeout=30000')
    os.chmod(path,0o600)
    return c

@contextlib.contextmanager
def tx(identity=None):
    c=connect(identity)
    try:
        c.execute('BEGIN IMMEDIATE')
        yield c
        c.commit()
    except BaseException:
        c.rollback(); raise
    finally: c.close()

def rows(sql, args=(), identity=None):
    with contextlib.closing(connect(identity)) as c: return [dict(x) for x in c.execute(sql,args)]
def one(sql,args=(),identity=None):
    r=rows(sql,args,identity); return r[0] if r else None

def log(c, action, detail='', job_id=None, task_id=None):
    c.execute('INSERT INTO activity(at,action,detail,job_id,task_id) VALUES(?,?,?,?,?)',(now(),action,detail,job_id,task_id))

SCHEMA='''
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, source_id TEXT NOT NULL, revision TEXT, captured_at TEXT NOT NULL, text TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE);
CREATE TRIGGER IF NOT EXISTS immutable_profiles BEFORE UPDATE ON profiles BEGIN SELECT RAISE(ABORT,'Profile snapshots are immutable'); END;
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, vacancy_key TEXT UNIQUE NOT NULL, title TEXT NOT NULL, company TEXT NOT NULL, location TEXT, arrangement TEXT, posted_at TEXT, found_at TEXT NOT NULL, last_seen TEXT NOT NULL, url TEXT NOT NULL, description TEXT NOT NULL, description_hash TEXT NOT NULL, source_id TEXT NOT NULL, source_job_id TEXT, salary TEXT, employment_type TEXT, country_restrictions TEXT, status TEXT NOT NULL DEFAULT 'found', availability TEXT NOT NULL DEFAULT 'open', filter_notes TEXT NOT NULL DEFAULT '[]', assessment TEXT, assessment_profile TEXT, assessment_jd_hash TEXT, model TEXT, assessed_at TEXT, feedback TEXT, test INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS job_captures(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),captured_at TEXT NOT NULL,description TEXT NOT NULL,sha256 TEXT NOT NULL,UNIQUE(job_id,sha256));
CREATE TABLE IF NOT EXISTS job_sources(job_id TEXT REFERENCES jobs(id), source_id TEXT, source_job_id TEXT, url TEXT, seen_at TEXT, PRIMARY KEY(job_id,source_id,url));
CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL REFERENCES jobs(id),state TEXT NOT NULL DEFAULT 'shortlisted',document_state TEXT NOT NULL DEFAULT 'not_started',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,checkpoint TEXT NOT NULL DEFAULT '{}',selected_documents TEXT NOT NULL DEFAULT '[]',answers TEXT NOT NULL DEFAULT '{}',approval_id TEXT,evidence TEXT,notes TEXT);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,application_id TEXT NOT NULL REFERENCES applications(id),kind TEXT NOT NULL,version INTEGER NOT NULL,drive_id TEXT NOT NULL,drive_url TEXT NOT NULL,drive_revision TEXT,local_path TEXT NOT NULL,sha256 TEXT NOT NULL,profile_id TEXT NOT NULL REFERENCES profiles(id),job_hash TEXT NOT NULL,changes TEXT NOT NULL,verified_at TEXT NOT NULL,verification TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(application_id,kind,version));
CREATE TRIGGER IF NOT EXISTS immutable_documents BEFORE UPDATE ON documents BEGIN SELECT RAISE(ABORT,'Document versions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_documents BEFORE DELETE ON documents BEGIN SELECT RAISE(ABORT,'Document versions are immutable'); END;
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,application_id TEXT NOT NULL REFERENCES applications(id),manifest TEXT NOT NULL,sha256 TEXT NOT NULL,scope TEXT NOT NULL,created_at TEXT NOT NULL,used_at TEXT);
CREATE TABLE IF NOT EXISTS answers(id TEXT PRIMARY KEY,question TEXT NOT NULL,value TEXT NOT NULL,provenance TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,kind TEXT NOT NULL,job_id TEXT REFERENCES jobs(id),application_id TEXT REFERENCES applications(id),state TEXT NOT NULL,payload TEXT NOT NULL,checkpoint TEXT NOT NULL DEFAULT '{}',progress TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 3,next_at REAL NOT NULL DEFAULT 0,owner TEXT,lease_until REAL,pid INTEGER,thread_id TEXT,model TEXT,result TEXT,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS unique_live_task ON tasks(kind,ifnull(job_id,'')) WHERE state IN ('queued','working','waiting_agent','waiting_user','paused','retry_wait');
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,job_id TEXT,task_id TEXT);
CREATE TABLE IF NOT EXISTS source_runs(id TEXT PRIMARY KEY,task_id TEXT,source_id TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,state TEXT NOT NULL,total INTEGER,matched INTEGER,error TEXT,partial INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS submission_attempts(id TEXT PRIMARY KEY,application_id TEXT NOT NULL REFERENCES applications(id),approval_id TEXT NOT NULL REFERENCES approvals(id),state TEXT NOT NULL,started_at TEXT NOT NULL,resolved_at TEXT,evidence TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_unresolved_submission ON submission_attempts(application_id) WHERE state IN ('attempting','uncertain','confirmed');
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,last_seen);
'''
SHARED='''
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,config TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,capabilities TEXT NOT NULL,last_success TEXT,last_failure TEXT,failure_detail TEXT,tested_at TEXT);
CREATE TABLE IF NOT EXISTS accounts(site TEXT PRIMARY KEY,label TEXT NOT NULL,email TEXT NOT NULL DEFAULT '',mapping TEXT NOT NULL DEFAULT 'shared',paused INTEGER NOT NULL DEFAULT 0,reason TEXT);
CREATE TABLE IF NOT EXISTS resource_locks(resource TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pursuit(vacancy_key TEXT NOT NULL,identity TEXT NOT NULL,application_id TEXT NOT NULL,state TEXT NOT NULL,PRIMARY KEY(vacancy_key,identity));
'''

def init():
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    from .paths import secure_data
    secure_data(DATA)
    with contextlib.closing(connect()) as c:
        c.executescript(SHARED); c.execute('INSERT OR IGNORE INTO migrations VALUES(1,?)',(now(),)); c.commit()
    from . import identities,sharing,reviews,notifications,resume_accounts
    notifications.init()
    resume_accounts.init()
    identities.load_registry()
    creating=[]
    for item in rows('SELECT id,state FROM identities'):
        initialize_identity(item['id'])
        if item['state']=='creating':creating.append(item['id'])
    sharing.migrate();sharing.recover();reviews.migrate();reviews.recover()
    for i in creating:
        identities.inherit_shared(i)
        with tx() as c:c.execute("UPDATE identities SET state='ready' WHERE id=?",(i,))
    if creating:identities.refresh()
    defaults={'model':'gpt-6-sol','batch_size':5,'discovery_concurrency':3,'paused':False,'development_mode':False,'execution_mode':'local_agent','account_policy':'shared','codex_path':''}
    for k,v in defaults.items():
        if get_setting(k) is None:set_setting(k,v)


def initialize_identity(identity,titles=None):
    with contextlib.closing(connect(identity)) as c:
        c.executescript(SCHEMA)
        if 'assessment_context_hash' not in {r[1] for r in c.execute('PRAGMA table_info(jobs)')}:c.execute('ALTER TABLE jobs ADD COLUMN assessment_context_hash TEXT')
        for version in (1,2,3):c.execute('INSERT OR IGNORE INTO migrations VALUES(?,?)',(version,now()))
        c.commit()
    if get_setting('preferences',None,identity) is None:
        if titles is None:
            titles={'strategy':['strategy','operations','business head','general manager','chief of staff','transformation','program management','supply chain'],'ai':['product manager','product management','product operations','product strategy','AI transformation','AI product','product lead']}.get(identity,[])
        set_setting('preferences',dict(titles=titles,locations=[],countries=[],arrangements=[],seniority=[],industries=[],employment_types=[],exclusions=[],minimum_salary=None,currency='INR',salary_period='annual',posting_age_days=None,work_authorization='',timezone='',confirmed=False),identity)
    from . import questions
    questions.migrate(identity)
    with tx(identity) as c:c.execute('PRAGMA user_version=6')


def get_setting(key,default=None,identity=None):
    r=one('SELECT value FROM settings WHERE key=?',(key,),identity)
    return unpack(r['value'],default) if r else default

def set_setting(key,value,identity=None):
    with tx(identity) as c: c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,dump(value)))

def capture_profile(identity, profile):
    if not MASTER_IDS.get(identity) or profile['document_id'] != MASTER_IDS[identity]: raise ValueError('Master profile does not belong to this role')
    content=profile['text']; h=digest(content); id=uid()
    if not isinstance(content,str) or not content.strip():raise ValueError('The profile must contain readable text')
    with tx(identity) as c:
        c.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?,?,?,?)',(id,profile['document_id'],profile.get('revision_id'),profile['captured_at'],content,h))
        log(c,'Master profile captured',f"Revision {profile.get('revision_id','unknown')}; source unchanged")
    return one('SELECT * FROM profiles WHERE sha256=?',(h,),identity)

def canonical_url(url):
    p=urlsplit(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:raise ValueError('Expected a normal job URL')
    q=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','gh_src')) and k not in ('source','ref','referral','lever-source','lever-origin')]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode(sorted(q)),''))

def vacancy_key(j):
    u=canonical_url(j['url']); p=urlsplit(u)
    if p.hostname=='greenhouse.io' or p.hostname.endswith('.greenhouse.io'):
        m=re.search(r'/([^/]+)/jobs/(\d+)',p.path)
        if m:return 'greenhouse:'+m[1]+':'+m[2]
    if p.hostname=='lever.co' or p.hostname.endswith('.lever.co'):
        m=re.search(r'/([^/]+)/([a-f0-9-]{20,})',p.path)
        if m:return 'lever:'+m[1]+':'+m[2]
    if p.hostname=='ashbyhq.com' or p.hostname.endswith('.ashbyhq.com'):
        return 'ashby:'+p.path.strip('/').replace('/application','')
    return 'url:'+digest(u)

def upsert_job(identity,j):
    for k in ['title','company','url','source_id']:
        if not j.get(k): raise ValueError('Job is missing '+k)
    key=vacancy_key(j); desc=j.get('description',''); h=digest(desc)
    with tx(identity) as c:
        old=c.execute('SELECT * FROM jobs WHERE vacancy_key=?',(key,)).fetchone(); id=old['id'] if old else uid()
        if old:
            c.execute('UPDATE jobs SET last_seen=?,availability=?,description=?,description_hash=?,filter_notes=? WHERE id=?',(now(),j.get('availability','open'),desc or old['description'],h if desc else old['description_hash'],dump(j.get('filter_notes',[])),id))
            for field in ('title','company','location','arrangement','posted_at','employment_type','salary','country_restrictions'):
                value=j.get(field)
                if value is not None:
                    if field in ('salary','country_restrictions'):value=dump(value)
                    c.execute('UPDATE jobs SET '+field+'=? WHERE id=?',(value,id))
            if desc and old['description_hash']!=h: log(c,'Job description changed','Existing assessments/documents retain their captured version; reassessment required.',id)
        else:
            c.execute('INSERT INTO jobs(id,vacancy_key,title,company,location,arrangement,posted_at,found_at,last_seen,url,description,description_hash,source_id,source_job_id,salary,employment_type,country_restrictions,filter_notes,test) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(id,key,j['title'],j['company'],j.get('location'),j.get('arrangement'),j.get('posted_at'),now(),now(),canonical_url(j['url']),desc,h,j['source_id'],str(j.get('source_job_id','')),dump(j['salary']) if j.get('salary') else None,j.get('employment_type'),dump(j.get('country_restrictions',[])),dump(j.get('filter_notes',[])),int(j.get('test',False))))
            log(c,'Opportunity discovered',j['company']+' · '+j['title'],id)
        c.execute('INSERT OR IGNORE INTO job_captures VALUES(?,?,?,?,?)',(uid(),id,now(),desc,h))
        c.execute('INSERT INTO job_sources VALUES(?,?,?,?,?) ON CONFLICT(job_id,source_id,url) DO UPDATE SET seen_at=excluded.seen_at',(id,j['source_id'],str(j.get('source_job_id','')),canonical_url(j['url']),now()))
        if j.get('discovered_url') and canonical_url(j['discovered_url'])!=canonical_url(j['url']):c.execute('INSERT INTO job_sources VALUES(?,?,?,?,?) ON CONFLICT(job_id,source_id,url) DO UPDATE SET seen_at=excluded.seen_at',(id,j['source_id'],str(j.get('source_job_id','')),canonical_url(j['discovered_url']),now()))
    return id

def get_job(identity,id):
    j=one('SELECT * FROM jobs WHERE id=?',(id,),identity)
    if not j:raise ValueError('Opportunity not found in this role')
    for f in ('filter_notes','assessment','country_restrictions','salary'):j[f]=unpack(j[f],None)
    return j

def shortlist(identity,job_id,ack_duplicate=False):
    with LOCK:return _shortlist(identity,job_id,ack_duplicate)

def _shortlist(identity,job_id,ack_duplicate=False):
    j=get_job(identity,job_id)
    existing=one('SELECT * FROM applications WHERE job_id=?',(job_id,),identity)
    if existing:return existing
    duplicates=rows("SELECT * FROM pursuit WHERE vacancy_key=? AND identity!=? AND state NOT IN ('withdrawn','rejected')",(j['vacancy_key'],identity))
    if duplicates and not ack_duplicate:raise ValueError('This same vacancy is already being pursued through the other role. Review and acknowledge the duplicate warning.')
    id=uid()
    with LOCK:
        with tx(identity) as c:
            c.execute('INSERT INTO applications(id,job_id,created_at,updated_at) VALUES(?,?,?,?)',(id,job_id,now(),now()))
            c.execute("UPDATE jobs SET status='shortlisted' WHERE id=?",(job_id,));log(c,'Shortlisted','Duplicate acknowledged' if duplicates else '',job_id)
        with tx() as c:c.execute('INSERT OR REPLACE INTO pursuit VALUES(?,?,?,?)',(j['vacancy_key'],identity,id,'shortlisted'))
    return one('SELECT * FROM applications WHERE id=?',(id,),identity)

def enqueue(identity,kind,job_id=None,payload=None,application_id=None):
    if kind not in ('discover','assess','prepare','fill','submit','verify','refresh_profile','web_discovery','scan_form','import_answers'):raise ValueError('Unknown task type')
    if kind in ('discover','web_discovery') and not get_setting('preferences',{},identity).get('titles'):raise ValueError('Add target roles in this role’s search preferences first')
    if kind=='refresh_profile' and not MASTER_IDS.get(identity):raise ValueError('Add this role’s Google Docs master-profile link in Role setup first')
    if job_id:get_job(identity,job_id)
    if application_id:
        application_row=one('SELECT id,state FROM applications WHERE id=? AND job_id=?',(application_id,job_id),identity)
        if not application_row:raise ValueError('Application role mismatch')
        if application_row['state']=='submitted' and kind in ('prepare','fill','submit','verify','scan_form'):
            raise ValueError('This application is already confirmed submitted; do not prepare or fill it again')
    state='waiting_agent' if kind in ('prepare','fill','submit','verify','refresh_profile','web_discovery','scan_form','import_answers') else 'queued'
    id=uid()
    with tx(identity) as c:
        old=c.execute("SELECT id FROM tasks WHERE kind=? AND ifnull(job_id,'')=? AND state IN ('queued','working','waiting_agent','waiting_user','paused','retry_wait')",(kind,job_id or '')).fetchone()
        if old:return old['id']
        payload=dict(payload or {});payload['identity']=identity
        payload.setdefault('preferences',get_setting('preferences',{},identity))
        if kind=='refresh_profile':payload.setdefault('master_document_id',MASTER_IDS.get(identity))
        if kind in ('assess','prepare'):
            profile=one('SELECT id FROM profiles WHERE source_id=? ORDER BY captured_at DESC LIMIT 1',(MASTER_IDS.get(identity),),identity)
            if not profile:raise ValueError('Capture this role’s master profile first')
            payload.setdefault('profile_id',profile['id'])
            payload.setdefault('job_hash',get_job(identity,job_id)['description_hash'])
            job=get_job(identity,job_id)
            payload.setdefault('job_snapshot',{k:job[k] for k in ('title','company','location','arrangement','country_restrictions','salary','url')})
        c.execute('INSERT INTO tasks(id,kind,job_id,application_id,state,payload,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(id,kind,job_id,application_id,state,dump(payload),'Waiting for desktop agent' if state=='waiting_agent' else 'Waiting for local worker',now(),now()))
        log(c,'Task requested',kind,job_id,id)
    return id

def task_update(identity,id,**fields):
    allowed={'state','checkpoint','progress','attempts','next_at','owner','lease_until','pid','thread_id','model','result','error'}
    if not set(fields)<=allowed:raise ValueError('Unsupported task update')
    fields['updated_at']=now()
    for k in ('checkpoint','result'):
        if k in fields and not isinstance(fields[k],str):fields[k]=dump(fields[k])
    with tx(identity) as c:c.execute('UPDATE tasks SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),id))
    if fields.get('state') in ('waiting_user','completed'):
        from . import notifications
        notifications.task_changed(identity,one('SELECT * FROM tasks WHERE id=?',(id,),identity))

def acquire(resource,owner,ttl=1800):
    with tx() as c:
        c.execute('DELETE FROM resource_locks WHERE expires<?',(time.time(),))
        old=c.execute('SELECT * FROM resource_locks WHERE resource=?',(resource,)).fetchone()
        if old and old['owner']!=owner:return False
        c.execute('INSERT OR REPLACE INTO resource_locks VALUES(?,?,?)',(resource,owner,time.time()+ttl));return True

def release(owner):
    with tx() as c:c.execute('DELETE FROM resource_locks WHERE owner=?',(owner,))

def release_task(identity,id):
    with tx() as c:c.execute('DELETE FROM resource_locks WHERE owner=? OR owner LIKE ?',(identity+':'+id,identity+':'+id+':%'))

def recover():
    for identity in IDENTITIES:
        with tx(identity) as c:
            for t in c.execute("SELECT * FROM tasks WHERE state='working'").fetchall():
                desktop=t['kind'] in ('prepare','fill','submit','verify','web_discovery','refresh_profile','scan_form','import_answers')
                if desktop and (t['lease_until'] or 0)>time.time():continue
                state='waiting_agent' if desktop else 'paused'
                message='Previous worker ended. Resume to re-check saved work before continuing.'
                c.execute('UPDATE tasks SET state=?,progress=?,pid=NULL,owner=NULL,lease_until=NULL,updated_at=? WHERE id=?',(state,message,now(),t['id']))
                log(c,'Task recovered',message,t['job_id'],t['id']);release_task(identity,t['id'])
            for attempt in c.execute("SELECT * FROM submission_attempts WHERE state='attempting'").fetchall():
                c.execute("UPDATE submission_attempts SET state='uncertain' WHERE id=?",(attempt['id'],))
                c.execute("UPDATE applications SET state='verification_needed',updated_at=? WHERE id=?",(now(),attempt['application_id']))
                log(c,'Submission needs verification','Worker restarted after submission began. Check for an existing receipt before any retry.')
    reconcile_pursuits()

def reconcile_pursuits():
    for identity in IDENTITIES:
        for a in rows('SELECT a.id,a.state,j.vacancy_key FROM applications a JOIN jobs j ON j.id=a.job_id',identity=identity):
            with tx() as c:c.execute('INSERT OR REPLACE INTO pursuit VALUES(?,?,?,?)',(a['vacancy_key'],identity,a['id'],a['state']))

def application(identity,id):
    a=one('SELECT * FROM applications WHERE id=?',(id,),identity)
    if not a:raise ValueError('Application not found in this role')
    for k in ['checkpoint','selected_documents','answers']:a[k]=unpack(a[k],{} if k!='selected_documents' else [])
    return a

def manifest(identity,id):
    a=application(identity,id);j=get_job(identity,a['job_id']);docs=[]
    for did in a['selected_documents']:
        d=one('SELECT * FROM documents WHERE id=? AND application_id=?',(did,id),identity)
        if not d:raise ValueError('Document does not belong to this application')
        path=DATA/identity/d['local_path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=d['sha256']:raise ValueError('An approved document file is missing or changed; create and review a new version')
        if d['job_hash']!=j['description_hash']:raise ValueError('The job description changed. Prepare and review current documents first.')
        docs.append({k:d[k] for k in ['id','kind','version','sha256','drive_id','drive_revision','profile_id','job_hash']})
    if not any(d['kind']=='cv' for d in docs):raise ValueError('Select a verified CV version before approval')
    from . import questions
    fields={f['question']:f for f in questions.readiness(identity,id)['fields']}
    reviewed_answers={}
    for k,v in a['answers'].items():
        field=fields.get(k)
        if isinstance(v,dict) and field and not field['required'] and not str(v.get('value','')).strip():continue
        if not isinstance(v,dict) or not v.get('confirmed'):raise ValueError('Confirm all consequential answers before approval')
        if v.get('expires_at') and v['expires_at']<now()[:10]:raise ValueError('An answer review date has passed. Confirm it again before approval')
        if field and not field['already_confirmed']:raise ValueError('Review this answer against the current form: '+k)
        reviewed_answers[k]=v
    for k,field in fields.items():
        if field['required'] and not field['already_confirmed']:raise ValueError('Confirm the required application answer: '+k)
    site=urlsplit(j['url']).hostname
    acct=one('SELECT * FROM accounts WHERE site=?',(site,))
    if acct and acct['paused']:raise ValueError('This shared account is paused: '+str(acct['reason'] or 'Resolve the restriction in Settings'))
    account_email=acct['email'] if acct else ''
    account_source='shared_site_account' if account_email else ''
    # The observed public Greenhouse form has an Email field and no login step.
    # Reuse only its confirmed value; a later login still requires browser handover.
    if not account_email and site=='job-boards.greenhouse.io' and 'Email' in fields:
        email_answer=reviewed_answers.get('Email',{})
        candidate=str(email_answer.get('value','')).strip() if isinstance(email_answer,dict) else ''
        if fields['Email']['already_confirmed'] and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',candidate):
            account_email=candidate
            account_source='confirmed_public_form_email'
    if not account_email:raise ValueError('Set the shared job-site account/email for '+site+' in Settings first')
    if j['availability']!='open':raise ValueError('This vacancy is not confirmed open. Re-check the source first.')
    return dict(identity=identity,application_id=id,destination=j['url'],job_hash=j['description_hash'],role=j['title'],company=j['company'],location=j['location'],arrangement=j['arrangement'],documents=docs,answers=reviewed_answers,account=account_email,account_source=account_source)

def approve(identity,id,scope='fill'):
    if scope not in ('fill','submit'):raise ValueError('Invalid approval scope')
    if application(identity,id)['state']=='submitted':raise ValueError('This application is already confirmed submitted')
    if scope=='submit' and get_setting('development_mode',False):raise ValueError('Real submission is locked during development. Turn off the legacy testing lock in Agent setup.')
    m=manifest(identity,id);ap=uid()
    with tx(identity) as c:
        c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,NULL)',(ap,id,dump(m),digest(m),scope,now()))
        c.execute('UPDATE applications SET approval_id=?,state=?,updated_at=? WHERE id=?',(ap,'ready_to_fill' if scope=='fill' else 'awaiting_submission',now(),id));log(c,'Approved '+scope,digest(m),m['application_id'])
    return ap

def verify_approval(identity,id,scope):
    a=application(identity,id);p=one('SELECT * FROM approvals WHERE id=?',(a['approval_id'],),identity)
    if not p or p['scope']!=scope or p['used_at']:raise ValueError('This action needs a current application-specific approval')
    if p['sha256']!=digest(manifest(identity,id)):raise ValueError('The application changed since approval. Review it again.')
    return p

def begin_submission(identity,id):
    if get_setting('development_mode',True):raise ValueError('Real submission is locked during development')
    if application(identity,id)['state']=='submitted':raise ValueError('This application is already confirmed submitted')
    approval=verify_approval(identity,id,'submit');attempt=uid()
    with tx(identity) as c:
        if c.execute("SELECT id FROM submission_attempts WHERE application_id=? AND state IN ('attempting','uncertain','confirmed')",(id,)).fetchone():raise ValueError('A previous submission requires verification; do not submit again')
        c.execute('INSERT INTO submission_attempts VALUES(?,?,?,?,?,NULL,NULL)',(attempt,id,approval['id'],'attempting',now()))
        c.execute('UPDATE approvals SET used_at=? WHERE id=?',(now(),approval['id']))
        c.execute("UPDATE applications SET state='verification_needed',updated_at=? WHERE id=?",(now(),id))
        log(c,'Submission attempt reserved','Approval consumed; confirmation evidence is required before Submitted status.')
    return attempt

def submission_result(identity,id,attempt,state,evidence):
    if state not in ('confirmed','uncertain','not_submitted'):raise ValueError('Invalid submission result')
    if not isinstance(evidence,dict) or not evidence.get('observed_at') or not evidence.get('url') or not evidence.get('observation'):raise ValueError('Record the observed page, time and confirmation evidence')
    canonical_url(evidence['url'])
    if state=='confirmed' and not (evidence.get('receipt') or evidence.get('confirmation_text')):raise ValueError('A reliable receipt or confirmation text is required')
    if state=='not_submitted' and not evidence.get('absence_verified'):raise ValueError('Verify absence of an existing submission before allowing another attempt')
    with tx(identity) as c:
        old=c.execute('SELECT * FROM submission_attempts WHERE id=? AND application_id=?',(attempt,id)).fetchone()
        if not old:raise ValueError('Submission attempt does not belong to this role/application')
        if old['state']=='confirmed':raise ValueError('Confirmed submission is final; record later outcomes separately')
        c.execute('UPDATE submission_attempts SET state=?,resolved_at=?,evidence=? WHERE id=?',(state,now(),dump(evidence),attempt))
        c.execute('UPDATE applications SET state=?,evidence=?,updated_at=? WHERE id=?',('submitted' if state=='confirmed' else 'verification_needed' if state=='uncertain' else 'awaiting_submission',dump(evidence),now(),id))
        log(c,'Submission '+state,evidence['observation'])
    reconcile_pursuits()

def record_external_submission(identity,id,evidence):
    """Reconcile a user-performed submission only after observing employer evidence."""
    if not isinstance(evidence,dict) or evidence.get('source') not in ('employer_email','employer_confirmation_page'):
        raise ValueError('An employer email or confirmation page is required')
    if not all(isinstance(evidence.get(k),str) and evidence[k].strip() for k in ('observed_at','url','observation','confirmation_text')):
        raise ValueError('Record the observed confirmation, its URL and time')
    canonical_url(evidence['url'])
    a=application(identity,id)
    if a['state']=='submitted':return {'recorded':False,'already_submitted':True}
    with tx(identity) as c:
        active=c.execute("SELECT id,state FROM tasks WHERE application_id=? AND state IN ('queued','working','waiting_agent','waiting_user','paused','retry_wait')",(id,)).fetchall()
        if any(t['state']=='working' for t in active):raise ValueError('A worker is using this application; checkpoint it before reconciling')
        c.execute("UPDATE applications SET state='submitted',evidence=?,updated_at=? WHERE id=?",(dump({**evidence,'method':'submitted_by_user'}),now(),id))
        for t in active:
            c.execute("UPDATE tasks SET state='stopped',progress='Employer confirmation observed; no further application work needed',error=NULL,updated_at=? WHERE id=?",(now(),t['id']))
        log(c,'External submission confirmed',evidence['observation'],a['job_id'])
    for t in active:release_task(identity,t['id'])
    reconcile_pursuits()
    return {'recorded':True,'stopped_tasks':len(active)}
