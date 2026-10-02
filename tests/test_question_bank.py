import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from hunter import db,questions,sharing,reviews

class UnifiedBankReviewTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def answer(self,label,value='Fixture answer',scope='identity',roles=('strategy','ai')):
  for i in roles:questions.save(i,{'question':label,'value':value,'confirmed':False,'reuse_scope':scope})
 def item(self,label,roles=('strategy','ai')):
  return {'entries':[{'identity':i,'id':r['id'],'version':r['version']} for i in roles for r in questions.catalog(i)['questions'] if r['question']==label]}
 def snapshot_roles(self):return db.rows('SELECT * FROM answer_shares ORDER BY identity,answer_id')
 def test_review_never_creates_sharing_or_changes_reuse_rules(self):
  self.answer('Email','fixture@example.test');self.answer('Notice period','Fixture: 30 days','application')
  result=reviews.review_many({'items':[self.item('Email'),self.item('Notice period')]})
  self.assertEqual(len(result['saved']),2);self.assertEqual(result['failed'],[]);self.assertEqual(self.snapshot_roles(),[])
  for i in db.IDENTITIES:
   rows=questions.catalog(i)['questions'];self.assertTrue(all(r['confirmed'] for r in rows));self.assertTrue(all(r['version']==2 for r in rows));self.assertEqual({r['status'] for r in rows},{'ready','application_review'})
 def test_bank_excludes_unassigned_job_specific_prompts_but_keeps_records(self):
  for label in ('Desired Pay','Will you require sponsorship for employment visa status?','Who referred you for this position?'):
   self.answer(label,scope='application',roles=('ai',))
  self.answer('Email','fixture@example.test',roles=('ai',))
  self.assertEqual([r['question'] for r in questions.catalog('ai')['questions']],['Email'])
  self.assertEqual(db.one('SELECT count(*) n FROM answers',identity='ai')['n'],4)
 def test_review_existing_all_role_assignment_is_unchanged(self):
  d={'question':'Email','value':'fixture@example.test','confirmed':False,'availability':'all'};d['target_versions']={x['identity']:x['version'] for x in sharing.preview('strategy',d)['targets']};sharing.save('strategy',d);before=self.snapshot_roles()
  reviews.review_many({'items':[self.item('Email')]});self.assertEqual(before,self.snapshot_roles())
 def test_single_role_review_does_not_create_or_update_another(self):
  self.answer('Email',roles=('ai',));reviews.review_many({'items':[self.item('Email',('ai',))]});self.assertEqual(questions.catalog('strategy')['questions'],[])
  self.answer('City');before=questions.catalog('strategy')['questions'];reviews.review_many({'items':[self.item('City',('ai',))]});self.assertEqual(before,questions.catalog('strategy')['questions'])
 def test_different_reuse_rules_are_preserved_during_review(self):
  self.answer('Email');q=questions.catalog('ai')['questions'][0];questions.save('ai',{'id':q['id'],'value':q['value'],'confirmed':False,'reuse_scope':'application'})
  reviews.review_many({'items':[self.item('Email')]});self.assertEqual(questions.get('ai',q['id'])['reuse_scope'],'application');self.assertEqual(questions.catalog('strategy')['questions'][0]['reuse_scope'],'identity')
 def test_stale_second_item_blocks_entire_preflight(self):
  self.answer('Email');self.answer('City');items=[self.item('Email'),self.item('City')]
  q=next(x for x in questions.catalog('ai')['questions'] if x['question']=='City');questions.save('ai',{'id':q['id'],'value':'Changed','confirmed':False})
  with self.assertRaisesRegex(ValueError,'changed'):reviews.review_many({'items':items})
  self.assertFalse(any(r['confirmed'] for r in questions.catalog('strategy')['questions']))
 def test_different_answers_not_overwritten(self):
  self.answer('City');q=questions.catalog('ai')['questions'][0];questions.save('ai',{'id':q['id'],'value':'Other city','confirmed':False})
  with self.assertRaisesRegex(ValueError,'Different answers'):reviews.review_many({'items':[self.item('City')]})
  self.assertEqual(questions.get('ai',q['id'])['value'],'Other city')
 def test_expiry_and_import_conflicts_require_individual_review(self):
  self.answer('Email');q=questions.catalog('ai')['questions'][0]
  with db.tx('ai') as c:c.execute('UPDATE answers SET expires_at=? WHERE id=?',('2000-01-01',q['id']))
  with self.assertRaisesRegex(ValueError,'individual review'):reviews.review_many({'items':[self.item('Email')]})
 def test_partial_failure_reports_and_recovers_exactly_once(self):
  self.answer('Email');item=self.item('Email');original=reviews._review_entry
  def fail(op,entry):
   if entry['identity']=='ai':raise OSError('Fixture disk failure')
   return original(op,entry)
  with patch('hunter.reviews._review_entry',side_effect=fail):result=reviews.review_many({'items':[item]})
  self.assertEqual(len(result['failed']),1);self.assertEqual(result['failed'][0]['question'],'Email');db.init();reviews.recover()
  for i in db.IDENTITIES:
   row=questions.catalog(i)['questions'][0];self.assertTrue(row['confirmed']);self.assertEqual(row['version'],2)
 def test_interrupted_review_does_not_confirm_later_changed_value(self):
  self.answer('Email');original=reviews._review_entry
  def fail(op,entry):
   if entry['identity']=='ai':raise OSError('Fixture interruption')
   return original(op,entry)
  with patch('hunter.reviews._review_entry',side_effect=fail):reviews.review_many({'items':[self.item('Email')]})
  q=questions.catalog('ai')['questions'][0];questions.save('ai',{'id':q['id'],'value':'new value','confirmed':False});reviews.recover()
  self.assertFalse(questions.get('ai',q['id'])['confirmed']);self.assertEqual(db.one('SELECT state FROM answer_review_operations')['state'],'needs_review')
 def test_review_address_does_not_rewrite_derived_fields(self):
  self.answer('Address','12 Example House, Gurgaon, Haryana - 122101');before={i:[r for r in questions.catalog(i)['questions'] if r['question']!='Address'] for i in db.IDENTITIES}
  reviews.review_many({'items':[self.item('Address')]})
  for i in db.IDENTITIES:self.assertEqual(before[i],[r for r in questions.catalog(i)['questions'] if r['question']!='Address'])
 def test_already_reviewed_answer_no_new_version(self):
  self.answer('Email');reviews.review_many({'items':[self.item('Email')]});before={i:questions.catalog(i) for i in db.IDENTITIES};reviews.review_many({'items':[self.item('Email')]});self.assertEqual(before,{i:questions.catalog(i) for i in db.IDENTITIES})
 def test_application_snapshot_is_unchanged(self):
  self.answer('Email','first@example.test');reviews.review_many({'items':[self.item('Email')]})
  j=db.upsert_job('ai',{'title':'Fixture','company':'Fixture','url':'https://example.test/job','source_id':'fixture'});a=db.shortlist('ai',j);questions.observe('ai',[{'question':'Email'}],a['id']);before=db.application('ai',a['id'])['answers']
  reviews.review_many({'items':[self.item('Email')]});self.assertEqual(before,db.application('ai',a['id'])['answers'])
