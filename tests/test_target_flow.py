"""Private pasted targets and immutable literal-source exports; synthetic only."""
import hashlib,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.service import SlateService,SlateError
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore
from slate_api.app import create_authenticated_app
from fastapi.testclient import TestClient
SOURCES=[
 'Alex Example\nEducation\nCommunity School - Year 12, 2025\nWork Experience\nShop assistant, Local Store\nHandled cash at a register.\nSkills\nCustomer service\nInventory management',
 'Blake Example\nEducation\nDiploma in Nursing, Community College, 2024\nWork Experience\nStaff nurse, City Hospital\nSkills\nWound care\nMedication administration',
 'Casey Example\nEducation\nElectrical apprenticeship, Technical Institute\nWork Experience\nElectrician, Local Services\nSkills\nCircuit testing\nSafety inspections',
]
def target(s,parent=None,text='User-pasted requirements: customer service and inventory management.'):
 return s.create_target('Shop assistant','Local Employer',text,'https://example.com/posting',parent)['target']
@pytest.mark.parametrize('source',SOURCES)
def test_literal_source_survives_draft_approve_download(source):
 s=SlateService();rid=s.upload_resume(source)['resumeId'];t=target(s);d=s.tailor_target(rid,t['targetId']);did=d['draftId']
 assert source in d['tailoredResume']
 assert t['rawText'] not in d['tailoredResume'] and t['rawText'] not in d['coverNote']
 assert d['outputMode']=='source_preserving_draft_not_rewrite'
 assert d['originalSourceSha256']==hashlib.sha256(source.encode()).hexdigest()
 with pytest.raises(SlateError,match='Only an approved'):s.download_draft(did)
 s.decide(did,'approve');out=s.download_draft(did)
 assert source in out and t['rawText'] in out and 'user-pasted, not verified' in out
 assert 'PASTED TARGET CONTEXT - NOT APPLICANT EVIDENCE' in out
 assert 'sample fixture' not in out

def test_version_lineage_and_exact_target_binding():
 s=SlateService();rid=s.upload_resume(SOURCES[0])['resumeId'];one=target(s);d=s.tailor_target(rid,one['targetId']);s.decide(d['draftId'],'approve')
 two=s.create_target('New title','Different organization','New requirements','',one['targetId'])
 assert d['draftId'] in two['invalidatedDraftIds']
 assert s.get_target(one['targetId'])['title']=='Shop assistant'
 assert s.get_draft(d['draftId'])['content']['targetSnapshot']==one
 with pytest.raises(SlateError):s.download_draft(d['draftId'])
 # Original historical version remains explicitly re-approvable, not silently changed.
 s.decide(d['draftId'],'approve');assert 'Title: Shop assistant' in s.download_draft(d['draftId'])

def test_original_block_immutable_and_appended_claims_still_checked():
 s=SlateService();r=s.upload_resume(SOURCES[2])['resumeId'];t=target(s);d=s.tailor_target(r,t['targetId']);s.decide(d['draftId'],'approve')
 with pytest.raises(SlateError,match='preserved original source block'):
  s.edit_draft(d['draftId'],tailoredResume=d['tailoredResume'].replace('Local Services','Invented Corp'))
 with pytest.raises(SlateError,match='python'):
  s.edit_draft(d['draftId'],tailoredResume=d['tailoredResume']+'\nPython expert')
 with pytest.raises(SlateError,match='python'):
  s.edit_draft(d['draftId'],coverNote='I am an expert in Python.')
 revised=s.edit_draft(d['draftId'],tailoredResume=d['tailoredResume']+'\nPlease contact me for more details.')
 assert s.get_draft(revised['draftId'])['status']=='draft' and s.get_draft(d['draftId'])['status']=='draft'
 s.decide(revised['draftId'],'approve');assert SOURCES[2] in s.download_draft(revised['draftId'])

def test_review_additions_keep_original_and_user_statement_provenance():
 s=SlateService();r=s.upload_resume(SOURCES[1])['resumeId'];r2=s.review_resume_skills(r,['wound care','medication administration'],True)['resumeId'];t=target(s);d=s.tailor_target(r2,t['targetId'])
 assert SOURCES[1] in d['tailoredResume']
 assert s.get_draft(d['draftId'])['source']['sourceText']==SOURCES[1]
 assert all(e['source']=='user_statement' for e in s.get_draft(d['draftId'])['source']['parsed']['skillEvidence'])
 s.decide(d['draftId'],'approve');assert 'user_statement' in s.download_draft(d['draftId'])

@pytest.mark.parametrize('field,value',[('targetSnapshot',{}),('originalSourceSha256','wrong'),('baselineSha256','wrong'),('originalSha256','wrong'),('targetSha256','wrong'),('tailoredResume','changed')])
def test_binding_rechecked_at_approval_and_download(field,value):
 s=SlateService();r=s.upload_resume(SOURCES[0])['resumeId'];t=target(s);d=s.tailor_target(r,t['targetId']);s.decide(d['draftId'],'approve');s.approvals.get(d['draftId'])['content'][field]=value
 with pytest.raises(SlateError):s.download_draft(d['draftId'])
 with pytest.raises(SlateError):s.decide(d['draftId'],'approve')

def test_target_resume_draft_account_isolation_and_restart(tmp_path):
 url='sqlite:///'+str(tmp_path/'state.db');a={'Authorization':'Bearer dev:a@example.com'};b={'Authorization':'Bearer dev:b@example.com'}
 def client():return TestClient(create_authenticated_app(DevAuth(),SqlUserStore(url)))
 c=client();r=c.post('/v1/resume',headers=a,json={'text':SOURCES[0]}).json()['resumeId'];t=c.post('/v1/targets',headers=a,json={'title':'Retail assistant','organization':'Example','rawText':'Customer service required.'}).json()['target'];tid=t['targetId']
 assert c.get('/v1/targets',headers=b).json()['targets']==[]
 assert c.get('/v1/targets/'+tid,headers=b).status_code==404
 assert c.post('/v1/tailor/target',headers=b,json={'resumeId':r,'targetId':tid}).status_code==404
 assert c.post('/v1/targets',headers=b,json={'title':'Other','rawText':'text','parentTargetId':tid}).status_code==404
 d=c.post('/v1/tailor/target',headers=a,json={'resumeId':r,'targetId':tid}).json();did=d['draftId'];assert c.post('/v1/approvals',headers=a,json={'draftId':did,'decision':'approve'}).status_code==200
 c=client();assert c.get('/v1/targets/'+tid,headers=a).json()==t
 assert SOURCES[0] in c.get('/v1/drafts/'+did+'/download',headers=a).text
 assert c.get('/v1/drafts/'+did+'/download',headers=b).status_code==404
 assert c.post('/v1/targets',json={'title':'bad','rawText':'test'}).status_code==401

def test_legacy_fixture_contract_unchanged():
 s=SlateService();r=s.upload_resume('Alex Example\nSkills: Python, SQL')['resumeId'];jobs=s.jobs(resume_id=r)['jobs'];assert len(jobs)==5
 d=s.tailor(r,jobs[0]['jobId']);assert 'targetId' not in d and 'skillGaps' in d
 s.decide(d['draftId'],'approve');assert 'sample fixture, not live-verified' in s.download_draft(d['draftId'])
