from __future__ import annotations
import base64, hashlib, json, mimetypes, os, re, secrets, signal, subprocess, threading, time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,quote
from . import application_answers,db,sources,desktop,backup,questions
from . import addressing,sharing,identities,browser_sessions,reviews
from .worker import Runner,auth_status,clean_env,codex_binary
from . import onboarding,goals,adapters,notifications,resume_accounts

RUNNER=None
AGENT=None
LOGIN_PROCESS=None
NOTIFIER=None
DOCUMENTS=None
BOOTSTRAP={}
CSRF=secrets.token_urlsafe(32)
PORT=8766
FIXTURE={}

def summary(identity):
    counts={k:0 for k in ('found','shortlisted','prepared','needs_help','submitted')}
    counts['found']=db.one('SELECT count(*) n FROM jobs WHERE test=0',identity=identity)['n']
    counts['shortlisted']=db.one('SELECT count(*) n FROM applications a JOIN jobs j ON j.id=a.job_id WHERE j.test=0',identity=identity)['n']
    counts['prepared']=db.one("SELECT count(*) n FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.document_state='prepared' AND j.test=0",identity=identity)['n']
    counts['needs_help']=db.one("SELECT count(*) n FROM tasks WHERE state='waiting_user'",identity=identity)['n']
    counts['submitted']=db.one("SELECT count(*) n FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.state='submitted' AND j.test=0",identity=identity)['n']
    return counts

