import http.client,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from hunter import db,server,questions,browser_sessions,identities

class LocalApiTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(db.DATA,db.ROOT,server.PORT);db.ROOT=Path(self.tmp.name);db.DATA=db.ROOT/'data';db.init();self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);server.PORT=self.http.server_port;browser_sessions.register('fixture-session',time.time()+60);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.http.shutdown();self.http.server_close();db.DATA,db.ROOT,server.PORT=self.old;self.tmp.cleanup()
 def request(self,path,body=None,auth=True,origin=None,csrf=True):
  c=http.client.HTTPConnection('127.0.0.1',self.http.server_port);headers={'Content-Type':'application/json'}
  if auth:headers['Cookie']=browser_sessions.cookie_name()+'=fixture-session'
  if body is not None:
   headers['Origin']=origin or f'http://127.0.0.1:{self.http.server_port}'
   if csrf:headers['X-Hunter-CSRF']=server.CSRF
  c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers);r=c.getresponse();value=json.loads(r.read());status=r.status;c.close();return status,value
 def test_home_and_scheduled_search_require_confirmed_preferences(self):
  self.assertEqual(self.request('/api/strategy/home')[0],200)
  self.assertEqual(self.request('/api/strategy/auto-discovery',{'enabled':True,'interval_hours':24})[0],400)
  prefs=db.get_setting('preferences',{},'strategy');prefs['confirmed']=True;db.set_setting('preferences',prefs,'strategy')
  self.assertEqual(self.request('/api/strategy/auto-discovery',{'enabled':True,'interval_hours':24})[0],200)
  self.assertTrue(self.request('/api/strategy/settings')[1]['auto_discovery']['enabled'])
  self.assertFalse(self.request('/api/ai/settings')[1]['auto_discovery']['enabled'])
 def test_email_alert_credentials_are_protected_by_session_and_csrf(self):
  body={'action':'configure','enabled':True,'channel':'email','email':{'username':'fixture@example.test','recipient':'fixture@example.test','password':'fixture-private-app-password'}}
  self.assertEqual(self.request('/api/notifications',body,auth=False)[0],401)
  self.assertEqual(self.request('/api/notifications',body,csrf=False)[0],403)
  code,status=self.request('/api/notifications',body);self.assertEqual(code,200);self.assertTrue(status['email_configured']);self.assertNotIn('fixture-private-app-password',json.dumps(status))
  code,status=self.request('/api/notifications');self.assertEqual(code,200);self.assertNotIn('password',status['email'])
  self.assertEqual(self.request('/api/notifications',{'action':'test'})[0],200)
 def test_question_bank_review_api_uses_displayed_version(self):
  q=questions.save('ai',{'question':'Email address','value':'fixture@example.test','confirmed':False})
  self.assertEqual(self.request('/api/ai/questions')[1]['counts']['needs_review'],1)
  self.assertEqual(self.request('/api/strategy/questions/'+q)[0],400)
  self.assertEqual(self.request('/api/ai/confirm-questions',{'ids':[q],'versions':{q:0}})[0],400)
  self.assertEqual(self.request('/api/ai/confirm-questions',{'ids':[q],'versions':{q:1}})[0],200)
  self.assertEqual(self.request('/api/ai/questions')[1]['counts']['ready'],1)
  contextual=questions.save('ai',{'question':'Expected salary','value':'Fixture','confirmed':False})
  self.assertEqual(self.request('/api/ai/confirm-questions',{'ids':[contextual],'versions':{contextual:1}})[0],400)
 def test_global_bank_review_requires_session_csrf_and_versions(self):
  q=questions.save('ai',{'question':'Email','value':'fixture@example.test','confirmed':False})
  item={'entries':[{'identity':'ai','id':q,'version':1}]}
  self.assertEqual(self.request('/api/question-bank/review',{'items':[item]},csrf=False)[0],403)
  self.assertEqual(self.request('/api/question-bank/review',{'items':[item]},auth=False)[0],401)
  self.assertEqual(self.request('/api/question-bank/confirm',{'items':[item]})[0],400)
  self.assertFalse(questions.get('ai',q)['confirmed'])
  status,result=self.request('/api/question-bank/review',{'items':[item]});self.assertEqual(status,200);self.assertEqual(len(result['saved']),1)
  self.assertEqual(self.request('/api/question-bank/review',{'items':[item]})[0],400)
  self.assertEqual(self.request('/api/strategy/questions')[1]['questions'],[])
 def test_alternatives_survive_api_and_cached_client_cannot_paste_all(self):
  values='Business Transformation Lead – AI\nChief Of Staff\nAI Transformation Lead'
  code,result=self.request('/api/ai/question',{'question':'Current job title','value':values,'confirmed':True,'reuse_scope':'identity','answer_mode':'jd_choice','availability':'this'})
  self.assertEqual(code,200);qid=result['id'];self.assertEqual(self.request('/api/ai/questions/'+qid)[1]['question']['answer_mode'],'jd_choice')
  j=db.upsert_job('ai',{'title':'Fixture','company':'Fixture','url':'https://example.test/choice','description':'Fixture JD','source_id':'fixture'});a=db.shortlist('ai',j)
  code,result=self.request('/api/ai/application',{'action':'answers','id':a['id'],'answers':{'Current job title':{'value':values,'answer_id':qid,'confirmed':True}}})
  self.assertEqual(code,400);self.assertEqual(db.application('ai',a['id'])['answers'],{})
 def test_application_questionnaire_and_batch_api(self):
  j=db.upsert_job('ai',dict(title='Fixture',company='Fixture',url='https://example.test/batch',description='Fixture',source_id='fixture'));a=db.shortlist('ai',j)
  questions.observe('ai',[{'question':'Notice period'},{'question':'Work authorisation — India','choices':['Yes','No']}],a['id'])
  code,d=self.request('/api/ai/jobs/'+j);self.assertEqual(code,200);self.assertEqual(len(d['application_fields']),2)
  old=db.application('ai',a['id'])['answers'];edits=[{'question':q,'value':v,'expected':old[q],'field_version':d['application_fields'][q]['field_version']} for q,v in [('Notice period','Fixture: 30 days'),('Work authorisation — India','Yes')]]
  body={'action':'answer_batch','id':a['id'],'confirmed':True,'edits':edits}
  self.assertEqual(self.request('/api/ai/application',body,csrf=False)[0],403)
  code,r=self.request('/api/ai/application',body);self.assertEqual(code,200);self.assertEqual(r['saved'],2)
  self.assertEqual(self.request('/api/strategy/application',body)[0],400)
  self.assertEqual(self.request('/api/ai/application',body)[0],400)
 def test_employer_question_appears_on_application_not_in_bank(self):
  question='Who referred you for this position?'
  j=db.upsert_job('ai',dict(title='Product Manager',company='Noora Health',url='https://example.test/noora',description='Fixture',source_id='fixture'));a=db.shortlist('ai',j)
  questions.observe('ai',[{'question':'Email'},{'question':question,'required':False}],a['id'],'https://example.test/noora')
  bank={row['question'] for row in self.request('/api/ai/questions')[1]['questions']}
  self.assertIn('Email',bank);self.assertNotIn(question,bank)
  listed=self.request('/api/ai/applications')[1][0];self.assertEqual(listed['form_questions_total'],2);self.assertEqual(listed['form_questions_to_review'],2)
  field=self.request('/api/ai/jobs/'+j)[1]['application_fields'][question];self.assertTrue(field['application_only'])
  edit={'question':question,'value':'Fixture referral','expected':db.application('ai',a['id'])['answers'].get(question),'field_version':field['field_version']}
  self.assertEqual(self.request('/api/ai/application',{'action':'answer_batch','id':a['id'],'confirmed':True,'edits':[edit]})[0],200)
  self.assertEqual(self.request('/api/ai/applications')[1][0]['form_questions_to_review'],1)
  self.assertNotIn(question,{row['question'] for row in self.request('/api/ai/questions')[1]['questions']})
 def test_requires_session_origin_and_csrf(self):
  self.assertEqual(self.request('/api/strategy/home',auth=False)[0],401)
  self.assertEqual(self.request('/api/strategy/preferences',{'titles':['Fixture']},origin='https://malicious.example')[0],403)
  self.assertEqual(self.request('/api/strategy/preferences',{'titles':['Fixture']},csrf=False)[0],403)
 def test_editor_policy_and_saved_choice_agree(self):
  policy=self.request('/api/strategy/question-policy',{'question':'Are you a veteran?'})[1];self.assertTrue(policy['automatic_allowed']);self.assertEqual(policy['default_scope'],'application')
  self.assertFalse(self.request('/api/strategy/question-policy',{'question':'Expected salary'})[1]['automatic_allowed'])
  data={'question':'Are you a veteran?','value':'No','confirmed':True,'reuse_scope':'identity','availability':'all'}
  plan=self.request('/api/strategy/sharing-preview',data)[1];data['target_versions']={r['identity']:r['version'] for r in plan['targets']}
  status,saved=self.request('/api/strategy/question',data);self.assertEqual(status,200);self.assertEqual(saved['reuse_scope'],'identity')
  detail=self.request('/api/strategy/questions/'+saved['id'])[1];self.assertEqual(detail['question']['reuse_scope'],'identity');self.assertTrue(detail['question']['reuse_policy']['automatic_allowed']);self.assertEqual(detail['sharing']['mode'],'all')
 def test_stale_csrf_is_rejected_before_mutation_with_reconnect_code(self):
  before=db.get_setting('preferences',{},'strategy')
  status,result=self.request('/api/strategy/preferences',{'titles':['Changed']},csrf=False)
  self.assertEqual(status,403);self.assertEqual(result['code'],'csrf_stale');self.assertEqual(db.get_setting('preferences',{},'strategy'),before)
 def test_imported_preference_reuse_choice_saves_across_roles(self):
  question='Are you looking for a manager or individual contributor role?';value="I don't have a preference"
  q=questions.import_profile('strategy',[{'question':question,'value':value,'category':'search_preferences'}],'https://simplify.jobs/profile/fixture')['ids'][0]
  detail=self.request('/api/strategy/questions/'+q)[1]['question'];self.assertTrue(detail['reuse_policy']['automatic_allowed'])
  data={'id':q,'value':value,'expected_version':detail['version'],'confirmed':True,'reuse_scope':'identity','availability':'all'}
  code,plan=self.request('/api/strategy/sharing-preview',data);self.assertEqual(code,200);data['target_versions']={r['identity']:r['version'] for r in plan['targets']}
  code,saved=self.request('/api/strategy/question',data);self.assertEqual(code,200);self.assertEqual(set(saved['saved_in']),{'strategy','ai'})
  db.init()
  for i in ('strategy','ai'):
   row=self.request('/api/'+i+'/questions')[1]['questions'][0];self.assertEqual(row['reuse_scope'],'identity');self.assertTrue(row['confirmed']);self.assertEqual(row['status'],'ready');self.assertTrue(row['reuse_policy']['automatic_allowed'])
 def test_create_identity_api_and_setup_survive_reload(self):
  status,result=self.request('/api/identities',{'name':'Fixture Added Identity','titles':['Fixture Lead']})
  self.assertEqual(status,200);i=result['id'];db.init()
  self.assertIn(i,self.request('/api/bootstrap')[1]['identities']);setup=self.request('/api/'+i+'/setup')[1]
  self.assertTrue(setup['can_search']);self.assertFalse(setup['can_assess']);self.assertFalse(setup['preferences_ready'])
  self.assertEqual(self.request('/api/'+i+'/jobs')[1]['total'],0)
 def test_address_preview_is_local_and_does_not_save_confirmation(self):
  status,result=self.request('/api/strategy/address-preview',{'value':'12 Example House, Gurgaon, Haryana - 122101'})
  self.assertEqual(status,200);self.assertEqual(result['parts'],{'City':'Gurgaon','Province':'Haryana','Postal code':'122101'})
  self.assertEqual(self.request('/api/strategy/questions')[1]['questions'],[])
  status,result=self.request('/api/strategy/question',{'question':'Address','value':'12 Example House, Gurgaon, Haryana - 122101','confirmed':True,'reuse_scope':'identity'})
  self.assertEqual(status,200);self.assertEqual(self.request('/api/strategy/questions')[1]['counts']['ready'],4)
 def test_preference_form_round_trip_is_separate(self):
  p={'titles':['AI Product Manager'],'locations':['Fixture city'],'countries':['India'],'work_authorization':'Fixture only','include_early_career':False}
  self.assertEqual(self.request('/api/ai/preferences',p)[0],200)
  ai=self.request('/api/ai/settings')[1]['preferences'];strategy=self.request('/api/strategy/settings')[1]['preferences'];self.assertTrue(ai['confirmed']);self.assertEqual(ai['locations'],['Fixture city']);self.assertEqual(strategy['locations'],[]);self.assertFalse(strategy['confirmed'])
 def test_resaving_unchanged_preferences_preserves_assessment_cache(self):
  p={'titles':['Strategy Lead'],'locations':['Mumbai']}
  self.assertEqual(self.request('/api/strategy/preferences',p)[0],200)
  j=db.upsert_job('strategy',{'title':'Strategy Lead','company':'Fixture','url':'https://example.test/cache','description':'Fixture','source_id':'fixture'})
  with db.tx('strategy') as c:c.execute("UPDATE jobs SET assessment=?,assessment_context_hash=? WHERE id=?",('{}','cached-context',j))
  code,result=self.request('/api/strategy/preferences',p)
  self.assertEqual((code,result.get('unchanged')),(200,True))
  self.assertEqual(db.one('SELECT assessment_context_hash FROM jobs WHERE id=?',(j,),'strategy')['assessment_context_hash'],'cached-context')
 def test_preference_update_refilters_existing_jobs_preserving_shortlist(self):
  def job(n,city):return db.upsert_job('strategy',{'title':'Strategy Lead','company':'Fixture','url':f'https://example.test/job/{n}','source_id':'fixture','description':'fixture','location':city,'arrangement':'onsite'})
  hidden=job(1,'London');kept=job(2,'Mumbai');shortlisted=job(3,'London');db.shortlist('strategy',shortlisted)
  self.assertEqual(self.request('/api/strategy/preferences',{'titles':['Strategy'],'locations':['Mumbai'],'arrangements':['on-site']})[0],200)
  self.assertEqual(db.get_job('strategy',hidden)['status'],'outside_preferences');self.assertEqual(db.get_job('strategy',kept)['status'],'found');self.assertEqual(db.get_job('strategy',shortlisted)['status'],'shortlisted')
  self.assertEqual(self.request('/api/strategy/preferences',{'titles':['Strategy'],'locations':[]})[0],200);self.assertEqual(db.get_job('strategy',hidden)['status'],'found')
 def test_total_records_are_independent_of_pagination(self):
  for n in range(35):db.upsert_job('strategy',{'title':'Strategy Lead','company':'Fixture','url':f'https://example.test/job/{n}','source_id':'fixture','description':'fixture'})
  status,d=self.request('/api/strategy/jobs?limit=7&offset=7');self.assertEqual(status,200);self.assertEqual(d['total'],35);self.assertEqual(len(d['jobs']),7)
 def test_global_start_resumes_only_globally_paused_work(self):
  t=db.enqueue('strategy','discover');other=db.enqueue('ai','discover');db.task_update('ai',other,state='paused')
  self.assertEqual(self.request('/api/control',{'action':'pause'})[0],200);self.assertEqual(db.one('SELECT state FROM tasks WHERE id=?',(t,),'strategy')['state'],'paused')
  self.assertEqual(self.request('/api/control',{'action':'start'})[0],200);self.assertEqual(db.one('SELECT state FROM tasks WHERE id=?',(t,),'strategy')['state'],'queued');self.assertEqual(db.one('SELECT state FROM tasks WHERE id=?',(other,),'ai')['state'],'paused')
 def test_submission_status_cannot_be_set_manually(self):
  j=db.upsert_job('strategy',{'title':'Fixture','company':'Fixture','url':'https://example.test/job','source_id':'fixture'});a=db.shortlist('strategy',j)
  status,result=self.request('/api/strategy/application',{'id':a['id'],'action':'outcome','state':'submitted'});self.assertEqual(status,400);self.assertIn('evidence',result['error'])
 def test_help_counts_follow_identity_outside_home_view(self):
  t=db.enqueue('ai','web_discovery');db.task_update('ai',t,state='waiting_user')
  self.assertEqual(self.request('/api/ai/counts')[1]['needs_help'],1);self.assertEqual(self.request('/api/strategy/counts')[1]['needs_help'],0)
 def test_desktop_handoff_prefills_exact_task_without_claiming_it(self):
  db.set_setting('execution_mode','desktop')
  t=db.enqueue('strategy','web_discovery')
  with patch.object(server.subprocess,'run') as opened:
   code,result=self.request('/api/strategy/launch-desktop',{'id':t})
  self.assertEqual(code,200,result);self.assertEqual((result['opened'],result['sent']),(True,False))
  args=opened.call_args.args[0];self.assertEqual(args[0],'/usr/bin/open')
  link=urlsplit(args[1]);self.assertEqual((link.scheme,link.netloc),('codex','new'))
  query=parse_qs(link.query);self.assertEqual(query['path'],[str(db.ROOT)])
  self.assertIn('Continue task '+t+' for identity strategy',query['prompt'][0])
  self.assertEqual(db.one('SELECT state FROM tasks WHERE id=?',(t,),'strategy')['state'],'waiting_agent')
  with patch.object(server.subprocess,'run') as denied:
   self.assertEqual(self.request('/api/ai/launch-desktop',{'id':t})[0],400)
   db.task_update('strategy',t,state='waiting_user')
   self.assertEqual(self.request('/api/strategy/launch-desktop',{'id':t})[0],400)
   denied.assert_not_called()
 def test_application_detail_exposes_blocked_fill_to_its_role_only(self):
  j=db.upsert_job('strategy',{'title':'Fixture','company':'Fixture','url':'https://example.test/fill','description':'Fixture','source_id':'fixture'});a=db.shortlist('strategy',j)
  t=db.enqueue('strategy','fill',job_id=j,application_id=a['id'])
  db.task_update('strategy',t,state='waiting_user',progress='Fixture upload needs your help')
  code,result=self.request('/api/strategy/jobs/'+j)
  self.assertEqual(code,200);self.assertEqual(result['active_fill']['state'],'waiting_user')
  self.assertEqual(result['active_fill']['id'],t)
  self.assertEqual(self.request('/api/ai/jobs/'+j)[0],400)
 def test_local_task_start_needs_no_new_desktop_chat(self):
  db.set_setting('execution_mode','local_agent');t=db.enqueue('strategy','scan_form')
  with patch.object(server.subprocess,'run') as opened:
   code,result=self.request('/api/strategy/launch-desktop',{'id':t})
  self.assertEqual((code,result['mode']),(200,'local_agent'));opened.assert_not_called()
  self.assertEqual(db.one('SELECT state FROM tasks WHERE id=?',(t,),'strategy')['state'],'waiting_agent')
 def test_native_handoff_is_per_task_and_respects_active_worker(self):
  identities.update('strategy',{'master_url':'https://docs.google.com/document/d/fixture-native-master/edit'})
  db.set_setting('execution_mode','local_agent');t=db.enqueue('strategy','refresh_profile')
  db.task_update('strategy',t,state='waiting_user',progress='Native master needs a connected document workflow')
  with patch.object(server.subprocess,'run') as opened:
   self.assertEqual(self.request('/api/ai/launch-desktop',{'id':t,'mode':'desktop'})[0],400)
   code,result=self.request('/api/strategy/launch-desktop',{'id':t,'mode':'desktop'})
   self.assertEqual((code,result['sent']),(200,False));opened.assert_called_once()
  task=db.one('SELECT * FROM tasks WHERE id=?',(t,),'strategy')
  self.assertEqual((task['state'],db.unpack(task['payload'])['execution_mode']),('waiting_agent','desktop'))
  self.assertEqual(db.get_setting('execution_mode'),'local_agent')
  db.task_update('strategy',t,state='working',owner='active-worker',lease_until=time.time()+60)
  with patch.object(server.subprocess,'run') as opened:
   self.assertEqual(self.request('/api/strategy/launch-desktop',{'id':t,'mode':'desktop'})[0],400);opened.assert_not_called()
  self.assertEqual(db.one('SELECT owner FROM tasks WHERE id=?',(t,),'strategy')['owner'],'active-worker')
 def test_wrong_identity_job_lookup_is_rejected(self):
  j=db.upsert_job('strategy',{'title':'Fixture','company':'Fixture','url':'https://example.test/job','source_id':'fixture'})
  self.assertEqual(self.request('/api/ai/jobs/'+j)[0],400)
if __name__=='__main__':unittest.main()
