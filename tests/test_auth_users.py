"""Authenticated multi-user tests: every data path needs a token, users are
isolated structurally, and each user's data survives a restart (new app objects
over the same database file). No network: providers are fakes/injected.
Run: python -m pytest tests/test_auth_users.py -q
"""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from slate_api.app import create_authenticated_app, _build_auth
from slate_core.auth import AuthError, DevAuth, GoogleAuth, SupabaseAuth
from slate_core.user_store import MemUserStore, SqlUserStore

RESUME_A = "Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\nIntern at ExampleCo (3 months)\nSkills: Python, Git, Excel\n"
RESUME_B = "Rohan Mehta\nB.Tech Mechanical, NIT Trichy, 2026\nSkills: CAD, MATLAB\n"
HA = {"Authorization": "Bearer dev:asha@example.com"}
HB = {"Authorization": "Bearer dev:rohan@example.com"}

@pytest.fixture()
def c(tmp_path):
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    return TestClient(create_authenticated_app(DevAuth(), store))

def _flow(c, H, resume):
    """upload -> tailor -> approve -> export -> roadmap -> interview; returns ids."""
    rid = c.post("/v1/resume", json={"text": resume}, headers=H).json()["resumeId"]
    did = c.post("/v1/tailor", json={"resumeId": rid, "jobId": "job_001"}, headers=H).json()["draftId"]
    return rid, did

# --- every personal-data path requires a token -------------------------------

CALLS = [
    ("post", "/v1/resume", {"json": {"text": RESUME_A}}),
    ("post", "/v1/resume/pdf", {"files": {"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")}}),
    ("get", "/v1/jobs", {}),
    ("post", "/v1/tailor", {"json": {"resumeId": "res_001", "jobId": "job_001"}}),
    ("post", "/v1/tailor/ai", {"json": {"resumeId": "res_001", "jobId": "job_001"}}),
    ("post", "/v1/drafts/draft_001/edit", {"json": {"coverNote": "x"}}),
    ("get", "/v1/drafts/draft_001/export", {}),
    ("post", "/v1/roadmap", {"json": {"resumeId": "res_001", "targetRole": "Data Analyst"}}),
    ("post", "/v1/interview/mock", {"json": {"targetRole": "Data Analyst"}}),
    ("post", "/v1/interview/int_001/answer", {"json": {"text": "hi"}}),
    ("get", "/v1/interview/int_001/feedback", {}),
    ("post", "/v1/approvals", {"json": {"draftId": "draft_001", "decision": "approve"}}),
]

@pytest.mark.parametrize("method,path,kw", CALLS)
def test_every_data_path_requires_a_token(c, method, path, kw, monkeypatch):
    monkeypatch.setenv("SLATE_DEMO_RESET", "1")
    r = getattr(c, method)(path, **kw)  # no Authorization header at all
    assert r.status_code == 401, (method, path, r.status_code)
    assert r.json()["error"]["code"] == "unauthenticated"

def test_malformed_headers_rejected(c):
    for bad in ["dev:asha@example.com", "Bearer", "Basic dev:asha@example.com", "Bearer dev:"]:
        r = c.get("/v1/jobs", headers={"Authorization": bad})
        assert r.status_code == 401, bad

def test_reset_requires_token_too(c, monkeypatch):
    monkeypatch.setenv("SLATE_DEMO_RESET", "1")
    assert c.post("/v1/demo/reset", json={"confirm": "reset"}).status_code == 401

# --- isolation: user B can never reach user A's data --------------------------

