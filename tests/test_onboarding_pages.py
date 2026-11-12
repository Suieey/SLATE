"""Onboarding & profile pages: routes, first-login gate, nav links, and the
profile contract the pages build on, checked fresh over HTTP (first-login
flow, skip semantics, per-user isolation, restart persistence).

No network: dev auth provider, local sqlite stores. The production no-dev-auth
provider preference is already covered in test_auth_users.py.
"""
import os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from slate_api.app import create_app, create_authenticated_app
from slate_core.service import SlateService
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore

HA = {"Authorization": "Bearer dev:asha@example.com"}
HB = {"Authorization": "Bearer dev:rohan@example.com"}

PAGES = ["/", "/ai", "/interview", "/practice"]


def test_onboarding_and_profile_pages_served():
    c = TestClient(create_app(SlateService()))
    r = c.get("/onboarding")
    assert r.status_code == 200 and 'id="stage-form"' in r.text and 'id="skip"' in r.text
    r = c.get("/profile")
    assert r.status_code == 200 and 'id="ansRows"' in r.text and 'id="editBtn"' in r.text


def test_nav_has_profile_link_on_every_page():
    c = TestClient(create_app(SlateService()))
    for route in PAGES + ["/profile", "/onboarding"]:
        r = c.get(route)
        assert r.status_code == 200 and 'href="/profile"' in r.text, route


def test_first_login_gate_on_existing_pages():
    c = TestClient(create_app(SlateService()))
    for route in PAGES:
        html = c.get(route).text
        assert "onboardingGate" in html and 'location.replace("/onboarding")' in html, route


def test_no_gate_on_setup_pages():
    # Onboarding and profile must never redirect to onboarding themselves.
    c = TestClient(create_app(SlateService()))
    for route in ("/onboarding", "/profile"):
        assert "onboardingGate" not in c.get(route).text, route


@pytest.fixture()
def pair(tmp_path):
    store = SqlUserStore(f"sqlite:///{tmp_path}/state.db")
    return TestClient(create_authenticated_app(DevAuth(), store)), tmp_path


def test_first_login_flow_over_http(pair):
    client, tmp_path = pair
    r = client.get("/v1/profile", headers=HA)
    assert r.json()["status"] == "not_started"  # what the gate redirects on
    # Skip: records a decision with NO answers, and never claims details.
    r = client.post("/v1/profile", json={"answers": {}, "confirm": True}, headers=HA)
    assert r.status_code == 200
    assert r.json()["status"] == "user_confirmed" and r.json()["answers"] == {}
    # Restart over the same database file: the recorded skip survives.
    client2 = TestClient(create_authenticated_app(
        DevAuth(), SqlUserStore(f"sqlite:///{tmp_path}/state.db")))
    r = client2.get("/v1/profile", headers=HA)
    assert r.json()["status"] == "user_confirmed" and r.json()["answers"] == {}
    # Saving real answers later works; blanks stay unknown.
    r = client2.post("/v1/profile", json={
        "answers": {"name": "Asha Verma", "github": "github.com/asha-verma"},
        "confirm": True}, headers=HA)
    assert r.json()["answers"]["github"] == "https://github.com/asha-verma"
    assert "phone" in r.json()["unknownFields"]


def test_profile_isolated_between_users(pair):
    client, _ = pair
    client.post("/v1/profile", json={"answers": {"name": "Asha Verma"}, "confirm": True}, headers=HA)
    r = client.get("/v1/profile", headers=HB)
    assert r.json()["status"] == "not_started" and r.json()["answers"] == {}


def test_practice_endpoints_require_a_token(pair):
    client, _ = pair
    checks = [
        ("get", "/v1/practice/companies", {}),
        ("post", "/v1/practice/scan", {"json": {}}),
        ("post", "/v1/practice/scan-pdf", {"files": {"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")}}),
        ("post", "/v1/practice/profile", {"json": {"username": "x"}}),
        ("post", "/v1/practice/sheet", {"json": {"username": "x", "company": "Amazon"}}),
        ("post", "/v1/practice/sheet-from-csv",
         {"files": {"file": ("s.csv", b"a,b\n", "text/csv")}, "data": {"username": "x", "company": ""}}),
    ]
    for method, path, kw in checks:
        r = getattr(client, method)(path, **kw)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "unauthenticated"
