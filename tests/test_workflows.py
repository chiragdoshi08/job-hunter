"""Durable alerts, native style invariants and résumé rollback under real failures."""
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import smtplib
from unittest.mock import patch
from hunter import db,notifications,resume_accounts,native_cv,adapters
from hunter.process_events import EventLines
from tests.test_browser import pdf_bytes

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
    def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
    def test_phone_alerts_are_opt_in_deduplicated_and_private(self):
        notifications.enqueue('one','Title','Message');self.assertFalse(db.rows('SELECT * FROM notification_outbox'))
        status=notifications.configure(True);self.assertGreaterEqual(len(status['topic']),40)
        t={'id':'fixture','state':'waiting_user','kind':'fill','checkpoint':'{}','progress':'PRIVATE candidate@example.test'}
        notifications.task_changed('strategy',t);notifications.task_changed('strategy',t)
        items=db.rows('SELECT * FROM notification_outbox');self.assertEqual(len(items),1);self.assertNotIn('PRIVATE',db.dump(items));self.assertNotIn('candidate@',db.dump(items))
        notifications.configure(False);self.assertEqual(db.rows('SELECT * FROM notification_outbox')[0]['state'],'cancelled')
    def test_phone_alert_retries_without_stopping_app_work(self):
        notifications.configure(True);notifications.enqueue('one','Title','Message')
        def offline(*args,**kwargs):raise OSError('Offline')
        self.assertTrue(notifications.deliver_once(offline,clock=lambda:100))
        item=db.rows('SELECT * FROM notification_outbox')[0];self.assertEqual(item['state'],'pending');self.assertEqual(item['next_at'],130)
        self.assertFalse(notifications.deliver_once(offline,clock=lambda:129))
        class Response(io.BytesIO):status=200
        def online(request,timeout):
            self.assertEqual(request.get_header('Cache'),'no')
            return Response(json.dumps({'event':'message','topic':notifications.status()['topic']}).encode())
        notifications.deliver_once(online,clock=lambda:131);self.assertEqual(db.rows('SELECT * FROM notification_outbox')[0]['state'],'sent')
    def test_email_settings_do_not_expose_or_backup_app_password(self):
        from hunter import backup
        import zipfile
        settings={'username':'fixture@example.test','recipient':'fixture@example.test','password':'private-fixture-app-password'}
        notifications.configure(True,'email',settings);self.assertNotIn(settings['password'],db.dump(notifications.status()))
        self.assertTrue(notifications.status()['email_configured'])
        notifications.configure(True,'email',{'password':''});self.assertEqual(notifications.configuration()['email']['password'],settings['password'])
        with zipfile.ZipFile(backup.create_backup()) as archive:self.assertNotIn('phone-alerts.json',archive.namelist())
        with self.assertRaisesRegex(ValueError,'app password'):notifications.configure(True,'email',{'host':'another.example.test'})
        self.assertEqual(notifications.configuration()['email']['host'],'smtp.gmail.com')
    def test_email_uses_tls_acknowledgment_and_durable_message_id(self):
        notifications.configure(True,'email',{'host':'smtp.example.test','port':587,'security':'starttls','username':'fixture@example.test','recipient':'fixture@example.test','password':'fixture-secret'})
        notifications.enqueue('mail-one','Job Hunter needs your help','Open Job Hunter.')
        calls=[];messages=[]
        class SMTP:
            def __init__(self,host,port,**kw):calls.append(('connect',host,port,kw['timeout']))
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def ehlo(self):calls.append(('ehlo',))
            def starttls(self,context):calls.append(('tls',context.check_hostname))
            def login(self,user,password):calls.append(('login',user,password))
            def send_message(self,message):messages.append(message);return {}
        notifications.deliver_once(clock=lambda:100,smtp_factory=SMTP)
        self.assertLess(calls.index(('tls',True)),calls.index(('login','fixture@example.test','fixture-secret')))
        item=db.rows('SELECT * FROM notification_outbox')[0];self.assertEqual(item['state'],'sent');self.assertIn(item['id'],messages[0]['Message-ID']);self.assertNotIn('fixture-secret',str(messages[0]))
    def test_email_bad_credentials_stop_retries_with_a_useful_private_error(self):
        notifications.configure(True,'email',{'username':'fixture@example.test','recipient':'fixture@example.test','password':'fixture-secret'});notifications.enqueue('mail-one','Title','Message')
        def refused(*args,**kw):raise smtplib.SMTPAuthenticationError(535,b'PRIVATE fixture-secret')
        notifications.deliver_once(clock=lambda:100,smtp_factory=refused);item=db.rows('SELECT * FROM notification_outbox')[0]
        self.assertEqual(item['state'],'failed');self.assertIn('app password',item['error']);self.assertNotIn('fixture-secret',item['error'])
    def backend(self,fail=False):
        original=pdf_bytes();replacement=original+b'\n% Reviewed replacement'
        class Backend:
            data=original;uploads=[]
            def download(self,config,path):path.write_bytes(self.data)
            def upload(self,config,path):
                self.uploads.append(path.read_bytes())
                if fail and path.name=='original.pdf':raise OSError('Cannot restore')
                self.data=path.read_bytes()
        configs={'naukri.com':{'profile_url':'https://www.naukri.com/profile','download_label':'Download','upload_label':'Resume'}};db.set_setting('resume_accounts',configs)
        file=db.ROOT/'reviewed.pdf';file.write_bytes(replacement);return Backend(),file,original
    def test_account_resume_round_trip_has_exact_byte_verification(self):
        backend,file,original=self.backend();t=resume_accounts.begin('strategy','application','https://www.naukri.com/job',file,backend)
        self.assertEqual(backend.data,file.read_bytes());self.assertEqual(resume_accounts.pending()[0]['state'],'active')
        resume_accounts.restore(t,backend);self.assertEqual(backend.data,original);self.assertEqual(resume_accounts.pending(),[])
    def test_restore_failure_pauses_only_affected_account_and_can_recover(self):
        backend,file,original=self.backend(fail=True);t=resume_accounts.begin('strategy','application','https://www.naukri.com/job',file,backend)
        with self.assertRaisesRegex(ValueError,'account is paused'):resume_accounts.restore(t,backend)
        self.assertTrue(db.one('SELECT paused FROM accounts WHERE site=?',('naukri.com',))['paused'])
        self.assertEqual(resume_accounts.pending()[0]['state'],'recovery_required')
        with self.assertRaisesRegex(ValueError,'Restore'):resume_accounts.begin('ai','another','https://naukri.com/job',file,backend)
        def upload(config,path):backend.data=path.read_bytes()
        backend.upload=upload;resume_accounts.recover('naukri.com',backend);self.assertEqual(backend.data,original);self.assertFalse(db.one('SELECT paused FROM accounts WHERE site=?',('naukri.com',))['paused'])
    def test_crash_after_upload_is_recovered_from_persisted_original(self):
        backend,file,original=self.backend();resume_accounts.begin('strategy','application','https://naukri.com/job',file,backend)
        db.init();resume_accounts.recover('naukri.com',backend);self.assertEqual(backend.data,original)
    def doc(self):
        text='Led operations with verified process improvements.\n'
        return {'documentStyle':{'marginLeft':{'magnitude':72}},'namedStyles':{},'tabs':[{'tabId':'t.0','title':'CV','index':0,'parentTabId':None,'body':{'content':[{'startIndex':1,'endIndex':1+len(text),'paragraph':{'paragraphStyle':{'indentStart':{'magnitude':-49.7}},'bullet':{'listId':'one'},'elements':[{'startIndex':1,'endIndex':1+len(text),'textRun':{'content':text,'textStyle':{'fontSize':{'magnitude':11},'weightedFontFamily':{'fontFamily':'Times New Roman'}}}}]}}]}}]}
    def test_native_edits_use_utf16_indexes_and_preserve_local_styles(self):
        doc=self.doc();plan={'edits':[{'run':'t.0:1','text':'Led verified operations and process improvements.','evidence':'Led operations with verified process improvements.'}],'remove_bullets':[]}
        requests=native_cv.requests_for(doc,plan,plan['edits'][0]['evidence'],'strategy_two_pages');self.assertEqual(requests[-1]['updateTextStyle']['textStyle']['weightedFontFamily']['fontFamily'],'Times New Roman')
        after=copy.deepcopy(doc);after['tabs'][0]['body']['content'][0]['paragraph']['elements'][0]['textRun']['content']=plan['edits'][0]['text']+'\n'
        self.assertTrue(native_cv.verify_preserved(doc,after,plan));after['documentStyle']={}
        with self.assertRaisesRegex(ValueError,'geometry'):native_cv.verify_preserved(doc,after,plan)
    def test_native_plan_cannot_change_unknown_ranges_or_invent_metrics(self):
        doc=self.doc();edit={'run':'t.0:1','text':'Grew revenue 900%.','evidence':'Led operations with verified process improvements.'};plan={'edits':[edit],'remove_bullets':[]}
        with self.assertRaisesRegex(ValueError,'number'):native_cv.requests_for(doc,plan,edit['evidence'],'strategy_two_pages')
        edit['run']='other:9'
        with self.assertRaisesRegex(ValueError,'unknown'):native_cv.requests_for(doc,plan,edit['evidence'],'strategy_two_pages')
        with self.assertRaisesRegex(ValueError,'one-page'):native_cv.requests_for(doc,{'edits':[],'remove_bullets':['t.0:1']},edit['evidence'],'strategy_two_pages')
    def test_native_default_style_omissions_are_equivalent_but_font_changes_fail(self):
        doc=self.doc();run=doc['tabs'][0]['body']['content'][0]['paragraph']['elements'][0]['textRun']
        run['textStyle'].update(bold=False,italic=False,baselineOffset='NONE')
        after=copy.deepcopy(doc);style=after['tabs'][0]['body']['content'][0]['paragraph']['elements'][0]['textRun']['textStyle']
        for key in ('bold','italic','baselineOffset'):style.pop(key)
        plan={'edits':[],'remove_bullets':[]}
        self.assertTrue(native_cv.verify_preserved(doc,after,plan))
        style['weightedFontFamily']['fontFamily']='Arial'
        with self.assertRaisesRegex(ValueError,'styling'):native_cv.verify_preserved(doc,after,plan)
    def test_native_evidence_matches_source_paragraph_whitespace_without_paraphrasing(self):
        doc=self.doc();profile='Led operations with\n\nverified process improvements.'
        edit={'run':'t.0:1','text':'Led verified operations and process improvements.','evidence':'“Led operations with verified process improvements.”'}
        plan={'edits':[edit],'remove_bullets':[]}
        native_cv.requests_for(doc,plan,profile,'strategy_two_pages');self.assertEqual(edit['evidence'],profile)
        edit['evidence']='Led operations with invented process improvements.'
        with self.assertRaisesRegex(ValueError,'supporting quote'):native_cv.requests_for(doc,plan,profile,'strategy_two_pages')
    def test_native_final_newline_is_retained_and_bullet_font_changes_are_rejected(self):
        doc=self.doc();plan={'edits':[],'remove_bullets':['t.0:1']}
        self.assertEqual(native_cv.requests_for(doc,plan,'Verified profile facts.','ai_one_page'),[]);self.assertEqual(plan['remove_bullets'],[])
        doc['tabs'][0]['lists']={'one':{'listProperties':{'nestingLevels':[{'glyphSymbol':'•','textStyle':{'weightedFontFamily':{'fontFamily':'Arial','weight':400}}}]}}}
        after=copy.deepcopy(doc);after['tabs'][0]['body']['content'][0]['paragraph']['bullet']['textStyle']={'weightedFontFamily':{'fontFamily':'Times New Roman','weight':400}}
        with self.assertRaisesRegex(ValueError,'formatting'):native_cv.verify_preserved(doc,after,plan)
    def test_native_fragment_deletion_cannot_empty_a_bullet(self):
        doc=self.doc();paragraph=doc['tabs'][0]['body']['content'][0]['paragraph'];original=paragraph['elements'][0]
        original['textRun']['content']=original['textRun']['content'].rstrip('\n')
        fragment=copy.deepcopy(original);fragment['startIndex']=50;fragment['textRun']['content']='Additional verified detail.\n';paragraph['elements'].append(fragment)
        evidence='Led operations with verified process improvements.'
        plan={'edits':[{'run':'t.0:1','text':'','evidence':evidence}],'remove_bullets':[]}
        requests=native_cv.requests_for(doc,plan,evidence,'strategy_two_pages')
        self.assertFalse(any('updateTextStyle' in r for r in requests))
        self.assertFalse(any('insertText' in r for r in requests))
        after=copy.deepcopy(doc);after['tabs'][0]['body']['content'][0]['paragraph']['elements'].pop(0)
        self.assertTrue(native_cv.verify_preserved(doc,after,plan))
        plan['edits'].append({'run':'t.0:50','text':'','evidence':evidence})
        with self.assertRaisesRegex(ValueError,'empty'):native_cv.requests_for(doc,plan,evidence,'strategy_two_pages')
    def test_native_pdf_renderer_exports_every_page(self):
        path=db.ROOT/'fixture.pdf';path.write_bytes(pdf_bytes());images=native_cv.render(path,db.ROOT)
        self.assertEqual(len(images),1);self.assertTrue(images[0].read_bytes().startswith(b'\x89PNG'))
    def test_stdout_reader_drains_events_after_process_exit(self):
        reader=EventLines(io.StringIO('first\nlast\n'));self.assertEqual(reader.next(1),(True,'first\n'));self.assertEqual(reader.next(1),(True,'last\n'));self.assertEqual(reader.next(1),(True,None))
    def test_job_page_search_box_is_not_an_application_form(self):
        obs={'url':'https://jobs.lever.co/fixture/job','text':'Operations role. Search jobs','elements':[{'tag':'input','type':'text','label':'Search'}]}
        self.assertFalse(adapters.application_form(obs));self.assertTrue(adapters.entry_button(obs,{'tag':'button','type':'button','label':'Apply now'}))
        self.assertFalse(adapters.entry_button(obs,{'tag':'button','type':'submit','label':'Apply'}))
if __name__=='__main__':unittest.main()