def test_two_users_fully_isolated(c):
    rid_a, did_a = _flow(c, HA, RESUME_A)
    # B has uploaded nothing: A's ids simply do not exist for B
    assert c.get("/v1/jobs", params={"resumeId": rid_a}, headers=HB).status_code == 404
    assert c.get(f"/v1/drafts/{did_a}/export", headers=HB).status_code == 404
    assert c.post("/v1/approvals", json={"draftId": did_a, "decision": "approve"}, headers=HB).status_code == 404
    # A approves + exports A's draft
    c.post("/v1/approvals", json={"draftId": did_a, "decision": "approve"}, headers=HA)
    exp_a = c.get(f"/v1/drafts/{did_a}/export", headers=HA).json()
    # B now runs the same flow: independent id space (same ids, different data)
    rid_b, did_b = _flow(c, HB, RESUME_B)
    assert (rid_a, did_a) == (rid_b, did_b) == ("res_001", "draft_001")
    c.post("/v1/approvals", json={"draftId": did_b, "decision": "approve"}, headers=HB)
    exp_b = c.get(f"/v1/drafts/{did_b}/export", headers=HB).json()
    assert exp_a != exp_b
    # A's data unchanged by B's identical ids
    assert c.get(f"/v1/drafts/{did_a}/export", headers=HA).json() == exp_a
    # interviews: A completes one with weak areas; B sees neither the session nor its memory
    sid_a = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}, headers=HA).json()["sessionId"]
    c.post(f"/v1/interview/{sid_a}/answer", json={"text": "short"}, headers=HA)
    c.get(f"/v1/interview/{sid_a}/feedback", headers=HA)
    assert c.get(f"/v1/interview/{sid_a}/feedback", headers=HB).status_code == 404
    first_b = c.post("/v1/interview/mock", json={"targetRole": "Data Analyst"}, headers=HB).json()
    assert first_b["carriedFromEarlier"] == []

def test_interleaved_writes_do_not_bleed(c):
    _flow(c, HA, RESUME_A)
    _flow(c, HB, RESUME_B)
    c.post("/v1/tailor", json={"resumeId": "res_001", "jobId": "job_002"}, headers=HA)
    c.post("/v1/approvals", json={"draftId": "draft_001", "decision": "reject"}, headers=HB)
    # A's drafts unaffected by B's reject of B's draft_001
    assert c.post("/v1/approvals", json={"draftId": "draft_001", "decision": "approve"}, headers=HA).json()["status"] == "approved"
    assert c.post("/v1/approvals", json={"draftId": "draft_001", "decision": "approve"}, headers=HB).status_code == 409

def test_user_id_in_body_cannot_override_token(c):
    """A userId in the request is ignored: data lands under the token's user."""
    r = c.post("/v1/resume", json={"text": RESUME_A, "userId": "victim", "user_id": "victim"}, headers=HA)
    assert r.status_code == 200  # extra field ignored
    assert c.get("/v1/jobs", params={"resumeId": "res_001"}, headers=HB).status_code == 404

# --- durability across restarts ----------------------------------------------

def test_restart_keeps_each_users_data(tmp_path):
    url = f"sqlite:///{tmp_path}/state.db"
    c1 = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))
    rid, did = _flow(c1, HA, RESUME_A)
    c1.post("/v1/approvals", json={"draftId": did, "decision": "approve"}, headers=HA)
    c2 = TestClient(create_authenticated_app(DevAuth(), SqlUserStore(url)))  # "restart": new app, same file
    assert "coverNote" in c2.get(f"/v1/drafts/{did}/export", headers=HA).json()
    assert c2.post("/v1/roadmap", json={"resumeId": rid, "targetRole": "Data Analyst"}, headers=HA).json()["milestones"]
    assert c2.get("/v1/jobs", params={"resumeId": rid}, headers=HB).status_code == 404  # B still empty

def test_mem_store_is_explicitly_ephemeral():
    c = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    rid, _ = _flow(c, HA, RESUME_A)
    c2 = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    assert c2.get("/v1/jobs", params={"resumeId": rid}, headers=HA).status_code == 404

# --- per-user demo reset ------------------------------------------------------

def test_reset_wipes_only_the_caller(c, monkeypatch):
    monkeypatch.setenv("SLATE_DEMO_RESET", "1")
    rid_a, did_a = _flow(c, HA, RESUME_A)
    rid_b, did_b = _flow(c, HB, RESUME_B)
    c.post("/v1/approvals", json={"draftId": did_b, "decision": "approve"}, headers=HB)
    assert c.post("/v1/demo/reset", json={"confirm": "reset"}, headers=HA).json()["reset"] is True
    assert c.get("/v1/jobs", params={"resumeId": rid_a}, headers=HA).status_code == 404      # A wiped
    assert "coverNote" in c.get(f"/v1/drafts/{did_b}/export", headers=HB).json()             # B intact

