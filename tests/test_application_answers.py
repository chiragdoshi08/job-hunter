from tests.helpers import fixture_masters
import tempfile,unittest
from pathlib import Path
from hunter import db,questions,application_answers,desktop
class ApplicationAnswerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init();fixture_masters()
  self.j=db.upsert_job('strategy',dict(title='Fixture',company='Fixture',url='https://example.test/form',description='Fixture job',source_id='fixture'));self.a=db.shortlist('strategy',self.j)
  questions.observe('strategy',[{'question':'Notice period','max_length':80},{'question':'Are you authorised to work in India?','choices':['Yes','No']},{'question':'Optional portfolio','required':False}],self.a['id'])
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def edit(self,q,value):
  return {'question':q,'value':value,'expected':db.application('strategy',self.a['id'])['answers'].get(q),'field_version':application_answers.fields('strategy',self.a['id']).get(q,{}).get('field_version')}
 def save(self,*edits):return application_answers.save_batch('strategy',self.a['id'],{'edits':list(edits),'confirmed':True})
 def answers(self):return db.application('strategy',self.a['id'])['answers']
 def test_two_answers_saved_separately_once_and_survive_restart(self):
  result=self.save(self.edit('Notice period','Fixture: 30 days'),self.edit('Are you authorised to work in India?','Yes'))
  self.assertEqual(result['saved'],2);db.init();self.assertEqual(self.answers()['Notice period']['value'],'Fixture: 30 days');self.assertEqual(self.answers()['Are you authorised to work in India?']['value'],'Yes');self.assertEqual(questions.readiness('strategy',self.a['id'])['confirmed'],2)
 def test_partial_save_keeps_remaining_questions_and_constraints(self):
  self.save(self.edit('Notice period','Fixture: 30 days'));fields=application_answers.fields('strategy',self.a['id']);self.assertEqual(db.unpack(fields['Are you authorised to work in India?']['choices']),['Yes','No']);self.assertFalse(self.answers()['Are you authorised to work in India?']['confirmed'])
 def test_invalid_later_row_rolls_back_entire_batch(self):
  before=self.answers()
  with self.assertRaisesRegex(ValueError,'current options'):self.save(self.edit('New question','New value'),self.edit('Are you authorised to work in India?','Maybe'))
  self.assertEqual(self.answers(),before);self.assertIsNone(db.one("SELECT id FROM answers WHERE question='New question'",identity='strategy'))
 def test_stale_answer_rejected_but_other_concurrent_answers_preserved(self):
  stale=self.edit('Notice period','Old edit');self.save(self.edit('Notice period','Newer edit'))
  with self.assertRaisesRegex(ValueError,'changed'):self.save(stale)
  waiting=self.edit('Are you authorised to work in India?','Yes');self.save(self.edit('Different question','Concurrent answer'));self.save(waiting);self.assertEqual(self.answers()['Different question']['value'],'Concurrent answer')
 def test_changed_form_constraints_rejected(self):
  old=self.edit('Notice period','30 days');questions.observe('strategy',[{'question':'Notice period','max_length':2}],self.a['id'])
  with self.assertRaisesRegex(ValueError,'form changed'):self.save(old)
  with self.assertRaisesRegex(ValueError,'limit'):self.save(self.edit('Notice period','30 days'))
 def test_scope_confirmation_duplicates_and_credentials(self):
  edit=self.edit('Notice period','Fixture')
  with self.assertRaises(ValueError):application_answers.save_batch('ai',self.a['id'],{'edits':[edit],'confirmed':True})
  with self.assertRaisesRegex(ValueError,'Confirm'):application_answers.save_batch('strategy',self.a['id'],{'edits':[edit],'confirmed':False})
  with self.assertRaisesRegex(ValueError,'twice'):self.save(edit,edit)
  with self.assertRaisesRegex(ValueError,'credentials'):self.save(self.edit('Password','secret'))
 def test_draft_bank_suggestion_not_confirmed_or_saved_by_reading(self):
  q=questions.ensure('strategy','Notice period');questions.save('strategy',{'id':q,'value':'Fixture: 45 days','confirmed':False})
  before=self.answers();fields=application_answers.fields('strategy',self.a['id']);self.assertEqual(fields['Notice period']['suggestion'],'Fixture: 45 days');self.assertEqual(self.answers(),before);self.assertFalse(questions.get('strategy',q)['confirmed'])
 def test_manual_question_enters_bank_as_draft_without_fake_form_capture(self):
  self.save(self.edit('Extra question','Fixture answer'));bank=db.one("SELECT * FROM answers WHERE question='Extra question'",identity='strategy');self.assertFalse(bank['confirmed']);self.assertEqual(bank['value'],'Fixture answer');self.assertNotIn('Extra question',application_answers.fields('strategy',self.a['id']))
 def test_specific_form_questions_live_only_in_the_application(self):
  question='Who referred you for this position?';other='What is a widely accepted practice you think is overrated?'
  result=questions.observe('strategy',[{'question':question,'required':False},{'question':other,'type':'textarea'}],self.a['id'],'https://example.test/form')
  self.assertEqual(len(result['questions']),2)
  bank={r['question'] for r in questions.catalog('strategy')['questions']}
  self.assertNotIn(question,bank);self.assertNotIn(other,bank);self.assertIn('Notice period',bank)
  before=db.one('SELECT * FROM answers WHERE id=?',(result['questions'][0]['id'],),'strategy')
  self.save(self.edit(question,'Fixture referee'))
  after=db.one('SELECT * FROM answers WHERE id=?',(result['questions'][0]['id'],),'strategy')
  self.assertEqual(before,after);self.assertEqual(self.answers()[question]['value'],'Fixture referee')
  listed=application_answers.list_with_question_counts('strategy',[dict(db.one('SELECT * FROM applications WHERE id=?',(self.a['id'],),'strategy'))])[0]
  self.assertEqual(listed['form_questions_total'],5);self.assertEqual(listed['form_questions_to_review'],4)
 def test_same_employer_question_is_scoped_to_each_application(self):
  question='Why are you interested in joining Fixture?'
  first=questions.observe('strategy',[{'question':question,'type':'textarea'}],self.a['id'],'https://example.test/form')['questions'][0]['id']
  j=db.upsert_job('strategy',dict(title='Other fixture',company='Fixture',url='https://example.test/other',description='Different role',source_id='fixture'));second_app=db.shortlist('strategy',j)
  second=questions.observe('strategy',[{'question':question,'type':'textarea'}],second_app['id'],'https://example.test/other')['questions'][0]['id']
  self.assertNotEqual(first,second)
  self.save(self.edit(question,'Reason for first role'))
  self.assertFalse(application_answers.fields('strategy',second_app['id'])[question]['suggestion'])
  self.assertNotIn(question,{r['question'] for r in questions.catalog('strategy')['questions']})
 def test_legacy_confirmed_bank_value_becomes_reviewable_application_suggestion(self):
  question='Date Available';url='https://example.test/form';qid=questions.ensure('strategy',question,source_url=url)
  questions.save('strategy',{'id':qid,'value':'2030-01-01','confirmed':True,'reuse_scope':'identity'})
  with db.tx('strategy') as c:c.execute('INSERT INTO question_encounters(id,answer_id,application_id,question,choices,required,field_type,source_url,observed_at,active) VALUES(?,?,?,?,?,?,?,?,?,1)',(db.uid(),qid,self.a['id'],question,'[]',0,'text',url,db.now()))
  self.assertNotIn(question,{r['question'] for r in questions.catalog('strategy')['questions']})
  self.assertEqual(application_answers.fields('strategy',self.a['id'])[question]['suggestion'],'2030-01-01')
  self.assertTrue(application_answers.fields('strategy',self.a['id'])[question]['application_only'])
  self.assertFalse(self.answers().get(question,{}).get('confirmed'))
  before=questions.get('strategy',qid)
  self.save(self.edit(question,'2030-01-02'))
  self.assertEqual(questions.get('strategy',qid),before)
  self.assertEqual(self.answers()[question]['value'],'2030-01-02')
 def test_manual_referral_answer_is_not_added_to_shared_bank(self):
  question='Who referred you for this position?'
  self.save(self.edit(question,'Fixture person'))
  self.assertEqual(self.answers()[question]['value'],'Fixture person')
  bank=db.one('SELECT * FROM answers WHERE question=?',(question,),'strategy')
  self.assertEqual(bank['category'],'application_only');self.assertEqual(bank['value'],'')
  self.assertNotIn(question,{r['question'] for r in questions.catalog('strategy')['questions']})
 def test_preparation_cannot_complete_without_questionnaire(self):
  from unittest.mock import patch
  db.capture_profile('ai',{'document_id':db.MASTER_IDS['ai'],'text':'Fixture Candidate fixture','captured_at':db.now()})
  j=db.upsert_job('ai',dict(title='Fixture AI',company='Fixture',url='https://example.test/ai',description='Fixture',source_id='fixture'));a=db.shortlist('ai',j);t=db.enqueue('ai','prepare',j,application_id=a['id']);desktop.claim('ai',t,'fixture')
  original=db.rows
  def mocked(sql,*args,**kw):return [{'kind':'cv'}] if sql.startswith('SELECT * FROM documents WHERE application_id') else original(sql,*args,**kw)
  with patch('hunter.db.rows',side_effect=mocked):
   with self.assertRaisesRegex(ValueError,'questions'):desktop.finish('ai',t,'fixture',{'evidence':'Controlled fixture'})
