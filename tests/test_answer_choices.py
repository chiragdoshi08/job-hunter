from tests.helpers import fixture_masters
"""Controlled alternatives and application snapshots; no live submissions."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from hunter import db,questions,desktop,answer_choices,sharing,reviews,backup,identities

class AnswerChoiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init();fixture_masters()
  db.capture_profile('ai',{'document_id':db.MASTER_IDS['ai'],'text':'Fixture Candidate\nBusiness Transformation Lead','captured_at':db.now()})
  self.job=db.upsert_job('ai',{'title':'AI Transformation Lead','company':'Fixture','url':'https://example.test/roles/choice','description':'Lead enterprise AI adoption and redesign cross-functional business workflows.','source_id':'fixture','test':True})
  self.app=db.shortlist('ai',self.job);self.task=db.enqueue('ai','scan_form',self.job,application_id=self.app['id']);desktop.claim('ai',self.task,'test-agent')
  self.values='Business Transformation Lead – AI\nChief Of Staff\nAI Transformation Lead'
  self.q=questions.save('ai',{'question':'Current job title','value':self.values,'answer_mode':'jd_choice','confirmed':True,'reuse_scope':'identity'})
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def observe(self,**extra):return questions.observe('ai',[{'question':'Current job title',**extra}],self.app['id'],'https://example.test/form',self.task)
 def selection(self,**extra):
  row=questions.get('ai',self.q)
  return dict(answer_id=self.q,answer_version=row['version'],value='AI Transformation Lead',reason='The role focuses on leading AI adoption.',job_quote='Lead enterprise AI adoption',job_hash=db.get_job('ai',self.job)['description_hash'],model='controlled-test-model',**extra)
 def choose(self,data=None):return answer_choices.select('ai',self.task,'test-agent',data or self.selection())
 def snapshot(self):return db.application('ai',self.app['id'])['answers']['Current job title']
 def test_never_pastes_list_and_selection_is_auditable(self):
  self.observe();self.assertEqual(self.snapshot()['value'],'');self.assertFalse(self.snapshot()['confirmed'])
  self.assertEqual(questions.readiness('ai',self.app['id'])['fields'][0]['alternatives'],self.values.splitlines())
  self.choose();snap=self.snapshot();self.assertEqual(snap['value'],'AI Transformation Lead');self.assertTrue(snap['confirmed']);self.assertEqual(snap['selection']['model'],'controlled-test-model');self.assertEqual(snap['answer_version'],1)
  self.assertEqual(questions.readiness('ai',self.app['id'])['confirmed'],1)
 def test_exact_options_evidence_version_owner_role_and_jd_required(self):
  self.observe()
  for key,value in [('value',self.values),('value','Invented title'),('job_quote','unobserved JD claim'),('answer_version',99),('job_hash','wrong'),('model','')]:
   d=self.selection();d[key]=value
   with self.assertRaises(ValueError):self.choose(d)
  with self.assertRaises(ValueError):answer_choices.select('ai',self.task,'another-agent',self.selection())
  with self.assertRaises(ValueError):answer_choices.select('strategy',self.task,'test-agent',self.selection())
 def test_observation_and_form_constraints_required(self):
  with self.assertRaisesRegex(ValueError,'Observe'):self.choose()
  self.observe(max_length=5)
  with self.assertRaisesRegex(ValueError,'length'):self.choose()
  self.observe(choices=['Chief Of Staff'])
  with self.assertRaisesRegex(ValueError,'choices'):self.choose()
 def test_restart_bank_edits_retries_and_backup_preserve_choice(self):
  self.observe();self.choose();snap=self.snapshot();questions.save('ai',{'id':self.q,'value':'Chief Of Staff\nBusiness Transformation Lead – AI','confirmed':True})
  db.init();questions.apply_to_application('ai',self.app['id']);self.assertEqual(self.snapshot(),snap)
  archive=backup.create_backup();backup.restore_backup(archive,db.ROOT/'restored')
  c=sqlite3.connect(db.ROOT/'restored/ai/tracker.sqlite');self.assertEqual(c.execute('select count(*) from answer_behaviors').fetchone()[0],2);c.close()
  with self.assertRaises(sqlite3.IntegrityError):
   with db.tx('ai') as c:c.execute("UPDATE answer_behaviors SET mode='single'")
 def test_selection_is_idempotent_and_invalidates_approval(self):
  self.observe();self.choose();snap=self.snapshot();result=self.choose();self.assertFalse(result['saved']);self.assertEqual(self.snapshot(),snap)
  self.assertIsNone(db.application('ai',self.app['id'])['approval_id'])
 def test_unconfirmed_expired_and_per_application_options(self):
  self.observe()
  for extra in ({'confirmed':False},{'confirmed':True,'expires_at':'2000-01-01'}):
   questions.save('ai',{'id':self.q,'value':self.values,**extra})
   with self.assertRaisesRegex(ValueError,'review'):self.choose()
  questions.save('ai',{'id':self.q,'value':self.values,'confirmed':True,'expires_at':None,'reuse_scope':'application'})
  self.choose();self.assertFalse(self.snapshot()['confirmed']);self.assertEqual(self.snapshot()['value'],'AI Transformation Lead')
 def test_bulk_review_and_role_sharing_preserve_answer_mode(self):
  questions.save('ai',{'id':self.q,'value':self.values,'confirmed':False});q=questions.get('ai',self.q)
  reviews.review_many({'items':[{'entries':[{'identity':'ai','id':self.q,'version':q['version']}]}]})
  q=questions.get('ai',self.q);self.assertEqual(q['answer_mode'],'jd_choice')
  data={'id':self.q,'expected_version':q['version'],'value':self.values,'confirmed':True,'availability':'all','reuse_scope':'identity'}
  plan=sharing.preview('ai',data);data['target_versions']={r['identity']:r['version'] for r in plan['targets']};sharing.save('ai',data)
  self.assertEqual(questions.catalog('strategy')['questions'][0]['answer_mode'],'jd_choice')
 def test_scalar_defaults_and_fact_fields_cannot_be_contextual_choices(self):
  q=questions.save('ai',{'question':'Email','value':'one@example.test','confirmed':True});self.assertEqual(questions.get('ai',q)['answer_mode'],'single')
  for label in ('Email','Are you a veteran?','Official current job title','Employment history title','Visa sponsorship'):
   with self.assertRaises(ValueError):questions.save('ai',{'question':label,'value':'A\nB','answer_mode':'jd_choice','confirmed':True})
  with self.assertRaises(ValueError):questions.save('ai',{'id':self.q,'value':'One line','answer_mode':'jd_choice'})
 def test_changed_jd_invalidates_old_selection(self):
  self.observe();self.choose();j=db.get_job('ai',self.job);j['description']='Changed responsibilities: AI governance.';db.upsert_job('ai',j)
  self.assertEqual(questions.readiness('ai',self.app['id'])['confirmed'],0)
  with self.assertRaisesRegex(ValueError,'captured|changed'):self.choose()
