"""Local real-browser acceptance tests. Set JOB_HUNTER_BROWSER_TESTS=1 to run."""
import os
import json
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from hunter import db,desktop,agent,questions,identities,onboarding,resume_accounts
from hunter.browser import Browser
from tests.helpers import fixture_masters

HTML='''<!doctype html><title>Fixture employer</title><form id="form"><label>Email<input type="email" required></label><label>Résumé<input type="file" required accept=".pdf"></label><label>I consent<input type="checkbox" required></label><button type="submit">Submit application</button></form><script>document.querySelector('form').onsubmit=e=>{e.preventDefault();document.body.innerHTML='<h1>Your application has been received</h1><p>Receipt fixture-confirmed</p>'}</script>'''


def pdf_bytes():
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    pdf=PdfWriter();page=pdf.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):pdf._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 780 Td (Fixture Candidate - reviewed operations resume. Led controlled operations programs and planning. This PDF is synthetic test data and contains no real personal information.) Tj ET')
    page[NameObject('/Contents')]=pdf._add_object(stream);out=io.BytesIO();pdf.write(out);return out.getvalue()


@unittest.skipUnless(os.environ.get('JOB_HUNTER_BROWSER_TESTS')=='1','Opt-in local browser test')
class BrowserAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
        class Handler(BaseHTTPRequestHandler):
            current_cv=pdf_bytes()
            def do_GET(self):
                self.send_response(200)
                if self.path=='/resume.pdf':
                    self.send_header('Content-Type','application/pdf');self.send_header('Content-Disposition','attachment; filename="resume.pdf"');self.end_headers();self.wfile.write(type(self).current_cv)
                else:
                    self.send_header('Content-Type','text/html');self.end_headers()
                    html='<a href="/resume.pdf">Download original</a><label>Resume<input type="file" onchange="fetch(\'/resume\',{method:\'POST\',body:this.files[0]})"></label>' if self.path=='/profile' else HTML
                    self.wfile.write(html.encode())
            def do_POST(self):
                type(self).current_cv=self.rfile.read(int(self.headers.get('Content-Length',0)));self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.http.server_port}/application';db.set_setting('test_fixture_url',self.url);db.set_setting('fixture_submission_enabled',True)
        self.browser=Browser(headless=True)
    def tearDown(self):self.browser.close();self.http.shutdown();self.http.server_close();db.DATA,db.ROOT=self.old;self.tmp.cleanup()
    def test_upload_review_fill_and_observed_confirmation(self):
        import base64
        onboard=onboarding.import_resume('strategy',{'name':'fixture-cv.pdf','content':base64.b64encode(pdf_bytes()).decode(),'reviewed':True})
        self.assertGreater(onboard['characters'],100)
        j=db.upsert_job('strategy',dict(title='Fixture Operations Lead',company='Fixture',url=self.url,source_id='fixture',description='Lead operations.',test=True));a=db.shortlist('strategy',j)
        with db.tx() as c:c.execute("INSERT INTO accounts VALUES('127.0.0.1','Fixture','fixture@example.test','shared',0,NULL)")
        runner=agent.AgentRunner(decider=lambda *args,**kw:dict(action='click',element=4,message='Submit reviewed fixture',blocker='none'));runner.browser=self.browser
        t=db.enqueue('strategy','prepare',j,application_id=a['id']);runner.run('strategy',desktop.task('strategy',t))
        scan=db.one("SELECT * FROM tasks WHERE kind='scan_form'",identity='strategy');runner.run('strategy',scan)
        questions.save('strategy',{'question':'Email','value':'fixture@example.test','confirmed':True});questions.apply_to_application('strategy',a['id'])
        app=db.application('strategy',a['id']);app['answers']['I consent']={'value':'Yes','confirmed':True,'provenance':'Fixture consent explicitly reviewed'}
        with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump(app['answers']),a['id']))
        db.approve('strategy',a['id']);fill=db.enqueue('strategy','fill',j,application_id=a['id']);runner.run('strategy',desktop.task('strategy',fill))
        self.assertEqual(db.application('strategy',a['id'])['state'],'awaiting_submission',desktop.task('strategy',fill))
        self.assertEqual(self.browser.page.locator('input[type=file]').evaluate('(e)=>e.files[0].name').split('.')[-1],'pdf')
        self.assertTrue(self.browser.page.locator('input[type=checkbox]').is_checked())
        db.approve('strategy',a['id'],'submit');submit=db.enqueue('strategy','submit',j,application_id=a['id']);runner.run('strategy',desktop.task('strategy',submit))
        self.assertEqual(db.application('strategy',a['id'])['state'],'submitted',desktop.task('strategy',submit))
        self.assertEqual(db.one('SELECT count(*) n FROM submission_attempts',identity='strategy')['n'],1)
        with self.assertRaises(ValueError):db.enqueue('strategy','submit',j,application_id=a['id'])
    def test_stale_dom_cannot_apply_action(self):
        obs=self.browser.navigate(self.url);self.browser.page.locator('input[type=email]').fill('changed@example.test')
        with self.assertRaisesRegex(ValueError,'page changed'):self.browser.act(obs,1,'fill','fixture@example.test')
    def test_hidden_react_select_validation_input_is_not_a_second_question(self):
        self.browser.start();self.browser.page.set_content('<fieldset><legend>Phone</legend><label id="country-label">Country</label><div><div class="select__single-value">Fixture country</div><input role="combobox" aria-labelledby="country-label"></div><input aria-hidden="true" required tabindex="-1"></fieldset><input type="file" aria-hidden="true" style="display:none" aria-label="Resume">')
        observation=self.browser.observe();fields=agent.observed_fields(observation)
        self.assertEqual([f['question'] for f in fields],['Phone · Country']);self.assertEqual(len([e for e in observation['elements'] if e['type']=='file']),1)
        self.assertEqual(next(e for e in observation['elements'] if e['type']=='combobox')['value'],'Fixture country')
    def test_two_applications_keep_separate_live_pages(self):
        self.browser.activate('first',self.url);self.browser.page.locator('input[type=email]').fill('first@example.test')
        self.browser.activate('second',self.url);self.browser.page.locator('input[type=email]').fill('second@example.test')
        self.browser.activate('first',self.url);self.assertEqual(self.browser.page.locator('input[type=email]').input_value(),'first@example.test')
    def test_visual_ats_labels_are_captured_without_field_ids_or_choice_text(self):
        self.browser.start();self.browser.page.set_content('<div><div class="application-label"><div class="text">Expected compensation<span>✱</span></div></div><div class="application-field"><textarea name="cards[fixture][field1]" required></textarea></div></div><div><div class="application-label">Notice period ✱</div><div class="application-field"><div class="application-dropdown"><select name="cards[fixture][field2]"><option>Choose</option><option>30 Days</option></select></div></div></div>')
        fields=agent.observed_fields(self.browser.observe());self.assertEqual([f['question'] for f in fields],['Expected compensation','Notice period'])
    def test_captcha_completion_is_observed_without_disclosing_response(self):
        self.browser.start();self.browser.page.set_content('<iframe src="about:blank#recaptcha" width="300" height="78"></iframe><textarea name="g-recaptcha-response" style="display:none"></textarea>')
        self.assertTrue(self.browser.observe()['captcha_present'])
        self.browser.page.locator('[name=g-recaptcha-response]').evaluate('(e)=>e.value="fixture-secret-response"')
        obs=self.browser.observe();self.assertFalse(obs['captcha_present']);self.assertNotIn('fixture-secret-response',json.dumps(obs))
    def test_password_values_are_never_observed(self):
        self.browser.start();self.browser.page.set_content('<input type="email" value="private@example.test"><input type="password" value="do-not-observe">')
        obs=self.browser.observe();self.assertTrue(obs['password_present']);self.assertNotIn('do-not-observe',json.dumps(obs));self.assertEqual(obs['elements'],[])
    def test_hidden_resume_input_remains_uploadable(self):
        self.browser.start();self.browser.page.set_content('<label>Resume<input type="file" style="display:none"></label>')
        obs=self.browser.observe();self.assertEqual(obs['elements'][0]['type'],'file')
        path=db.ROOT/'resume.pdf';path.write_bytes(pdf_bytes());self.browser.act(obs,1,'upload',file=path)
        self.assertEqual(self.browser.page.locator('input').evaluate('(e)=>e.files[0].name'),'resume.pdf')
    def test_custom_dropdown_choices_are_observed_before_selection(self):
        self.browser.start();self.browser.page.set_content('<label id="question">Notice period</label><input role="combobox" aria-labelledby="question" aria-controls="choices"><div id="choices" style="display:none"><div role="option">30 Days</div><div role="option">60 Days</div></div><script>let input=document.querySelector("input"),list=document.querySelector("#choices");input.onclick=()=>list.style.display="block";input.onkeydown=e=>{if(e.key==="Escape")list.style.display="none"};for(let o of list.children)o.onclick=()=>{input.value=o.innerText;list.style.display="none"}</script>')
        obs=self.browser.read_choices(self.browser.observe(),1);self.assertEqual(obs['elements'][0]['choices'],['30 Days','60 Days'])
        obs=self.browser.act(obs,1,'select','60 Days');self.assertEqual(obs['elements'][0]['value'],'60 Days')
    def test_account_resume_restores_original_in_actual_browser(self):
        profile=self.url.rsplit('/',1)[0]+'/profile';db.set_setting('resume_accounts',{'naukri.com':{'profile_url':profile,'download_label':'Download original','upload_label':'Resume'}})
        original=self.http.RequestHandlerClass.current_cv;replacement=db.ROOT/'reviewed.pdf';replacement.write_bytes(original+b'\n% Reviewed replacement')
        self.browser.activate('application',self.url);self.browser.page.locator('input[type=email]').fill('fixture@example.test')
        backend=resume_accounts.BrowserBackend(self.browser);t=resume_accounts.begin('strategy','fixture','https://naukri.com/job',replacement,backend)
        self.assertEqual(self.http.RequestHandlerClass.current_cv,replacement.read_bytes());resume_accounts.restore(t,backend)
        self.assertEqual(self.http.RequestHandlerClass.current_cv,original);self.assertEqual(self.browser.page.locator('input[type=email]').input_value(),'fixture@example.test')

if __name__=='__main__':unittest.main()
