"""Atomic, role-bound edits to several application answers at once."""
import re
from . import db,questions,answer_choices

def field_version(field):
    return db.digest({k:field[k] for k in ('answer_id','question','choices','required','field_type','max_length')}) if field else None

def list_with_question_counts(identity, applications):
    by_app={a['id']:[] for a in applications}
    if not by_app:return applications
    for field in db.rows('SELECT application_id,question FROM question_encounters WHERE active=1',identity=identity):
        if field['application_id'] in by_app:by_app[field['application_id']].append(field['question'])
    for app in applications:
        answers=db.unpack(app['answers'],{});labels=by_app[app['id']]
        app['form_questions_total']=len(labels)
        app['form_questions_to_review']=sum(not answers.get(label,{}).get('confirmed') for label in labels)
    return applications

def fields(identity,application_id):
    rows=db.rows('SELECT * FROM question_encounters WHERE application_id=? AND active=1 ORDER BY rowid',(application_id,),identity)
    app=db.application(identity,application_id);job=db.get_job(identity,app['job_id']);result={}
    for position,f in enumerate(rows):
        bank=questions.get(identity,f['answer_id']);choices=db.unpack(f['choices'],[])
        specific=questions.application_only(f['question'],bank['category'],job['company'],f['field_type'],True)
        same_application_source=bool(bank['source_url']) and bank['source_url']==f['source_url']
        candidate=bank['value'] if (not specific or same_application_source) and bank['answer_mode']=='single' and not bank['review_note'] and (not choices or bank['value'] in choices) and (not f['max_length'] or len(bank['value'])<=f['max_length']) else ''
        result[f['question']]=dict(f,position=position,field_version=field_version(f),suggestion=candidate,suggestion_source=bank['provenance'] if candidate else None,bank_id=bank['id'],bank_version=bank['version'],application_only=specific)
    return result

