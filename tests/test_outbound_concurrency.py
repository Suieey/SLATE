"""Regression: the global expensive-work slot must be held ACROSS the outbound
call, not released before it. Previously several routes did
`with get_svc(request, "fetch"): pass` and ran the real network fetch after
the slot was released, so the concurrency bound was illusory. These tests run
real overlapping HTTP requests against the route surface."""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from slate_api.app import create_authenticated_app  # noqa: E402
from slate_core.auth import DevAuth  # noqa: E402
from slate_core.user_store import MemUserStore  # noqa: E402
from slate_core import leetcode_sheet as lc  # noqa: E402

H = {"authorization": "Bearer dev:conc@example.com"}


def _client(monkeypatch, concurrency="1"):
    monkeypatch.setenv("SLATE_EXPENSIVE_CONCURRENCY", concurrency)
    monkeypatch.setenv("SLATE_RATE_FETCH_USER", "50")
    monkeypatch.setenv("SLATE_RATE_FETCH_GLOBAL", "100")
    return TestClient(create_authenticated_app(DevAuth(), MemUserStore()))


def test_overlapping_profile_fetch_is_bounded(monkeypatch):
    """With one slot, two overlapping profile fetches cannot both run: the
    second gets the honest busy signal instead of an unbounded queue."""
    inside = {"cur": 0, "max": 0}

    def slow_profile(username):
        inside["cur"] += 1
        inside["max"] = max(inside["max"], inside["cur"])
        time.sleep(0.4)
        inside["cur"] -= 1
        return {"username": username, "totalSolved": 1, "recentSolved": []}

    monkeypatch.setattr(lc, "fetch_public_profile", slow_profile)
    c = _client(monkeypatch, "1")
    results = []

    def call():
        r = c.post("/v1/practice/profile", json={"username": "someone"}, headers=H)
        results.append(r.status_code)

    t1, t2 = threading.Thread(target=call), threading.Thread(target=call)
    t1.start(); time.sleep(0.05); t2.start()
    t1.join(); t2.join()
    assert inside["max"] == 1, "two outbound fetches ran at once under a one-slot bound"
    assert sorted(results) == [200, 429], results


def test_projects_review_is_now_gated(monkeypatch):
    """/v1/projects/review previously ran with no bucket at all: unauthenticated
    callers must be rejected, and authed calls count against the fetch budget."""
    monkeypatch.setattr("slate_core.project_review.build_review",
                        lambda repos: {"reviews": [], "repos": repos})
    monkeypatch.setenv("SLATE_RATE_FETCH_USER", "1")
    monkeypatch.setenv("SLATE_RATE_FETCH_GLOBAL", "100")
    monkeypatch.setenv("SLATE_EXPENSIVE_CONCURRENCY", "4")
    c = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    body = {"repos": ["https://github.com/a/b"]}
    assert c.post("/v1/projects/review", json=body).status_code in (401, 503)
    assert c.post("/v1/projects/review", json=body, headers=H).status_code == 200
    second = c.post("/v1/projects/review", json=body, headers=H)
    assert second.status_code == 429, "second in-window call must hit the per-user fetch budget"
