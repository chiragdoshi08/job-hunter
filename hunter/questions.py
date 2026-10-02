"""Role-scoped question capture and deterministic answer reuse; no model calls."""
import re, unicodedata
from datetime import date
from . import db
from . import addressing,answer_choices

ALIASES={'email':'email address','e mail':'email address','first name':'first name','given name':'first name','last name':'last name','surname':'last name','phone':'phone number','mobile number':'phone number','telephone':'phone number','linkedin':'linkedin url','linkedin profile':'linkedin url'}
ALIASES.update({'state':'province','state province':'province','province state':'province','zip code':'postal code','postcode':'postal code','pin code':'postal code','pincode':'postal code'})
ALIASES.update({
    'current company':'current employer',
    'mobile phone':'phone number','mobile phone number':'phone number',
    'phone country code':'phone country','mobile phone country code':'phone country',
    'gender':'what is your gender','gender select one':'what is your gender',
    'what is your notice period with your current employer':'what is your availability to start notice period',
    'how soon are you able to join if selected':'what is your availability to start notice period',
})
STABLE_ANSWER_KEYS={'first name','last name','email address','phone number','phone country','current employer','what is your gender','what is your availability to start notice period'}
CATEGORIES=('contact','availability','work_authorisation','compensation','experience','education','motivation','sensitive','search_preferences','general','application_only')

def normal(text):
    text=unicodedata.normalize('NFKC',str(text)).casefold()
    return ' '.join(re.sub(r'[^\w\s$€₹£%]',' ',text).split())

def classify(question):
    q=normal(question)
    if any(x in q for x in ('ethnicity','disability','lgbtq','gender','veteran','birthday','date of birth','religion','race')):return 'sensitive','application'
    if any(x in q for x in ('salary','compensation','expected pay','desired pay')):return 'compensation','application'
    if any(x in q for x in ('why ','this company','our company','this role','non profit','sponsorship','relocat')):return 'motivation' if 'why ' in q else 'general','application'
    if any(x in q for x in ('authorized','authorised','authorization','authorisation','visa')):return 'work_authorisation','identity' if any(x in q.split() for x in ('us','canada','uk','india')) or 'united kingdom' in q else 'application'
    if q in ALIASES or q in ('full name','email address','phone number','current location','linkedin url','preferred name','address','full address','home address','residential address','current address','city','province','postal code','country'):return 'contact','identity'
    if any(x in q for x in ('notice period','available','start date')) or ('how soon' in q and 'join' in q):return 'availability','application'
    if any(x in q for x in ('education','degree','university')):return 'education','identity'
    if any(x in q for x in ('experience','employment','skills','languages','current job','current employer')):return 'experience','identity'
    return 'general','application'

def application_only(question, category=None, company='', field_type='', observed=False):
    """Keep employer and vacancy prompts with the application that asked them."""
    if category=='application_only':return True
    q=normal(question);employer=normal(company)
    if category in ('motivation','compensation'):return True
    if any(phrase in q for phrase in ('this role','this position','this job','our company','date available','desired pay','salary expectation','by checking this box','sponsorship','relocat')):return True
    if re.search(r'\b(referral|referred|referrer)\b',q):return True
    if not observed:return False
    if employer and len(employer)>=4 and re.search(r'\b'+re.escape(employer)+r'\b',q):return True
    return field_type in ('textarea','multiline') and category not in ('contact','availability','work_authorisation','experience','education','sensitive','search_preferences')

