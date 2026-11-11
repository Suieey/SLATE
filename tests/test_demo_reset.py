"""Demo reset: opt-in only, typed confirmation, wipes resumes+drafts, keeps interview sessions."""
import os, sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_api.app import create_app  # noqa: E402
from slate_core import SlateService  # noqa: E402
from slate_core.persistence import SqlSnapshot  # noqa: E402

RESUME = "Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\nIntern at ExampleCo (3 months)\nSkills: Python, Git, Excel, communication\n"

@pytest.fixture()
def c(monkeypatch):
    monkeypatch.setenv("SLATE_DEMO_RESET", "1")
    return TestClient(create_app())

def _flow(c):
    rid = c.post("/v1/resume", json={"text": RESUME}).json()["resumeId"]
    jid = c.get("/v1/jobs", params={"resumeId": rid}).json()["jobs"][0]["jobId"]
    did = c.post("/v1/tailor", json={"resumeId": rid, "jobId": jid}).json()["draftId"]
    c.post("/v1/approvals", json={"draftId": did, "decision": "approve"})
    sid = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}).json()["sessionId"]
    return rid, did, sid

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SLATE_DEMO_RESET", raising=False)
    c = TestClient(create_app())
    rid, did, sid = _flow(c)
    r = c.post("/v1/demo/reset", json={"confirm": "reset"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_reset_disabled"
    assert c.get("/v1/interview/%s/feedback" % sid).status_code == 200  # nothing wiped

def test_requires_typed_confirmation(c):
    _flow(c)
    r = c.post("/v1/demo/reset", json={"confirm": "yes"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reset_not_confirmed"
    r = c.post("/v1/demo/reset", json={})
    assert r.status_code == 422

def test_reset_wipes_resumes_and_drafts_keeps_sessions(c):
    rid, did, sid = _flow(c)
    assert c.post("/v1/demo/reset", json={"confirm": "reset"}).json() == {"reset": True}
    assert c.get("/v1/drafts/%s/export" % did).status_code == 404
    assert c.post("/v1/roadmap", json={"resumeId": rid, "targetRole": "Data Analyst"}).status_code == 404
    assert c.get("/v1/interview/%s/feedback" % sid).status_code == 200  # interview-owned state kept
    assert c.post("/v1/resume", json={"text": RESUME}).json()["resumeId"] == "res_001"

def test_reset_persists_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("SLATE_DEMO_RESET", "1")
    url = f"sqlite:///{tmp_path}/state.db"
    c = TestClient(create_app(SlateService(SqlSnapshot(url))))
    _flow(c)
    c.post("/v1/demo/reset", json={"confirm": "reset"})
    c2 = TestClient(create_app(SlateService(SqlSnapshot(url))))
    assert c2.post("/v1/resume", json={"text": RESUME}).json()["resumeId"] == "res_001"
