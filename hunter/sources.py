from __future__ import annotations
import html, json, re, threading, time, urllib.request, urllib.error, socket, ipaddress, ssl
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit, quote
from html.parser import HTMLParser
from . import db

class SourceError(Exception): pass
class PartialSourceError(SourceError): pass
_locks={}; _guard=threading.Lock(); _last={}; _cache={}
def public_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise SourceError('Only public HTTPS URLs are accepted')
    try:
        for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(x[4][0]).is_global:raise SourceError('Private network destinations are not allowed')
    except socket.gaierror as e:raise SourceError('Could not resolve source hostname') from e
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def request(url):
    public_url(url);host=urlsplit(url).hostname
    with _guard:lock=_locks.setdefault(host,threading.Lock())
    with lock:
        cached=_cache.get(url)
        if cached and time.monotonic()-cached[0]<120:return cached[1]
        gap=.7-(time.monotonic()-_last.get(host,0))
        if gap>0:time.sleep(gap)
        _last[host]=time.monotonic()
        req=urllib.request.Request(url,headers={'User-Agent':'JobHunter/0.2 (local personal job discovery)','Accept':'application/json, application/rss+xml, text/html;q=0.7'})
        try:
            with urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile="/etc/ssl/cert.pem" if Path("/etc/ssl/cert.pem").exists() else None))).open(req,timeout=30) as r:
                raw=r.read(12_000_001)
                if len(raw)>12_000_000:raise SourceError('Source response exceeds the safe size limit')
                content=raw.decode('utf-8','replace');_cache[url]=(time.monotonic(),content);return content
        except urllib.error.HTTPError as e:
            raise SourceError(f'HTTP {e.code}: '+('access restricted; use browser handoff' if e.code in (401,403,429) else 'source request failed')) from e
        except (urllib.error.URLError,TimeoutError,OSError) as e:raise SourceError(str(e)[:200]) from e

def plain(s):
    s=html.unescape(html.unescape(s or ''))
    s=re.sub(r'<(script|style)\b[^>]*>.*?</\1>','',s,flags=re.S|re.I)
    s=re.sub(r'<\s*(?:/p|br|/li|/h\d|/div)\s*/?>','\n',s,flags=re.I)
    return re.sub(r'[ \t]+',' ',re.sub('<[^>]+>','',s)).strip()

def posted(v):
    if not v:return None
    if isinstance(v,(int,float)):
        try:return datetime.fromtimestamp(v/(1000 if v>10**11 else 1),timezone.utc).isoformat()
        except (ValueError,OSError):return None
    return str(v)

def get_json(url):
    try:return json.loads(request(url))
    except json.JSONDecodeError as e:raise SourceError('Source returned a page instead of structured jobs') from e

def jobposting_data(page):
    class Parser(HTMLParser):
        def __init__(self):super().__init__();self.active=False;self.parts=[];self.blocks=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script' and dict(attrs).get('type','').lower()=='application/ld+json':self.active=True;self.parts=[]
        def handle_data(self,data):
            if self.active:self.parts.append(data)
        def handle_endtag(self,tag):
            if tag=='script' and self.active:self.blocks.append(''.join(self.parts));self.active=False
    parser=Parser();parser.feed(page);found=[]
    def walk(v):
        if isinstance(v,list):
            for x in v:walk(x)
        elif isinstance(v,dict):
            typ=v.get('@type',[])
            if typ=='JobPosting' or isinstance(typ,list) and 'JobPosting' in typ:found.append(v)
            if '@graph' in v:walk(v['@graph'])
            if 'itemListElement' in v:walk(v['itemListElement'])
            if 'item' in v:walk(v['item'])
    for block in parser.blocks:
        try:walk(json.loads(block))
        except json.JSONDecodeError:continue
    return found

