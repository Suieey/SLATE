"""HTTP-level tests. Need: pip install fastapi httpx pytest. Run: python -m pytest tests -q"""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from slate_api.app import create_app
from slate_core import SlateService
from slate_core.tailor import check_claims

RESUME = "Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\nIntern at ExampleCo (3 months)\nSkills: Python, Git, Excel\n"

@pytest.fixture()
def c(): return TestClient(create_app(SlateService()))

def _rid(c): return c.post("/v1/resume", json={"text": RESUME}).json()["resumeId"]

def test_full_demo_flow(c):
    rid = _rid(c)
    jobs = c.get("/v1/jobs", params={"query": "analyst", "resumeId": rid}).json()["jobs"]
    assert jobs and jobs[0]["matchScore"] >= jobs[-1]["matchScore"]
    d = c.post("/v1/tailor", json={"resumeId": rid, "jobId": jobs[0]["jobId"]}).json()
    assert d["status"] == "draft"
    assert c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"}).json()["status"] == "approved"
    assert "coverNote" in c.get(f"/v1/drafts/{d['draftId']}/export").json()
    assert c.post("/v1/roadmap", json={"resumeId": rid, "targetRole": "Data Analyst"}).json()["milestones"]
    sid = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}).json()["sessionId"]
    c.post(f"/v1/interview/{sid}/answer", json={"text": "short"})
    fb = c.get(f"/v1/interview/{sid}/feedback").json()
    assert fb["transcriptRef"] == sid
    again = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}).json()
    assert again["carriedFromEarlier"]  # memory across sessions

def test_gate_holds_when_client_bypasses_ui(c):
    """Direct API calls, no UI: unapproved, edited-after-approval and rejected drafts cannot be exported."""
    rid = _rid(c)
    d = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}).json()["draftId"]
    assert c.get(f"/v1/drafts/{d}/export").status_code == 403
    c.post("/v1/approvals", json={"draftId": d, "decision": "approve"})
    new = c.post(f"/v1/drafts/{d}/edit", json={"coverNote": "changed"}).json()["draftId"]
    assert new != d and c.get(f"/v1/drafts/{new}/export").status_code == 403
    d2 = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}).json()["draftId"]
    c.post("/v1/approvals", json={"draftId": d2, "decision": "reject"})
    assert c.post("/v1/approvals", json={"draftId": d2, "decision": "approve"}).status_code == 409
    assert c.get(f"/v1/drafts/{d2}/export").status_code == 403

def test_errors_use_contract_shape(c):
    for resp in (c.post("/v1/resume", json={"text": ""}), c.post("/v1/tailor", json={"resumeId": "x", "jobId": "y"}),
                 c.post("/v1/resume", json={}), c.post("/v1/approvals", json={"draftId": "d", "decision": "maybe"}),
                 c.get("/v1/interview/nope/feedback")):
        assert resp.status_code >= 400
        assert set(resp.json()["error"]) == {"code", "message"}

def test_empty_query_is_not_a_crash(c):
    assert c.get("/v1/jobs", params={"query": "zzzz"}).json() == {"jobs": []}

def test_claim_check_flags_unbacked_claims():
    parsed = {"skills": ["python"]}
    assert check_claims(parsed, ["python", "sql"]) == ["sql"]

def test_edit_with_unsupported_claim_is_rejected_over_http(c):
    rid = _rid(c)
    d = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}).json()["draftId"]
    r = c.post(f"/v1/drafts/{d}/edit", json={"coverNote": "5 years of SQL and Java at Google"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_claim"
    ok = c.post(f"/v1/drafts/{d}/edit", json={"coverNote": "I use Python and Git."})
    assert ok.status_code == 200

def test_interview_accepts_resume_context_and_voice_mode(c):
    rid = _rid(c)
    started = c.post("/v1/interview/mock", json={
        "targetRole": "Data Analyst", "mode": "voice", "resumeId": rid
    })
    assert started.status_code == 200
    body = started.json()
    assert body["mode"] == "voice"
    assert body["sessionId"]
    assert body["firstQuestion"]
    assert body["coachMode"] == "deterministic_fallback"
    answer = c.post(f"/v1/interview/{body['sessionId']}/answer",
                    json={"text": "I used Python to clean a dataset and checked missing values."})
    assert answer.status_code == 200
    assert "evaluation" in answer.json()


def test_interview_rejects_empty_answer(c):
    sid = c.post("/v1/interview/mock",
                 json={"targetRole": "Data Analyst"}).json()["sessionId"]
    response = c.post(f"/v1/interview/{sid}/answer", json={"text": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "answer_empty"


def test_direct_interview_page_is_served(c):
    response = c.get("/interview")
    assert response.status_code == 200
    assert "Slate" in response.text
    assert "Start interview" in response.text


def test_interview_only_ends_when_end_endpoint_is_called(c):
    started = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}).json()
    sid = started["sessionId"]
    for _ in range(8):
        answer = c.post(f"/v1/interview/{sid}/answer", json={
            "text": "I would inspect the data, validate assumptions, and communicate the result.",
            "deliveryMetrics": {"wordsPerMinute": 130, "pauseRatio": 0.2, "fillerCount": 1}
        })
        assert answer.status_code == 200
        assert answer.json()["done"] is False
    feedback = c.post(f"/v1/interview/{sid}/end")
    assert feedback.status_code == 200
    assert feedback.json()["ended"] is True
    assert feedback.json()["answeredCount"] == 8
    after_end = c.post(f"/v1/interview/{sid}/answer", json={"text": "late answer"})
    assert after_end.status_code == 409
