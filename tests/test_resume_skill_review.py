"""Synthetic skill review/version/provenance checks. No personal resume fixtures."""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from slate_core import SlateService, SlateError
from slate_core.resume import parse_resume
from slate_core.resume_review import section_previews
from slate_core.auth import DevAuth
from slate_core.user_store import MemUserStore, SqlUserStore
from slate_api.app import create_authenticated_app
from slate_core.ai_service import AISlateService
from slate_core.llm import MockLLM

SOURCE = 'Alex Example\nSkills: Python, Git, Excel, communication\nEducation\nCommunity College, Year 11\nWork Experience\nCanteen service volunteer, Example Club\nHandled cash at a register.\nReferences\nAvailable on request'


def test_new_version_keeps_source_and_user_statement_provenance():
    service = SlateService()
    parent = service.upload_resume(SOURCE)['resumeId']
    r = service.review_resume_skills(parent, ['Python', 'wound care'], True)
    assert r['resumeId'] != parent
    assert service._resumes[parent]['skills'] == ['cash handling', 'communication', 'excel', 'git', 'python']
    assert r['parsed']['skills'] == ['python', 'wound care']
    by_skill = {e['skill']: e for e in r['parsed']['skillEvidence']}
    assert by_skill['python']['source'] == 'known_phrase'
    assert by_skill['python']['reviewStatus'] == 'user_confirmed'
    assert by_skill['wound care']['source'] == 'user_statement'
    assert by_skill['wound care']['reviewStatus'] == 'user_provided_not_source_extracted'
    assert service._texts[parent] == SOURCE
    assert 'User-provided skill statements (not independently verified)' in service._texts[r['resumeId']]
    assert r['parsed']['skillReview']['originalResumeId'] == parent


def test_successful_correction_invalidates_only_approved_parent_drafts():
    s = SlateService(); parent = s.upload_resume(SOURCE)['resumeId']
    d = s.tailor(parent, 'job_001')['draftId'];s.decide(d, 'approve')
    rejected = s.tailor(parent, 'job_002')['draftId'];s.decide(rejected, 'reject')
    other = s.upload_resume(SOURCE)['resumeId']; untouched = s.tailor(other, 'job_001')['draftId'];s.decide(untouched, 'approve')
    r = s.review_resume_skills(parent, ['python', 'git'], True)
    assert r['invalidatedDraftIds'] == [d]
    assert s.approvals.get(d)['resumeId'] == parent
    assert s.approvals.get(rejected)['status'] == 'rejected'
    assert s.approvals.get(untouched)['status'] == 'approved'
    with pytest.raises(SlateError): s.export_draft(d)
    new = s.tailor(r['resumeId'], 'job_002')['draftId']
    assert s.approvals.get(new)['status'] == 'draft'
    with pytest.raises(SlateError): s.export_draft(new)


@pytest.mark.parametrize('skills, confirm', [(['python'], False), (['sql\ninjection'], True),
    (['<script>'], True), (['x'*71], True), (['I use SQL every day'], True), (['x']*65, True)])
def test_invalid_review_is_atomic(skills, confirm):
    s = SlateService();rid = s.upload_resume(SOURCE)['resumeId'];d = s.tailor(rid, 'job_001')['draftId'];s.decide(d, 'approve')
    before = len(s._resumes)
    with pytest.raises(SlateError):s.review_resume_skills(rid, skills, confirm)
    assert len(s._resumes) == before
    assert s.approvals.get(d)['status'] == 'approved'


def test_removed_known_skill_cannot_leak_back_into_drafts():
    s = SlateService();rid = s.upload_resume(SOURCE)['resumeId']
    r = s.review_resume_skills(rid, ['python'], True)
    d = s.tailor(r['resumeId'], 'job_001')
    assert d['claimsChecked'] == ['python']
    with pytest.raises(SlateError, match='excel'):
        s.edit_draft(d['draftId'], coverNote='I use Excel')


def test_user_addition_is_not_approval_and_other_claim_gates_remain():
    s = SlateService();rid = s.upload_resume(SOURCE)['resumeId']
    reviewed = s.review_resume_skills(rid, ['python', 'sql'], True)['resumeId']
    d = s.tailor(reviewed, 'job_001');assert set(d['claimsChecked']) == {'python', 'sql'}
    with pytest.raises(SlateError):s.export_draft(d['draftId'])
    with pytest.raises(SlateError):s.edit_draft(d['draftId'], coverNote='I have 30 years of experience')
    with pytest.raises(SlateError):s.edit_draft(d['draftId'], coverNote='I have a PhD')


def test_repeated_review_rebuilds_addendum_from_original_not_removed_statements():
    s = SlateService();root = s.upload_resume(SOURCE)['resumeId']
    first = s.review_resume_skills(root, ['python', 'sql'], True)['resumeId']
    second = s.review_resume_skills(first, ['python', 'wound care'], True)['resumeId']
    assert 'Skills: sql' not in s._texts[second]
    assert s._texts[second].count('User-provided skill statements') == 1
    assert s._resumes[second]['skillReview']['originalResumeId'] == root
    assert s._texts[root] == SOURCE


