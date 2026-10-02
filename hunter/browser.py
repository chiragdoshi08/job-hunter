"""Visible, dedicated Playwright browser. All access stays on the agent thread."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from . import db, sources

class StalePage(ValueError):pass

OBSERVE = r'''() => {
 const out=[]; let n=0;
 const clean=s=>String(s||'').replace(/\s*[✱*]\s*$/u,'').replace(/\s+/g,' ').trim();
 const visualLabel=e=>{
  const labelled=(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.innerText||'').join(' ');
  if(labelled.trim())return labelled;
  for(let p=e.parentElement,level=0;p&&p!==document.body&&level<5;p=p.parentElement,level++){
   const label=p.querySelector(':scope > .application-label,:scope > .field-label,:scope > .form-label,:scope > label');
   if(label&&!label.contains(e))return label.innerText;
  }
  return '';
 };
 for(const e of document.querySelectorAll('input,textarea,select,button,a[href],[role="button"]')) {
  if(!e.getClientRects().length || e.disabled || e.type==='hidden')continue;
  const type=e.type||e.tagName.toLowerCase();
  if(type==='password' || /otp|one.time|verification.code|security.code/i.test(e.autocomplete||''))continue;
  e.setAttribute('data-job-hunter',String(++n));
  const field=['INPUT','TEXTAREA','SELECT'].includes(e.tagName)&&!['submit','button'].includes(type);
  const label=clean(e.getAttribute('aria-label')||(field?(e.labels?.[0]?.innerText||visualLabel(e)||e.getAttribute('placeholder')||e.name):(e.innerText||e.value))||'');
  const section=e.closest('fieldset')?.querySelector('legend')?.innerText?.trim()||'';
  const group=e.name||'';
  out.push({id:n,group,question:section||e.closest('[role=radiogroup]')?.getAttribute('aria-label')||group,tag:e.tagName.toLowerCase(),type,label:label.slice(0,1500),section,
   required:!!e.required||e.getAttribute('aria-required')==='true',
   max_length:e.maxLength>0?e.maxLength:null,
   choices:e.tagName==='SELECT'?Array.from(e.options).map(o=>o.text.trim()).filter(Boolean):[],
   files:type==='file'?Array.from(e.files||[]).map(f=>f.name):[],
   href:e.tagName==='A'?e.href:null, checked:['checkbox','radio'].includes(type)?e.checked:null,
   value:['input','textarea','select'].includes(e.tagName.toLowerCase()) && type!=='file'?e.value:null});
 }
 return {url:location.href,title:document.title,text:document.body.innerText.slice(0,16000),elements:out.slice(0,300),element_count:out.length,
  password_present:!!document.querySelector('input[type=password]'),
  captcha_present:!Array.from(document.querySelectorAll('[name="g-recaptcha-response"],[name="h-captcha-response"]')).some(e=>!!e.value)&&Array.from(document.querySelectorAll('iframe')).some(e=>{const r=e.getBoundingClientRect();return /recaptcha|hcaptcha|challenge/i.test(e.src)&&r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'})};
}'''


class Browser:
    def __init__(self, headless=False):
        self.headless=headless; self.context=None; self.page=None; self.runtime=None; self.pages={}

    def start(self):
        if self.context:return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError('Browser runtime is missing. Run Install Job Hunter.command, then retry.') from e
        self.runtime=sync_playwright().start()
        path=db.DATA/'browser-profile';path.mkdir(mode=0o700,parents=True,exist_ok=True)
        try:
            self.context=self.runtime.chromium.launch_persistent_context(str(path),headless=self.headless,accept_downloads=False)
            self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception:
            self.runtime.stop();self.runtime=None
            raise RuntimeError('The Job Hunter browser could not start. Close another Job Hunter browser using this profile, or reinstall its Chromium runtime.')

    def close(self):
        if self.context:self.context.close()
        if self.runtime:self.runtime.stop()
        self.context=self.runtime=self.page=None

    def activate(self,key,url):
        self.start()
        page=self.pages.get(key)
        if page and not page.is_closed():
            self.page=page;self.page.bring_to_front();return self.observe()
        self.page=next((p for p in self.context.pages if p.url==url and p not in self.pages.values()),None) or self.context.new_page()
        self.pages[key]=self.page
        if self.page.url!=url:return self.navigate(url)
        self.page.bring_to_front();return self.observe()

    def navigate(self,url):
        self.start()
        if not (db.get_setting('test_fixture_url') and url.startswith(db.get_setting('test_fixture_url'))):sources.public_url(url)
        self.page.goto(url,wait_until='domcontentloaded',timeout=45000)
        self.page.bring_to_front()
        return self.observe()

    def observe(self):
        self.start()
        # Recover an application popup rather than read an unrelated browser tab.
        if self.page.is_closed():self.page=self.context.pages[-1] if self.context.pages else self.context.new_page()
        result=self.page.evaluate(OBSERVE)
        if result.get('element_count',0)>300:raise ValueError('This form has more than 300 visible controls. Inspect its sections before continuing.')
        # Login and challenge contents never become candidate answer prompts.
        if result['password_present']:
            result['elements']=[];result['text']='This page requires account sign-in. Use the visible Job Hunter browser.'
        result['revision']=db.digest({'url':result['url'],'elements':result['elements'],'text':result['text']})
        return result

    def element(self,observation,index):
        if self.observe()['revision']!=observation['revision']:raise StalePage('The page changed; inspect it again before acting.')
        element=next((e for e in observation['elements'] if e['id']==index),None)
        if not element:raise ValueError('Choose an element from the current observation')
        return element,self.page.locator('[data-job-hunter="'+str(index)+'"]')

    def act(self,observation,index,action,value=None,file=None):
        element,loc=self.element(observation,index)
        if action=='fill':loc.fill(value)
        elif action=='select':loc.select_option(label=value)
        elif action=='check':loc.set_checked(bool(value))
        elif action=='upload':loc.set_input_files(str(file))
        elif action=='click':
            pages=set(self.context.pages);loc.click(timeout=20000)
            new=[p for p in self.context.pages if p not in pages]
            if new:self.page=new[-1]
        else:raise ValueError('Unsupported browser action')
        self.page.wait_for_timeout(250)
        return self.observe()

    def screenshot(self,path):
        self.page.screenshot(path=str(path),full_page=True)
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
