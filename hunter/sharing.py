"""Explicit sharing of answer-bank values; application snapshots remain independent."""
import re
from datetime import date
from . import db,questions,answer_choices

def migrate():
    with db.tx() as c:
        c.execute('CREATE TABLE IF NOT EXISTS answer_shares(identity TEXT NOT NULL,answer_id TEXT NOT NULL,group_id TEXT NOT NULL,mode TEXT NOT NULL,PRIMARY KEY(identity,answer_id),UNIQUE(group_id,identity))')
        c.execute('CREATE TABLE IF NOT EXISTS answer_share_operations(id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')

def info(identity,qid):
    row=db.one('SELECT * FROM answer_shares WHERE identity=? AND answer_id=?',(identity,qid))
    if not row:return {'mode':'this','identities':[identity]}
    members=db.rows('SELECT identity FROM answer_shares WHERE group_id=?',(row['group_id'],))
    return {'mode':row['mode'],'identities':[r['identity'] for r in members]}

def targets(identity,data):
    mode=data.get('availability','this')
    if mode not in ('this','all','selected'):raise ValueError('Choose this role, all roles or selected roles')
    selected=list(db.IDENTITIES) if mode=='all' else data.get('identities',[]) if mode=='selected' else [identity]
    if not isinstance(selected,list) or not selected or any(i not in db.IDENTITIES for i in selected):raise ValueError('Choose valid roles')
    return mode,([identity] if identity in selected else [])+[i for i in dict.fromkeys(selected) if i!=identity]

def preview(identity,data):
    mode,selected=targets(identity,data)
    source=questions.get(identity,data['id']) if data.get('id') else None
    label=source['question'] if source else data.get('question','')
    context=db.unpack(source['context'],{}) if source else data.get('context',{})
    key=db.digest({'question':questions.ALIASES.get(questions.normal(label),questions.normal(label)),'context':context})
    rows=[]
    for i in selected:
        row=source if i==identity and source else db.one('SELECT * FROM answers WHERE question_key=?',(key,),i)
        if row:answer_choices.enrich(i,row)
        source_share=db.one('SELECT group_id FROM answer_shares WHERE identity=? AND answer_id=?',(identity,source['id'])) if source else None
        target_share=db.one('SELECT group_id FROM answer_shares WHERE identity=? AND answer_id=?',(i,row['id'])) if row else None
        already_shared=bool(source and row and source_share and target_share and source_share['group_id']==target_share['group_id'] and row['value']==source['value'] and row['answer_mode']==source['answer_mode'])
        rows.append({'identity':i,'id':row['id'] if row else None,'version':row['version'] if row else None,
            'value':row['value'] if row else '', 'conflict':bool(i!=identity and row and row['value'] and (row['value']!=data.get('value','') or row['answer_mode']!=data.get('answer_mode',source['answer_mode'] if source else 'single')) and not already_shared)})
    return {'mode':mode,'targets':rows}

def save(identity,data):
    with db.LOCK:
        plan=preview(identity,data);source=questions.get(identity,data['id']) if data.get('id') else None
        if source and data.get('expected_version')!=source['version']:raise ValueError('This answer changed. Reload before saving.')
        if len(plan['targets'])>1 or any(r['identity']!=identity for r in plan['targets']):
            if any(data.get('target_versions',{}).get(r['identity'],'missing')!=r['version'] for r in plan['targets']):raise ValueError('Review the current answers in each selected role before saving')
            if any(r['conflict'] for r in plan['targets']) and not data.get('replace_conflicts'):raise ValueError('Review the different saved answers before replacing them')
        # Validate before starting a durable multi-identity operation.
        label=source['question'] if source else data.get('question','');value=data.get('value','')
        if not isinstance(label,str) or not label.strip() or len(label)>5000:raise ValueError('Enter a valid question')
        if not isinstance(value,str) or len(value)>50000:raise ValueError('Enter a valid text answer')
        if data.get('confirmed') and not value.strip():raise ValueError('Enter an answer before confirming it')
        if value and re.search(r'\b(password|passcode|otp|one time password|security answer|social security number|passport number|api key|access token)\b',questions.normal(label)):raise ValueError('Do not save credentials or sensitive identifiers in the question bank')
        expires=data.get('expires_at') or None
        if expires:date.fromisoformat(expires)
        category=source['category'] if source else questions.classify(label)[0]
        scope=questions.enforced_scope(label,category,data.get('reuse_scope',source['reuse_scope'] if source else None))
        mode=data.get('answer_mode',source['answer_mode'] if source else 'single');answer_choices.validate(label,category,value,mode)
        context=db.unpack(source['context'],{}) if source else data.get('context',{})
        previous=db.one('SELECT group_id FROM answer_shares WHERE identity=? AND answer_id=?',(identity,source['id'])) if source and any(r['identity']==identity for r in plan['targets']) else None
        payload={'identity':identity,'group_id':previous['group_id'] if previous else db.uid(),'mode':plan['mode'],
            'targets':plan['targets'],'source_id':source['id'] if source else None,'question':label,'value':value,
            'answer_mode':mode,'confirmed':bool(data.get('confirmed')),'reuse_scope':scope,'expires_at':expires,'category':category,'context':context}
        # A partially completed write can resume after restart, without repeating a version.
        op=db.uid()
        with db.tx() as c:c.execute('INSERT INTO answer_share_operations VALUES(?,?,?,NULL,?,?)',(op,db.dump(payload),'pending',db.now(),db.now()))
        return _apply(op,payload)