def save_batch(identity,application_id,data):
    edits=data.get('edits')
    if data.get('confirmed') is not True:raise ValueError('Confirm that the answers you are saving are accurate for this application')
    if not isinstance(edits,list) or not 1<=len(edits)<=100:raise ValueError('Add between 1 and 100 question–answer pairs')
    with db.LOCK,db.tx(identity) as c:
        record=c.execute('SELECT * FROM applications WHERE id=?',(application_id,)).fetchone()
        if not record:raise ValueError('Application not found in this role')
        app=dict(record);job=c.execute('SELECT company,description_hash FROM jobs WHERE id=?',(app['job_id'],)).fetchone();answers=db.unpack(app['answers'],{});seen=set();plan=[]
        observed={f['question']:dict(f) for f in c.execute('SELECT * FROM question_encounters WHERE application_id=? AND active=1',(application_id,))}
        # Validate the full batch before creating bank entries or changing the application.
        for edit in edits:
            if not isinstance(edit,dict):raise ValueError('Use one question and one answer per row')
            label=edit.get('question');value=edit.get('value')
            if not isinstance(label,str) or not label.strip() or len(label)>5000:raise ValueError('Enter a question for each answer')
            label=label.strip();key=questions.normal(label)
            if key in seen:raise ValueError('“'+label+'” appears twice. Keep one answer per question.')
            seen.add(key)
            if not isinstance(value,str) or not value.strip() or len(value)>50000:raise ValueError('Enter an answer for “'+label+'”')
            if re.search(r'\b(password|passcode|otp|one time password|security answer|social security number|passport number|api key|access token)\b',key):raise ValueError('Enter credentials and sensitive identifiers directly on the website')
            old=answers.get(label)
            if 'expected' not in edit or edit['expected']!=old:raise ValueError('“'+label+'” changed since you opened it. Reopen the application to review the latest answer; your draft is kept.')
            field=observed.get(label)
            if 'field_version' not in edit or edit['field_version']!=field_version(field):raise ValueError('The form changed for “'+label+'”. Reopen the application and review its current choices.')
            category=questions.classify(label)[0]
            specific=questions.application_only(label,category,job['company'],field['field_type'] if field else '',True)
            if field:
                choices=db.unpack(field['choices'],[])
                if choices and value not in choices:raise ValueError('Choose one of the form’s current options for “'+label+'”')
                if field['max_length'] and len(value)>field['max_length']:raise ValueError('“'+label+'” exceeds the form’s character limit')
                bank=c.execute('SELECT * FROM answers WHERE id=?',(field['answer_id'],)).fetchone()
            else:
                canonical=questions.ALIASES.get(key,key);context={'application_id':application_id} if specific else {};question_key=db.digest({'question':canonical,'context':context})
                bank=c.execute('SELECT * FROM answers WHERE question_key=?',(question_key,)).fetchone()
            if bank:
                bank=dict(bank);behavior=c.execute('SELECT mode FROM answer_behaviors WHERE answer_id=? AND version=?',(bank['id'],bank['version'])).fetchone()
                if behavior and behavior['mode']=='jd_choice' and value==bank['value']:raise ValueError('Choose one alternative for “'+label+'”, not the whole list')
            source=None
            if edit.get('bank_id'):
                if specific:raise ValueError('Enter this answer for the application, not from the shared Question bank')
                source=c.execute('SELECT * FROM answers WHERE id=?',(edit['bank_id'],)).fetchone()
                if not source or not bank or source['id']!=bank['id'] or edit.get('bank_version')!=source['version'] or not source['confirmed'] or questions.state(dict(source))!='ready' or source['value']!=value:raise ValueError('The saved bank answer changed. Add it again or enter your answer directly.')
                source=dict(source)
            plan.append((label,value,old,bank,source,specific))
        for label,value,old,bank,source,specific in plan:
            if not bank:
                qid=db.uid();category,scope=questions.classify(label);canonical=questions.ALIASES.get(questions.normal(label),questions.normal(label));context={'application_id':application_id} if specific else {};key=db.digest({'question':canonical,'context':context})
                if specific:category='application_only'
                # A manual question is recorded without pretending that its employer form was inspected.
                c.execute('INSERT INTO answers(id,question,value,provenance,confirmed,updated_at,question_key,category,reuse_scope,first_seen,last_seen,context,version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (qid,label,'' if specific else value,'Entered for one application' if specific else 'Entered for one application; review before general reuse',0,db.now(),key,category,scope,db.now(),db.now(),db.dump(context),1))
                c.execute('INSERT INTO answer_versions VALUES(?,?,?,?,?,?,?,?)',(db.uid(),qid,1,'' if specific else value,0,'Entered for one application' if specific else 'Entered for one application; review before general reuse',None,db.now()))
                answer_choices.save_behavior(c,qid,1,'single');bank={'id':qid}
            elif not specific and not bank['value'] and not bank['confirmed'] and not bank['review_note']:
                version=bank['version']+1;provenance='Entered for application '+application_id+'; review before general reuse'
                c.execute('INSERT INTO answer_versions VALUES(?,?,?,?,?,?,?,?)',(db.uid(),bank['id'],version,value,0,provenance,None,db.now()))
                answer_choices.save_behavior(c,bank['id'],version,'single')
                c.execute('UPDATE answers SET value=?,version=?,provenance=?,updated_at=? WHERE id=?',(value,version,provenance,db.now(),bank['id']))
            snapshot={'value':value,'confirmed':True,'provenance':'Confirmed by you for this application','answer_id':bank['id']}
            if source:snapshot.update(provenance=source['provenance'],answer_version=source['version'],expires_at=source['expires_at'])
            elif old and old.get('value')==value:
                snapshot={**old,**snapshot,'expires_at':None}
                if snapshot.get('selection'):
                    if snapshot['selection']['job_hash']!=job['description_hash']:snapshot.pop('selection')
            answers[label]=snapshot
        c.execute('UPDATE applications SET answers=?,approval_id=NULL,updated_at=? WHERE id=?',(db.dump(answers),db.now(),application_id))
        db.log(c,'Application answers saved together',str(len(plan))+' separate answers confirmed: '+', '.join(p[0] for p in plan),app['job_id'])
    return {'saved':len(plan)}
