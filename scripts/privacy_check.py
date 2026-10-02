"""Fail releases that contain runtime data, credentials or private local paths."""
import re
import subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[1]
result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True)
paths=result.stdout.decode().strip('\0').split('\0')
issues=[]
for name in paths:
 p=root/name
 if not p.is_file():continue
 if any(part in ('data','backups','browser-profile','.venv') for part in p.relative_to(root).parts) or p.suffix in ('.sqlite','.pdf','.zip','.log'):issues.append(name+': runtime data')
 if p.suffix not in ('.py','.md','.js','.html','.css','.txt','.yml','.toml','.command','.bat'):continue
 text=p.read_text(errors='replace')
 if re.search(r'(?:/'+r'Users/[^/\s]+/|sk-[A-Za-z0-9]{20,}|gh[opusr]_[A-Za-z0-9]{20,}|^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)',text,re.MULTILINE):issues.append(name+': private path or credential')
if issues:raise SystemExit('\n'.join(issues))
print(f'Privacy check passed: {len(paths)} tracked files; no runtime databases, PDFs, browser profiles or credentials.')