def fetch(source, cancelled=lambda:False):
    cfg=db.unpack(source['config'],{});kind=source['kind'];slug=cfg.get('slug','');out=[]
    def add(**j):
        employment=j.get('employment_type')
        if isinstance(employment,list):employment=', '.join(str(x) for x in employment)
        if employment:
            employment=str(employment).lower().replace('_','-')
            j['employment_type']={'fulltime':'full-time','parttime':'part-time'}.get(employment,employment)
        arrangement=j.get('arrangement')
        if arrangement:j['arrangement']={'onsite':'on-site','on_site':'on-site'}.get(str(arrangement).lower(),str(arrangement).lower())
        j['source_id']=source['id'];j['company']=j.get('company') or cfg.get('company') or source['name'];out.append(j)
    if kind=='jsonld':
        data=jobposting_data(request(cfg['url']))
        if not data:raise SourceError('No public JobPosting data found. Use desktop browser capture; this page may require JavaScript or login.')
        for j in data:
            locations=j.get('jobLocation') or [];locations=locations if isinstance(locations,list) else [locations];loc=[]
            for location in locations:
                address=location.get('address',{})
                if isinstance(address,str):loc.append(address)
                else:loc.append(', '.join(str(address[k]) for k in ('addressLocality','addressRegion','addressCountry') if address.get(k)))
            countries=j.get('applicantLocationRequirements') or [];countries=countries if isinstance(countries,list) else [countries]
            salary=j.get('baseSalary');sal=None
            if isinstance(salary,dict):
                value=salary.get('value',{});value=value if isinstance(value,dict) else {'value':value}
                sal={'minimum':value.get('minValue') or value.get('value'),'maximum':value.get('maxValue') or value.get('value'),'currency':salary.get('currency'),'period':{'YEAR':'annual','MONTH':'monthly'}.get(value.get('unitText'),value.get('unitText'))}
            availability='open'
            if j.get('validThrough'):
                try:
                    end=datetime.fromisoformat(j['validThrough'].replace('Z','+00:00'));end=end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
                    if end<datetime.now(timezone.utc):availability='closed'
                except ValueError:pass
            org=j.get('hiringOrganization') or {};identifier=j.get('identifier') or {}
            add(title=j['title'],company=org.get('name') if isinstance(org,dict) else str(org),url=cfg.get('original_url') or j.get('url') or cfg['url'],discovered_url=cfg['url'],description=plain(j.get('description')),location='; '.join(loc) or None,arrangement='remote' if j.get('jobLocationType')=='TELECOMMUTE' else None,source_job_id=identifier.get('value') if isinstance(identifier,dict) else str(identifier),posted_at=j.get('datePosted'),salary=sal,employment_type=j.get('employmentType'),country_restrictions=[c.get('name','') for c in countries if isinstance(c,dict)],availability=availability)
        return out,'Single page check only; no claim of complete coverage for this website.'
    elif kind=='greenhouse':
        data=get_json(f'https://boards-api.greenhouse.io/v1/boards/{quote(slug)}/jobs?content=true')
        if 'jobs' not in data:raise SourceError('Job collection missing')
        for j in data['jobs']:
            loc=j.get('location',{}).get('name','')
            add(title=j['title'],location=loc,arrangement='remote' if 'remote' in loc.lower() else None,url=j['absolute_url'],source_job_id=str(j['id']),description=plain(j.get('content')),posted_at=j.get('first_published'))
    elif kind=='lever':
        skip=0
        while True:
            if cancelled():raise SourceError('Search paused')
            data=get_json(f'https://api.lever.co/v0/postings/{quote(slug)}?mode=json&limit=100&skip={skip}')
            if not isinstance(data,list):raise SourceError('Job collection missing')
            for j in data:
                cats=j.get('categories',{});desc=j.get('descriptionPlain') or plain(j.get('description'))
                desc+='\n'+'\n'.join(s.get('text','')+'\n'+plain(s.get('content')) for s in j.get('lists',[]))+'\n'+plain(j.get('additional'))
                add(title=j['text'],location=cats.get('location'),arrangement=j.get('workplaceType'),employment_type=cats.get('commitment'),url=j['hostedUrl'],source_job_id=j['id'],description=desc,posted_at=posted(j.get('createdAt')),salary=j.get('salaryRange'))
            if len(data)<100:break
            skip+=100
            if skip>=10000:raise PartialSourceError('More than 10000 records; narrow this source')
    elif kind=='ashby':
        data=get_json(f'https://api.ashbyhq.com/posting-api/job-board/{quote(slug)}?includeCompensation=true')
        if 'jobs' not in data:raise SourceError('Job collection missing')
        for j in data['jobs']:
            if j.get('isListed') is False:continue
            add(title=j['title'],location=j.get('location'),arrangement=j.get('workplaceType') or ('remote' if j.get('isRemote') else None),employment_type=j.get('employmentType'),url=j.get('jobUrl') or j['applyUrl'],source_job_id=j.get('id') or j.get('jobUrl'),description=j.get('descriptionPlain') or plain(j.get('descriptionHtml')),posted_at=j.get('publishedAt'),salary=j.get('compensation'))
    elif kind=='remotive':
        data=get_json('https://remotive.com/api/remote-jobs')
        if 'jobs' not in data:raise SourceError('Job collection missing')
        for j in data['jobs']:
            add(title=j['title'],company=j['company_name'],location=j.get('candidate_required_location'),country_restrictions=[j['candidate_required_location']] if j.get('candidate_required_location') else [],arrangement='remote',url=j['url'],description=plain(j.get('description')),source_job_id=str(j['id']),posted_at=j.get('publication_date'),salary={'text':j['salary']} if j.get('salary') else None,employment_type=j.get('job_type'))
    elif kind=='remoteok':
        data=get_json('https://remoteok.com/api')
        if not isinstance(data,list):raise SourceError('Job collection missing')
        for j in data:
            if not j.get('position'):continue
            add(title=j['position'],company=j.get('company'),location=j.get('location'),arrangement='remote',url=j['url'],description=plain(j.get('description')),source_job_id=str(j.get('id')),posted_at=j.get('date'),salary={'minimum':j['salary_min'],'maximum':j.get('salary_max'),'currency':'USD','period':'annual'} if j.get('salary_min') else None)
    elif kind=='himalayas':
        offset=0; page_limit=int(cfg.get('page_limit',5));truncated=False
        for page in range(page_limit):
            if cancelled():raise SourceError('Search paused')
            data=get_json(f'https://himalayas.app/jobs/api?limit=20&offset={offset}')
            if 'jobs' not in data:raise SourceError('Job collection missing')
            for j in data['jobs']:
                countries=j.get('locationRestrictions',[])
                add(title=j['title'],company=j.get('companyName'),location=', '.join(countries) or 'Remote — country unknown',country_restrictions=countries,arrangement='remote',url=j.get('applicationLink') or j.get('guid'),source_job_id=j.get('guid'),description=plain(j.get('description')),posted_at=posted(j.get('pubDate')),employment_type=j.get('employmentType'))
            offset+=len(data['jobs'])
            if not data['jobs'] or offset>=data.get('totalCount',offset):break
            truncated=True
        if truncated and offset<data.get('totalCount',offset):return out, f'Partial: newest {offset} of {data["totalCount"]} records. Increase page limit in source settings.'
    elif kind=='rss':
        root=ET.fromstring(request(cfg['url']))
        for j in root.findall('.//item'):
            add(title=j.findtext('title') or '',url=j.findtext('link') or '',company=j.findtext('author') or cfg.get('company') or 'See listing',description=plain(j.findtext('description')),location=None,arrangement='remote' if cfg.get('remote') else None,posted_at=j.findtext('pubDate'),source_job_id=j.findtext('guid'))
    elif kind=='smartrecruiters':
        offset=0
        while True:
            if cancelled():raise SourceError('Search paused')
            data=get_json(f'https://api.smartrecruiters.com/v1/companies/{quote(slug)}/postings?limit=100&offset={offset}')
            if 'content' not in data:raise SourceError('Job collection missing')
            for j in data['content']:
                loc=j.get('location',{});jid=j['id'];url=f'https://jobs.smartrecruiters.com/{slug}/{jid}'
                add(title=j['name'],location=', '.join(str(loc[x]) for x in ('city','country') if loc.get(x)),arrangement='remote' if loc.get('remote') else None,url=url,source_job_id=jid,description='',posted_at=j.get('releasedDate'),detail_url=f'https://api.smartrecruiters.com/v1/companies/{quote(slug)}/postings/{jid}')
            offset+=len(data['content'])
            if offset>=data.get('totalFound',offset) or not data['content']:break
    else:raise SourceError('Use desktop web discovery for this source; no automated fetch adapter')
    return out,None

