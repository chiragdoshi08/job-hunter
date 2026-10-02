"""Journal account-wide résumé changes before any upload; restore and verify."""
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit
from . import db,sources

SITES=('iimjobs.com','hirist.tech','hirist.com','naukri.com')
SCHEMA='''CREATE TABLE IF NOT EXISTS resume_transactions(
 id TEXT PRIMARY KEY, site TEXT NOT NULL, identity TEXT NOT NULL, application_id TEXT NOT NULL,
 state TEXT NOT NULL, original_path TEXT NOT NULL, original_sha256 TEXT NOT NULL,
 replacement_sha256 TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT);
 CREATE UNIQUE INDEX IF NOT EXISTS one_resume_change ON resume_transactions(site)
 WHERE state!='restored';'''

def init():
    with db.tx() as c:c.executescript(SCHEMA)

def account_site(url):
    host=urlsplit(url).hostname or ''
    return next((site for site in SITES if host==site or host.endswith('.'+site)),host)

def needs_swap(url):return account_site(url) in SITES

def configuration(url):return db.get_setting('resume_accounts',{}).get(account_site(url))

def configure(data):
    site=account_site('https://'+str(data.get('site','')))
    if site not in SITES:raise ValueError('Choose an account-wide résumé site')
    url=sources.public_url(data.get('profile_url',''))
    if account_site(url)!=site:raise ValueError('The résumé page must belong to this job-site account')
    if not data.get('reviewed'):raise ValueError('Review the original résumé download and replacement controls first')
    labels={key:str(data.get(key,'')).strip() for key in ('download_label','upload_label')}
    if any(not value or len(value)>200 for value in labels.values()):raise ValueError('Enter the exact visible labels for downloading and uploading the résumé')
    configs=db.get_setting('resume_accounts',{});configs[site]={'profile_url':url,**labels,'reviewed_at':db.now()};db.set_setting('resume_accounts',configs)
    return configs[site]

def pending(site=None):
    return db.rows("SELECT * FROM resume_transactions WHERE state!='restored'"+(' AND site=?' if site else ''),(site,) if site else ())

def pdf_hash(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size>10_000_000 or not path.read_bytes().startswith(b'%PDF-'):raise ValueError('The account résumé must be a recoverable PDF under 10 MB')
    from pypdf import PdfReader
    if not PdfReader(str(path)).pages:raise ValueError('The account résumé PDF is empty')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def state(id,value,error=None):
    with db.tx() as c:c.execute('UPDATE resume_transactions SET state=?,error=?,updated_at=? WHERE id=?',(value,error,db.now(),id))

def begin(identity,application_id,url,replacement,backend):
    site=account_site(url);config=configuration(url)
    if not config:raise ValueError('Set up a recoverable original résumé for '+site+' in Agent setup before applying.')
    if pending(site):raise ValueError('Restore the saved original résumé for '+site+' before another application.')
    replacement_hash=pdf_hash(replacement);id=db.uid();folder=db.DATA/'account_resumes'/id;folder.mkdir(parents=True,mode=0o700)
    original=folder/'original.pdf';backend.download(config,original);original_hash=pdf_hash(original);os.chmod(original,0o400)
    with db.tx() as c:c.execute('INSERT INTO resume_transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
       (id,site,identity,application_id,'saved',original.relative_to(db.DATA).as_posix(),original_hash,replacement_hash,db.now(),db.now(),None))
    transaction=db.one('SELECT * FROM resume_transactions WHERE id=?',(id,))
    try:
        # A crash from this point is conservatively treated as a changed account.
        state(id,'changing');backend.upload(config,Path(replacement));check=folder/'replacement-check.pdf';backend.download(config,check)
        if pdf_hash(check)!=replacement_hash:raise ValueError('The job site did not return the exact reviewed résumé after replacement')
        state(id,'active');return transaction
    except BaseException:
        restore(transaction,backend)
        raise

def restore(transaction,backend):
    config=configuration('https://'+transaction['site']);original=db.DATA/transaction['original_path']
    try:
        if not config or pdf_hash(original)!=transaction['original_sha256']:raise ValueError('The saved original résumé failed its integrity check')
        state(transaction['id'],'restoring');backend.upload(config,original)
        check=original.parent/'restored-check.pdf';backend.download(config,check)
        if pdf_hash(check)!=transaction['original_sha256']:raise ValueError('Original résumé restoration could not be verified')
        state(transaction['id'],'restored')
    except Exception:
        message='Original résumé restoration needs your help. This account is paused; open its résumé page and retry recovery.'
        state(transaction['id'],'recovery_required',message)
        with db.tx() as c:
            c.execute('INSERT INTO accounts(site,label,paused,reason) VALUES(?,?,1,?) ON CONFLICT(site) DO UPDATE SET paused=1,reason=excluded.reason',
              (transaction['site'],transaction['site'],message))
        from .notifications import enqueue
        enqueue('resume-recovery:'+transaction['id'],'Job Hunter needs your help','An original résumé needs recovery. Open Job Hunter; the affected account is paused.')
        raise ValueError(message)

def recover(site,backend):
    site=account_site('https://'+site)
    for transaction in pending(site):restore(transaction,backend)
    with db.tx() as c:c.execute("UPDATE accounts SET paused=0,reason=NULL WHERE site=? AND reason LIKE 'Original résumé restoration%'",(site,))
    return {'restored':True}

class BrowserBackend:
    def __init__(self,browser):self.browser=browser
    def _page(self,config):
        self.browser.start();page=self.browser.context.new_page();page.goto(config['profile_url'],wait_until='domcontentloaded',timeout=45000)
        if account_site(page.url)!=account_site(config['profile_url']):page.close();raise ValueError('Sign in to the résumé account before recovery')
        return page
    def download(self,config,path):
        page=self._page(config)
        try:
            control=page.get_by_role('link',name=config['download_label'],exact=True)
            if control.count()!=1:control=page.get_by_role('button',name=config['download_label'],exact=True)
            if control.count()!=1:raise ValueError('The original résumé download control changed. Review this account before uploading.')
            with page.expect_download(timeout=30000) as result:control.click()
            result.value.save_as(str(path))
        finally:page.close()
    def upload(self,config,path):
        page=self._page(config)
        try:
            control=page.get_by_label(config['upload_label'],exact=True)
            if control.count()!=1 or control.get_attribute('type')!='file':raise ValueError('The résumé upload control changed. Review this account before continuing.')
            control.set_input_files(str(path));page.wait_for_timeout(1500)
        finally:page.close()
