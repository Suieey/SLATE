"""Approval invalidation is specific to successful edits, not new uploads."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))
import pytest
from fastapi.testclient import TestClient
from slate_api.app import create_authenticated_app
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore
from slate_core import SlateService, SlateError
from slate_core.ai_service import AISlateService
from slate_core.llm import MockLLM

RESUME = 'Asha Verma\nSkills: Python, Git, Excel'
HA = {'Authorization': 'Bearer dev:a@example.com'}
HB = {'Authorization': 'Bearer dev:b@example.com'}

def approved(s):
    rid = s.upload_resume(RESUME)['resumeId']
    did = s.tailor(rid, 'job_001')['draftId']
    s.decide(did, 'approve')
    return rid, did

def blocked(s, did):
    with pytest.raises(SlateError) as e:
        s.export_draft(did)
    assert e.value.code == 'draft_not_approved'

def test_successful_edit_invalidates_parent_and_child_not_other_drafts():
    s = SlateService()
    rid, old = approved(s)
    other = s.tailor(rid, 'job_002')['draftId']; s.decide(other, 'approve')
    old_content = dict(s.export_draft(old))
    new = s.edit_draft(old, coverNote='I use Python.')['draftId']
    assert new != old
    blocked(s, old); blocked(s, new)
    assert s.export_draft(other)
    assert s.approvals.get(old)['content'] == old_content
    # Reapproval always applies to the exact requested version, never its child.
    s.decide(old, 'approve'); assert s.export_draft(old) == old_content
    blocked(s, new)
    s.decide(new, 'approve'); assert s.export_draft(new)['coverNote'] == 'I use Python.'

def test_reparse_creates_new_source_without_mutating_old_approved_version():
    s = SlateService(); rid, old = approved(s); before = dict(s.export_draft(old))
    new_rid = s.upload_resume('Asha Verma\nSkills: Git')['resumeId']
    assert rid != new_rid
    assert s.approvals.get(old)['resumeId'] == rid
    assert s.export_draft(old) == before

def test_failed_edit_does_not_invalidate_approval_or_create_child():
    s = SlateService(); _, old = approved(s); before = dict(s.export_draft(old))
    n = len(s.approvals._drafts)
    with pytest.raises(SlateError):
        s.edit_draft(old, coverNote='I have 10 years of Java at Google.')
    assert len(s.approvals._drafts) == n
    assert s.export_draft(old) == before

def test_rejected_parent_is_not_revived_by_edit():
    s = SlateService(); _, old = approved(s); s.decide(old, 'reject')
    s.edit_draft(old, coverNote='I use Python.')
    assert s.approvals.get(old)['status'] == 'rejected'
    with pytest.raises(SlateError) as e: s.decide(old, 'approve')
    assert e.value.code == 'draft_rejected'

def test_invalidation_persists_and_is_scoped_to_owner(tmp_path):
    url = f'sqlite:///{tmp_path}/state.db'
    c = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    def flow(h):
        rid = c.post('/v1/resume', json={'text': RESUME}, headers=h).json()['resumeId']
        did = c.post('/v1/tailor', json={'resumeId':rid, 'jobId':'job_001'}, headers=h).json()['draftId']
        c.post('/v1/approvals',json={'draftId':did,'decision':'approve'},headers=h)
        return did
    old = flow(HA); other = flow(HB)
    new = c.post(f'/v1/drafts/{old}/edit',json={'coverNote':'I use Python.'},headers=HA).json()['draftId']
    restart = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    for did in (old, new):
        assert restart.get(f'/v1/drafts/{did}/export',headers=HA).status_code == 403
    assert restart.get(f'/v1/drafts/{other}/export',headers=HB).status_code == 200

def test_ai_edit_invalidates_parent_without_losing_grounding_marker():
    s = AISlateService(llm_client=MockLLM('RESUME\nAsha Verma [S1]\nPython, Git, Excel [S2]\nCOVER NOTE\nPython, Git [S2]'))
    rid = s.upload_resume(RESUME)['resumeId']
    old = s.tailor_ai(rid,'job_001')['draftId']; s.decide(old,'approve')
    new = s.edit_draft(old,coverNote='Python [S2]')['draftId']
    blocked(s, old); blocked(s, new)
    assert s.approvals.get(new)['content']['aiGenerated'] is True
    s.decide(new,'approve'); assert s.export_draft(new)['coverNote'] == 'Python [S2]'