def detail(j):
    if j.get('detail_url'):
        d=get_json(j['detail_url']);sections=d.get('jobAd',{}).get('sections',{})
        j['description']='\n'.join(plain(v.get('text','')) for v in sections.values())
    return j

def filter_job(j,p):
    title=j['title'].lower();full=(title+' '+j.get('description','')).lower();notes=[]
    if not p.get('include_early_career',False) and re.search(r'\b(intern(ship)?|junior|entry[- ]level|fresher|trainee)\b',title):return False,['Early-career role; enable these in preferences to include']
    if any(x.lower() in full for x in p.get('exclusions',[]) if x.strip()):return False,['Excluded keyword']
    titles=p.get('titles',[])
    title_match=any(x.lower() in title for x in titles)
    patterns=['p&l','operating model','business transformation','strategic initiatives'] if not any('product' in t.lower() for t in titles) else ['product requirements','product roadmap','ai adoption','user workflows']
    if titles and not title_match and sum(x in full for x in patterns)<2:return False,['Outside role patterns']
    if not title_match:notes.append('Responsibility match; title needs review')
    loc=(j.get('location') or '').lower();arr=(j.get('arrangement') or '').lower()
    if p.get('countries'):
        restrictions=j.get('country_restrictions') or []
        def country(s):return {'in':'india','us':'united states','usa':'united states','uk':'united kingdom'}.get(s.strip().lower(),s.strip().lower())
        known_countries={'india','united states','united kingdom','canada','australia','germany','france','singapore','united arab emirates','ireland','netherlands','new zealand','japan','china'}
        restricted={country(r) for r in restrictions};wanted={country(w) for w in p['countries']}
        if restricted and restricted<=known_countries and wanted<=known_countries:
            if not restricted & wanted:return False,['Hiring country restriction does not match preferences']
        else:notes.append('Hiring country is not confirmed; country regions and free-text restrictions need eligibility review')
    if p.get('locations') and loc and not any(x.lower() in loc for x in p['locations']) and arr!='remote':return False,['Outside selected locations']
    normal_arr=lambda value: str(value).lower().replace('_','-').replace('onsite','on-site')
    if p.get('arrangements') and arr and normal_arr(arr) not in [normal_arr(x) for x in p['arrangements']]:return False,['Working arrangement excluded']
    if p.get('employment_types') and j.get('employment_type') and not any(x.lower().replace('_','-') in j['employment_type'].lower().replace('_','-').replace('fulltime','full-time').replace('parttime','part-time').split(', ') for x in p['employment_types']):return False,['Employment type excluded']
    if p.get('seniority') and not any(x.lower() in title for x in p['seniority']):notes.append('Seniority needs review against selected levels')
    if p.get('industries'):notes.append('Industry preference needs assessment')
    if p.get('minimum_salary'):
        s=j.get('salary') or {};s=s if isinstance(s,dict) else {};minimum=s.get('minimum') or s.get('min');maximum=s.get('maximum') or s.get('max')
        if maximum and str(s.get('currency','')).upper()==p.get('currency') and s.get('period')==p.get('salary_period'):
            try:
                if float(maximum)<float(p['minimum_salary']):return False,['Below compensation minimum']
            except (ValueError,TypeError):notes.append('Compensation could not be compared')
        else:notes.append('Compensation unavailable or not comparable')
    if p.get('posting_age_days') and j.get('posted_at'):
        try:
            d=datetime.fromisoformat(j['posted_at'].replace('Z','+00:00'))
            if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc)-d).days>int(p['posting_age_days']):return False,['Older than selected posting age']
        except ValueError:notes.append('Posting date could not be parsed')
    if not j.get('posted_at'):notes.append('Posting date unknown')
    if arr=='remote':notes.append('Remote hiring country, time zone and work authorisation must be checked')
    if not p.get('confirmed'):notes.append('Exploratory — search preferences not confirmed')
    if not j.get('location'):notes.append('Location unknown')
    if not arr:notes.append('Working arrangement unknown')
    return True,notes

