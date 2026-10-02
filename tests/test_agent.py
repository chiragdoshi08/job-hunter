"""Recovery, approvals and isolation for the automatic browser worker."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hunter import db,desktop,agent,questions,goals,onboarding,adapters,identities
from tests.helpers import fixture_masters


def element(id,label,type='text',value='',required=True,tag='input',**extra):
    return dict(id=id,label=label,type=type,value=value,required=required,tag=tag,choices=[],max_length=None,section='',checked=False,files=[],**extra)


class FakeBrowser:
    def __init__(self,elements=None,url='https://jobs.lever.co/fixture/form',text='Application'):
        self.context=True;self.elements=elements or [];self.url=url;self.text=text;self.calls=[]
    def activate(self,key,url):return self.observe()
    def observe(self):
        r=dict(url=self.url,text=self.text,elements=self.elements,password_present=False,captcha_present=False)
        r['revision']=db.digest(r);return r
    def act(self,obs,index,action,value=None,file=None):
        self.calls.append((index,action,value,str(file) if file else None))
        e=next(e for e in self.elements if e['id']==index)
        if action in ('fill','select'):e['value']=value
        if action=='check':e['checked']=bool(value)
        if action=='upload':e['files']=[file.name]
        if action=='click':self.text='Your application has been received';self.elements=[]
        return self.observe()
    def close(self):pass


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init();fixture_masters()
        self.profile=db.capture_profile('strategy',{'document_id':db.MASTER_IDS['strategy'],'text':'Fixture Candidate\nVerified operations experience','captured_at':db.now()})
        self.job=db.upsert_job('strategy',dict(title='Operations Lead',company='Fixture Employer',url='https://jobs.lever.co/fixture/form',source_id='fixture',description='Lead operations.',test=True));self.app=db.shortlist('strategy',self.job)
    def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
    def prepare(self):
        t=db.enqueue('strategy','prepare',self.job,application_id=self.app['id']);desktop.claim('strategy',t,'fixture')
        f=db.ROOT/'cv.pdf';f.write_bytes(b'%PDF-fixture')
        d=desktop.register_document('strategy',t,'fixture',dict(kind='cv',drive_id='fixture-doc',drive_url='https://docs.google.com/document/d/fixture-doc/edit',profile_id=self.profile['id'],job_hash=db.get_job('strategy',self.job)['description_hash'],visual_verified=True,verification={'fixture':True}),f)
        db.task_update('strategy',t,state='completed');db.release_task('strategy',t)
        with db.tx() as c:c.execute("INSERT INTO accounts VALUES('jobs.lever.co','Fixture','fixture@example.test','shared',0,NULL)")
        with db.tx('strategy') as c:c.execute("UPDATE applications SET document_state='prepared' WHERE id=?",(self.app['id'],))
        return d
    def task(self,kind):return db.enqueue('strategy',kind,self.job,application_id=self.app['id'])
    def runner(self,browser,decision=None):
        r=agent.AgentRunner(decider=decision or (lambda *a,**k:dict(action='click',element=3,message='Click final action',blocker='none')));r.browser=browser;return r
    def test_fresh_install_has_no_personal_google_ids(self):
        self.assertEqual(db.DEFAULT_MASTER_IDS,{'strategy':None,'ai':None});self.assertFalse(db.get_setting('development_mode'))
    def test_scan_saves_exact_questions_without_fill_or_model(self):
        browser=FakeBrowser([element(1,'Email')]);r=self.runner(browser,lambda *a,**k:self.fail('No model needed for a visible form'))
        t=self.task('scan_form');r.run('strategy',desktop.task('strategy',t))
        self.assertEqual(desktop.task('strategy',t)['state'],'completed');self.assertEqual(browser.calls,[]);self.assertEqual(questions.readiness('strategy',self.app['id'])['total'],1)
    def test_known_answer_and_exact_document_are_filled(self):
        self.prepare();questions.observe('strategy',[{'question':'Email'}],self.app['id']);questions.save('strategy',{'question':'Email','value':'fixture@example.test','confirmed':True});questions.apply_to_application('strategy',self.app['id']);db.approve('strategy',self.app['id'])
        b=FakeBrowser([element(1,'Email'),element(2,'Résumé',type='file'),element(3,'Submit application',type='submit',tag='button',required=False)])
        t=self.task('fill');self.runner(b).run('strategy',desktop.task('strategy',t))
        self.assertEqual(db.application('strategy',self.app['id'])['state'],'awaiting_submission');self.assertEqual([x[1] for x in b.calls],['fill','upload']);self.assertTrue(b.elements[1]['files'])
    def test_new_question_invalidates_approval_before_private_fill(self):
        self.prepare();db.approve('strategy',self.app['id']);b=FakeBrowser([element(1,'Work authorization')]);t=self.task('fill');self.runner(b).run('strategy',desktop.task('strategy',t))
        self.assertEqual(b.calls,[]);self.assertEqual(desktop.task('strategy',t)['state'],'waiting_user');self.assertIsNone(db.application('strategy',self.app['id'])['approval_id'])
    def test_login_retains_checkpoint_and_releases_browser(self):
        b=FakeBrowser();b.observe=lambda:dict(url=b.url,revision='login',text='Sign in',elements=[],password_present=True,captcha_present=False)
        t=self.task('scan_form');self.runner(b).run('strategy',desktop.task('strategy',t));r=desktop.task('strategy',t)
        self.assertEqual(db.unpack(r['checkpoint'])['step'],'login');self.assertEqual(r['state'],'waiting_user');self.assertFalse(db.rows('SELECT * FROM resource_locks'))
    def test_paused_task_cannot_mutate_browser(self):
        t=self.task('scan_form');db.task_update('strategy',t,state='paused');b=FakeBrowser();self.runner(b).run('strategy',desktop.task('strategy',t));self.assertEqual(b.calls,[]);self.assertEqual(desktop.task('strategy',t)['state'],'paused')
    def test_scan_cannot_click_submit_or_next_form_button(self):
        obs=FakeBrowser([element(1,'Continue',type='submit',tag='button')]).observe()
        with self.assertRaises(ValueError):agent.validate_click(obs,1,'scan_form')
    def test_fill_cannot_click_final_submission(self):
        obs=FakeBrowser([element(1,'Submit',type='submit',tag='button')]).observe()
        with self.assertRaises(ValueError):agent.validate_click(obs,1,'fill')
    def test_submission_requires_destination_configuration(self):
        with self.assertRaisesRegex(ValueError,'not enabled'):adapters.require_submission('https://jobs.lever.co/fixture/form')
        adapters.enable({'site':'jobs.lever.co','reviewed':True,'confirmation_text':'Your application has been received'});self.assertTrue(adapters.capability('https://jobs.lever.co/fixture/form')['enabled'])
    def test_confirmation_must_come_from_configured_hostname(self):
        adapters.enable({'site':'jobs.lever.co','reviewed':True,'confirmation_text':'Your application has been received'})
        obs=dict(url='https://elsewhere.example/receipt',text='Your application has been received',elements=[])
        self.assertIsNone(adapters.confirmation(obs,db.get_job('strategy',self.job)))
    def test_repeat_labels_block_instead_of_conflating_employers(self):
        with self.assertRaisesRegex(ValueError,'repeats'):agent.observed_fields(FakeBrowser([element(1,'Company'),element(2,'Company')]).observe())
    def test_radio_and_consent_capture_choices(self):
        obs=FakeBrowser([element(1,'Yes',type='radio',group='visa',question='Need sponsorship?'),element(2,'No',type='radio',group='visa',question='Need sponsorship?'),element(3,'I consent',type='checkbox')]).observe()
        fields=agent.observed_fields(obs);self.assertEqual(fields[0]['choices'],['Yes','No']);self.assertEqual(fields[1]['question'],'Need sponsorship?')
    def test_same_application_reuses_confirmed_answer_after_label_punctuation_changes(self):
        q='What is your expected CTC (Expected Cost to Company)?'
        questions.observe('strategy',[{'question':q}],self.app['id'])
        a=db.application('strategy',self.app['id']);a['answers'][q]={'value':'Fixture reviewed expectation','confirmed':True,'provenance':'Reviewed for this employer'}
        with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump(a['answers']),self.app['id']))
        updated=q.upper().replace('?','')
        questions.observe('strategy',[{'question':updated}],self.app['id'])
        self.assertEqual(db.application('strategy',self.app['id'])['answers'][updated]['value'],'Fixture reviewed expectation')
        self.assertTrue(db.application('strategy',self.app['id'])['answers'][updated]['confirmed'])
    def test_multi_page_capture_retains_earlier_questions(self):
        t=desktop.task('strategy',self.task('scan_form'));agent.capture('strategy',t,FakeBrowser([element(1,'Email')]).observe());agent.capture('strategy',t,FakeBrowser([element(1,'Phone')]).observe());self.assertEqual(questions.readiness('strategy',self.app['id'])['total'],2)
    def test_goal_requires_real_connection_browser_and_preferences(self):
        with patch('hunter.worker.auth_status',return_value={'ok':True}):
            with self.assertRaisesRegex(ValueError,'Finish Setup'):goals.start('strategy',{})
            prefs=db.get_setting('preferences',{},'strategy');prefs['confirmed']=True;db.set_setting('preferences',prefs,'strategy');db.set_setting('browser_check',{'ok':True});db.set_setting('inference_check',{'ok':True})
            self.assertTrue(goals.start('strategy',{'max_applications':2})['enabled'])
    def test_goal_chains_confirmed_fit_to_preparation_and_keeps_unknowns_out(self):
        goal={'enabled':True,'started_at':db.now(),'max_applications':2,'discovery_requested':True}
        db.set_setting('agent_goal',goal,'strategy')
        assessment={'recommendation':'pursue','eligibility':{'status':'confirmed'},'requirements':[{'mandatory':True,'status':'met'}]}
        with db.tx('strategy') as c:c.execute('UPDATE jobs SET test=0,assessment=?,assessment_profile=?,assessment_jd_hash=description_hash,assessment_context_hash=? WHERE id=?',(db.dump(assessment),self.profile['id'],'fixture-hash',self.job))
        from hunter.worker import assessment_hash
        for job in (self.job,):
            h=assessment_hash(self.profile,db.get_job('strategy',job),db.get_setting('preferences',{},'strategy'))
            with db.tx('strategy') as c:c.execute('UPDATE jobs SET assessment_context_hash=? WHERE id=?',(h,job))
        goals.tick();self.assertTrue(db.one("SELECT id FROM tasks WHERE kind='prepare'",identity='strategy'))
        other=db.upsert_job('strategy',dict(title='Operations Director',company='Another Fixture',url='https://jobs.lever.co/fixture/another',source_id='fixture',description='Lead operations.'))
        assessment['eligibility']['status']='unknown'
        with db.tx('strategy') as c:c.execute('UPDATE jobs SET assessment=?,assessment_profile=?,assessment_jd_hash=description_hash,assessment_context_hash=? WHERE id=?',(db.dump(assessment),self.profile['id'],'fixture-hash',other))
        h=assessment_hash(self.profile,db.get_job('strategy',other),db.get_setting('preferences',{},'strategy'))
        with db.tx('strategy') as c:c.execute('UPDATE jobs SET assessment_context_hash=? WHERE id=?',(h,other))
        goals.tick();self.assertFalse(db.one('SELECT id FROM applications WHERE job_id=?',(other,),'strategy'))
    def test_goal_reassesses_when_preferences_changed_during_model_execution(self):
        from hunter.worker import assessment_hash
        j=db.get_job('strategy',self.job);old=assessment_hash(self.profile,j,db.get_setting('preferences',{},'strategy'))
        assessment={'recommendation':'pursue','eligibility':{'status':'confirmed'},'requirements':[]}
        with db.tx('strategy') as c:c.execute('UPDATE jobs SET test=0,assessment=?,assessment_profile=?,assessment_jd_hash=description_hash,assessment_context_hash=? WHERE id=?',(db.dump(assessment),self.profile['id'],old,self.job))
        prefs=db.get_setting('preferences',{},'strategy');prefs['work_authorization']='Different verified eligibility';db.set_setting('preferences',prefs,'strategy')
        db.set_setting('agent_goal',{'enabled':True,'started_at':db.now(),'max_applications':1,'discovery_requested':True},'strategy')
        goals.tick();self.assertTrue(db.one("SELECT id FROM tasks WHERE kind='assess'",identity='strategy'));self.assertFalse(db.one("SELECT id FROM tasks WHERE kind='prepare'",identity='strategy'))
    def test_expired_scan_lease_recovers_as_agent_task(self):
        t=self.task('scan_form');db.task_update('strategy',t,state='working',lease_until=0);db.recover();self.assertEqual(desktop.task('strategy',t)['state'],'waiting_agent')
    def test_unknown_native_template_cannot_be_replaced_by_baseline(self):
        t=self.task('prepare');desktop.claim('strategy',t,'fixture');db.set_setting('cv_template_id','fixture-required','strategy')
        with self.assertRaisesRegex(ValueError,'native Google Docs template'):onboarding.baseline_document('strategy',t,'fixture')
    def test_blank_pdf_is_rejected_without_profile_changes(self):
        from pypdf import PdfWriter
        import io
        out=io.BytesIO();pdf=PdfWriter();pdf.add_blank_page(width=595,height=842);pdf.write(out)
        with self.assertRaisesRegex(ValueError,'readable'):onboarding.import_resume('ai',{'content':base64.b64encode(out.getvalue()).decode(),'reviewed':True,'name':'resume.pdf'})
        self.assertFalse(db.rows('SELECT * FROM profiles',identity='ai'))

if __name__=='__main__':unittest.main()
