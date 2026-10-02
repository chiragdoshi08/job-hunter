import importlib,json,sqlite3,tempfile,time,unittest,zipfile
from unittest.mock import patch
from pathlib import Path
from hunter import db,identities,questions,sharing,desktop,backup,browser_sessions

class IdentitySetupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def create(self,**values):
  return identities.create(dict(name='Fixture General Management',master_url='https://docs.google.com/document/d/fixture-master/edit',titles=['General Manager'],**values))
 def test_new_identity_has_its_own_profile_preferences_jobs_and_answers(self):
  row=self.create();i=row['id'];self.assertTrue(db.identity_path(i).is_file());self.assertEqual(db.get_setting('preferences',{},i)['titles'],['General Manager'])
  self.assertEqual(db.rows('SELECT * FROM jobs',identity=i),[]);self.assertEqual(db.rows('SELECT * FROM answers',identity=i),[])
  p=db.capture_profile(i,{'document_id':'fixture-master','text':'Fixture Candidate\nControlled fixture profile','captured_at':db.now()})
  self.assertTrue(identities.setup(i)['can_assess']);self.assertEqual(db.rows('SELECT * FROM profiles',identity='strategy'),[])
  with self.assertRaises(ValueError):db.capture_profile(i,{'document_id':db.DEFAULT_MASTER_IDS['ai'],'text':'Fixture Candidate','captured_at':db.now()})
 def test_registry_survives_restart_and_workers_keep_original_identity(self):
  first=self.create();i=first['id'];t=db.enqueue(i,'refresh_profile');identities.create({'name':'Fixture Second Positioning'})
  db.init();self.assertIn(i,db.IDENTITIES);self.assertEqual(db.MASTER_IDS[i],'fixture-master')
  ctx=desktop.claim(i,t,'fixture');self.assertEqual(ctx['task']['id'],t);self.assertEqual(ctx['master_document_id'],'fixture-master')
  self.assertEqual(db.unpack(ctx['task']['payload'])['identity'],i)
  with self.assertRaises(ValueError):desktop.claim('ai',t,'fixture')
 def test_missing_master_or_titles_is_actionable(self):
  i=identities.create({'name':'Fixture Incomplete'})['id']
  with self.assertRaisesRegex(ValueError,'target roles'):db.enqueue(i,'discover')
  with self.assertRaisesRegex(ValueError,'master-profile'):db.enqueue(i,'refresh_profile')
  self.assertFalse(identities.setup(i)['can_assess']);self.assertFalse(identities.setup(i)['can_search'])
 def test_new_identity_inherits_only_answers_marked_all(self):
  questions.save('strategy',{'question':'Only Strategy','value':'Fixture','confirmed':True})
  data={'question':'Email address','value':'fixture@example.test','confirmed':True,'reuse_scope':'identity','availability':'all'}
  data['target_versions']={r['identity']:r['version'] for r in sharing.preview('strategy',data)['targets']};sharing.save('strategy',data)
  i=self.create()['id'];rows=questions.catalog(i)['questions'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['value'],'fixture@example.test');self.assertEqual(rows[0]['sharing']['mode'],'all')
  self.assertEqual(set(rows[0]['sharing']['identities']),set(db.IDENTITIES))
 def test_backup_restore_uses_the_backups_identity_registry(self):
  old_backup=backup.create_backup();i=self.create()['id'];questions.save(i,{'question':'Fixture question','value':'Fixture answer','confirmed':False})
  archive=backup.create_backup();dest=db.ROOT/'restore-three';backup.restore_backup(archive,dest)
  c=sqlite3.connect(dest/i/'tracker.sqlite');self.assertEqual(c.execute('SELECT value FROM answers').fetchone()[0],'Fixture answer');c.close()
  backup.restore_backup(old_backup,db.ROOT/'restore-two');self.assertFalse((db.ROOT/'restore-two'/i).exists())
 def test_profile_reference_change_does_not_reuse_old_capture_for_assessment(self):
  i=self.create()['id'];db.capture_profile(i,{'document_id':'fixture-master','text':'Fixture Candidate\nFixture','captured_at':db.now()})
  identities.update(i,{'master_url':'https://docs.google.com/document/d/fixture-new/edit'})
  self.assertFalse(identities.setup(i)['can_assess']);self.assertEqual(len(db.rows('SELECT * FROM profiles',identity=i)),1)
  j=db.upsert_job(i,{'title':'Fixture General Manager','company':'Fixture','url':'https://example.test/job','source_id':'fixture'})
  with self.assertRaisesRegex(ValueError,'master profile'):db.enqueue(i,'assess',j)
 def test_duplicate_names_and_untrusted_profile_urls_rejected(self):
  self.create()
  with self.assertRaisesRegex(ValueError,'already exists'):self.create()
  with self.assertRaises(ValueError):identities.create({'name':'Bad URL','master_url':'file:///private/file'})
  with self.assertRaises(ValueError):db.identity_path('../outside')
 def test_local_browser_session_persists_without_raw_tokens_or_backup(self):
  token=browser_sessions.issue();self.assertTrue(browser_sessions.valid(token));stored=(db.DATA/'browser-sessions.json').read_text();self.assertNotIn(token,stored)
  importlib.reload(browser_sessions);self.assertTrue(browser_sessions.valid(token));self.assertFalse(browser_sessions.valid('wrong-session-token'))
  browser_sessions.register('expired-fixture-token',time.time()-1);self.assertFalse(browser_sessions.valid('expired-fixture-token'))
  if __import__('os').name!='nt':self.assertEqual((db.DATA/'browser-sessions.json').stat().st_mode&0o777,0o600)
  with zipfile.ZipFile(backup.create_backup()) as z:self.assertFalse(any('session' in n for n in z.namelist()))
 def test_browser_connections_do_not_collide_between_live_and_test_installations(self):
  original=db.DATA;live_name=browser_sessions.cookie_name();token=browser_sessions.issue()
  try:
   db.DATA=db.ROOT/'isolated-fixture';self.assertNotEqual(browser_sessions.cookie_name(),live_name);self.assertFalse(browser_sessions.valid(token));browser_sessions.issue()
  finally:db.DATA=original
  self.assertTrue(browser_sessions.valid(token));self.assertEqual(browser_sessions.cookie_name(),live_name)
 def test_identity_names_can_start_with_numbers_or_use_non_latin_characters(self):
  for name in ('360 Business','रणनीति'):
   i=identities.create({'name':name})['id'];self.assertTrue(db.identity_path(i).is_file());self.assertEqual(db.IDENTITIES[i],name)
 def test_interrupted_creation_finishes_shared_answer_inheritance_on_restart(self):
  data={'question':'Email address','value':'fixture@example.test','confirmed':True,'reuse_scope':'identity','availability':'all'}
  data['target_versions']={r['identity']:r['version'] for r in sharing.preview('strategy',data)['targets']};sharing.save('strategy',data)
  with patch('hunter.identities.inherit_shared',side_effect=RuntimeError('Fixture interruption')):
   with self.assertRaises(RuntimeError):self.create()
  row=db.one("SELECT * FROM identities WHERE state='creating'");self.assertNotIn(row['id'],db.IDENTITIES)
  db.init();self.assertIn(row['id'],db.IDENTITIES);self.assertEqual(questions.catalog(row['id'])['questions'][0]['value'],'fixture@example.test')

if __name__=='__main__':unittest.main()