class Handler(BaseHTTPRequestHandler):
    server_version='JobHunter/1.0'
    def log_message(self,format,*args):pass # Never log request URLs or auth material.
    def send(self,status,data,ctype='application/json',headers=None):
        raw=(db.dump(data).encode() if ctype=='application/json' else data.encode() if isinstance(data,str) else data)
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)
    def error(self,e,code=400):self.send(code,{'error':str(e)})
    def host_ok(self):return self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
    def authenticated(self):
        cookies=dict(x.strip().split('=',1) for x in self.headers.get('Cookie','').split(';') if '=' in x)
        return browser_sessions.valid(cookies.get(browser_sessions.cookie_name(),''))
    def guard(self,write=False):
        if not self.host_ok():self.error('Invalid local host',403);return False
        if not self.authenticated():self.error('Open Job Hunter using its Mac launcher to connect this browser.',401);return False
        if write:
            origin=self.headers.get('Origin')
            if origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
                self.error('Local request verification failed',403);return False
            if self.headers.get('X-Hunter-CSRF')!=CSRF:
                self.send(403,{'error':'The app restarted. Refresh the connection and try again.','code':'csrf_stale'});return False
        return True
    def do_GET(self):
        try:self.get()
        except Exception as e:self.error(e)
    def get(self):
        path=urlsplit(self.path).path;q=parse_qs(urlsplit(self.path).query)
        if not self.host_ok():return self.error('Invalid local host',403)
        if path=='/health':return self.send(200,{'service':'job-hunter','ok':True})
        if path=='/connect':
            if self.authenticated():return self.send(303,'','text/plain',{'Location':'/'})
            token=q.get('token',[''])[0]
            if BOOTSTRAP.pop(token,0)<time.time():return self.send(401,'This launch link expired. Reopen Launch Job Hunter.command.','text/plain')
            sid=browser_sessions.issue()
            return self.send(303,'','text/plain',{'Location':'/','Set-Cookie':f'{browser_sessions.cookie_name()}={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800'})
        if path in ('/','/app.js','/style.css','/fixture.js','/questions.js','/application-answers.js','/identities.js','/agent.js'):
            p=db.ROOT/'static'/({'/':'index.html'}.get(path,path.lstrip('/')))
            return self.send(200,p.read_bytes(),mimetypes.guess_type(p)[0] or 'text/plain')
        if path=='/fixture':
            if not self.guard():return
            return self.send(200,(db.ROOT/'static/fixture.html').read_bytes(),'text/html')
        if not self.guard():return
        if path=='/api/bootstrap':return self.send(200,dict(csrf=CSRF,identities=db.IDENTITIES,settings={k:db.get_setting(k) for k in ('model','batch_size','discovery_concurrency','paused','development_mode','account_policy','execution_mode')},auth=auth_status()))
        if path=='/api/identities':return self.send(200,[identities.setup(i) for i in db.IDENTITIES])
        if path=='/api/sources':return self.send(200,db.rows('SELECT * FROM sources ORDER BY kind,name'))
        if path=='/api/accounts':return self.send(200,db.rows('SELECT * FROM accounts ORDER BY site'))
        if path=='/api/notifications':return self.send(200,notifications.status())
        if path=='/api/resume-accounts':return self.send(200,{'config':db.get_setting('resume_accounts',{}),'pending':resume_accounts.pending(),'check':db.get_setting('resume_recovery_check',{})})
        if path=='/api/backups':return self.send(200,[{'name':p.name,'size':p.stat().st_size} for p in sorted((db.DATA.parent/'backups').glob('*.zip'),reverse=True)])
        if path.startswith('/api/backup/'):
            name=path.rsplit('/',1)[-1]
            if not re.fullmatch(r'job-hunter-[A-Za-z0-9:._+-]+\.zip',name):raise ValueError('Invalid backup name')
            return self.send(200,(db.DATA.parent/'backups'/name).read_bytes(),'application/zip',{'Content-Disposition':f'attachment; filename="{name}"'})
        if path=='/api/fixture':return self.send(200,{'csrf':CSRF,'state':FIXTURE})
        parts=path.strip('/').split('/')
        if len(parts)<3 or parts[0]!='api' or parts[1] not in db.IDENTITIES:return self.error('Not found',404)
        i=parts[1];view=parts[2]
        if view=='counts':return self.send(200,summary(i))
        if view=='agent':return self.send(200,onboarding.readiness(i))
        if view=='setup':return self.send(200,identities.setup(i))
        if view=='home':return self.send(200,{'counts':summary(i),'tasks':db.rows("SELECT * FROM tasks WHERE state!='stopped' ORDER BY CASE WHEN state IN ('working','waiting_user','waiting_agent','paused','retry_wait','queued') THEN 0 ELSE 1 END,created_at DESC LIMIT 40",identity=i),'reviews':db.rows("SELECT a.id,j.id job_id,j.title,j.company FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.document_state='prepared' AND a.state='review' AND j.test=0 ORDER BY a.updated_at DESC LIMIT 5",identity=i),'activity':db.rows('SELECT * FROM activity ORDER BY id DESC LIMIT 25',identity=i),'preferences':db.get_setting('preferences',{},i),'profile':db.one('SELECT id,source_id,revision,captured_at,sha256 FROM profiles ORDER BY captured_at DESC LIMIT 1',identity=i)})
        if view=='jobs':
            if len(parts)>3:
                j=db.get_job(i,parts[3]);a=db.one('SELECT * FROM applications WHERE job_id=?',(j['id'],),i)
                active_fill=db.one("SELECT id,state,progress FROM tasks WHERE application_id=? AND kind='fill' AND state IN ('queued','working','waiting_agent','waiting_user','paused','retry_wait') ORDER BY created_at DESC LIMIT 1",(a['id'],),i) if a else None
                return self.send(200,{'job':j,'application':a,'active_fill':active_fill,'application_fields':application_answers.fields(i,a['id']) if a else {},'documents':db.rows('SELECT * FROM documents WHERE application_id=?',(a['id'],),i) if a else [],'sources':db.rows('SELECT * FROM job_sources WHERE job_id=?',(j['id'],),i),'activity':db.rows('SELECT * FROM activity WHERE job_id=? ORDER BY id DESC',(j['id'],),i),'duplicates':db.rows('SELECT * FROM pursuit WHERE vacancy_key=? AND identity!=?',(j['vacancy_key'],i)),'answers':questions.catalog(i)['questions'],'capability':adapters.capability(j['url'])})
            where=['test=0'];args=[]
            if q.get('q'):where.append('(title LIKE ? OR company LIKE ? OR location LIKE ?)');args += ['%'+q['q'][0]+'%']*3
            if q.get('status',['active'])[0]=='active':where.extend(["status NOT IN ('dismissed','outside_preferences')","availability='open'"])
            elif q.get('status') and q['status'][0]!='all':where.append('status=?');args.append(q['status'][0])
            if q.get('recommendation') and q['recommendation'][0]!='all':where.append("json_extract(assessment,'$.recommendation')=?");args.append(q['recommendation'][0])
            clause=' AND '.join(where);total=db.one('SELECT count(*) n FROM jobs WHERE '+clause,args,i)['n'];limit=min(100,max(1,int(q.get('limit',[30])[0])));offset=max(0,int(q.get('offset',[0])[0]))
            order={'new':'found_at DESC','company':'company,title','title':'title','recommended':"CASE json_extract(assessment,'$.recommendation') WHEN 'pursue' THEN 0 WHEN 'consider' THEN 1 WHEN 'needs_information' THEN 2 ELSE 3 END,found_at DESC"}.get(q.get('sort',['new'])[0],'found_at DESC')
            jobs=db.rows('SELECT id,title,company,location,arrangement,posted_at,found_at,last_seen,url,source_id,status,availability,assessment,model,filter_notes FROM jobs WHERE '+clause+' ORDER BY '+order+' LIMIT ? OFFSET ?',(*args,limit,offset),i)
            return self.send(200,{'jobs':jobs,'total':total,'offset':offset,'limit':limit})
        if view=='applications':return self.send(200,application_answers.list_with_question_counts(i,db.rows('SELECT a.*,j.title,j.company,j.location,j.url FROM applications a JOIN jobs j ON j.id=a.job_id WHERE j.test=0 ORDER BY a.updated_at DESC',identity=i)))
        if view=='review' and len(parts)>3:return self.send(200,db.manifest(i,parts[3]))
        if view=='documents':return self.send(200,db.rows('SELECT d.*,j.title,j.company FROM documents d JOIN applications a ON a.id=d.application_id JOIN jobs j ON j.id=a.job_id ORDER BY d.created_at DESC',identity=i))
        if view=='document' and len(parts)>3:
            d=db.one('SELECT * FROM documents WHERE id=?',(parts[3],),i)
            if not d:raise ValueError('Document not found')
            p=db.DATA/i/d['local_path'];return self.send(200,p.read_bytes(),'application/pdf',{'Content-Disposition':f'inline; filename="Candidate-{i}-{d["kind"]}-v{d["version"]}.pdf"'})
        if view=='questions':
            if len(parts)>3:
                item=questions.get(i,parts[3]);item['reuse_policy']=questions.reuse_policy(item['question'],item['category']);return self.send(200,{'question':item,'sharing':sharing.info(i,item['id']),'history':db.rows('SELECT * FROM answer_versions WHERE answer_id=? ORDER BY version DESC',(item['id'],),i),'encounters':db.rows('SELECT e.*,j.company,j.title FROM question_encounters e JOIN applications a ON a.id=e.application_id JOIN jobs j ON j.id=a.job_id WHERE e.answer_id=? ORDER BY e.observed_at DESC',(item['id'],),i),'imports':db.rows('SELECT * FROM answer_imports WHERE answer_id=? ORDER BY observed_at DESC',(item['id'],),i)})
            return self.send(200,questions.catalog(i))
        if view=='readiness':return self.send(200,questions.readiness(i,parts[3]))
        if view=='batch-prompt':return self.send(200,{'prompt':desktop.batch_prompt(i)})
        if view=='settings':return self.send(200,{'preferences':db.get_setting('preferences',{},i),'auto_discovery':db.get_setting('auto_discovery',{'enabled':False,'interval_hours':24},i),'answers':questions.catalog(i)['questions']})
        if view=='tasks':return self.send(200,db.rows("SELECT * FROM tasks WHERE state NOT IN ('completed','stopped') ORDER BY CASE WHEN state='waiting_user' THEN 0 WHEN state='working' THEN 1 ELSE 2 END,created_at DESC",identity=i))
        if view=='runs':return self.send(200,db.rows('SELECT * FROM source_runs ORDER BY started_at DESC LIMIT 100',identity=i))
        if view=='prompt':return self.send(200,{'prompt':desktop.prompt(i,parts[3])})
        if view=='export':return self.send(200,{table:db.rows('SELECT * FROM '+table,identity=i) for table in ('settings','profiles','jobs','job_sources','job_captures','applications','documents','answers','answer_versions','answer_behaviors','question_encounters','answer_imports','approvals','submission_attempts','tasks','activity','source_runs')},headers={'Content-Disposition':f'attachment; filename="job-hunter-{i}.json"'})
        self.error('Not found',404)
    def do_POST(self):
        try:
            if not self.guard(write=True):return
            length=int(self.headers.get('Content-Length',0))
            if length>15_000_000:return self.error('Request too large',413)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.error('JSON required',415)
            body=json.loads(self.rfile.read(length) or '{}');self.post(urlsplit(self.path).path,body)
        except Exception as e:self.error(e)
    def post(self,path,b):
        if path=='/api/notifications':
            if b.get('action')=='configure':return self.send(200,notifications.configure(b.get('enabled') is True))
            if b.get('action')=='test':
                if not notifications.status()['enabled']:raise ValueError('Enable phone alerts first')
                notifications.enqueue('test:'+db.uid(),'Job Hunter connected','Phone alerts are connected. Open Job Hunter to review your saved applications.')
                return self.send(200,{'queued':True})
            raise ValueError('Unknown notification action')
        if path=='/api/agent':
            global LOGIN_PROCESS
            action=b.get('action');i=b.get('identity')
            if action=='login':
                if auth_status()['ok']:return self.send(200,{'connected':True})
                if LOGIN_PROCESS is None or LOGIN_PROCESS.poll() is not None:
                    with (db.DATA/'login.log').open('w') as output:
                        LOGIN_PROCESS=subprocess.Popen([codex_binary(),'login'],stdout=output,stderr=output,env=clean_env(),cwd=db.DATA)
                return self.send(200,{'started':True})
            if action in ('browser-check','inference-check','open-browser','show-task','drive-check','resume-recovery'):
                if AGENT is None:raise ValueError('Restart Job Hunter to connect the local agent')
                if action=='show-task':
                    desktop.task(i,b['id']);AGENT.commands.put(('show-task',(i,b['id'])))
                elif action=='open-browser':
                    sources.public_url(b['url']);AGENT.open(b['url'])
                elif action=='resume-recovery':AGENT.commands.put(('resume-recovery',b['site']))
                elif action=='drive-check':
                    db.set_setting('drive_check',{'running':True,'observed_at':db.now()});AGENT.commands.put(('drive-check',None))
                else:
                    key='browser_check' if action=='browser-check' else 'inference_check'
                    db.set_setting(key,{'running':True,'observed_at':db.now()})
                    AGENT.commands.put(('check' if action=='browser-check' else 'inference',None))
                return self.send(200,{'started':True})
            if action=='enable-site':return self.send(200,adapters.enable(b))
            if action=='resume-account':return self.send(200,resume_accounts.configure(b))
            if action=='mode':
                if b.get('mode') not in ('local_agent','desktop'):raise ValueError('Choose an execution mode')
                db.set_setting('execution_mode',b['mode']);return self.send(200,{'ok':True})
            if i not in db.IDENTITIES:raise ValueError('Choose a role first')
            if action=='resume-import':return self.send(200,onboarding.import_resume(i,b))
            if action=='capture-native-profile':
                id=db.enqueue(i,'refresh_profile');t=desktop.task(i,id)
                if t['state'] in ('waiting_user','paused'):db.task_update(i,id,state='waiting_agent',progress='Waiting to capture the connected native master')
                with db.tx(i) as c:
                    payload=db.unpack(t['payload'],{});payload['execution_mode']='local_agent';c.execute('UPDATE tasks SET payload=? WHERE id=?',(db.dump(payload),id))
                db.set_setting('paused',False)
                return self.send(200,{'task':id})
            if action=='start':return self.send(200,goals.start(i,b))
            if action=='stop':
                goal=db.get_setting('agent_goal',{},i);goal['enabled']=False;db.set_setting('agent_goal',goal,i)
                return self.send(200,goal)
            raise ValueError('Unknown agent action')
        if path=='/api/question-bank/confirm':raise ValueError('The question bank has changed. Refresh to use Mark as reviewed; no answers were changed.')
        if path=='/api/question-bank/review':return self.send(200,reviews.review_many(b))
        if path=='/api/identities':return self.send(200,identities.create(b))
        if path=='/api/control':
            action=b['action']
            if action not in ('pause','start','stop'):raise ValueError('Invalid control')
            db.set_setting('paused',action!='start')
            if action=='start':
                for i,id in db.get_setting('globally_paused_tasks',[]):
                    t=db.one('SELECT * FROM tasks WHERE id=?',(id,),i)
                    if t and t['state']=='paused':db.task_update(i,id,state='waiting_agent' if t['kind'] in desktop.DESKTOP_KINDS else 'queued',next_at=0,progress='Waiting to resume from the saved checkpoint')
                db.set_setting('globally_paused_tasks',[])
            if action in ('pause','stop'):
                paused=[]
                for i in db.IDENTITIES:
                    for t in db.rows("SELECT id,state FROM tasks WHERE state IN ('queued','working','retry_wait','waiting_agent')",identity=i):
                        db.task_update(i,t['id'],state='stopped' if action=='stop' else 'paused',progress='Stopped by you' if action=='stop' else 'Paused by you; completed work saved')
                        db.release_task(i,t['id'])
                        paused.append([i,t['id']])
                db.set_setting('globally_paused_tasks',paused if action=='pause' else [])
            return self.send(200,{'ok':True})
        if path in ('/api/search-both','/api/search-all'):
            db.set_setting('paused',False)
            eligible=[i for i in db.IDENTITIES if db.get_setting('preferences',{},i).get('titles')]
            return self.send(200,{'tasks':{i:db.enqueue(i,'discover',payload={'preferences':db.get_setting('preferences',{},i)}) for i in eligible},'skipped':[db.IDENTITIES[i] for i in db.IDENTITIES if i not in eligible]})
        if path=='/api/backup':return self.send(200,{'name':backup.create_backup().name})
        if path=='/api/open-codex':
            subprocess.Popen(['open','-a','ChatGPT'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            return self.send(200,{'ok':True})
        if path=='/api/source':
            if b.get('action')=='toggle':
                with db.tx() as c:c.execute('UPDATE sources SET enabled=? WHERE id=?',(bool(b['enabled']),b['id']))
            elif b.get('action')=='configure':
                old=db.one('SELECT * FROM sources WHERE id=?',(b['id'],))
                if not old:raise ValueError('Source missing')
                cfg=db.unpack(old['config'],{})
                if 'page_limit' in b:cfg['page_limit']=max(1,min(1000,int(b['page_limit'])))
                with db.tx() as c:c.execute('UPDATE sources SET config=? WHERE id=?',(db.dump(cfg),b['id']))
            else:sources.add_source(b)
            return self.send(200,{'ok':True})
        if path=='/api/account':
            site=b['site'].strip().lower()
            if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',site):raise ValueError('Enter the site hostname, such as jobs.lever.co')
            if b.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',b['email']):raise ValueError('Enter an email address')
            with db.tx() as c:c.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?) ON CONFLICT(site) DO UPDATE SET label=excluded.label,email=excluded.email,paused=excluded.paused,reason=excluded.reason',(site,b.get('label',site),b.get('email',''),'shared',bool(b.get('paused')),b.get('reason','')))
            return self.send(200,{'ok':True})
        if path=='/api/config':
            if 'model' in b:
                if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',b['model']):raise ValueError('Invalid model name')
                if b['model']!=db.get_setting('model'):db.set_setting('inference_check',{})
                db.set_setting('model',b['model'])
            for key in ('batch_size','discovery_concurrency'):
                if key in b:
                    v=int(b[key])
                    if v<1 or v>(20 if key=='discovery_concurrency' else 10000):raise ValueError('Value outside supported range')
                    db.set_setting(key,v)
            return self.send(200,{'ok':True})
        if path=='/api/fixture':
            action=b.get('action')
            if action=='reset':FIXTURE.clear();FIXTURE.update(step='login',completed={},submissions=0)
            elif action=='login':FIXTURE.update(step='form')
            elif action=='save':
                if FIXTURE.get('step')!='form':raise ValueError('Resolve the fixture login first')
                FIXTURE['completed']=b.get('fields',{});FIXTURE['step']='review'
            elif action=='submit':
                if FIXTURE.get('step')!='review' or not b.get('approved'):raise ValueError('Review and approve this fixture first')
                if not FIXTURE.get('completed',{}).get('cv_name'):raise ValueError('Upload the fixture CV first')
                FIXTURE['submissions']=FIXTURE.get('submissions',0)+1
                FIXTURE['receipt']='fixture-'+db.uid();FIXTURE['step']='uncertain' if b.get('uncertain') else 'confirmed'
            elif action=='verify':
                if not FIXTURE.get('receipt'):raise ValueError('No submission receipt exists')
                FIXTURE['step']='confirmed'
            (db.DATA/'fixture.json').write_text(db.dump(FIXTURE))
            return self.send(200,FIXTURE)
        parts=path.strip('/').split('/')
        if len(parts)<3 or parts[1] not in db.IDENTITIES:return self.error('Not found',404)
        i=parts[1];action=parts[2]
        if action=='launch-desktop':
            task=desktop.task(i,b['id'])
            if b.get('mode')=='desktop':
                if task['state'] not in ('waiting_agent','waiting_user','paused'):raise ValueError('This task cannot be handed over while another worker owns it')
                payload=db.unpack(task['payload'],{});payload['execution_mode']='desktop'
                with db.tx(i) as c:c.execute("UPDATE tasks SET payload=?,state='waiting_agent',owner=NULL,lease_until=NULL WHERE id=?",(db.dump(payload),task['id']))
                task=desktop.task(i,task['id'])
            if db.get_setting('execution_mode')=='local_agent' and b.get('mode')!='desktop':
                if task['state'] not in ('waiting_agent','working','completed','waiting_user'):raise ValueError('Resume the task before starting it')
                return self.send(200,{'started':True,'mode':'local_agent','state':task['state']})
            if task['kind'] not in desktop.DESKTOP_KINDS or task['state']!='waiting_agent':
                raise ValueError('This desktop task is not waiting to start')
            # A documented deep link prefills the composer; it cannot send a turn or
            # grant desktop browser/Drive access to a CLI process.
            prompt=desktop.prompt(i,task['id'])
            url='codex://new?path='+quote(str(desktop.workspace()),safe='')+'&prompt='+quote(prompt,safe='')
            subprocess.run(['/usr/bin/open',url],check=True,timeout=10,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            return self.send(200,{'opened':True,'sent':False,'state':task['state']})
        if action=='setup':return self.send(200,identities.update(i,b))
        if action=='preferences':
            allowed={'titles','locations','countries','arrangements','seniority','industries','employment_types','exclusions','minimum_salary','currency','salary_period','posting_age_days','work_authorization','timezone','confirmed','include_early_career'}
            if set(b)-allowed:raise ValueError('Unsupported preference')
            for k in ('titles','locations','countries','arrangements','seniority','industries','employment_types','exclusions'):
                if not isinstance(b.get(k,[]),list) or any(not isinstance(x,str) for x in b.get(k,[])):raise ValueError('Invalid preference list')
            for k in ('minimum_salary','posting_age_days'):
                if b.get(k) is not None and float(b[k])<0:raise ValueError('Values must not be negative')
            b['confirmed']=True
            if b==db.get_setting('preferences',{},i):return self.send(200,{'ok':True,'unchanged':True})
            db.set_setting('preferences',b,i)
            with db.tx(i) as c:
                c.execute('UPDATE jobs SET assessment_context_hash=NULL WHERE assessment IS NOT NULL')
                for row in c.execute("SELECT * FROM jobs WHERE status IN ('found','outside_preferences')").fetchall():
                    job=dict(row)
                    for field in ('salary','country_restrictions'):job[field]=db.unpack(job[field],None)
                    included,notes=sources.filter_job(job,b)
                    c.execute('UPDATE jobs SET status=?,filter_notes=? WHERE id=?',('found' if included else 'outside_preferences',db.dump(notes),job['id']))
                db.log(c,'Search preferences updated','Existing discoveries filtered again. Shortlists and profile facts unchanged; assessments require review against new preferences')
            return self.send(200,{'ok':True})
        if action=='auto-discovery':
            enabled=b.get('enabled') is True
            hours=int(b.get('interval_hours',24))
            if hours<6 or hours>168:raise ValueError('Choose an interval from 6 hours to 7 days')
            prefs=db.get_setting('preferences',{},i)
            if enabled and (not prefs.get('confirmed') or not prefs.get('titles')):raise ValueError('Save this role’s search preferences before starting scheduled searches')
            previous=db.get_setting('auto_discovery',{},i)
            db.set_setting('auto_discovery',{'enabled':enabled,'interval_hours':hours,'last_requested_at':previous.get('last_requested_at',0) if enabled and previous.get('enabled') else 0},i)
            with db.tx(i) as c:db.log(c,'Scheduled search '+('enabled' if enabled else 'disabled'),f'Every {hours} hours while Job Hunter is running')
            return self.send(200,{'ok':True,'enabled':enabled})
        if action=='address-preview':return self.send(200,{'parts':addressing.extract(b.get('value',''))})
        if action=='question-policy':return self.send(200,questions.reuse_policy(b.get('question','')))
        if action=='sharing-preview':return self.send(200,sharing.preview(i,b))
        if action in ('answer','question'):
            if 'availability' in b:return self.send(200,sharing.save(i,b))
            return self.send(200,{'id':questions.save(i,b)})
        if action=='confirm-questions':
            ids=b.get('ids',[])
            if not ids or len(ids)>200:raise ValueError('Select up to 200 displayed answers')
            for id in ids:
                row=questions.get(i,id)
                if row['reuse_scope']!='identity' or row['category'] in ('sensitive','compensation','search_preferences','motivation') or not row['value'] or row['review_note']:raise ValueError('Review contextual, conflicting or blank answers individually')
                if b.get('versions',{}).get(id)!=row['version']:raise ValueError('An answer changed. Reload before confirming.')
            for id in ids:
                row=questions.get(i,id);questions.save(i,{'id':id,'value':row['value'],'confirmed':True,'expires_at':row['expires_at'],'expected_version':b['versions'][id]})
            return self.send(200,{'confirmed':len(ids)})
        if action=='reuse-answers':return self.send(200,questions.apply_to_application(i,b['application_id']))
        if action=='prepare-batch':
            ready=db.rows("SELECT id,job_id FROM applications WHERE document_state='not_started' AND state='shortlisted' ORDER BY created_at LIMIT ?",(int(db.get_setting('batch_size',5)),),i)
            tasks=[]
            for a in ready:
                tasks.append(db.enqueue(i,'prepare',a['job_id'],application_id=a['id']))
                with db.tx(i) as c:c.execute("UPDATE applications SET document_state='waiting_agent' WHERE id=?",(a['id'],))
            return self.send(200,{'tasks':tasks})
        if action=='task':
            if b.get('action') in ('resume','pause','stop'):
                t=desktop.task(i,b['id'])
                if b['action']=='resume':
                    if t['application_id'] and db.application(i,t['application_id'])['state']=='submitted':raise ValueError('The employer already confirmed this application; there is nothing to resume')
                    if t['state'] not in ('paused','waiting_user','waiting_agent','failed','retry_wait','stopped'):raise ValueError('This task is not waiting to resume')
                    state='waiting_agent' if t['kind'] in desktop.DESKTOP_KINDS else 'queued';db.set_setting('paused',False)
                    db.task_update(i,t['id'],state=state,next_at=0,error=None,attempts=0,progress='Waiting for the agent to re-check the saved page' if state=='waiting_agent' else 'Waiting for local worker')
                else:
                    db.task_update(i,t['id'],state='paused' if b['action']=='pause' else 'stopped',progress='Paused by you' if b['action']=='pause' else 'Stopped by you')
                    db.release_task(i,t['id'])
                return self.send(200,{'ok':True})
            kind=b['kind'];jid=b.get('job_id');aid=b.get('application_id')
            if kind in ('fill','submit'):db.verify_approval(i,aid,'fill' if kind=='fill' else 'submit')
            if kind=='prepare':
                a=db.application(i,aid)
                if a['state']=='submitted':raise ValueError('This application is already confirmed submitted')
                with db.tx(i) as c:c.execute("UPDATE applications SET document_state='waiting_agent' WHERE id=?",(aid,))
            payload={'preferences':db.get_setting('preferences',{},i)} if kind=='discover' else b.get('payload',{})
            return self.send(200,{'id':db.enqueue(i,kind,jid,payload,aid)})
        if action=='assess-batch':
            batch=int(db.get_setting('batch_size',5));profile=db.one('SELECT id FROM profiles WHERE source_id=? ORDER BY captured_at DESC LIMIT 1',(db.MASTER_IDS.get(i),),i)
            jobs=db.rows("SELECT id FROM jobs WHERE test=0 AND availability='open' AND status NOT IN ('dismissed','outside_preferences') AND (assessment IS NULL OR assessment_jd_hash!=description_hash OR assessment_context_hash IS NULL OR assessment_profile!=?) AND description!='' ORDER BY found_at DESC LIMIT ?",(profile['id'] if profile else '',batch),i)
            return self.send(200,{'tasks':[db.enqueue(i,'assess',j['id']) for j in jobs]})
        if action=='shortlist':return self.send(200,db.shortlist(i,b['job_id'],bool(b.get('ack_duplicate'))))
        if action=='feedback':
            db.get_job(i,b['job_id'])
            with db.tx(i) as c:
                c.execute('UPDATE jobs SET feedback=?,assessment_context_hash=NULL,status=CASE WHEN ? THEN \'dismissed\' ELSE status END WHERE id=?',(b.get('feedback',''),bool(b.get('dismiss')),b['job_id']));db.log(c,'Recommendation feedback saved',b.get('feedback',''),b['job_id'])
            return self.send(200,{'ok':True})
        if action=='application':
            a=db.application(i,b['id'])
            if a['state']=='submitted' and b['action'] in ('answer_batch','answers','documents'):raise ValueError('Submitted application answers and document selection are fixed')
            if b['action']=='answer_batch':return self.send(200,application_answers.save_batch(i,a['id'],b))
            if b['action']=='approve':return self.send(200,{'approval_id':db.approve(i,a['id'],b.get('scope','fill'))})
            if b['action']=='answers':
                answers=b['answers']
                if not isinstance(answers,dict):raise ValueError('Invalid answers')
                if any(not isinstance(v,dict) or not isinstance(v.get('value'),str) or not isinstance(v.get('confirmed'),bool) for v in answers.values()):raise ValueError('Use text answers with confirmation status')
                for question,value in answers.items():
                    old_answer=a['answers'].get(question)
                    if value!=old_answer:
                        if value.get('answer_id'):
                            saved=questions.get(i,value['answer_id'])
                            if saved['answer_mode']=='jd_choice' and value['value']==saved['value']:raise ValueError('Choose one approved alternative using the application agent; do not paste the entire list')
                        observed=questions.observe(i,[{'question':question}],a['id'],db.get_job(i,a['job_id'])['url'],apply=False)
                        qid=observed['questions'][0]['id'];bank=questions.get(i,qid)
                        if value['value'] and not bank['confirmed'] and bank['answer_mode']=='single':questions.save(i,{'id':qid,'value':value['value'],'confirmed':False},provenance='Answer from '+db.get_job(i,a['job_id'])['company']+' application; review before general reuse')
                with db.tx(i) as c:c.execute('UPDATE applications SET answers=?,approval_id=NULL,updated_at=? WHERE id=?',(db.dump(answers),db.now(),a['id']))
            elif b['action']=='documents':
                kinds=[]
                for did in b['ids']:
                    doc=db.one('SELECT kind FROM documents WHERE id=? AND application_id=?',(did,a['id']),i)
                    if not doc:raise ValueError('Document role mismatch')
                    if doc['kind'] in kinds:raise ValueError('Select only one version of each document type')
                    kinds.append(doc['kind'])
                with db.tx(i) as c:c.execute('UPDATE applications SET selected_documents=?,approval_id=NULL,updated_at=? WHERE id=?',(db.dump(b['ids']),db.now(),a['id']))
            elif b['action']=='outcome':
                if b['state'] not in ('interview','offer','rejected','withdrawn','verification_needed'):raise ValueError('Use the evidence workflow to record a submission')
                with db.tx(i) as c:c.execute('UPDATE applications SET state=?,notes=?,updated_at=? WHERE id=?',(b['state'],b.get('notes',''),db.now(),a['id']));db.log(c,'Outcome updated',b['state']+' '+b.get('notes',''),a['job_id'])
                db.reconcile_pursuits()
            else:raise ValueError('Unknown application action')
            return self.send(200,{'ok':True})
        return self.error('Not found',404)

def serve(port=8766):
    global RUNNER,AGENT,PORT,FIXTURE,NOTIFIER,DOCUMENTS
    os.umask(0o077);db.DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    service_lock=(db.DATA/'service.lock').open('a')
    try:
        if os.name=='nt':
            import msvcrt
            service_lock.write('0');service_lock.flush();service_lock.seek(0);msvcrt.locking(service_lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(service_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except (BlockingIOError,OSError):raise RuntimeError('Job Hunter is already running with this database')
    db.init();sources.seed()
    if (db.DATA/'fixture.json').exists():FIXTURE=db.unpack((db.DATA/'fixture.json').read_text(),{})
    for candidate in range(port,port+20):
        try:s=ThreadingHTTPServer(('127.0.0.1',candidate),Handler);PORT=candidate;break
        except OSError:continue
    else:raise RuntimeError('No free local port in the selected range')
    db.DATA.joinpath('server.pid').write_text(str(os.getpid()));db.DATA.joinpath('port').write_text(str(PORT))
    (db.DATA/'stop.request').unlink(missing_ok=True)
    # A local launcher creates one-use connection links via a protected owner-only file.
    def link_loop():
        while True:
            path=db.DATA/'connect.request'
            if path.exists():
                try:
                    token=path.read_text().strip();path.unlink()
                    if re.fullmatch('[A-Za-z0-9_-]{32,100}',token):BOOTSTRAP[token]=time.time()+120
                except OSError:pass
            stop_request=db.DATA/'stop.request'
            if stop_request.exists():
                stop_request.unlink(missing_ok=True);shutdown();return
            time.sleep(.1)
    threading.Thread(target=link_loop,daemon=True).start()
    RUNNER=Runner();RUNNER.start()
    from .agent import AgentRunner,DocumentRunner
    AGENT=AgentRunner();AGENT.start()
    DOCUMENTS=DocumentRunner();DOCUMENTS.start()
    NOTIFIER=notifications.Notifier();NOTIFIER.start()
    def shutdown(*_):
        AGENT.stop();DOCUMENTS.stop();RUNNER.stop();NOTIFIER.stop()
        # Let the browser worker restore an account-wide résumé before closing.
        def finish_shutdown():
            if AGENT.thread:AGENT.thread.join(timeout=90)
            if DOCUMENTS.thread:DOCUMENTS.thread.join(timeout=10)
            threading.Thread(target=s.shutdown,daemon=True).start()
        threading.Thread(target=finish_shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    print(f'Job Hunter listening at http://127.0.0.1:{PORT}',flush=True)
    try:s.serve_forever(poll_interval=.3)
    finally:s.server_close();(db.DATA/'server.pid').unlink(missing_ok=True)