def reuse_policy(question,category=None):
    if not isinstance(question,str) or len(question)>5000:raise ValueError('Question must be text, up to 5,000 characters')
    detected=classify(question)[0];category=category or detected;q=normal(question)
    # An imported search-preference label is not a reason to prohibit reuse.
    # Still recognize contextual pay questions even when the importer grouped them as preferences.
    if category=='application_only':reason='This answer belongs to one application. Review it there.'
    elif 'compensation' in (category,detected):reason='Compensation can depend on the role, location and pay period. Review this answer for each application.'
    elif category=='motivation' or any(x in q for x in ('this company','our company','this role','why ')):reason='This answer depends on the company or vacancy. Review it for each application.'
    elif any(x in q for x in ('sponsorship','relocat')):reason='Sponsorship and relocation depend on the destination and employer. Review this answer for each application.'
    else:reason=''
    return {'automatic_allowed':not bool(reason),'default_scope':'application' if reason else classify(question)[1],'reason':reason,'personal_disclosure':category=='sensitive'}

def enforced_scope(question,category,requested):
    policy=reuse_policy(question,category)
    if requested not in (None,'identity','application'):raise ValueError('Choose how this answer should be used')
    if requested=='identity' and not policy['automatic_allowed']:raise ValueError(policy['reason']+' Choose “Ask me to review every application”.')
    return requested or policy['default_scope']

def migrate(identity):
    answer_choices.migrate(identity)
    with db.tx(identity) as c:
        present={r[1] for r in c.execute('PRAGMA table_info(answers)')}
        for name,typ in {'derived_from':'TEXT REFERENCES answers(id)','derived_version':'INTEGER'}.items():
            if name not in present:c.execute('ALTER TABLE answers ADD COLUMN '+name+' '+typ)
        c.execute('INSERT OR IGNORE INTO migrations VALUES(5,?)',(db.now(),))
        if c.execute('SELECT 1 FROM migrations WHERE version=4').fetchone():return
        columns={'question_key':'TEXT','category':"TEXT NOT NULL DEFAULT 'general'",'reuse_scope':"TEXT NOT NULL DEFAULT 'application'",'source_url':'TEXT','first_seen':'TEXT','last_seen':'TEXT','expires_at':'TEXT','context':"TEXT NOT NULL DEFAULT '{}'",'review_note':"TEXT NOT NULL DEFAULT ''",'version':'INTEGER NOT NULL DEFAULT 0'}
        present={r[1] for r in c.execute('PRAGMA table_info(answers)')}
        for name,typ in columns.items():
            if name not in present:c.execute('ALTER TABLE answers ADD COLUMN '+name+' '+typ)
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS question_key_unique ON answers(question_key) WHERE question_key IS NOT NULL')
        c.execute('CREATE TABLE IF NOT EXISTS answer_versions(id TEXT PRIMARY KEY,answer_id TEXT NOT NULL REFERENCES answers(id),version INTEGER NOT NULL,value TEXT NOT NULL,confirmed INTEGER NOT NULL,provenance TEXT NOT NULL,expires_at TEXT,created_at TEXT NOT NULL,UNIQUE(answer_id,version))')
        c.execute('CREATE TABLE IF NOT EXISTS question_encounters(id TEXT PRIMARY KEY,answer_id TEXT NOT NULL REFERENCES answers(id),application_id TEXT NOT NULL REFERENCES applications(id),question TEXT NOT NULL,choices TEXT NOT NULL,required INTEGER NOT NULL,field_type TEXT,max_length INTEGER,source_url TEXT,task_id TEXT,observed_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(application_id,answer_id,question))')
        c.execute('CREATE TABLE IF NOT EXISTS answer_imports(id TEXT PRIMARY KEY,answer_id TEXT NOT NULL REFERENCES answers(id),value TEXT NOT NULL,provenance TEXT NOT NULL,source_url TEXT,observed_at TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE)')
        c.execute("CREATE TRIGGER IF NOT EXISTS immutable_answer_versions BEFORE UPDATE ON answer_versions BEGIN SELECT RAISE(ABORT,'Answer versions are immutable'); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS keep_answer_versions BEFORE DELETE ON answer_versions BEGIN SELECT RAISE(ABORT,'Answer versions are immutable'); END")
    # Upgrade legacy saved answers and previously encountered application questions.
    for a in db.rows('SELECT * FROM answers WHERE question_key IS NULL ORDER BY confirmed DESC,updated_at DESC',identity=identity):
        category,scope=classify(a['question'])
        canonical=ALIASES.get(normal(a['question']),normal(a['question']));key=db.digest({'question':canonical,'context':{}})
        if db.one('SELECT id FROM answers WHERE question_key=?',(key,),identity):key='legacy:'+a['id']
        with db.tx(identity) as c:
            c.execute('UPDATE answers SET question_key=?,category=?,reuse_scope=?,first_seen=?,last_seen=?,version=1 WHERE id=?',(key,category,scope,a['updated_at'],a['updated_at'],a['id']))
            c.execute('INSERT INTO answer_versions VALUES(?,?,?,?,?,?,?,?)',(db.uid(),a['id'],1,a['value'],a['confirmed'],a['provenance'],None,a['updated_at']))
    for app in db.rows('SELECT id,job_id,answers FROM applications',identity=identity):
        values=db.unpack(app['answers'],{});url=db.get_job(identity,app['job_id'])['url']
        for question,answer in values.items():
            result=observe(identity,[{'question':question}],app['id'],url,apply=False)
            qid=result['questions'][0]['id'];row=get(identity,qid)
            if not row['value'] and answer.get('value'):save(identity,{'id':qid,'value':answer['value'],'confirmed':bool(answer.get('confirmed'))},provenance=answer.get('provenance','Existing application answer'))
    with db.tx(identity) as c:c.execute('INSERT OR IGNORE INTO migrations VALUES(4,?)',(db.now(),))

