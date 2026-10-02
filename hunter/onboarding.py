"""User-owned profiles and resumés; no personal defaults in a fresh install."""
import base64
import hashlib
import io
import os
from pathlib import Path
from . import db,identities


def import_resume(identity,data):
    name=Path(str(data.get('name','resume.pdf'))).name
    if not name.lower().endswith('.pdf'):raise ValueError('Upload a PDF résumé')
    try:raw=base64.b64decode(data['content'],validate=True)
    except (KeyError,ValueError):raise ValueError('The upload was incomplete; choose the PDF again')
    if len(raw)>10_000_000 or not raw.startswith(b'%PDF-'):raise ValueError('Choose a PDF under 10 MB')
    from pypdf import PdfReader
    try:
        reader=PdfReader(io.BytesIO(raw));text='\n'.join(p.extract_text() or '' for p in reader.pages)
    except Exception as e:raise ValueError('This PDF could not be read. Export an unlocked PDF and upload it again.') from e
    if len(text.strip())<100:raise ValueError('This PDF has no readable résumé text. Upload a text-based PDF.')
    if not data.get('reviewed'):raise ValueError('Confirm that you reviewed this résumé before importing it')
    meta=identities.record(identity)
    if meta['master_id'] and not meta['master_id'].startswith('local:'):
        # An uploaded baseline never silently replaces a native master/template.
        profile=db.one('SELECT * FROM profiles WHERE source_id=? ORDER BY captured_at DESC LIMIT 1',(meta['master_id'],),identity)
        if not profile:raise ValueError('Capture your connected native master first, or use a separate role for this uploaded résumé.')
    else:
        source='local:'+hashlib.sha256(raw).hexdigest()
        with db.tx() as c:c.execute('UPDATE identities SET master_id=? WHERE id=?',(source,identity))
        identities.refresh()
        profile=db.capture_profile(identity,{'document_id':source,'captured_at':db.now(),'text':text})
    folder=db.DATA/identity/'profile_files';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    sha=hashlib.sha256(raw).hexdigest();path=folder/(sha+'.pdf');path.write_bytes(raw);os.chmod(path,0o400)
    baseline={'path':str(path.relative_to(db.DATA/identity)),'sha256':sha,'name':name,'profile_id':profile['id'],'pages':len(reader.pages),'reviewed_at':db.now(),'policy':'use_original'}
    db.set_setting('baseline_resume',baseline,identity)
    return {'profile_id':profile['id'],'pages':baseline['pages'],'characters':len(text),'name':name}


def readiness(identity):
    from .worker import auth_status
    import importlib.util
    setup=identities.setup(identity)
    return {'auth':auth_status(),'profile':bool(setup['profile']),'preferences':setup['preferences_ready'],
       'browser_installed':bool(importlib.util.find_spec('playwright')),
       'browser_check':db.get_setting('browser_check',{}),
       'inference_check':db.get_setting('inference_check',{}),
       'drive_check':db.get_setting('drive_check',{}),
       'native_template':db.get_setting('cv_template_id',None,identity),
       'baseline_resume':{k:v for k,v in db.get_setting('baseline_resume',{},identity).items() if k!='path'},
       'data_directory':str(db.DATA),'execution_mode':db.get_setting('execution_mode'),
       'goal':db.get_setting('agent_goal',{'enabled':False,'stage':'review'},identity)}


def baseline_document(identity,task,owner):
    """Register the unchanged, user-reviewed original; never claim it was tailored."""
    from . import desktop
    t=desktop.ensure_owner(identity,task,owner);ctx=desktop.context(identity,task)
    if not t['application_id']:raise ValueError('Choose an application for document preparation')
    if db.get_setting('cv_template_id',None,identity):
        raise ValueError('This role requires a native Google Docs template. Use the connected document workflow; an uploaded baseline cannot replace that template.')
    baseline=db.get_setting('baseline_resume',{},identity)
    if not baseline:raise ValueError('Upload and review this role’s résumé in Setup, or prepare its native template document.')
    if baseline['profile_id']!=ctx['profile']['id']:raise ValueError('The profile changed. Upload and review a current résumé first.')
    file=db.DATA/identity/baseline['path']
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=baseline['sha256']:raise ValueError('The original résumé changed or is missing. Upload it again.')
    existing=db.one('SELECT id FROM documents WHERE application_id=? AND kind=? AND sha256=? AND job_hash=?',(t['application_id'],'cv',baseline['sha256'],ctx['job']['description_hash']),identity)
    if existing:return existing['id']
    did=db.uid();relative=Path('documents')/t['application_id']/(did+'.pdf');dest=db.DATA/identity/relative;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700);dest.write_bytes(file.read_bytes());os.chmod(dest,0o400)
    with db.tx(identity) as c:
        version=c.execute("SELECT coalesce(max(version),0)+1 FROM documents WHERE application_id=? AND kind='cv'",(t['application_id'],)).fetchone()[0]
        c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(did,t['application_id'],'cv',version,'local:'+baseline['sha256'],'','uploaded',str(relative),baseline['sha256'],ctx['profile']['id'],ctx['job']['description_hash'],'Original user-reviewed résumé, unchanged; no tailoring claimed.',db.now(),db.dump({'user_reviewed':True,'pages':baseline['pages'],'original_unchanged':True}),db.now()))
        a=db.application(identity,t['application_id']);selected=[x for x in a['selected_documents'] if not c.execute("SELECT id FROM documents WHERE id=? AND kind='cv'",(x,)).fetchone()]+[did]
        c.execute("UPDATE applications SET selected_documents=?,document_state='prepared',state='review',approval_id=NULL,updated_at=? WHERE id=?",(db.dump(selected),db.now(),t['application_id']))
    return did