def test_reset_still_env_gated(c, monkeypatch):
    monkeypatch.delenv("SLATE_DEMO_RESET", raising=False)
    assert c.post("/v1/demo/reset", json={"confirm": "reset"}, headers=HA).status_code == 403

# --- provider behavior --------------------------------------------------------

def _google_app(verifier, store):
    return TestClient(create_authenticated_app(GoogleAuth("client-123", verifier=verifier), store))

def test_google_token_verification(tmp_path):
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    good = lambda token, aud: {"sub": "42", "email": "asha@example.com"} if (token, aud) == ("good", "client-123") else (_ for _ in ()).throw(ValueError("bad"))
    c = _google_app(good, store)
    assert c.post("/v1/resume", json={"text": RESUME_A}, headers={"Authorization": "Bearer good"}).status_code == 200
    for bad in ["expired", "wrong-audience", "forged"]:
        r = c.get("/v1/jobs", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"

def test_google_sub_is_the_user_id(tmp_path):
    """Two Google users (different subs) are isolated; sub, not email, keys the data."""
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    subs = {"t1": {"sub": "u1", "email": "a@x.com"}, "t2": {"sub": "u2", "email": "a@x.com"}}
    c = _google_app(lambda token, aud: subs[token], store)
    c.post("/v1/resume", json={"text": RESUME_A}, headers={"Authorization": "Bearer t1"})
    assert c.get("/v1/jobs", params={"resumeId": "res_001"}, headers={"Authorization": "Bearer t2"}).status_code == 404

def test_google_token_without_sub_rejected(tmp_path):
    c = _google_app(lambda token, aud: {"email": "a@x.com"}, SqlUserStore(f"sqlite:///{tmp_path}/s.db"))
    assert c.get("/v1/jobs", headers={"Authorization": "Bearer whatever"}).status_code == 401

def test_supabase_provider(tmp_path):
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    ok = TestClient(create_authenticated_app(
        SupabaseAuth("https://proj.supabase.co", "anon", opener=lambda url, key, tok: {"id": "u9", "email": "a@x.com"}), store))
    assert ok.post("/v1/resume", json={"text": RESUME_A}, headers={"Authorization": "Bearer sb-token"}).status_code == 200
    bad = TestClient(create_authenticated_app(
        SupabaseAuth("https://proj.supabase.co", "anon", opener=lambda url, key, tok: (_ for _ in ()).throw(Exception("401"))), store))
    r = bad.get("/v1/jobs", headers={"Authorization": "Bearer stale"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"

def test_real_provider_wins_over_dev_flag(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123")
    monkeypatch.setenv("SLATE_DEV_AUTH", "1")
    assert isinstance(_build_auth(), GoogleAuth)  # dev flag ignored, no silent fallback
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert isinstance(_build_auth(), DevAuth)
    monkeypatch.delenv("SLATE_DEV_AUTH")
    monkeypatch.delenv("SUPABASE_URL", raising=False); monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert _build_auth() is None

def test_unconfigured_server_refuses_data_calls(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False); monkeypatch.delenv("SLATE_DEV_AUTH", raising=False)
    c = TestClient(create_authenticated_app(None, MemUserStore()))
    r = c.get("/v1/jobs")
    assert r.status_code == 503 and r.json()["error"]["code"] == "auth_not_configured"
    assert c.get("/v1/config").json()["mode"] == "unconfigured"

# --- same-user concurrency and size limits ------------------------------------

def test_same_user_concurrent_requests_no_lost_updates(tmp_path):
    """Two threads acting as the SAME user interleave load->mutate->save through
    the per-user lock; without it this loses updates. Store-level race test."""
    import threading
    from slate_core.user_store import locked
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    store.save("u1", {"n": 0})
    def bump():
        for _ in range(25):
            with locked("u1"):
                st = store.load("u1"); st["n"] += 1; store.save("u1", st)
    ts = [threading.Thread(target=bump) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert store.load("u1")["n"] == 100

def test_oversized_inputs_rejected(c):
    assert c.get("/v1/jobs", headers={"Authorization": "Bearer dev:" + "x" * 9000}).status_code == 401
    r = c.post("/v1/resume", json={"text": "x" * 200_001}, headers=HA)
    assert r.status_code == 422
