from tests.helpers import fixture_masters
"""Controlled fixtures; no tests touch the real application data or websites."""
import hashlib,json,sqlite3,tempfile,unittest,zipfile,io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from hunter import db,desktop,backup,sources,questions
from hunter.worker import Runner,validate_assessment,clean_env

class CoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(db.DATA,db.ROOT);db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init();fixture_masters();db.set_setting('development_mode',True);self.profiles={}
  for i in db.IDENTITIES:self.profiles[i]=db.capture_profile(i,{'document_id':db.MASTER_IDS[i],'text':'Fixture Candidate\nVerified P&L experience. '+i,'captured_at':db.now(),'revision_id':'fixture-rev'})
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def job(self,i='strategy',url='https://jobs.lever.co/fixture/11111111-1111-1111-1111-111111111111',desc='Lead operations and P&L.'):
  return db.upsert_job(i,dict(title='Head of Operations',company='Fixture Employer',url=url,source_id='fixture',description=desc,test=True))
 def prepared(self):
  i='strategy';j=self.job();a=db.shortlist(i,j);t=db.enqueue(i,'prepare',j,application_id=a['id']);ctx=desktop.claim(i,t,'tester');f=db.ROOT/'fixture.pdf';f.write_bytes(b'%PDF-1.4\ncontrolled test placeholder')
  m=dict(kind='cv',drive_id='fixture-doc',drive_url='https://docs.google.com/document/d/fixture-doc/edit',drive_revision='fixture',profile_id=ctx['profile']['id'],job_hash=ctx['job']['description_hash'],visual_verified=True,verification={'test_fixture':True},template_id='fixture-template')
  d=desktop.register_document(i,t,'tester',m,f)
  with db.tx() as c:c.execute("INSERT INTO accounts VALUES('jobs.lever.co','Fixture','fixture@example.test','shared',0,NULL)")
  return j,a,t,d
 def test_identity_storage_boundary(self):
  j=self.job();self.assertEqual(db.rows('SELECT * FROM jobs',identity='ai'),[])
  with self.assertRaises(ValueError):db.get_job('ai',j)
  with self.assertRaises(ValueError):db.identity_path('../strategy')
  with self.assertRaises(ValueError):db.capture_profile('ai',{'document_id':db.MASTER_IDS['strategy'],'text':'Fixture Candidate','captured_at':db.now()})
  db.set_setting('preferences',{'locations':['Fixture city']},'strategy');self.assertNotEqual(db.get_setting('preferences',{},'ai'),db.get_setting('preferences',{},'strategy'))
 def test_dedup_and_cross_identity_warning(self):
  j=self.job();self.assertEqual(j,self.job(url='https://jobs.lever.co/fixture/11111111-1111-1111-1111-111111111111?utm_source=another'));a=db.shortlist('strategy',j);other=self.job('ai')
  with self.assertRaisesRegex(ValueError,'other role'):db.shortlist('ai',other)
  self.assertNotEqual(a['id'],db.shortlist('ai',other,True)['id']);db.shortlist('ai',self.job('ai','https://jobs.lever.co/fixture/22222222-2222-2222-2222-222222222222'))
  self.assertEqual(len(db.rows('SELECT * FROM applications',identity='ai')),2)
 def test_frozen_task_context(self):
  j=self.job();t=db.enqueue('strategy','assess',j);db.capture_profile('strategy',{'document_id':db.MASTER_IDS['strategy'],'text':'Fixture Candidate\nNew version','captured_at':'2099-01-01','revision_id':'new'});self.job(desc='Changed requirements');db.set_setting('preferences',{'locations':['New city']},'strategy');ctx=desktop.context('strategy',t)
  self.assertEqual(ctx['profile']['id'],self.profiles['strategy']['id']);self.assertEqual(ctx['job']['description'],'Lead operations and P&L.');self.assertNotIn('New city',ctx['preferences'].get('locations',[]))
  with self.assertRaises(ValueError):desktop.context('ai',t)
 def test_immutable_documents_approval_and_hash(self):
  j,a,t,d=self.prepared();db.approve('strategy',a['id']);db.verify_approval('strategy',a['id'],'fill')
  with self.assertRaises(sqlite3.IntegrityError):
   with db.tx('strategy') as c:c.execute("UPDATE documents SET drive_id='different' WHERE id=?",(d,))
  with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump({'Question':{'value':'Changed','confirmed':True}}),a['id']))
  with self.assertRaisesRegex(ValueError,'changed'):db.verify_approval('strategy',a['id'],'fill')
  doc=db.one('SELECT * FROM documents WHERE id=?',(d,),'strategy');p=db.DATA/'strategy'/doc['local_path'];p.chmod(0o600);p.write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'missing or changed'):db.manifest('strategy',a['id'])
 def test_document_registration_is_idempotent(self):
  j,a,t,d=self.prepared();doc=db.one('SELECT * FROM documents WHERE id=?',(d,),'strategy');m=dict(kind='cv',drive_id=doc['drive_id'],drive_url=doc['drive_url'],drive_revision=doc['drive_revision'],profile_id=doc['profile_id'],job_hash=doc['job_hash'],visual_verified=True,verification={'test_fixture':True},template_id='fixture-template')
  self.assertEqual(desktop.register_document('strategy',t,'tester',m,db.ROOT/'fixture.pdf'),d);self.assertEqual(len(db.rows('SELECT * FROM documents',identity='strategy')),1)
  desktop.draft_answers('strategy',t,'tester',{'Why this role?':'Fixture draft'})
  self.assertFalse(db.application('strategy',a['id'])['answers']['Why this role?']['confirmed'])
  with self.assertRaises(ValueError):db.approve('strategy',a['id'])
 def test_unknown_answers_and_development_lock(self):
  j,a,t,d=self.prepared()
  with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump({'Authorisation':{'value':'unknown','confirmed':False}}),a['id']))
  with self.assertRaisesRegex(ValueError,'Confirm'):db.approve('strategy',a['id'])
  with self.assertRaisesRegex(ValueError,'locked'):db.approve('strategy',a['id'],'submit')
  with self.assertRaisesRegex(ValueError,'locked'):db.begin_submission('strategy',a['id'])
 def test_approval_validates_required_fields_and_skips_optional_blanks(self):
  j,a,t,d=self.prepared()
  fields=[{'question':'Email','required':True},{'question':'Optional portfolio','required':False}]
  questions.observe('strategy',fields,a['id'])
  with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump({'Optional portfolio':{'value':'','confirmed':False}}),a['id']))
  with self.assertRaisesRegex(ValueError,'required'):db.approve('strategy',a['id'])
  questions.save('strategy',{'question':'Email address','value':'fixture@example.test','confirmed':True});questions.apply_to_application('strategy',a['id'])
  m=db.manifest('strategy',a['id']);self.assertNotIn('Optional portfolio',m['answers']);db.approve('strategy',a['id'])
  questions.observe('strategy',[{'question':'Email','required':True,'max_length':3}],a['id'])
  with self.assertRaises(ValueError):db.approve('strategy',a['id'])
 def test_public_greenhouse_form_reuses_confirmed_email_without_site_account(self):
  j,a,t,d=self.prepared()
  with db.tx('strategy') as c:c.execute('UPDATE jobs SET url=? WHERE id=?',('https://job-boards.greenhouse.io/fixture/jobs/123',j))
  questions.observe('strategy',[{'question':'Email','required':True}],a['id'])
  with self.assertRaisesRegex(ValueError,'Confirm'):db.manifest('strategy',a['id'])
  questions.save('strategy',{'question':'Email','value':'fixture@example.test','confirmed':True});questions.apply_to_application('strategy',a['id'])
  m=db.manifest('strategy',a['id']);self.assertEqual(m['account'],'fixture@example.test');self.assertEqual(m['account_source'],'confirmed_public_form_email')
  self.assertFalse(db.rows("SELECT * FROM accounts WHERE site='job-boards.greenhouse.io'"))
  db.approve('strategy',a['id'])
 def test_handover_resume_and_worker_exclusion(self):
  j,a,t,d=self.prepared()
  with self.assertRaises(ValueError):desktop.claim('strategy',t,'another-worker')
  desktop.checkpoint('strategy',t,'tester',{'step':'login','message':'Resolve fixture login','url':'https://example.test/form','completed_fields':['name']},True)
  with self.assertRaises(ValueError):desktop.finish('strategy',t,'tester',{'evidence':'not yet'})
  db.task_update('strategy',t,state='waiting_agent');ctx=desktop.claim('strategy',t,'new-worker');self.assertEqual(db.unpack(ctx['task']['checkpoint'])['completed_fields'],['name']);questions.observe('strategy',[{'question':'Name'}],a['id']);desktop.finish('strategy',t,'new-worker',{'evidence':'fixture rechecked'});self.assertEqual(db.application('strategy',a['id'])['document_state'],'prepared')
 def test_restart_recovery_and_no_duplicate_task(self):
  j=self.job();t=db.enqueue('strategy','assess',j);db.task_update('strategy',t,state='working',checkpoint={'completed':['step-one']},pid=98765);db.recover();r=desktop.task('strategy',t)
  self.assertEqual(r['state'],'paused');self.assertIsNone(r['pid']);self.assertIn('step-one',r['checkpoint']);self.assertEqual(db.enqueue('strategy','assess',j),t)
 def test_uncertain_submission_verify_before_retry(self):
  j,a,t,d=self.prepared();db.set_setting('development_mode',False);db.approve('strategy',a['id'],'submit');attempt=db.begin_submission('strategy',a['id']);db.recover();self.assertEqual(db.application('strategy',a['id'])['state'],'verification_needed')
  with self.assertRaises(ValueError):db.begin_submission('strategy',a['id'])
  evidence={'observed_at':db.now(),'url':'https://example.test/confirmation','observation':'Fixture receipt read','receipt':'fixture-123'};db.submission_result('strategy',a['id'],attempt,'confirmed',evidence);self.assertEqual(db.application('strategy',a['id'])['state'],'submitted')
  with self.assertRaises(ValueError):db.submission_result('strategy',a['id'],attempt,'uncertain',evidence)
  self.assertEqual(len(db.rows('SELECT * FROM submission_attempts',identity='strategy')),1)
 def test_native_cli_records_submit_receipt_only_for_expected_destination(self):
  from hunter import cli,adapters
  j,a,t,d=self.prepared();db.set_setting('development_mode',False)
  phrase='Your application has been received'
  adapters.enable({'site':'jobs.lever.co','confirmation_text':phrase,'reviewed':True})
  db.release_task('strategy',t);db.task_update('strategy',t,state='completed',lease_until=None)
  db.approve('strategy',a['id'],'submit');submit=db.enqueue('strategy','submit',j,application_id=a['id']);desktop.claim('strategy',submit,'native-fixture')
  attempt=db.begin_submission('strategy',a['id']);f=db.ROOT/'receipt.json'
  evidence={'url':'https://unrelated.example/confirmation','observed_at':db.now(),'observation':'Fixture confirmation read','confirmation_text':phrase,'page_rechecked':True,'form_absent':True}
  argv=['hunter','submission-result','--identity','strategy','--task',submit,'--owner','native-fixture','--application',a['id'],'--attempt',attempt,'--file',str(f)]
  f.write_text(db.dump({'state':'confirmed','evidence':evidence}))
  with patch('sys.argv',argv),self.assertRaisesRegex(ValueError,'configured employer destination'):cli.main()
  self.assertEqual(db.application('strategy',a['id'])['state'],'verification_needed')
  evidence['url']='https://jobs.lever.co/fixture/confirmation';f.write_text(db.dump({'state':'confirmed','evidence':evidence}))
  with patch('sys.argv',argv),redirect_stdout(io.StringIO()):cli.main()
  self.assertEqual(db.application('strategy',a['id'])['state'],'submitted')
 def test_packaged_native_handoff_has_bundled_cli_and_writable_workspace(self):
  workflow=db.ROOT/'workflows/job-hunter-desktop/SKILL.md';workflow.parent.mkdir(parents=True);workflow.write_text('Fixture workflow')
  t=db.enqueue('strategy','refresh_profile')
  with patch.object(desktop.sys,'frozen',True,create=True),patch.object(desktop.sys,'executable',str(db.ROOT/'Job Hunter.app/Contents/MacOS/Job Hunter')):
   prompt=desktop.prompt('strategy',t);folder=desktop.workspace()
  self.assertEqual(folder,db.DATA.parent/'desktop-workspace')
  self.assertEqual((folder/'workflows/job-hunter-desktop/SKILL.md').read_text(),'Fixture workflow')
  self.assertIn('--cli',prompt);self.assertIn('JOB_HUNTER_DATA=',prompt);self.assertIn(str(folder),prompt)
 def test_external_submission_reconciles_blocker_without_crossing_roles(self):
  j,a,t,d=self.prepared();db.task_update('strategy',t,state='waiting_user',progress='Fixture upload blocked')
  evidence={'source':'employer_email','observed_at':db.now(),'url':'https://mail.google.com/mail/u/0/#all/fixture','observation':'Employer receipt for fixture role observed','confirmation_text':'We received your application for Head of Operations'}
  with self.assertRaises(ValueError):db.record_external_submission('strategy',a['id'],{'source':'user_report'})
  with self.assertRaises(ValueError):db.record_external_submission('ai',a['id'],evidence)
  result=db.record_external_submission('strategy',a['id'],evidence)
  self.assertTrue(result['recorded']);self.assertEqual(result['stopped_tasks'],1)
  self.assertEqual(db.application('strategy',a['id'])['state'],'submitted')
  self.assertEqual(desktop.task('strategy',t)['state'],'stopped')
  self.assertTrue(db.record_external_submission('strategy',a['id'],evidence)['already_submitted'])
  with self.assertRaisesRegex(ValueError,'already confirmed submitted'):db.enqueue('strategy','fill',j,application_id=a['id'])
 def test_scheduled_discovery_requires_confirmed_preferences_and_deduplicates(self):
  runner=Runner();config={'enabled':True,'interval_hours':24,'last_requested_at':0}
  db.set_setting('auto_discovery',config,'strategy');runner.schedule_discovery(100000)
  self.assertFalse(db.rows("SELECT id FROM tasks WHERE kind='discover'",identity='strategy'))
  prefs=db.get_setting('preferences',{},'strategy');prefs['confirmed']=True;db.set_setting('preferences',prefs,'strategy')
  runner.schedule_discovery(100000);runner.schedule_discovery(100001)
  self.assertEqual(len(db.rows("SELECT id FROM tasks WHERE kind='discover'",identity='strategy')),1)
  self.assertFalse(db.rows("SELECT id FROM tasks WHERE kind='discover'",identity='ai'))
  runner.stop()
 def test_backup_restore_history_and_documents(self):
  j,a,t,d=self.prepared();archive=backup.create_backup();dest=db.ROOT/'restored';backup.restore_backup(archive,dest);c=sqlite3.connect(dest/'strategy/tracker.sqlite');self.assertEqual(c.execute('SELECT id FROM documents').fetchone()[0],d);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(c.execute('SELECT state FROM tasks').fetchone()[0],'paused');c.close()
  with zipfile.ZipFile(archive) as z:self.assertFalse(any('token' in x or 'cookie' in x or 'auth.json' in x for x in z.namelist()))
  bad=db.ROOT/'bad.zip'
  with zipfile.ZipFile(bad,'w') as z:z.writestr('manifest.json',json.dumps({'version':1,'files':{'../escape':'bad'}}))
  with self.assertRaisesRegex(ValueError,'Unsafe'):backup.restore_backup(bad,db.ROOT/'badrestore')
 def test_source_failure_is_visible_not_zero(self):
  sources.add_source({'id':'fixture','name':'Fixture','kind':'remotive','config':{}});t=db.enqueue('strategy','discover');db.task_update('strategy',t,state='working',attempts=1);r=Runner()
  with patch('hunter.sources.fetch',side_effect=sources.SourceError('HTTP 403: fixture block')):r.run('strategy',desktop.task('strategy',t))
  run=db.one('SELECT * FROM source_runs',identity='strategy');self.assertEqual(run['state'],'failed');self.assertIsNone(run['matched']);self.assertIn('403',run['error']);self.assertEqual(desktop.task('strategy',t)['state'],'retry_wait');r.stop()
 def test_filters_unknowns_and_country_restrictions(self):
  j={'title':'AI Product Manager','description':'Own product roadmap','location':None,'arrangement':'remote','country_restrictions':['United States']};self.assertFalse(sources.filter_job(j,{'titles':['product'],'countries':['India']})[0]);j['country_restrictions']=[];ok,notes=sources.filter_job(j,{'titles':['product'],'countries':['India']});self.assertTrue(ok);self.assertIn('Posting date unknown',notes);j['title']='Junior Product Manager';self.assertFalse(sources.filter_job(j,{'titles':['product']})[0]);self.assertTrue(sources.filter_job(j,{'titles':['product'],'include_early_career':True})[0])
 def test_untrusted_sources_and_api_keys(self):
  with self.assertRaises(sources.SourceError):sources.public_url('https://127.0.0.1/')
  with self.assertRaises(ValueError):db.canonical_url('javascript:alert(1)')
  with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture-key','ANTHROPIC_API_KEY':'fixture-key'}):self.assertNotIn('OPENAI_API_KEY',clean_env())
  result={'recommendation':'consider','summary':'test','strengths':[{'reason':'match','profile_quote':'invented','job_quote':'job'}],'requirements':[],'gaps':[],'questions':[],'eligibility':{'status':'unknown','explanation':'unknown'}}
  with self.assertRaisesRegex(ValueError,'experience'):validate_assessment(result,'profile','job')

if __name__=='__main__':unittest.main()
