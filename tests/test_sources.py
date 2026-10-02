import unittest,json
from unittest.mock import patch
from hunter import sources,db
class StructuredPageTests(unittest.TestCase):
 def test_jobposting_graph_and_unknown_fields(self):
  data={'@graph':[{'@type':'Organization','name':'Ignore'},{'@type':'JobPosting','title':'AI Product Manager','description':'<p>Own roadmap.</p>','hiringOrganization':{'name':'Fixture'},'jobLocation':{'address':{'addressLocality':'Bengaluru','addressCountry':'IN'}},'datePosted':'2026-09-01','employmentType':['FULL_TIME'],'jobLocationType':'TELECOMMUTE','applicantLocationRequirements':{'@type':'Country','name':'India'}}]}
  page='<script type="application/ld+json">'+json.dumps(data)+'</script>'
  src={'id':'fixture','name':'Fixture','kind':'jsonld','config':db.dump({'url':'https://example.test/job'})}
  with patch('hunter.sources.request',return_value=page):jobs,partial=sources.fetch(src)
  self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['description'],'Own roadmap.');self.assertIsNone(jobs[0]['salary']);self.assertEqual(jobs[0]['country_restrictions'],['India']);self.assertTrue(partial);self.assertEqual(jobs[0]['employment_type'],'full-time')
 def test_region_restriction_stays_unknown_instead_of_wrongly_excluding_country(self):
  j={'title':'AI Product Manager','description':'Own roadmap','country_restrictions':['Asia'],'arrangement':'remote'}
  ok,notes=sources.filter_job(j,{'countries':['India'],'titles':['product'],'confirmed':True})
  self.assertTrue(ok);self.assertTrue(any('eligibility review' in n for n in notes))
  j['country_restrictions']=['United States'];self.assertFalse(sources.filter_job(j,{'countries':['India'],'titles':['product']})[0])
 def test_no_jobposting_is_failure_not_zero(self):
  with patch('hunter.sources.request',return_value='<h1>Sign in</h1>'):
   with self.assertRaises(sources.SourceError):sources.fetch({'id':'fixture','name':'Fixture','kind':'jsonld','config':db.dump({'url':'https://example.test/job'})})
if __name__=='__main__':unittest.main()
