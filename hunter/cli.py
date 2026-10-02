import argparse,json,sys
from pathlib import Path
from . import db,desktop,backup,sources,questions,answer_choices

def main():
    db.init()
    p=argparse.ArgumentParser(description='Job Hunter local task interface')
    p.add_argument('action',choices=['queue','context','claim','checkpoint','complete','document','draft-answers','select-answer','observe-questions','import-profile-answers','import-jobs','profile','source-check','begin-submission','submission-result','external-submission','backup','restore'])
    p.add_argument('--identity',choices=list(db.IDENTITIES));p.add_argument('--task');p.add_argument('--owner',default='desktop-agent');p.add_argument('--file');p.add_argument('--metadata');p.add_argument('--blocked',action='store_true');p.add_argument('--destination');p.add_argument('--application');p.add_argument('--attempt')
    a=p.parse_args()
    def read(path):return json.loads(Path(path).read_text())
    if a.action=='backup':r={'path':str(backup.create_backup())}
    elif a.action=='restore':r={'previous':str(backup.restore_backup(a.file,a.destination))}
    else:
        if not a.identity:p.error('--identity is required')
        if a.action=='queue':r=db.rows("SELECT id,kind,state,progress FROM tasks WHERE state NOT IN ('completed','stopped') ORDER BY created_at",identity=a.identity)
        elif a.action=='context':r=desktop.context(a.identity,a.task)
        elif a.action=='claim':r=desktop.claim(a.identity,a.task,a.owner)
        elif a.action=='checkpoint':desktop.checkpoint(a.identity,a.task,a.owner,read(a.file),a.blocked);r={'saved':True}
        elif a.action=='complete':desktop.finish(a.identity,a.task,a.owner,read(a.file));r={'completed':True}
        elif a.action=='document':r={'document_id':desktop.register_document(a.identity,a.task,a.owner,read(a.metadata),a.file)}
        elif a.action=='draft-answers':desktop.draft_answers(a.identity,a.task,a.owner,read(a.file));r={'saved':True,'confirmed':False}
        elif a.action=='select-answer':r=answer_choices.select(a.identity,a.task,a.owner,read(a.file))
        elif a.action=='observe-questions':r=desktop.observe_questions(a.identity,a.task,a.owner,read(a.file))
        elif a.action=='import-profile-answers':
            data=read(a.file);r=questions.import_profile(a.identity,data['items'],data['source_url'])
        elif a.action=='profile':r=db.capture_profile(a.identity,read(a.file))
        elif a.action=='source-check':desktop.source_check(a.identity,a.task,a.owner,read(a.file));r={'saved':True}
        elif a.action=='begin-submission':
            desktop.ensure_owner(a.identity,a.task,a.owner)
            from . import adapters
            t=desktop.task(a.identity,a.task)
            if t['kind']!='submit' or t['application_id']!=a.application:raise ValueError('Use this application’s submission task')
            adapters.require_submission(db.get_job(a.identity,t['job_id'])['url'])
            r={'attempt_id':db.begin_submission(a.identity,a.application)}
        elif a.action=='submission-result':
            t=desktop.ensure_owner(a.identity,a.task,a.owner)
            if t['kind'] not in ('submit','verify') or t['application_id']!=a.application:raise ValueError('Use this application’s submission or verification task')
            data=read(a.file)
            if data['state']=='confirmed':
                from . import adapters
                evidence=data['evidence'];job=db.get_job(a.identity,t['job_id'])
                if not evidence.get('page_rechecked') or not evidence.get('form_absent'):raise ValueError('Re-check the employer confirmation page and absence of the application form')
                if not adapters.confirmation({'url':evidence['url'],'text':evidence.get('confirmation_text',''),'elements':[]},job):raise ValueError('Confirmation must match this application’s configured employer destination')
            db.submission_result(a.identity,a.application,a.attempt,data['state'],data['evidence']);r={'recorded':True}
        elif a.action=='external-submission':
            if not a.application or not a.file:raise ValueError('Application and observed confirmation evidence are required')
            r=db.record_external_submission(a.identity,a.application,read(a.file))
        elif a.action=='import-jobs':
            t=desktop.ensure_owner(a.identity,a.task,a.owner)
            if t['kind']!='web_discovery':raise ValueError('Job imports require a web-discovery task')
            ids=[]
            for j in read(a.file):
                if not j.get('description') or not j.get('observed_at'):raise ValueError('A live job needs captured description and observed_at evidence')
                ok,notes=sources.filter_job(j,db.unpack(t['payload'],{}).get('preferences',db.get_setting('preferences',{},a.identity)))
                if ok:j['filter_notes']=notes;ids.append(db.upsert_job(a.identity,j))
            r={'imported':ids}
    print(db.dump(r))
if __name__=='__main__':
    try:main()
    except Exception as e:print(db.dump({'error':str(e)}),file=sys.stderr);sys.exit(1)
