"""User-created professional workspaces, each with a separate durable database."""
import re
from urllib.parse import urlsplit
from . import db

def document_id(value):
    if not value:return None
    if not isinstance(value,str):raise ValueError('Enter a Google Docs master-profile link')
    p=urlsplit(value.strip())
    m=re.fullmatch(r'/document/d/([A-Za-z0-9_-]+)(?:/.*)?',p.path)
    if p.scheme!='https' or p.hostname!='docs.google.com' or p.username or p.password or not m:raise ValueError('Use a normal https://docs.google.com/document/d/... master-profile link')
    return m[1]

def load_registry():
    with db.tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS identities(id TEXT PRIMARY KEY,name TEXT NOT NULL COLLATE NOCASE UNIQUE,master_id TEXT,positioning TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'ready',created_at TEXT NOT NULL)")
        for i,name in db.DEFAULT_IDENTITIES.items():
            c.execute('INSERT OR IGNORE INTO identities(id,name,master_id,created_at) VALUES(?,?,?,?)',(i,name,db.DEFAULT_MASTER_IDS[i],db.now()))
    refresh()

def refresh():
    records=db.rows("SELECT * FROM identities WHERE state='ready' ORDER BY created_at,rowid")
    # Replace dictionaries rather than mutate a worker's active iteration.
    db.IDENTITIES={r['id']:r['name'] for r in records}
    db.MASTER_IDS={r['id']:r['master_id'] for r in records}

def record(i):
    row=db.one('SELECT * FROM identities WHERE id=?',(i,))
    if not row:raise ValueError('Role not found')
    row['master_url']='https://docs.google.com/document/d/'+row['master_id']+'/edit' if row['master_id'] and not row['master_id'].startswith('local:') else ''
    return row

def create(data):
    name=str(data.get('name','')).strip();positioning=str(data.get('positioning','')).strip()
    if not name or len(name)>80:raise ValueError('Give this role a name, up to 80 characters')
    if len(positioning)>4000:raise ValueError('Keep the positioning note under 4,000 characters')
    master=document_id(data.get('master_url',''))
    titles=data.get('titles',[])
    if not isinstance(titles,list) or any(not isinstance(x,str) or len(x)>200 for x in titles):raise ValueError('Enter target role names')
    with db.LOCK:
        if db.one('SELECT id FROM identities WHERE name=? COLLATE NOCASE',(name,)):raise ValueError('A role with that name already exists')
        slug=re.sub('[^a-z0-9]+','-',name.lower()).strip('-')[:40] or 'identity'
        if not slug[0].isalpha():slug='identity-'+slug
        i=slug+'-'+db.uid()[:6]
        with db.tx() as c:c.execute("INSERT INTO identities VALUES(?,?,?,?,'creating',?)",(i,name,master,positioning,db.now()))
        db.initialize_identity(i,titles=titles)
        inherit_shared(i)
        with db.tx() as c:c.execute("UPDATE identities SET state='ready' WHERE id=?",(i,))
        refresh()
        with db.tx(i) as c:db.log(c,'Role created',name+' · separate profile, preferences, questions, jobs and applications')
    return record(i)

def update(i,data):
    row=record(i);master=document_id(data.get('master_url',row['master_url']))
    if not master and row['master_id'] and row['master_id'].startswith('local:'):master=row['master_id']
    positioning=str(data.get('positioning',row['positioning'])).strip()
    if len(positioning)>4000:raise ValueError('Keep the positioning note under 4,000 characters')
    with db.LOCK:
        with db.tx() as c:c.execute('UPDATE identities SET master_id=?,positioning=? WHERE id=?',(master,positioning,i))
        refresh()
        with db.tx(i) as c:db.log(c,'Role setup updated','Master reference/positioning saved. Existing profile and application versions remain fixed.')
    return record(i)

def inherit_shared(i):
    from . import questions
    groups=db.rows("SELECT group_id,identity,answer_id FROM answer_shares WHERE mode='all' GROUP BY group_id")
    for group in groups:
        if db.one('SELECT 1 FROM answer_shares WHERE group_id=? AND identity=?',(group['group_id'],i)):continue
        source=questions.get(group['identity'],group['answer_id'])
        qid=questions.ensure(i,source['question'],db.unpack(source['context'],{}),source.get('source_url') or '',source['category'],source['reuse_scope'])
        target=questions.get(i,qid)
        if target['value'] and target['value']!=source['value']:
            with db.tx(i) as c:c.execute('UPDATE answers SET review_note=? WHERE id=?',('An all-roles answer differs. Review it before sharing.',qid))
            continue
        questions.save(i,{'id':qid,'answer_mode':source['answer_mode'],'value':source['value'],'confirmed':bool(source['confirmed']) and not source['review_note'],'reuse_scope':source['reuse_scope'],'expires_at':source['expires_at']},'Inherited answer explicitly available in all roles · '+db.IDENTITIES[group['identity']])
        with db.tx() as c:c.execute('INSERT OR IGNORE INTO answer_shares VALUES(?,?,?,?)',(i,qid,group['group_id'],'all'))

def setup(i):
    meta=record(i);prefs=db.get_setting('preferences',{},i)
    profile=db.one('SELECT id,captured_at,revision FROM profiles WHERE source_id=? ORDER BY captured_at DESC LIMIT 1',(meta['master_id'],),i) if meta['master_id'] else None
    active=db.one("SELECT id,state,progress FROM tasks WHERE kind='refresh_profile' AND state NOT IN ('completed','stopped') ORDER BY created_at DESC LIMIT 1",identity=i)
    return {'identity':meta,'profile':profile,'profile_task':active,'preferences_ready':bool(prefs.get('confirmed') and prefs.get('titles')),
        'answers_ready':db.one("SELECT count(*) n FROM answers WHERE confirmed=1 AND value<>'' AND review_note=''",identity=i)['n'],
        'accounts_ready':db.one("SELECT count(*) n FROM accounts WHERE email<>'' AND paused=0")['n'],
        'can_search':bool(prefs.get('titles')),'can_assess':bool(profile),'workflow':['Discover','Assess','Shortlist','Prepare documents','Review','Fill application','Confirm submission','Track outcome']}
