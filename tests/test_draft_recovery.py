"""Synthetic saved-work recovery and exact approved artifact checks."""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core import SlateService, SlateError
from slate_core.ai_service import AISlateService
from slate_core.llm import MockLLM
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore
from slate_api.app import create_authenticated_app
SOURCE='Alex Example\nSkills: Python, SQL, Excel, communication'

def setup():
 s=SlateService();rid=s.upload_resume(SOURCE)['resumeId'];did=s.tailor(rid,'job_001')['draftId'];return s,rid,did

def test_reopen_is_deep_copy_and_not_approval():
 s,rid,did=setup();d=s.get_draft(did);d['content']['coverNote']='modified';d['source']['parsed']['skills'].clear()
 assert s.get_draft(did)['content']['coverNote']!='modified'
 assert s.get_resume(rid)['parsed']['skills']
 assert s.get_draft(did)['status']=='draft'
 with pytest.raises(SlateError):s.download_draft(did)

@pytest.mark.parametrize('action',['unapproved','rejected','edited'])
def test_download_needs_current_exact_approval(action):
 s,rid,did=setup()
 if action=='rejected':s.decide(did,'reject')
 if action=='edited':s.decide(did,'approve');s.edit_draft(did,coverNote='Updated note')
 with pytest.raises(SlateError):s.download_draft(did)

def test_exact_artifact_preserves_review_origin_and_source():
 s,rid,did=setup();rid=s.review_resume_skills(rid,['python','sql'],True)['resumeId'];did=s.tailor(rid,'job_001')['draftId'];s.decide(did,'approve')
 out=s.download_draft(did)
 assert s.export_draft(did)['tailoredResume'] in out
 assert s.export_draft(did)['coverNote'] in out
 assert 'Source version: '+rid in out and 'Original source SHA-256:' in out
 assert 'not a full original CV' in out and 'sample fixture' in out
 assert s.get_draft(did)['source']['sourceText']==SOURCE

def test_download_rechecks_rules_after_bad_stored_content():
 s,rid,did=setup();s.decide(did,'approve');s.approvals.get(did)['content']['coverNote']='I have a PhD'
 with pytest.raises(SlateError):s.download_draft(did)

def test_ai_recovery_keeps_citations_and_grounding_warnings():
 s=AISlateService(llm_client=MockLLM('RESUME\nInvented employer [S1]\nCOVER NOTE\nInvented role [J]'));rid=s.upload_resume(SOURCE)['resumeId'];d=s.tailor_ai(rid,'job_001');opened=s.get_draft(d['draftId'])
 assert opened['content']['aiGenerated'] and '[S1]' in opened['content']['tailoredResume'] and opened['violations']
 s.approvals.get(d['draftId'])['status']='approved'
 with pytest.raises(SlateError):s.download_draft(d['draftId'])

def test_api_sqlite_recovery_scoped_and_persistent(tmp_path):
 url='sqlite:///'+str(tmp_path/'state.db')
 def client():return TestClient(create_authenticated_app(DevAuth(),SqlUserStore(url)))
 a={'Authorization':'Bearer dev:a@example.com'};b={'Authorization':'Bearer dev:b@example.com'};c=client()
 rid=c.post('/v1/resume',headers=a,json={'text':SOURCE}).json()['resumeId'];did=c.post('/v1/tailor',headers=a,json={'resumeId':rid,'jobId':'job_001'}).json()['draftId']
 assert c.get('/v1/drafts').status_code==401
 assert c.get('/v1/drafts',headers=b).json()['drafts']==[]
 for suffix in ['', '/download']:
  assert c.get('/v1/drafts/'+did+suffix,headers=b).status_code==404
 assert c.get('/v1/drafts/'+did+'/download',headers=a).status_code==403
 c.post('/v1/approvals',headers=a,json={'draftId':did,'decision':'approve'});c=client()
 assert c.get('/v1/drafts',headers=a).json()['drafts'][0]['status']=='approved'
 assert c.get('/v1/drafts/'+did,headers=a).json()['source']['sourceText']==SOURCE
 out=c.get('/v1/drafts/'+did+'/download',headers=a)
 assert out.status_code==200 and 'attachment;' in out.headers['content-disposition'] and out.headers['cache-control']=='no-store'
 assert c.get('/v1/drafts/'+did+'/export',headers=a).json()['tailoredResume'] in out.text

def test_list_newest_hundred_and_total():
 s,rid,did=setup()
 for _ in range(101):s.tailor(rid,'job_001')
 result=s.list_drafts();assert result['totalCount']==102 and len(result['drafts'])==100
 assert result['drafts'][0]['draftId']=='draft_102'
