"""HTTP-level tests for the opt-in AI tailoring path, including grounding."""
import os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from fastapi.testclient import TestClient  # noqa: E402
from slate_api.app import create_app  # noqa: E402
from slate_core import SlateService  # noqa: E402
from slate_core.ai_service import AISlateService  # noqa: E402
from slate_core.llm import MockLLM  # noqa: E402

RESUME = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
          "Intern at ExampleCo (3 months)\nSkills: Python, Git, Excel\n")


def _client(monkeypatch, key, service):
    if key is None:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("LLM_API_KEY", key)
    return TestClient(create_app(service))


def _draft(c, rid):
    r = c.post("/v1/tailor/ai", json={"resumeId": rid, "jobId": "job_001"})
    assert r.status_code == 200
    return r.json()


def _upload(c):
    return c.post("/v1/resume", json={"text": RESUME}).json()["resumeId"]


def test_ai_tailor_off_without_key(monkeypatch):
    c = _client(monkeypatch, None, AISlateService(llm_client=MockLLM()))
    rid = _upload(c)
    r = c.post("/v1/tailor/ai", json={"resumeId": rid, "jobId": "job_001"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ai_not_configured"


def test_ai_tailor_off_on_plain_service(monkeypatch):
    c = _client(monkeypatch, "dummy-key", SlateService())
    rid = _upload(c)
    r = c.post("/v1/tailor/ai", json={"resumeId": rid, "jobId": "job_001"})
    assert r.status_code == 503


def test_ai_tailor_full_review_flow(monkeypatch):
    reply = ("RESUME\nAsha Verma [S1]\nSkills: Python, Git. Strong with SQL. [S4]\n\n"
             "COVER NOTE\nI improved efficiency by 40% at ExampleCo [S3]")
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM(reply)))
    d = _draft(c, _upload(c))
    assert d["aiGenerated"] is True and d["requiresApproval"] is True
    assert d["status"] == "draft"
    # the claim rules surface both the unsupported skill and the invented metric
    assert any("sql" in s.lower() for s in d["flaggedClaims"] + d["violations"])
    assert any("40%" in v for v in d["violations"])
    # approval is re-validated by the normal path: a violating draft cannot
    # be approved as-is, so the human decision is structural, not cosmetic
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "unsupported_claim"


def test_ai_tailor_clean_draft_can_be_approved(monkeypatch):
    reply = ("RESUME\nAsha Verma [S1]\n"
             "B.Tech Computer Science, IIITM Gwalior, 2027 [S2]\n"
             "Intern at ExampleCo (3 months) [S3]\n"
             "Skills: Python, Git, Excel [S4]\n\n"
             "COVER NOTE\nI am applying for the Data Analyst role at ExampleCo [J]\n"
             "I know Python, Git and Excel from my internship [S3][S4]")
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM(reply)))
    d = _draft(c, _upload(c))
    assert d["flaggedClaims"] == [] and d["violations"] == []
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 200 and r2.json()["status"] == "approved"


def test_ungrounded_cover_note_is_caught(monkeypatch):
    """The observed failure mode: the LLM adds plausible-but-invented experience
    to the cover note. Old rules passed this; grounding must not."""
    reply = ("RESUME\nAsha Verma [S1]\nSkills: Python, Git, Excel [S4]\n\n"
             "COVER NOTE\nI have hands-on experience with data analysis and "
             "cross-team collaboration [S3]")
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM(reply)))
    d = _draft(c, _upload(c))
    assert any("not grounded" in v for v in d["violations"])
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 422


def test_uncited_line_is_caught(monkeypatch):
    reply = ("RESUME\nAsha Verma\nSkills: Python, Git, Excel [S4]\n\n"
             "COVER NOTE\nI know Python from my internship [S3][S4]")
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM(reply)))
    d = _draft(c, _upload(c))
    assert any("no source citation" in v for v in d["violations"])
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 422


def test_job_posting_cited_as_resume_fact_is_caught(monkeypatch):
    """Observed live failure: the model put the job posting into the RESUME
    section, citing [J]. The job is not a fact about the candidate."""
    reply = ("RESUME\nAsha Verma [S1]\nData Analyst at ExampleCo, Indore [J]\n"
             "Skills: Python, Git, Excel [S4]\n\n"
             "COVER NOTE\nI know Python from my internship [S3][S4]")
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM(reply)))
    d = _draft(c, _upload(c))
    assert any("cited as a resume fact" in v for v in d["violations"])
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 422


def test_deterministic_draft_unaffected_on_ai_service(monkeypatch):
    """The standard tailor path keeps working under AISlateService: its drafts
    have no citations and must NOT be grounding-checked at approval."""
    c = _client(monkeypatch, "dummy-key", AISlateService(llm_client=MockLLM()))
    rid = _upload(c)
    d = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}).json()
    r2 = c.post("/v1/approvals", json={"draftId": d["draftId"], "decision": "approve"})
    assert r2.status_code == 200 and r2.json()["status"] == "approved"
