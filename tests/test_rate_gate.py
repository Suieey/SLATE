"""Rate gate: per-user and global ceilings, concurrency bound, honest 429.

Covers the abuse class that per-request size caps cannot: repeated and
concurrent expensive requests on a public deployment. No network: dev auth,
local stores, LLM unset so the interview runs its deterministic fallback.
"""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from slate_api.app import create_authenticated_app
from slate_core.auth import DevAuth
from slate_core.rate_gate import RateGate
from slate_core.service import SlateError
from slate_core.user_store import SqlUserStore

HA = {"Authorization": "Bearer dev:asha@example.com"}
HB = {"Authorization": "Bearer dev:rohan@example.com"}


def _app(tmp_path, **env):
    for k, v in env.items():
        os.environ[k] = str(v)
    try:
        store = SqlUserStore("sqlite:///" + str(tmp_path / "state.db"))
        return TestClient(create_authenticated_app(DevAuth(), store))
    finally:
        for k in env:
            os.environ.pop(k, None)


def test_per_user_ceiling_gives_honest_429(tmp_path, monkeypatch):
    monkeypatch.setenv("SLATE_RATE_AI_USER", "2")
    c = _app(tmp_path)
    body = {"targetRole": "data analyst", "mode": "text"}
    assert c.post("/v1/interview/mock", json=body, headers=HA).status_code == 200
    assert c.post("/v1/interview/mock", json=body, headers=HA).status_code == 200
    r = c.post("/v1/interview/mock", json=body, headers=HA)
    assert r.status_code == 429
    detail = r.json().get("error", {})
    assert detail.get("code") == "rate_limited" and "Try again" in detail.get("message", "")


def test_ceiling_is_per_user_not_per_app(tmp_path, monkeypatch):
    monkeypatch.setenv("SLATE_RATE_AI_USER", "1")
    c = _app(tmp_path)
    body = {"targetRole": "data analyst", "mode": "text"}
    assert c.post("/v1/interview/mock", json=body, headers=HA).status_code == 200
    assert c.post("/v1/interview/mock", json=body, headers=HA).status_code == 429
    # another signed-in user is unaffected
    assert c.post("/v1/interview/mock", json=body, headers=HB).status_code == 200


def test_global_ceiling_bounds_total_load(tmp_path, monkeypatch):
    monkeypatch.setenv("SLATE_RATE_AI_USER", "100")
    monkeypatch.setenv("SLATE_RATE_AI_GLOBAL", "3")
    c = _app(tmp_path)
    body = {"targetRole": "data analyst", "mode": "text"}
    codes = [c.post("/v1/interview/mock", json=body,
                    headers={"Authorization": "Bearer dev:user%d@example.com" % i}).status_code
             for i in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_ungated_endpoints_unaffected(tmp_path, monkeypatch):
    monkeypatch.setenv("SLATE_RATE_AI_USER", "1")
    c = _app(tmp_path)
    # profile writes are cheap and stay ungated even after the AI ceiling is hit
    body = {"targetRole": "data analyst", "mode": "text"}
    c.post("/v1/interview/mock", json=body, headers=HA)
    assert c.post("/v1/interview/mock", json=body, headers=HA).status_code == 429
    r = c.post("/v1/profile", json={"answers": {"name": "Asha"}, "confirm": True}, headers=HA)
    assert r.status_code == 200


def test_gate_unit_concurrency_and_window():
    g = RateGate()
    g._sem = __import__("threading").BoundedSemaphore(1)
    g.acquire()
    with pytest.raises(SlateError) as e:
        g.acquire()
    assert e.value.code == "rate_limited"
    g.release()
    g.acquire(); g.release()  # released capacity is reusable


def test_gate_memory_map_is_bounded(monkeypatch):
    monkeypatch.setenv("SLATE_RATE_MAX_TRACKED", "5")
    g = RateGate()
    refused = 0
    for i in range(50):
        try:
            g.check("fetch", "user%d" % i)  # flood of distinct users cannot grow the map
        except SlateError as e:
            assert e.code == "rate_limited"
            refused += 1
    assert refused > 0  # fail closed once pruning fresh keys is not enough
    assert len(g._hits) <= 6  # hard cap, never the flood size
