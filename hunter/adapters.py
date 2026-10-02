"""Explicit capability records; unsupported sites never masquerade as verified."""
import re
from urllib.parse import urlsplit
from . import db

PLATFORMS={
 'lever':('lever.co',), 'greenhouse':('greenhouse.io',), 'ashby':('ashbyhq.com',),
 'workday':('myworkdayjobs.com','myworkdaysite.com'), 'bamboohr':('bamboohr.com',),
 'keka':('keka.com','kekahire.com'), 'linkedin':('linkedin.com',)}

def platform(url):
    host=urlsplit(url).hostname or ''
    return next((name for name,domains in PLATFORMS.items() if any(host==d or host.endswith('.'+d) for d in domains)),'generic')

def application_form(obs):
    controls=[e for e in obs['elements'] if e['tag'] in ('input','textarea','select') or e.get('type')=='combobox']
    if any(e['type']=='file' for e in controls):return True
    labels=' '.join(e['label'] for e in controls)
    if obs['text'].strip().lower() in ('application','job application','application form') and re.search('email|name',labels,re.I):return True
    return bool(re.search(r'first name|full name|your name',labels,re.I) and re.search(r'email',labels,re.I) and not obs.get('password_present'))

def entry_button(obs,e):
    return platform(obs['url']) in ('lever','greenhouse','ashby','workday','bamboohr','keka') and not application_form(obs) and e['tag']=='button' and e['type']!='submit' and bool(re.fullmatch(r'apply(?: now| for (?:this (?:job|position)|job))?',e['label'],re.I))


def capability(url):
    host=urlsplit(url).hostname or ''
    if host in ('127.0.0.1','localhost'):
        return {'host':host,'fill':'fixture','submit':'fixture','enabled':bool(db.get_setting('fixture_submission_enabled',False))}
    recorded=db.get_setting('submission_sites',{}).get(host,{})
    return {'host':host,'platform':platform(url),'fill':'observed_form_with_review','submit':'user_enabled' if recorded.get('enabled') else 'disabled',
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
