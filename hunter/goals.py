"""Continue useful work across stages while a single application needs help."""
import time
from . import db,sources
from .worker import assessment_hash


def start(identity,config):
    from . import onboarding
    ready=onboarding.readiness(identity)
    missing=[]
    if not ready['auth']['ok']:missing.append('ChatGPT sign-in')
    if not ready['profile']:missing.append('a captured profile or uploaded résumé')
    if not ready['preferences']:missing.append('confirmed job preferences')
    if not ready['inference_check'].get('ok'):missing.append('a successful ChatGPT connection check')
    if not ready['browser_check'].get('ok'):missing.append('a successful browser and upload check')
    if missing:raise ValueError('Finish Setup first: '+', '.join(missing))
    maximum=int(config.get('max_applications',5))
    if not 1<=maximum<=50:raise ValueError('Choose between 1 and 50 applications per run')
    goal={'enabled':True,'stage':'review','started_at':db.now(),'max_applications':maximum,'discovery_requested':False}
    db.set_setting('agent_goal',goal,identity);db.set_setting('execution_mode','local_agent');db.set_setting('paused',False)
    return goal


def tick():
    for i in db.IDENTITIES:
        goal=db.get_setting('agent_goal',{},i)
        if not goal.get('enabled'):continue
        if not goal.get('discovery_requested'):
            db.enqueue(i,'discover');goal['discovery_requested']=True;db.set_setting('agent_goal',goal,i)
        active=db.rows("SELECT kind,job_id,application_id,state FROM tasks WHERE state NOT IN ('completed','stopped')",identity=i)
        assessment_count=sum(t['kind']=='assess' and t['state'] in ('queued','working') for t in active)
        profile=db.one('SELECT id FROM profiles WHERE source_id=? ORDER BY captured_at DESC LIMIT 1',(db.MASTER_IDS.get(i),),i)
        if not profile:continue
        candidates=db.rows("SELECT * FROM jobs WHERE test=0 AND availability='open' AND status NOT IN ('dismissed','outside_preferences') AND description<>'' ORDER BY found_at DESC",identity=i)
        for raw in candidates:
            j=db.get_job(i,raw['id'])
            ok,_=sources.filter_job(j,db.get_setting('preferences',{},i))
            if not ok:continue
            fresh=j['assessment'] and j['assessment_profile']==profile['id'] and j['assessment_jd_hash']==j['description_hash'] and j.get('assessment_context_hash')==assessment_hash(profile,j,db.get_setting('preferences',{},i))
            if not fresh:
                if assessment_count<min(3,int(db.get_setting('batch_size',5))) and not any(t['kind']=='assess' and t['job_id']==j['id'] for t in active):
                    db.enqueue(i,'assess',j['id']);assessment_count+=1
                continue
            a=j['assessment']
            if a['recommendation']!='pursue' or a['eligibility']['status']!='confirmed' or any(r['mandatory'] and r['status']!='met' for r in a['requirements']):continue
            existing=db.one('SELECT * FROM applications WHERE job_id=?',(j['id'],),i)
            count=db.one('SELECT count(*) n FROM applications WHERE created_at>=?',(goal['started_at'],),i)['n']
            if not existing:
                if count>=goal['max_applications']:continue
                try:existing=db.shortlist(i,j['id'])
                except ValueError:continue # A duplicate in another role remains reviewable.
            if existing['state'] in ('submitted','verification_needed','rejected','withdrawn','interview','offer'):continue
            if existing['document_state']!='prepared':
                done=db.one("SELECT id FROM tasks WHERE application_id=? AND kind='prepare' AND state='completed'",(existing['id'],),i)
                if not done:db.enqueue(i,'prepare',j['id'],application_id=existing['id'])
            elif not db.one('SELECT id FROM question_encounters WHERE application_id=? AND active=1 LIMIT 1',(existing['id'],),i):
                db.enqueue(i,'scan_form',j['id'],application_id=existing['id'])
            if existing['state']=='ready_to_fill':db.enqueue(i,'fill',j['id'],application_id=existing['id'])
            if existing.get('approval_id'):
                approval=db.one('SELECT scope,used_at FROM approvals WHERE id=?',(existing['approval_id'],),i)
                if approval and approval['scope']=='submit' and not approval['used_at']:db.enqueue(i,'submit',j['id'],application_id=existing['id'])
