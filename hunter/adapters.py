"""Explicit capability records; unsupported sites never masquerade as verified."""
import re
from urllib.parse import urlsplit
from . import db


def capability(url):
    host=urlsplit(url).hostname or ''
    if host in ('127.0.0.1','localhost'):
        return {'host':host,'fill':'fixture','submit':'fixture','enabled':bool(db.get_setting('fixture_submission_enabled',False))}
    recorded=db.get_setting('submission_sites',{}).get(host,{})
    return {'host':host,'fill':'generic_unverified','submit':'user_enabled' if recorded.get('enabled') else 'disabled',
        'enabled':bool(recorded.get('enabled')),'reviewed_at':recorded.get('reviewed_at'),
        'confirmation_pattern':recorded.get('confirmation_pattern','')}


def enable(data):
    host=str(data.get('site','')).strip().lower()
    if not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',host):raise ValueError('Enter the exact employer application hostname')
    if not data.get('reviewed'):raise ValueError('Review this destination’s form and confirmation behavior before enabling submission')
    pattern=str(data.get('confirmation_text','')).strip()
    if len(pattern)<15 or len(pattern)>300:raise ValueError('Enter the employer’s exact confirmation phrase, between 15 and 300 characters')
    sites=db.get_setting('submission_sites',{});sites[host]={'enabled':bool(data.get('enabled',True)),
        'reviewed_at':db.now(),'confirmation_pattern':pattern,'validation':'user_reviewed_not_certified'}
    db.set_setting('submission_sites',sites)
    return capability('https://'+host)


def require_submission(url):
    c=capability(url)
    if not c['enabled']:raise ValueError('Submission is not enabled for '+c['host']+'. Fill and review the form, then enable this exact destination in Agent setup. Generic site automation has not been certified.')
    return c


def confirmation(obs,job):
    c=capability(job['url']);host=urlsplit(obs['url']).hostname
    if host!=c['host']:return None
    if c['submit']=='fixture':
        pattern='Your application has been received'
    else:pattern=c.get('confirmation_pattern','')
    if pattern and pattern in obs['text'] and not any(e['type']=='file' for e in obs['elements']):return pattern
    return None
