"""Extract explicit address components locally; never geocode or guess missing parts."""
import re

ADDRESS_LABELS={'address','full address','home address','residential address','current address'}

def is_address(question):
    return ' '.join(str(question).casefold().split()) in ADDRESS_LABELS

def extract(value):
    if not isinstance(value,str):return {}
    parts=[p.strip() for p in re.split(r'[,\n]+',value.strip()) if p.strip()]
    country=None
    if parts and parts[-1].casefold()=='india':country=parts.pop()
    # Only a clearly delimited street, city, state and six-digit PIN are supported.
    # Other formats stay manual rather than treating a locality or building as a city.
    if len(parts)<3:return {}
    tail=parts[-1]
    if re.fullmatch(r'[1-9]\d{5}',tail) and len(parts)>=4:
        tail=parts[-2]+' '+parts[-1];parts.pop()
    match=re.fullmatch(r"([A-Za-z][A-Za-z .&'\-]*?)\s*[-–—]?\s+([1-9]\d{5})",tail)
    if not match:return {}
    city=parts[-2];state=match[1].strip(' -–—');postal=match[2]
    if not re.fullmatch(r"[A-Za-z][A-Za-z .&'\-]*",city):return {}
    if re.search(r'\b(road|street|sector|block|phase|floor|apartment|near|lane)\b',city,re.I):return {}
    result={'City':city,'Province':state,'Postal code':postal}
    if country:result['Country']='India'
    return result

def sync(identity,parent):
    from . import db,questions
    values=extract(parent['value'])
    # Previously derived values become review items if the new address cannot be read.
    for child in db.rows('SELECT * FROM answers WHERE derived_from=?',(parent['id'],),identity):
        if child['question'] not in values:
            with db.tx(identity) as c:c.execute('UPDATE answers SET review_note=? WHERE id=?',('The source address changed and this part could not be extracted. Review this answer.',child['id']))
    for label,value in values.items():
        qid=questions.ensure(identity,label,category='contact',reuse_scope=parent['reuse_scope'])
        child=questions.get(identity,qid)
        if child['value'] and child['derived_from']!=parent['id']:
            if questions.normal(child['value'])!=questions.normal(value):
                with db.tx(identity) as c:c.execute('UPDATE answers SET review_note=? WHERE id=?',('This saved answer differs from the address. Review it; your existing value was kept.',qid))
            continue
        questions.save(identity,{'id':qid,'value':value,'confirmed':bool(parent['confirmed']),
            'reuse_scope':parent['reuse_scope'],'expires_at':parent['expires_at']},
            provenance='Extracted from '+parent['question']+' · version '+str(parent['version'])+' · '+('confirmed with address' if parent['confirmed'] else 'address still needs confirmation'),
            _derived_from=parent['id'],_derived_version=parent['version'])
    return values
