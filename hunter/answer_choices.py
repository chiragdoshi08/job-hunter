"""Explicit user-approved alternatives; agent selections are application snapshots."""
from datetime import date
from . import db

def migrate(identity):
    with db.tx(identity) as c:
        c.execute("CREATE TABLE IF NOT EXISTS answer_behaviors(answer_id TEXT NOT NULL REFERENCES answers(id),version INTEGER NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('single','jd_choice')),PRIMARY KEY(answer_id,version))")
        c.execute("CREATE TRIGGER IF NOT EXISTS immutable_answer_behaviors BEFORE UPDATE ON answer_behaviors BEGIN SELECT RAISE(ABORT,'Answer behaviors are immutable'); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS keep_answer_behaviors BEFORE DELETE ON answer_behaviors BEGIN SELECT RAISE(ABORT,'Answer behaviors are immutable'); END")
        c.execute('INSERT OR IGNORE INTO migrations VALUES(6,?)',(db.now(),))

def enrich(identity,row):
    policy=db.one('SELECT mode FROM answer_behaviors WHERE answer_id=? AND version=?',(row['id'],row['version']),identity)
    row['answer_mode']=policy['mode'] if policy else 'single'
    row['alternatives']=options(row['value']) if row['answer_mode']=='jd_choice' else []
    return row

def options(value):
    return [x.strip() for x in value.splitlines() if x.strip()]

def validate(question,category,value,mode):
    if mode not in ('single','jd_choice'):raise ValueError('Choose one answer or alternatives matched to the job description')
    if mode=='single':return
    from .questions import normal
    if category not in ('experience','general','motivation') or any(x in normal(question) for x in ('official','legal','employment history','previous employer','previous title','sponsorship','relocat','visa','authoriz','authoris')):
        raise ValueError('This field needs a factual answer, not job-dependent alternatives')
    values=options(value)
    if not 2<=len(values)<=12 or any(len(x)>1000 for x in values):raise ValueError('Enter 2–12 alternatives, one per line, up to 1,000 characters each')
    if len({normal(x) for x in values})!=len(values):raise ValueError('Each alternative must be different')

def save_behavior(c,qid,version,mode):
    c.execute('INSERT INTO answer_behaviors VALUES(?,?,?)',(qid,version,mode))

def select(identity,task_id,owner,data):
    """Called by the claimed desktop agent after reading the pinned JD. No guessed choices."""
    from . import desktop,questions
    with db.LOCK:
        task=desktop.ensure_owner(identity,task_id,owner)
        if task['kind'] not in ('prepare','scan_form','fill','verify') or not task['application_id']:raise ValueError('Select alternatives within a claimed application task')
        ctx=desktop.context(identity,task_id);job=ctx['job'];app=db.application(identity,task['application_id'])
        if not job['description'].strip() or data.get('job_hash')!=job['description_hash']:raise ValueError('Use the task’s captured job description')
        # A newer live JD needs a new task, not a selection based on an obsolete capture.
        if db.get_job(identity,task['job_id'])['description_hash']!=job['description_hash']:raise ValueError('The job description changed. Start preparation again before selecting an answer.')
        row=questions.get(identity,data.get('answer_id'))
        if row['answer_mode']!='jd_choice' or data.get('answer_version')!=row['version']:raise ValueError('Read the current alternatives and their version before choosing')
        if not row['confirmed'] or row['review_note'] or (row['expires_at'] and row['expires_at']<date.today().isoformat()):raise ValueError('The alternatives need the user’s review first')
        value=data.get('value');reason=data.get('reason');quote=data.get('job_quote');model=data.get('model')
        if value not in row['alternatives']:raise ValueError('Choose exactly one saved alternative; do not combine or rewrite them')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>2000:raise ValueError('Explain why this option matches the job')
        if not isinstance(quote,str) or len(quote.strip())<8 or quote not in job['description']:raise ValueError('Include an exact supporting quote from the captured job description')
        if not isinstance(model,str) or not model.strip() or len(model)>150:raise ValueError('Record the selecting model, or explicitly record that its name is unavailable')
        fields=db.rows('SELECT * FROM question_encounters WHERE application_id=? AND answer_id=? AND active=1',(app['id'],row['id']),identity)
        if not fields:raise ValueError('Observe the actual application question before choosing its answer')
        original_answers=db.dump(app['answers']);answers=app['answers'];changed=False
        for f in fields:
            choices=db.unpack(f['choices'],[])
            if (f['max_length'] and len(value)>f['max_length']) or (choices and value not in choices):raise ValueError('This alternative does not fit the observed form choices or length limit')
            old=answers.get(f['question'],{})
            if old.get('confirmed') and old.get('value'):continue # preserve a previously approved snapshot
            selection={'value':value,'confirmed':row['reuse_scope']=='identity','provenance':'Chosen from user-approved alternatives by '+model,'answer_id':row['id'],'answer_version':row['version'],'expires_at':row['expires_at'],
                'selection':{'reason':reason.strip(),'job_quote':quote,'job_hash':job['description_hash'],'alternatives':row['alternatives'],'model':model,'task_id':task_id,'selected_at':db.now()}}
            if old.get('selection',{}).get('job_hash')==job['description_hash'] and old.get('answer_version')==row['version']:continue
            answers[f['question']]=selection;changed=True
        if changed:
            with db.tx(identity) as c:
                current=c.execute('SELECT version,confirmed,review_note FROM answers WHERE id=?',(row['id'],)).fetchone()
                saved_app=c.execute('SELECT answers FROM applications WHERE id=?',(app['id'],)).fetchone()
                if current['version']!=row['version'] or not current['confirmed'] or current['review_note']:raise ValueError('The alternatives changed while choosing. Read the current version and try again.')
                if db.dump(db.unpack(saved_app['answers'],{}))!=original_answers:raise ValueError('The application answers changed while choosing. Re-check before saving.')
                c.execute('UPDATE applications SET answers=?,approval_id=NULL,updated_at=? WHERE id=?',(db.dump(answers),db.now(),app['id']))
                db.log(c,'Answer selected for this job',row['question']+' · '+value+' · '+reason.strip(),app['job_id'],task_id)
        return {'saved':changed,'value':value,'readiness':questions.readiness(identity,app['id'])}
