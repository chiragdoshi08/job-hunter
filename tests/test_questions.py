import unittest,tempfile,sqlite3,json
from pathlib import Path
from hunter import db,questions,desktop,backup,addressing

class QuestionBankTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=db.DATA,db.ROOT;db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init()
 def tearDown(self):db.DATA,db.ROOT=self.old;self.tmp.cleanup()
 def app(self,identity='strategy',n=1):
  j=db.upsert_job(identity,{'title':'Fixture role','company':'Fixture '+str(n),'url':f'https://example.test/jobs/{n}','description':'Fixture','source_id':'fixture'});return db.shortlist(identity,j)
 def answer(self,q='Email address',value='fixture@example.test',**extra):
  return questions.save('strategy',dict(question=q,value=value,confirmed=True,**extra))
 def test_bank_rejects_credentials_and_stale_edits(self):
  with self.assertRaisesRegex(ValueError,'credentials'):self.answer('Password','fixture-secret')
  q=self.answer()
  with self.assertRaisesRegex(ValueError,'changed'):questions.save('strategy',{'id':q,'value':'outdated@example.test','confirmed':True,'expected_version':0})
 def test_address_parts_inherit_confirmation_scope_and_expiry(self):
  q=self.answer('Address','12 Example House, Example Road, Gurgaon, Haryana - 122101',reuse_scope='identity',expires_at='2099-01-01')
  values={r['question']:r for r in questions.catalog('strategy')['questions']}
  self.assertEqual(values['City']['value'],'Gurgaon');self.assertEqual(values['Province']['value'],'Haryana');self.assertEqual(values['Postal code']['value'],'122101')
  self.assertEqual(values['Province']['derived_from'],q);self.assertEqual(values['Province']['expires_at'],'2099-01-01')
  a=self.app();r=questions.observe('strategy',[{'question':'City'},{'question':'State'},{'question':'PIN code'}],a['id']);self.assertEqual(r['readiness']['confirmed'],3)
  self.assertEqual(questions.catalog('ai')['questions'],[])
 def test_address_updates_preserve_application_snapshots_and_manual_corrections(self):
  q=self.answer('Address','12 Example House, Gurgaon, Haryana - 122101',reuse_scope='identity')
  a=self.app();questions.observe('strategy',[{'question':'City'}],a['id'])
  questions.save('strategy',{'id':q,'value':'12 Example House, Jaipur, Rajasthan - 302001','confirmed':True})
  city=next(r for r in questions.catalog('strategy')['questions'] if r['question']=='City')
  self.assertEqual(city['value'],'Jaipur');self.assertEqual(city['derived_version'],2)
  questions.apply_to_application('strategy',a['id']);self.assertEqual(db.application('strategy',a['id'])['answers']['City']['value'],'Gurgaon')
  questions.save('strategy',{'id':city['id'],'value':'Independently entered city','confirmed':True})
  questions.save('strategy',{'id':q,'value':'12 Example House, Mumbai, Maharashtra - 400001','confirmed':True})
  city=questions.get('strategy',city['id']);self.assertEqual(city['value'],'Independently entered city');self.assertEqual(questions.state(city),'needs_review')
 def test_unclear_or_unconfirmed_address_never_produces_ready_guesses(self):
  for value in ('Example Road, Haryana - 122101','12 Building, Sector 70A, Haryana - 122101','No city or state supplied'):
   self.assertEqual(addressing.extract(value),{})
  q=questions.save('strategy',{'question':'Address','value':'12 Example House, Gurgaon, Haryana - 122101','confirmed':False,'reuse_scope':'application'})
  parts=[r for r in questions.catalog('strategy')['questions'] if r['derived_from']==q]
  self.assertEqual(len(parts),3);self.assertTrue(all(not r['confirmed'] and r['reuse_scope']=='application' for r in parts))
  questions.save('strategy',{'id':q,'value':'Address changed; city not specified','confirmed':True})
  self.assertTrue(all(questions.get('strategy',r['id'])['review_note'] for r in parts))
 def test_new_questions_are_persisted_and_known_answers_reused_without_ai(self):
  q=self.answer();a=self.app();r=questions.observe('strategy',[{'question':'Email'},{'question':'What is your notice period?'}],a['id'],'https://example.test/form')
  self.assertEqual(r['readiness']['confirmed'],1);self.assertEqual(r['readiness']['needs_answer'],1);self.assertEqual(len(questions.catalog('strategy')['questions']),2)
  snap=db.application('strategy',a['id'])['answers']['Email'];self.assertEqual(snap['answer_id'],q);self.assertEqual(snap['answer_version'],1)
  questions.observe('strategy',[{'question':'Email'}],a['id']);self.assertEqual(db.one('SELECT count(*) n FROM question_encounters',identity='strategy')['n'],2)
 def test_stable_facts_follow_common_form_wording_and_section_changes(self):
  self.answer('Current employer','Fixture Corp',reuse_scope='identity')
  self.answer('Phone number','1234567890',reuse_scope='identity')
  self.answer('Phone — Country','+91',reuse_scope='identity')
  self.answer('What is your availability to start? (notice period)','15 days',reuse_scope='identity')
  a=self.app();r=questions.observe('strategy',[
   {'question':'Current company'},
   {'question':'Mobile phone number','context':{'section':'Contact page'}},
   {'question':'Phone country code','context':{'section':'Contact page'}},
   {'question':'How soon are you able to join if selected?','type':'textarea','context':{'section':'Final page'}},
  ],a['id'])
  self.assertEqual(r['readiness']['confirmed'],4)
  answers=db.application('strategy',a['id'])['answers']
  self.assertEqual(answers['Current company']['value'],'Fixture Corp')
  self.assertEqual(answers['How soon are you able to join if selected?']['value'],'15 days')
  self.answer('What are your base salary expectations?','7000000')
  b=self.app(n=2);r=questions.observe('strategy',[{'question':'Current CTC'}],b['id'])
  self.assertEqual(r['readiness']['needs_answer'],1)
 def test_import_remains_unconfirmed_and_cannot_overwrite_confirmed_answer(self):
  q=self.answer();r=questions.import_profile('strategy',[{'question':'Email address','value':'changed@example.test'}],'https://simplify.jobs/profile/fixture')
  row=questions.get('strategy',q);self.assertEqual(row['value'],'fixture@example.test');self.assertEqual(questions.state(row),'needs_review')
  questions.import_profile('ai',[{'question':'Email address','value':'changed@example.test'}],'https://simplify.jobs/profile/fixture');self.assertFalse(questions.catalog('ai')['questions'][0]['confirmed'])
  self.assertEqual(db.one('SELECT count(*) n FROM answer_imports',identity='strategy')['n'],1)
 def test_country_scope_negation_and_context_are_not_fuzzy_matched(self):
  self.answer('Are you authorized to work in the US?','No');a=self.app()
  result=questions.observe('strategy',[{'question':'Are you authorized to work in Canada?'},{'question':'Are you NOT authorized to work in the US?'}],a['id'])
  self.assertEqual(result['readiness']['confirmed'],0)
 def test_contextual_answers_are_never_automatic_even_if_same_wording(self):
  for q in ['Why do you want to join our company?','Expected salary','Will you require sponsorship?']:
   qid=self.answer(q,'Fixture answer');version=questions.get('strategy',qid)['version']
   with self.assertRaisesRegex(ValueError,'Review|review'):questions.save('strategy',{'id':qid,'value':'Changed fixture','confirmed':True,'reuse_scope':'identity'})
   row=questions.get('strategy',qid);self.assertEqual(row['reuse_scope'],'application');self.assertEqual(row['value'],'Fixture answer');self.assertEqual(row['version'],version)
  a=self.app();r=questions.observe('strategy',[{'question':'Why do you want to join our company?'}],a['id']);self.assertEqual(r['readiness']['confirmed'],0)
 def test_imported_search_preference_can_reuse_when_explicitly_confirmed(self):
  question='Are you looking for a manager or individual contributor role?';value="I don't have a preference"
  q=questions.import_profile('strategy',[{'question':question,'value':value,'category':'search_preferences'}],'https://simplify.jobs/profile/fixture')['ids'][0]
  original=questions.get('strategy',q);self.assertFalse(original['confirmed']);self.assertEqual(original['reuse_scope'],'application')
  self.assertTrue(questions.reuse_policy(question,original['category'])['automatic_allowed'])
  questions.save('strategy',{'id':q,'value':value,'confirmed':False,'reuse_scope':'identity'})
  a=self.app();questions.observe('strategy',[{'question':question,'choices':['Manager','Individual contributor',value]}],a['id']);self.assertFalse(db.application('strategy',a['id'])['answers'][question]['confirmed'])
  questions.save('strategy',{'id':q,'value':value,'confirmed':True,'reuse_scope':'identity'});db.init()
  self.assertEqual(questions.get('strategy',q)['reuse_scope'],'identity');self.assertEqual(questions.apply_to_application('strategy',a['id'])['confirmed'],1)
  questions.save('strategy',{'id':q,'value':'Manager','confirmed':True,'reuse_scope':'application'})
  self.assertEqual(questions.apply_to_application('strategy',a['id'])['confirmed'],1);self.assertEqual(db.application('strategy',a['id'])['answers'][question]['value'],value)
  self.assertEqual(questions.catalog('ai')['questions'],[])
 def test_import_category_does_not_bypass_context_dependent_review(self):
  for q in ['Expected salary','Why do you want to join our company?','Will you require sponsorship?','Are you willing to relocate?']:
   with self.subTest(question=q):
    with self.assertRaisesRegex(ValueError,'Review|review'):self.answer(q,'Fixture',category='search_preferences',reuse_scope='identity')
 def test_personal_disclosure_needs_explicit_reuse_choice_and_confirmation(self):
  q=self.answer('Are you a veteran?','No');self.assertEqual(questions.state(questions.get('strategy',q)),'application_review')
  a=self.app();questions.observe('strategy',[{'question':'Are you a veteran?','choices':['Yes','No']}],a['id']);self.assertFalse(db.application('strategy',a['id'])['answers']['Are you a veteran?']['confirmed'])
  questions.save('strategy',{'id':q,'value':'No','confirmed':False,'reuse_scope':'identity'});self.assertEqual(questions.state(questions.get('strategy',q)),'needs_review')
  questions.save('strategy',{'id':q,'value':'No','confirmed':True,'reuse_scope':'identity'});db.init();self.assertEqual(questions.get('strategy',q)['reuse_scope'],'identity')
  self.assertEqual(questions.apply_to_application('strategy',a['id'])['confirmed'],1)
  questions.observe('strategy',[{'question':'Are you a veteran?','choices':['Protected veteran','Not a protected veteran']}],a['id']);self.assertFalse(db.application('strategy',a['id'])['answers']['Are you a veteran?']['confirmed'])
 def test_expiry_and_changed_form_constraints_block_reuse(self):
  self.answer(expires_at='2000-01-01');a=self.app();r=questions.observe('strategy',[{'question':'Email'}],a['id']);self.assertEqual(r['readiness']['confirmed'],0)
  self.answer('First name','Taylor');r=questions.observe('strategy',[{'question':'First name','max_length':2}],a['id']);self.assertEqual(r['readiness']['confirmed'],0)
  q=self.answer('Are you authorized to work in the US?','No');questions.observe('strategy',[{'question':'Are you authorized to work in the US?','choices':['Yes','No']}],a['id']);self.assertTrue(db.application('strategy',a['id'])['answers']['Are you authorized to work in the US?']['confirmed'])
  questions.observe('strategy',[{'question':'Are you authorized to work in the US?','choices':['Yes','Prefer not to say']}],a['id']);self.assertFalse(db.application('strategy',a['id'])['answers']['Are you authorized to work in the US?']['confirmed'])
 def test_bank_edits_do_not_rewrite_application_snapshots(self):
  q=self.answer();a=self.app();questions.observe('strategy',[{'question':'Email'}],a['id']);questions.save('strategy',{'id':q,'value':'updated@example.test','confirmed':True});questions.apply_to_application('strategy',a['id'])
  self.assertEqual(db.application('strategy',a['id'])['answers']['Email']['value'],'fixture@example.test');self.assertEqual(len(db.rows('SELECT * FROM answer_versions',identity='strategy')),2)
  with self.assertRaises(sqlite3.IntegrityError):
   with db.tx('strategy') as c:c.execute("UPDATE answer_versions SET value='mutated'")
 def test_identity_separation_and_backup_preserve_bank(self):
  q=self.answer();self.assertEqual(questions.catalog('ai')['questions'],[])
  with self.assertRaises(ValueError):questions.get('ai',q)
  a=self.app();questions.observe('strategy',[{'question':'Email'}],a['id']);archive=backup.create_backup();backup.restore_backup(archive,db.ROOT/'restored');c=sqlite3.connect(db.ROOT/'restored/strategy/tracker.sqlite');self.assertEqual(c.execute('SELECT count(*) FROM answer_versions').fetchone()[0],1);self.assertEqual(c.execute('SELECT count(*) FROM question_encounters').fetchone()[0],1);c.close()
 def test_changed_country_context_keeps_history_but_rechecks_current_field(self):
  a=self.app();r=questions.observe('strategy',[{'question':'Work authorization','context':{'country':'India'}}],a['id']);qid=r['questions'][0]['id']
  with db.tx('strategy') as c:c.execute('UPDATE applications SET answers=? WHERE id=?',(db.dump({'Work authorization':{'value':'Yes','confirmed':True,'answer_id':qid}}),a['id']))
  r=questions.observe('strategy',[{'question':'Work authorization','context':{'country':'Canada'}}],a['id'])
  self.assertEqual(r['readiness']['total'],1);self.assertEqual(r['readiness']['confirmed'],0);self.assertEqual(db.one('SELECT count(*) n FROM question_encounters',identity='strategy')['n'],2)
 def test_optional_unknown_question_does_not_block_application(self):
  a=self.app();r=questions.observe('strategy',[{'question':'Optional portfolio','required':False}],a['id']);self.assertEqual(r['readiness']['needs_answer'],0);self.assertEqual(db.application('strategy',a['id'])['answers'],{})
 def test_legacy_saved_answer_migration_preserves_confirmation(self):
  with db.tx('strategy') as c:
   c.execute('DELETE FROM migrations WHERE version=4');c.execute('INSERT INTO answers(id,question,value,provenance,confirmed,updated_at) VALUES(?,?,?,?,?,?)',('old','Email address','legacy@example.test','User confirmed',1,db.now()))
  questions.migrate('strategy');a=self.app();questions.observe('strategy',[{'question':'Email'}],a['id']);self.assertEqual(db.application('strategy',a['id'])['answers']['Email']['value'],'legacy@example.test')
 def test_desktop_scan_records_unknowns_in_real_task_context(self):
  a=self.app();t=db.enqueue('strategy','scan_form',a['job_id'],application_id=a['id']);desktop.claim('strategy',t,'fixture');r=desktop.observe_questions('strategy',t,'fixture',{'fields':[{'question':'Start date?'}],'url':'https://example.test/form'})
  self.assertEqual(r['readiness']['needs_answer'],1)
  with self.assertRaises(ValueError):desktop.observe_questions('ai',t,'fixture',{'fields':[]})

if __name__=='__main__':unittest.main()