BROWSER_SOURCES=[('linkedin','LinkedIn','https://www.linkedin.com/jobs/'),('naukri','Naukri','https://www.naukri.com/'),('iimjobs','iimjobs','https://www.iimjobs.com/'),('indeed','Indeed','https://in.indeed.com/'),('foundit','foundit','https://www.foundit.in/'),('glassdoor','Glassdoor','https://www.glassdoor.co.in/Job/'),('cutshort','Cutshort','https://cutshort.io/jobs'),('simplify','Simplify Jobs','https://simplify.jobs/'),('wellfound','Wellfound','https://wellfound.com/jobs'),('instahyre','Instahyre','https://www.instahyre.com/'),('hirist','hirist','https://www.hirist.tech/'),('remote-co','Remote.co','https://remote.co/remote-jobs/'),('yc','Y Combinator','https://www.ycombinator.com/jobs'),('workday','Workday','https://www.myworkdayjobs.com/'),('workable','Workable','https://jobs.workable.com/'),('direct','Company career pages','https://www.google.com/'),('darwinbox','Darwinbox','https://www.darwinbox.com/'),('talent500','Talent500','https://talent500.com/')]

def seed():
    entries=[dict(id='remotive',name='Remotive',kind='remotive',config={}),dict(id='himalayas',name='Himalayas',kind='himalayas',config={'page_limit':5}),dict(id='remoteok',name='Remote OK',kind='remoteok',config={}),dict(id='wwr',name='We Work Remotely',kind='rss',config={'url':'https://weworkremotely.com/remote-jobs.rss','remote':True})]
    for id,name,url in BROWSER_SOURCES:entries.append(dict(id=id,name=name,kind='browser',config={'url':url}))
    for s in entries:add_source(s,ignore=True)