def _apply(op,payload):
    try:
        for item in payload['targets']:
            i=item['identity'];qid=item['id'] or questions.ensure(i,payload['question'],payload['context'],category=payload['category'],reuse_scope=payload['reuse_scope'])
            row=questions.get(i,qid);provenance='Confirmed/edited by you · answer sharing '+op
            if row['provenance']!=provenance:
                if row['version']!=(item['version'] or 0):raise ValueError('An answer changed while sharing was pending. Review and save it again.')
                questions.save(i,{'id':qid,'answer_mode':payload.get('answer_mode','single'),'value':payload['value'],'confirmed':payload['confirmed'],'reuse_scope':payload['reuse_scope'],'expires_at':payload['expires_at'],'expected_version':row['version']},provenance)
            item['id']=qid
        with db.tx() as c:
            # Leaving a group keeps its last copies as independent local answers.
            if payload['mode']=='this':
                c.execute('DELETE FROM answer_shares WHERE identity=? AND answer_id=?',(payload['identity'],payload['targets'][0]['id']))
            else:
                c.execute('DELETE FROM answer_shares WHERE group_id=?',(payload['group_id'],))
                for item in payload['targets']:
                    c.execute('INSERT INTO answer_shares VALUES(?,?,?,?) ON CONFLICT(identity,answer_id) DO UPDATE SET group_id=excluded.group_id,mode=excluded.mode',(item['identity'],item['id'],payload['group_id'],payload['mode']))
            c.execute('DELETE FROM answer_shares WHERE group_id IN (SELECT group_id FROM answer_shares GROUP BY group_id HAVING count(*)<2)')
            # A group that no longer covers all roles must not claim all-role scope.
            c.execute("UPDATE answer_shares SET mode='selected' WHERE mode='all' AND group_id IN (SELECT group_id FROM answer_shares GROUP BY group_id HAVING count(*)<>?)",(len(db.IDENTITIES),))
            c.execute("UPDATE answer_share_operations SET state='completed',payload=?,error=NULL,updated_at=? WHERE id=?",(db.dump(payload),db.now(),op))
        return {'id':next((x['id'] for x in payload['targets'] if x['identity']==payload['identity']),payload['targets'][0]['id']),'saved_in':[x['identity'] for x in payload['targets']],'reuse_scope':payload['reuse_scope'],'confirmed':payload['confirmed']}
    except Exception as error:
        with db.tx() as c:c.execute("UPDATE answer_share_operations SET error=?,updated_at=? WHERE id=?",(str(error),db.now(),op))
        raise

def recover():
    for op in db.rows("SELECT * FROM answer_share_operations WHERE state='pending'"):
        try:_apply(op['id'],db.unpack(op['payload']))
        except ValueError:
            with db.tx() as c:c.execute("UPDATE answer_share_operations SET state='needs_review' WHERE id=?",(op['id'],))
            for item in db.unpack(op['payload'])['targets']:
                if item['id']:
                    with db.tx(item['identity']) as c:
                        c.execute('UPDATE answers SET review_note=? WHERE id=?',('Sharing was interrupted because an answer changed. Review and save it again.',item['id']))
                        db.log(c,'Answer sharing needs review','An answer changed during an interrupted save; existing application versions are unchanged.')