def test_authenticated_review_is_scoped_and_survives_sqlite_restart(tmp_path):
    url = 'sqlite:///' + str(tmp_path/'synthetic.sqlite')
    def client():return TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    a,b = {'Authorization': 'Bearer dev:a@example.com'}, {'Authorization': 'Bearer dev:b@example.com'}
    c=client();rid=c.post('/v1/resume',json={'text':SOURCE},headers=a).json()['resumeId']
    body={'skills':['Python','SQL'], 'confirm':True}
    assert c.post(f'/v1/resume/{rid}/skills/review',json=body).status_code==401
    assert c.post(f'/v1/resume/{rid}/skills/review',json=body,headers=b).status_code==404
    r=c.post(f'/v1/resume/{rid}/skills/review',json=body,headers=a);assert r.status_code==200
    new=r.json()['resumeId']
    c=client();jobs=c.get('/v1/jobs',params={'resumeId':new},headers=a).json()['jobs']
    assert next(j for j in jobs if j['jobId']=='job_001')['matchedSkills']==['python','sql']
    assert c.get('/v1/jobs',params={'resumeId':new},headers=b).status_code==404


def test_strict_confirmation_no_implicit_truthy_string():
    c=TestClient(create_authenticated_app(DevAuth(),MemUserStore()));h={'Authorization':'Bearer dev:a@example.com'}
    rid=c.post('/v1/resume',json={'text':SOURCE},headers=h).json()['resumeId']
    assert c.post(f'/v1/resume/{rid}/skills/review',json={'skills':['sql'],'confirm':'yes'},headers=h).status_code==422


@pytest.mark.parametrize('heading', ['Education','Formation','Educación','Ausbildung','शिक्षा','教育'])
def test_literal_qualification_sections_never_invent_degrees(heading):
    parsed=parse_resume('Alex Example\n'+heading+'\nCommunity School - Year 11\nSkills: wound care')
    assert parsed['sectionReview']['education']['status']=='source_section_needs_review'
    assert 'Community School - Year 11' in parsed['sectionReview']['education']['sourceLines']
    assert parsed['education']==[]


def test_unrecognized_section_does_not_mean_no_experience():
    sections=section_previews('Alex Example\nVolunteer at a community garden for a season')
    assert sections['experience']['status']=='not_recognized'
    assert 'does not mean no qualifications or experience' in sections['experience']['note']


def test_ai_draft_still_checks_source_grounding_after_review():
    s=AISlateService(llm_client=MockLLM('RESUME\nInvented Employer 999 [R1]\nCOVER NOTE\nI am applying [J]'))
    rid=s.upload_resume(SOURCE)['resumeId'];new=s.review_resume_skills(rid,['python','sql'],True)['resumeId']
    draft=s.tailor_ai(new,'job_001')
    assert draft['violations']
    with pytest.raises(SlateError):s.decide(draft['draftId'],'approve')



def test_degree_substrings_in_company_or_verbs_are_not_credentials():
    parsed=parse_resume('Alex Example\nWork Experience\nCustomer support at Mastercard\nMastering cash handling through practice')
    assert parsed['education']==[]


def test_unknown_layout_leaves_literal_preview_unrecognized_not_fabricated():
    parsed=parse_resume('Alex Example | Skills: wound care | Community School Year 11 | Volunteer at a garden')
    assert parsed['sectionReview']['education']['status']=='not_recognized'
    assert parsed['education']==[]



def test_multiple_review_generations_invalidate_reapproved_ancestors_not_other_branches():
    s=SlateService();root=s.upload_resume(SOURCE)['resumeId']
    old=s.tailor(root,'job_001')['draftId'];s.decide(old,'approve')
    first=s.review_resume_skills(root,['python','sql'],True)['resumeId']
    s.decide(old,'approve')  # explicit historical reapproval before next correction
    current=s.tailor(first,'job_001')['draftId'];s.decide(current,'approve')
    second=s.review_resume_skills(first,['python'],True)
    assert set(second['invalidatedDraftIds'])=={old,current}
    third=s.review_resume_skills(second['resumeId'],['python','sql'],True)
    e=next(e for e in third['parsed']['skillEvidence'] if e['skill']=='sql')
    assert e['source']=='user_statement'
    assert e['reviewStatus']=='user_provided_not_source_extracted'
    assert s._texts[third['resumeId']].count('User-provided skill statements')==1
    assert s._resumes[root]['skills']!=third['parsed']['skills']


def test_added_skill_retains_user_statement_origin_when_confirmed_again():
    s=SlateService();root=s.upload_resume(SOURCE)['resumeId']
    first=s.review_resume_skills(root,['sql'],True)['resumeId']
    second=s.review_resume_skills(first,['sql'],True)
    e=second['parsed']['skillEvidence'][0]
    assert e['source']=='user_statement' and e['reviewStatus']=='user_confirmed'
    assert 'not independently verified' in s._texts[second['resumeId']]
