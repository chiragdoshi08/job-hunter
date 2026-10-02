import unittest,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch
from hunter import db,questions,sharing,backup

class AnswerSharingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def save(self,i='strategy',**kw):
  data=dict(question='Email address',value='fixture@example.test',confirmed=True,reuse_scope='identity',availability='all');data.update(kw)
  data['target_versions']={r['identity']:r['version'] for r in sharing.preview(i,data)['targets']}
  return sharing.save(i,data)
 def test_explicit_all_identity_sharing_and_confirm_once(self):
  result=self.save();self.assertEqual(set(result['saved_in']),{'strategy','ai'})
  for i in db.IDENTITIES:
   rows=questions.catalog(i)['questions'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'ready');self.assertEqual(rows[0]['sharing']['mode'],'all')
  self.assertNotEqual(questions.catalog('strategy')['questions'][0]['id'],questions.catalog('ai')['questions'][0]['id'])
 def test_confirmed_personal_answer_reuse_is_saved_across_all_roles(self):
  result=self.save(question='Are you a veteran?',value='No');self.assertEqual(result['reuse_scope'],'identity');self.assertTrue(result['confirmed']);db.init()
  for i in db.IDENTITIES:
   q=questions.catalog(i)['questions'][0];self.assertEqual(q['reuse_scope'],'identity');self.assertEqual(q['status'],'ready');self.assertEqual(q['sharing']['mode'],'all')
 def test_contextual_sharing_rejects_unsupported_choice_before_any_write(self):
  with self.assertRaisesRegex(ValueError,'Compensation'):self.save(question='Expected salary',value='Fixture')
  self.assertEqual(db.rows('SELECT * FROM answer_share_operations'),[])
  for i in db.IDENTITIES:self.assertEqual(questions.catalog(i)['questions'],[])
 def test_local_default_and_selected_identity_validation(self):
  self.save(availability='this');self.assertEqual(questions.catalog('ai')['questions'],[])
  with self.assertRaises(ValueError):self.save(availability='selected',identities=['missing'])
  result=self.save(availability='selected',identities=['ai']);self.assertEqual(result['saved_in'],['ai'])
 def test_choose_single_named_role_excluding_source(self):
  source=questions.save('strategy',{'question':'Email','value':'fixture@example.test','confirmed':False})
  before=questions.get('strategy',source)
  result=self.save(question='Email',id=source,expected_version=before['version'],availability='selected',identities=['ai'])
  self.assertEqual(result['saved_in'],['ai']);self.assertEqual(before,questions.get('strategy',source));self.assertEqual(questions.catalog('ai')['questions'][0]['value'],'fixture@example.test')
 def test_single_other_role_requires_version_and_conflict_review(self):
  source=questions.save('strategy',{'question':'Email','value':'fixture@example.test','confirmed':False});target=questions.save('ai',{'question':'Email','value':'different@example.test','confirmed':True})
  data={'id':source,'expected_version':1,'value':'fixture@example.test','confirmed':True,'availability':'selected','identities':['ai'],'target_versions':{'ai':1}}
  with self.assertRaisesRegex(ValueError,'different'):sharing.save('strategy',data)
  data['replace_conflicts']=True;data['target_versions']['ai']=0
  with self.assertRaisesRegex(ValueError,'current'):sharing.save('strategy',data)
  data['target_versions']['ai']=1;sharing.save('strategy',data);self.assertEqual(questions.get('ai',target)['value'],'fixture@example.test')
 def test_named_role_override_does_not_claim_all_roles(self):
  from hunter import identities
  third=identities.create({'name':'Fixture Third Role','titles':[]})['id'];result=self.save()
  data={'id':result['id'],'expected_version':1,'value':'new@example.test','confirmed':True,'availability':'selected','identities':['ai'],'target_versions':{'ai':1},'replace_conflicts':True}
  sharing.save('strategy',data)
  self.assertEqual(questions.catalog('strategy')['questions'][0]['value'],'fixture@example.test');self.assertEqual(questions.catalog(third)['questions'][0]['value'],'fixture@example.test')
  self.assertEqual(questions.catalog('strategy')['questions'][0]['sharing']['mode'],'selected');self.assertEqual(questions.catalog('ai')['questions'][0]['sharing']['mode'],'this')
 def test_conflict_needs_review_and_versions_cannot_race(self):
  q=questions.save('ai',{'question':'Email address','value':'different@example.test','confirmed':True})
  with self.assertRaisesRegex(ValueError,'different'):self.save()
  self.assertEqual(questions.catalog('strategy')['questions'],[])
  data={'question':'Email address','value':'fixture@example.test','confirmed':True,'availability':'all','target_versions':{'strategy':None,'ai':1},'replace_conflicts':True}
  questions.save('ai',{'id':q,'value':'changed@example.test','confirmed':True})
  with self.assertRaisesRegex(ValueError,'current'):sharing.save('strategy',data)
  self.save(replace_conflicts=True);self.assertEqual(questions.get('ai',q)['value'],'fixture@example.test')
 def test_shared_edits_leave_application_versions_fixed(self):
  result=self.save();q=result['id'];j=db.upsert_job('ai',{'title':'Fixture','company':'Fixture','url':'https://example.test/job','source_id':'fixture'});a=db.shortlist('ai',j);questions.observe('ai',[{'question':'Email'}],a['id'])
  self.save(id=q,expected_version=1,value='new@example.test',replace_conflicts=True)
  questions.apply_to_application('ai',a['id']);self.assertEqual(db.application('ai',a['id'])['answers']['Email']['value'],'fixture@example.test')
  self.assertEqual(questions.catalog('ai')['questions'][0]['value'],'new@example.test')
 def test_stopping_sharing_keeps_independent_copies(self):
  result=self.save();self.save(id=result['id'],expected_version=1,availability='this',value='local@example.test')
  self.assertEqual(questions.catalog('ai')['questions'][0]['value'],'fixture@example.test')
  self.assertEqual(questions.catalog('ai')['questions'][0]['sharing']['mode'],'this')
 def test_shared_address_extracts_separate_confirmed_parts(self):
  self.save(question='Address',value='12 Example House, Gurgaon, Haryana - 122101')
  for i in db.IDENTITIES:
   rows=questions.catalog(i)['questions'];self.assertEqual(len(rows),4);self.assertTrue(all(r['confirmed'] for r in rows))
 def test_backup_preserves_sharing_and_address_dependencies(self):
  self.save(question='Address',value='12 Example House, Gurgaon, Haryana - 122101')
  archive=backup.create_backup();dest=db.ROOT/'restored';backup.restore_backup(archive,dest)
  c=sqlite3.connect(dest/'shared.sqlite');self.assertEqual(c.execute('SELECT count(*) FROM answer_shares').fetchone()[0],2);c.close()
  c=sqlite3.connect(dest/'ai/tracker.sqlite');self.assertEqual(c.execute('SELECT count(*) FROM answers WHERE derived_from IS NOT NULL').fetchone()[0],3);self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],6);c.close()
 def test_interrupted_share_recovers_without_duplicate_versions(self):
  original=questions.save
  def fail_second(i,*args,**kwargs):
   if i=='ai':raise OSError('Controlled interrupted write')
   return original(i,*args,**kwargs)
  with patch('hunter.sharing.questions.save',side_effect=fail_second):
   with self.assertRaises(OSError):self.save()
  self.assertEqual(questions.catalog('strategy')['questions'][0]['version'],1)
  sharing.recover();sharing.recover()
  self.assertEqual(questions.catalog('strategy')['questions'][0]['version'],1);self.assertEqual(questions.catalog('ai')['questions'][0]['version'],1)
  self.assertEqual(db.one('SELECT state FROM answer_share_operations')['state'],'completed')

if __name__=='__main__':unittest.main()