def get(identity,id):
    row=db.one('SELECT * FROM answers WHERE id=?',(id,),identity)
    if not row:raise ValueError('Question not found in this role')
    return answer_choices.enrich(identity,row)

def state(row):
    if not row['value']:return 'unanswered'
    if row['review_note']:return 'needs_review'
    if row['expires_at'] and row['expires_at']<date.today().isoformat():return 'expired'
    if not row['confirmed']:return 'needs_review'
    return 'ready' if row['reuse_scope']=='identity' else 'application_review'

def catalog(identity):
    from . import sharing
    rows=db.rows('SELECT a.*,(SELECT count(*) FROM question_encounters e WHERE e.answer_id=a.id) times_seen FROM answers a ORDER BY a.last_seen DESC,a.question',identity=identity)
    observed={}
    for f in db.rows('SELECT e.answer_id,e.question,e.field_type,j.company FROM question_encounters e JOIN applications ap ON ap.id=e.application_id JOIN jobs j ON j.id=ap.job_id WHERE e.active=1',identity=identity):observed.setdefault(f['answer_id'],[]).append(f)
    rows=[r for r in rows if not application_only(r['question'],r['category']) and not any(application_only(r['question'],r['category'],f['company'],f['field_type'],True) for f in observed.get(r['id'],[]))]
    for row in rows:answer_choices.enrich(identity,row);row['status']=state(row);row['sharing']=sharing.info(identity,row['id']);row['reuse_policy']=reuse_policy(row['question'],row['category'])
    return {'questions':rows,'counts':{s:sum(r['status']==s for r in rows) for s in ('unanswered','needs_review','ready','expired','application_review')}}

