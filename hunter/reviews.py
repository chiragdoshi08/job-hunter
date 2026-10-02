"""Review existing answer versions without assigning roles or copying values."""
from . import db,questions,answer_choices

def migrate():
    with db.tx() as c:
        c.execute('CREATE TABLE IF NOT EXISTS answer_review_operations(id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')

def review_many(data):
    items=data.get('items')
    if not isinstance(items,list) or not 1<=len(items)<=200:raise ValueError('Select between 1 and 200 questions to review')
    with db.LOCK:
        payload=[];seen=set()
        for item in items:
            entries=item.get('entries') if isinstance(item,dict) else None
            if not isinstance(entries,list) or not entries:raise ValueError('Select existing answers to review')
            group=[];keys=set();values=set();roles=set()
            for entry in entries:
                if not isinstance(entry,dict) or entry.get('identity') not in db.IDENTITIES:raise ValueError('Choose a valid role')
                i=entry['identity'];row=questions.get(i,entry.get('id'))
                if i in roles:raise ValueError('Each role can appear only once for a question')
                roles.add(i)
                if entry.get('version')!=row['version']:raise ValueError('An answer changed. Refresh the question bank before marking it as reviewed.')
                if not row['value'].strip() or row['review_note'] or questions.state(row)=='expired':raise ValueError('“'+row['question']+'” needs individual review. Open its editor.')
                keys.add(row['question_key']);values.add((row['value'],row['answer_mode']))
                group.append({'identity':i,'id':row['id'],'version':row['version']})
            if len(keys)!=1:raise ValueError('Review matching questions together')
            key=keys.pop()
            if key in seen:raise ValueError('Select each question only once')
            if len(values)!=1:raise ValueError('Different answers need individual review. Open the editor.')
            seen.add(key);payload.append({'question':row['question'],'entries':group})
        op=db.uid()
        with db.tx() as c:c.execute('INSERT INTO answer_review_operations VALUES(?,?,?,NULL,?,?)',(op,db.dump(payload),'pending',db.now(),db.now()))
        return _apply(op,payload)

def _review_entry(op,entry):
    # No questions.save call: a review does not rewrite role scope, expiry,
    # derived address fields, or any other answer. History changes atomically.
    i=entry['identity'];provenance='Reviewed by you · bank review '+op
    with db.tx(i) as c:
        found=c.execute('SELECT * FROM answers WHERE id=?',(entry['id'],)).fetchone()
        if not found:raise ValueError('The answer no longer exists')
        row=dict(found)
        if row['version']==entry['version']+1 and row['provenance']==provenance:return
        if row['version']!=entry['version']:raise ValueError('The answer changed during review. Open it to review the current version.')
        if not row['value'].strip() or row['review_note'] or questions.state(row)=='expired':raise ValueError('The answer now needs individual review')
        if row['confirmed']:return
        answer_choices.enrich(i,row)
        version=row['version']+1
        c.execute('INSERT INTO answer_versions VALUES(?,?,?,?,?,?,?,?)',(db.uid(),row['id'],version,row['value'],1,provenance,row['expires_at'],db.now()))
        c.execute('UPDATE answers SET confirmed=1,version=?,provenance=?,updated_at=? WHERE id=?',(version,provenance,db.now(),row['id']))
        answer_choices.save_behavior(c,row['id'],version,row['answer_mode'])
        db.log(c,'Answer reviewed',row['question']+' · version '+str(version))

def _apply(op,payload):
    saved=[];failed=[];retry=False
    for group in payload:
        try:
            for entry in group['entries']:_review_entry(op,entry)
            saved.append({'question':group['question'],'reviewed_in':[x['identity'] for x in group['entries']]})
        except Exception as error:
            retry=retry or not isinstance(error,ValueError)
            failed.append({'question':group['question'],'error':group['question']+': '+str(error)})
    state='pending' if retry else 'needs_review' if failed else 'completed'
    with db.tx() as c:c.execute('UPDATE answer_review_operations SET state=?,error=?,updated_at=? WHERE id=?',(state,db.dump(failed) if failed else None,db.now(),op))
    return {'saved':saved,'failed':failed}

def recover():
    with db.LOCK:
        for op in db.rows("SELECT * FROM answer_review_operations WHERE state='pending'"):_apply(op['id'],db.unpack(op['payload']))