def add_source(s,ignore=False):
    if s['kind'] not in ('greenhouse','lever','ashby','remotive','remoteok','himalayas','rss','smartrecruiters','jsonld','browser'):raise ValueError('Unsupported adapter')
    if not re.fullmatch('[a-z0-9_-]{1,80}',s['id']):raise ValueError('Source ID must be lowercase letters, numbers, hyphens')
    cfg=s['config']
    if s['kind'] in ('jsonld','rss') and not cfg.get('url'):raise ValueError('A public source URL is required')
    if s['kind'] in ('greenhouse','lever','ashby','smartrecruiters') and not re.fullmatch('[a-zA-Z0-9_-]{1,100}',cfg.get('slug','')):raise ValueError('Enter the board slug from the employer career URL')
    if cfg.get('url') and (urlsplit(cfg['url']).scheme!='https' or not urlsplit(cfg['url']).hostname):raise ValueError('Source URL must be HTTPS')
    caps={'discovery':'desktop_search_unverified' if s['kind']=='browser' else 'implemented_unverified','description':'unverified','login':'may_be_required' if s['kind']=='browser' else 'not_required_for_discovery','fill':'desktop_case_by_case_unverified','upload':'desktop_case_by_case_unverified','submit':'approval_required_untested'}
    with db.tx() as c:
        c.execute('INSERT '+('OR IGNORE ' if ignore else '')+'INTO sources(id,name,kind,config,capabilities) VALUES(?,?,?,?,?)',(s['id'],s['name'],s['kind'],db.dump(cfg),db.dump(caps)))