def ensure(identity,question,context=None,source_url='',category=None,reuse_scope=None):
    if not isinstance(question,str) or not question.strip() or len(question)>5000:raise ValueError('Question must be text, up to 5,000 characters')
    question=question.strip();context=dict(context or {});detected,default=classify(question);category=category or detected
    if category not in CATEGORIES:raise ValueError('Unknown question category')
    scope=enforced_scope(question,category,reuse_scope)
    # Context includes explicit country/currency/period and choice set. Never fuzzy-match eligibility questions.
    canonical=normal(question);canonical=ALIASES.get(canonical,canonical)
    # A form section identifies where a stable fact was asked, not a different
    # value. Keep country and other substantive context for eligibility fields.
    if canonical in STABLE_ANSWER_KEYS:context.pop('section',None)
    key=db.digest({'question':canonical,'context':context})
    old=db.one('SELECT * FROM answers WHERE question_key=?',(key,),identity)
    if old:return old['id']
    id=db.uid()
    with db.tx(identity) as c:
        c.execute('INSERT OR IGNORE INTO answers(id,question,value,provenance,confirmed,updated_at,question_key,category,reuse_scope,source_url,first_seen,last_seen,context) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(id,question,'','Observed question; answer unknown',0,db.now(),key,category,scope,source_url,db.now(),db.now(),db.dump(context)))
    return db.one('SELECT id FROM answers WHERE question_key=?',(key,),identity)['id']

def save(identity,data,provenance='Confirmed/edited by you in Question bank',_derived_from=None,_derived_version=None):
    qid=data.get('id') or ensure(identity,data.get('question',''),data.get('context'),category=data.get('category'),reuse_scope=data.get('reuse_scope'))
    old=get(identity,qid);value=data.get('value','')
    if not isinstance(value,str) or len(value)>50000:raise ValueError('Answer must be text, up to 50,000 characters')
    mode=data.get('answer_mode',old['answer_mode']);answer_choices.validate(old['question'],old['category'],value,mode)
    expires=data.get('expires_at',old['expires_at']) or None
    if expires:
        try:date.fromisoformat(expires)
        except ValueError:raise ValueError('Use a valid review date')
    if value and re.search(r'\b(password|passcode|otp|one time password|security answer|social security number|passport number|api key|access token)\b',normal(old['question'])):raise ValueError('Enter credentials and sensitive identifiers directly on the website; do not save them in the question bank')
    confirmed=bool(data.get('confirmed'))
    if confirmed and not value.strip():raise ValueError('Enter an answer before confirming it')
    scope=enforced_scope(old['question'],old['category'],data.get('reuse_scope',old['reuse_scope']))
    with db.tx(identity) as c:
        current=dict(c.execute('SELECT * FROM answers WHERE id=?',(qid,)).fetchone());version=current['version']+1
        if data.get('expected_version') is not None and data['expected_version']!=current['version']:raise ValueError('This answer changed. Reload before saving.')
        c.execute('INSERT INTO answer_versions VALUES(?,?,?,?,?,?,?,?)',(db.uid(),qid,version,value,int(confirmed),provenance,expires,db.now()))
        c.execute("UPDATE answers SET value=?,confirmed=?,provenance=?,expires_at=?,reuse_scope=?,updated_at=?,version=?,review_note='',derived_from=?,derived_version=? WHERE id=?",(value,int(confirmed),provenance,expires,scope,db.now(),version,_derived_from,_derived_version,qid))
        answer_choices.save_behavior(c,qid,version,mode)
        db.log(c,'Question bank answer saved',old['question']+' · version '+str(version))
    if addressing.is_address(old['question']):addressing.sync(identity,get(identity,qid))
    return qid

def import_profile(identity,items,source_url,source='Simplify profile'):
    if not source_url.startswith('https://simplify.jobs/'):raise ValueError('Use the observed Simplify profile URL')
    result=[]
    for item in items:
        value=item.get('value','')
        if not isinstance(value,str):raise ValueError('Imported answers must be text')
        id=ensure(identity,item['question'],item.get('context'),source_url,item.get('category'),item.get('reuse_scope'));old=get(identity,id)
        sha=db.digest([id,value,source_url])
        if db.one('SELECT id FROM answer_imports WHERE sha256=?',(sha,),identity):result.append(id);continue
        provenance=source+' · captured '+db.now()+' · review before reuse'
        with db.tx(identity) as c:c.execute('INSERT INTO answer_imports VALUES(?,?,?,?,?,?,?)',(db.uid(),id,value,provenance,source_url,db.now(),sha))
        if old['value'] and old['value']!=value:
            with db.tx(identity) as c:c.execute('UPDATE answers SET review_note=?,last_seen=? WHERE id=?',('New imported value differs from your saved answer. Review the import and keep or replace it.',db.now(),id))
        elif not old['value']:save(identity,{'id':id,'value':value,'confirmed':False},provenance)
        result.append(id)
    with db.tx(identity) as c:db.log(c,'Simplify profile imported',str(len(result))+' question/answer entries; no master profile or search preferences changed')
    return {'imported':len(result),'ids':result}

def observe(identity,fields,application_id,source_url='',task_id=None,apply=True):
    app=db.application(identity,application_id);job=db.get_job(identity,app['job_id'])
    if source_url:db.canonical_url(source_url)
    if not isinstance(fields,list) or len(fields)>300:raise ValueError('Use a list of at most 300 observed fields')
    result=[]
    for field in fields:
        if not isinstance(field,dict):raise ValueError('Fields must be objects')
        question=field['question'];choices=field.get('choices',[])
        if not isinstance(choices,list) or any(not isinstance(x,str) for x in choices):raise ValueError('Choices must be text')
        context=dict(field.get('context') or {})
        if field.get('max_length') is not None and (not isinstance(field['max_length'],int) or field['max_length']<1):raise ValueError('Maximum length must be positive')
        category=classify(question)[0]
        specific=application_only(question,category,job['company'],field.get('type','text'),True)
        if specific:
            previous_for_app=db.one('SELECT answer_id FROM question_encounters WHERE application_id=? AND question=? ORDER BY active DESC,observed_at DESC',(application_id,question),identity)
            if previous_for_app:qid=previous_for_app['answer_id']
            else:
                context['application_id']=application_id
                qid=ensure(identity,question,context,source_url,category='application_only')
        else:qid=ensure(identity,question,context,source_url)
        with db.tx(identity) as c:
            previous=c.execute('SELECT choices,required,max_length,answer_id FROM question_encounters WHERE application_id=? AND question=?',(application_id,question)).fetchone()
            if not previous or previous['choices']!=db.dump(choices) or previous['required']!=bool(field.get('required',True)) or previous['max_length']!=field.get('max_length') or previous['answer_id']!=qid:
                c.execute('UPDATE applications SET approval_id=NULL WHERE id=?',(application_id,))
            c.execute('UPDATE question_encounters SET active=0 WHERE application_id=? AND question=? AND answer_id<>?',(application_id,question,qid))
            c.execute('INSERT INTO question_encounters(id,answer_id,application_id,question,choices,required,field_type,max_length,source_url,task_id,observed_at,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(application_id,answer_id,question) DO UPDATE SET active=1,choices=excluded.choices,required=excluded.required,field_type=excluded.field_type,max_length=excluded.max_length,source_url=excluded.source_url,task_id=excluded.task_id,observed_at=excluded.observed_at',(db.uid(),qid,application_id,question,db.dump(choices),bool(field.get('required',True)),field.get('type','text'),field.get('max_length'),source_url,task_id,db.now()))
            c.execute('UPDATE answers SET last_seen=? WHERE id=?',(db.now(),qid))
        result.append({'id':qid,'question':question})
    with db.tx(identity) as c:db.log(c,'Application questions captured',str(len(fields))+' fields captured and matched locally',app['job_id'],task_id)
    return {'questions':result,'readiness':apply_to_application(identity,application_id) if apply else readiness(identity,application_id)}

def readiness(identity,application_id):
    app=db.application(identity,application_id);job=db.get_job(identity,app['job_id']);fields=db.rows('SELECT * FROM question_encounters WHERE application_id=? AND active=1 ORDER BY observed_at,question',(application_id,),identity);items=[]
    for f in fields:
        row=get(identity,f['answer_id']);current=app['answers'].get(f['question'],{});reason=None;ready=state(row)=='ready';choices=db.unpack(f['choices'],[])
        if not ready:reason={'unanswered':'Needs your answer','expired':'Review date has passed','needs_review':'Review the saved answer','application_review':'Confirm for this application'}.get(state(row))
        if application_only(f['question'],row['category'],job['company'],f['field_type'],True):ready=False;reason='Confirm for this application'
        if row['answer_mode']=='jd_choice':ready=False;reason='Agent will choose one approved option using this job description' if row['confirmed'] and not row['review_note'] else 'Review the alternatives first'
        if ready and f['max_length'] and len(row['value'])>f['max_length']:ready=False;reason='Answer exceeds this form’s character limit'
        if ready and choices and normal(row['value']) not in [normal(x) for x in choices]:ready=False;reason='Saved answer does not match the current choices'
        confirmed=bool(current.get('confirmed')) and bool(current.get('value')) and not (current.get('expires_at') and current['expires_at']<date.today().isoformat())
        if confirmed and ((choices and normal(current['value']) not in [normal(x) for x in choices]) or (f['max_length'] and len(current['value'])>f['max_length']) or (current.get('answer_id') and current['answer_id']!=row['id'])):confirmed=False;reason='Form context or constraints changed; review this answer'
        if confirmed and current.get('selection') and current['selection']['job_hash']!=db.get_job(identity,app['job_id'])['description_hash']:confirmed=False;reason='Job description changed; review the selected answer'
        items.append(dict(f,answer_mode=row['answer_mode'],alternatives=row['alternatives'],bank_status=state(row),reusable=ready,already_confirmed=confirmed,reason=reason,answer=row['value'] if ready else None,answer_version=row['version']))
    return {'fields':items,'total':len(items),'reusable':sum(x['reusable'] for x in items),'confirmed':sum(x['already_confirmed'] for x in items),'needs_answer':sum(x['required'] and not (x['reusable'] or x['already_confirmed']) for x in items)}

def apply_to_application(identity,application_id):
    with db.LOCK:
        status=readiness(identity,application_id);app=db.application(identity,application_id);answers=app['answers'];changed=False
        for f in status['fields']:
            if f['already_confirmed']:continue # fixed snapshots never track later bank edits
            row=get(identity,f['answer_id'])
            # Same application, same semantic question: retain an already reviewed
            # value when an ATS changes punctuation/case or its required marker.
            previous=next((v for q,v in answers.items() if q!=f['question'] and v.get('confirmed') and
                (v.get('answer_id')==f['answer_id'] or normal(q)==normal(f['question'])) and
                not (v.get('expires_at') and v['expires_at']<date.today().isoformat()) and
                (not f['max_length'] or len(v['value'])<=f['max_length']) and
                (not db.unpack(f['choices'],[]) or normal(v['value']) in [normal(x) for x in db.unpack(f['choices'],[])])),None)
            if previous:
                answers[f['question']]=dict(previous,answer_id=f['answer_id']);changed=True;continue
            if answers.get(f['question'],{}).get('confirmed') and not f['already_confirmed']:
                answers[f['question']]['confirmed']=False;changed=True
            if f['reusable']:
                value=row['value'];choices=db.unpack(f['choices'],[])
                if choices:value=next(x for x in choices if normal(x)==normal(value))
                answers[f['question']]={'value':value,'confirmed':True,'provenance':row['provenance'],'answer_id':row['id'],'answer_version':row['version'],'expires_at':row['expires_at']};changed=True
            elif f['required'] and f['question'] not in answers:
                answers[f['question']]={'value':'','confirmed':False,'provenance':'Observed application question; personal answer required','answer_id':row['id']};changed=True
        if changed:
            with db.tx(identity) as c:
                c.execute('UPDATE applications SET answers=?,approval_id=NULL,updated_at=? WHERE id=?',(db.dump(answers),db.now(),application_id));db.log(c,'Saved answers matched','Exact confirmed answers copied; document and answer review still required',app['job_id'])
        return readiness(identity,application_id)
