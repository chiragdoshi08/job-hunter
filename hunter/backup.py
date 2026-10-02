import hashlib, json, os, shutil, sqlite3, tempfile, zipfile
from pathlib import Path
from . import db

def create_backup():
    out=db.DATA.parent/'backups';out.mkdir(exist_ok=True,mode=0o700)
    target=out/('job-hunter-'+db.now().replace(':','-')+'-'+db.uid()[:4]+'.zip')
    with db.LOCK,tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);files={}
        for i in [None,*db.IDENTITIES]:
            rel=Path(i or '')/('tracker.sqlite' if i else 'shared.sqlite');dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            src=db.connect(i);to=sqlite3.connect(dest);src.backup(to);to.close();src.close()
        for i in db.IDENTITIES:
            for category in ('documents','runs','profile_files'):
                folder=db.DATA/i/category
                if folder.exists():shutil.copytree(folder,stage/i/category)
        if (db.DATA/'account_resumes').exists():shutil.copytree(db.DATA/'account_resumes',stage/'account_resumes')
        for p in stage.rglob('*'):
            if p.is_file():files[p.relative_to(stage).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
        (stage/'manifest.json').write_text(db.dump({'version':1,'created_at':db.now(),'identities':list(db.IDENTITIES),'files':files}))
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for p in stage.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(stage))
    os.chmod(target,0o600);return target

def restore_backup(path,destination=None):
    """Offline only. Validate all bytes before swapping; retain previous state."""
    dest=Path(destination or db.DATA).resolve()
    if destination is None and (dest/'server.pid').exists():
        try:os.kill(int((dest/'server.pid').read_text()),0)
        except (ProcessLookupError,ValueError):pass
        else:raise ValueError('Stop Job Hunter before restoring a backup')
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        stage=Path(tmp)/'restore';stage.mkdir()
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist())>500_000_000:raise ValueError('Backup is unexpectedly large')
            manifest=json.loads(z.read('manifest.json'))
            if manifest.get('version')!=1:raise ValueError('Unsupported backup version')
            for name,h in manifest['files'].items():
                if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe backup path')
                data=z.read(name)
                if hashlib.sha256(data).hexdigest()!=h:raise ValueError('Backup integrity check failed')
                p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        if not (stage/'shared.sqlite').is_file():raise ValueError('The shared database is missing')
        registry=sqlite3.connect(stage/'shared.sqlite')
        has_registry=registry.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='identities'").fetchone()
        identities=[r[0] for r in registry.execute("SELECT id FROM identities WHERE state='ready'")] if has_registry else list(db.DEFAULT_IDENTITIES)
        registry.close()
        import re
        if not identities or any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',i) for i in identities):raise ValueError('Invalid roles in backup')
        for rel in ['shared.sqlite',*[i+'/tracker.sqlite' for i in identities]]:
            if not (stage/rel).is_file():raise ValueError('A role database is missing from the backup')
            c=sqlite3.connect(stage/rel)
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed')
            if c.execute('PRAGMA user_version').fetchone()[0]>6:raise ValueError('Database is from a newer app')
            c.close()
        # Mappings and browser claims cannot survive a machine restart.
        shared=sqlite3.connect(stage/'shared.sqlite');shared.execute('DELETE FROM resource_locks');shared.commit();shared.close()
        for identity in identities:
            c=sqlite3.connect(stage/identity/'tracker.sqlite');c.execute("UPDATE tasks SET state='paused',owner=NULL,lease_until=NULL,pid=NULL,progress='Restored from backup. Resume to re-check saved work.' WHERE state='working'");c.commit();c.close()
        previous=dest.parent/(dest.name+'-before-restore-'+db.uid())
        if dest.exists():dest.rename(previous)
        shutil.move(stage,dest)
        for p in dest.rglob('*'):
            if p.is_file():os.chmod(p,0o600)
        return previous
