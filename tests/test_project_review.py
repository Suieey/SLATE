"""GitHub project review feature. Synthetic fixtures only: every test injects
fake transports; nothing here touches github.com or any network."""
import io
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from slate_api.app import create_app  # noqa: E402
from slate_core import SlateService  # noqa: E402
from slate_core import project_review as pr  # noqa: E402
from slate_core.service import SlateError  # noqa: E402

SHA = "abc123def4567890abc123def4567890abc12345"
META = {
    "full_name": "srt-dev/zipkit", "description": "tiny zip library",
    "default_branch": "main", "stargazers_count": 7, "forks_count": 2,
    "open_issues_count": 1, "created_at": "2026-01-02T00:00:00Z",
    "pushed_at": "2026-11-01T00:00:00Z", "fork": False, "archived": False,
    "license": {"spdx_id": "MIT"},
}
TREE = {
    "truncated": False,
    "tree": [
        {"type": "blob", "path": "README.md", "size": 900},
        {"type": "blob", "path": "requirements.txt", "size": 60},
        {"type": "blob", "path": ".github/workflows/ci.yml", "size": 200},
        {"type": "blob", "path": "zipkit/__init__.py", "size": 120},
        {"type": "blob", "path": "zipkit/core.py", "size": 3200},
        {"type": "blob", "path": "tests/test_core.py", "size": 800},
        {"type": "blob", "path": "tests/test_edge.py", "size": 500},
    ],
}
README = "# zipkit\n\n## Installation\n\npip install zipkit\n\n## Usage\n\nzipkit.compress(src)\n"
REQS = "requests==2.31.0\nclick>=8.0\n"
CI_YML = "name: ci\non: [push]\njobs:\n  test:\n    steps:\n      - run: pytest -q\n"
TEST_WITH_ASSERTS = "def test_compress_roundtrip():\n    assert compress(b'x')\n\ndef test_empty():\n    assert compress(b'') == b''\n"
TEST_NO_MECH = "def test_placeholder():\n    pass\n"
CHECK_RUNS_PASS = {"total_count": 1, "check_runs": [
    {"name": "pytest (3.11)", "status": "completed", "conclusion": "success"}]}
CHECK_RUNS_BOTS = {"total_count": 1, "check_runs": [
    {"name": "stale-bot", "status": "completed", "conclusion": "success"}]}


def fake_json(check_runs=CHECK_RUNS_PASS, calls=None):
    def get(url, timeout=15.0):
        if calls is not None:
            calls.append(url)
        if url.endswith("/repos/srt-dev/zipkit"):
            return META
        if url.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/git/trees/" in url:
            return TREE
        if "/check-runs" in url:
            return check_runs
        if url.endswith("/status"):
            return {"state": "pending", "statuses": []}
        raise AssertionError("unexpected api url: " + url)
    return get


def fake_text(url, timeout=20.0):
    assert SHA in url, "raw reads must be pinned to the head commit"
    if url.endswith("/README.md"):
        return README
    if url.endswith("/requirements.txt"):
        return REQS
    if url.endswith("/ci.yml"):
        return CI_YML
    if url.endswith("/test_core.py"):
        return TEST_WITH_ASSERTS
    if url.endswith("/test_edge.py"):
        return TEST_NO_MECH
    if url.endswith(".py"):
        return "# code\n"
    raise AssertionError("unexpected raw url: " + url)


@pytest.fixture(autouse=True)
def _no_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


def _sig(analysis, name):
    return {s["name"]: s for s in analysis["signals"]}[name]


# --- input validation / SSRF defense -----------------------------------------

def test_parse_repo_ref_variants():
    assert pr.parse_repo_ref("srt-dev/zipkit") == ("srt-dev", "zipkit")
    assert pr.parse_repo_ref("https://github.com/srt-dev/zipkit") == ("srt-dev", "zipkit")
    assert pr.parse_repo_ref("github.com/srt-dev/zipkit.git") == ("srt-dev", "zipkit")
    assert pr.parse_repo_ref("https://github.com/srt-dev/zipkit/tree/main/src") == ("srt-dev", "zipkit")


def test_parse_repo_ref_rejects_non_github_and_tricks():
    for bad in ["https://evil.com/srt-dev/zipkit",
                "https://github.com.evil.com/a/b",
                "https://user:pw@github.com/a/b",
                "https://github.com:8080/a/b",
                "https://127.0.0.1/a/b",
                "javascript:alert(1)",
                "https://api.github.com/repos/a/b",
                "justonepart",
                ""]:
        with pytest.raises(SlateError) as e:
            pr.parse_repo_ref(bad)
        assert e.value.code == "invalid_repo"


def test_parse_username_variants():
    assert pr.parse_github_username("srt-dev") == "srt-dev"
    assert pr.parse_github_username("https://github.com/srt-dev") == "srt-dev"
    with pytest.raises(SlateError):
        pr.parse_github_username("https://evil.com/srt-dev")


def test_extract_links_from_text():
    text = ("Projects: https://github.com/srt-dev/zipkit and github.com/srt-dev/zipkit "
            "profile https://github.com/srt-dev plus site page https://github.com/features")
    found = pr.extract_github_links(text)
    assert found["repos"] == [{"owner": "srt-dev", "repo": "zipkit", "ref": "srt-dev/zipkit"}]  # deduped
    assert found["usernames"] == ["srt-dev"]
    assert "features" not in found["usernames"]  # site sections are not usernames


def _pdf_with_link(uri=None):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, ArrayObject, RectangleObject, TextStringObject
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    if uri:
        annot = DictionaryObject()
        annot.update({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): RectangleObject([0, 0, 10, 10]),
            NameObject("/A"): DictionaryObject({
                NameObject("/S"): NameObject("/URI"),
                NameObject("/URI"): TextStringObject(uri),
            }),
        })
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_annotation_carries_repo_link():
    pdf = _pdf_with_link(uri="https://github.com/srt-dev/hidden-proj")
    found = pr.extract_pdf_github_links(pdf)
    assert found["repos"] == [{"owner": "srt-dev", "repo": "hidden-proj", "ref": "srt-dev/hidden-proj"}]


def test_pdf_visible_text_link():
    pdf = _pdf_with_link()
    found = pr.extract_pdf_github_links(pdf, text="Code: https://github.com/srt-dev/zipkit")
    assert found["repos"][0]["ref"] == "srt-dev/zipkit"


# --- analysis: evidence and honesty ------------------------------------------

def test_analyze_repo_full():
    a = pr.analyze_repo("https://github.com/srt-dev/zipkit", get_json=fake_json(), get_text=fake_text)
    assert a["commit"] == SHA and a["status"] if "status" in a else True
    assert _sig(a, "README present")["status"] == "met"
    assert _sig(a, "README has setup/run steps")["status"] == "met"
    assert _sig(a, "README has usage examples")["status"] == "met"
    assert _sig(a, "Dependencies declared")["status"] == "met"
    assert _sig(a, "Dependencies pinned/locked")["status"] == "partial"  # 1 of 2 pinned
    assert "1 of 2" in _sig(a, "Dependencies pinned/locked")["evidence"]
    assert _sig(a, "Automated tests present")["status"] == "met"
    sub = _sig(a, "Tests are substantive")
    assert sub["status"] == "partial"  # one sampled file has no assertion mechanism
    assert "tests/test_edge.py" in sub["evidence"]  # named, not generic
    assert _sig(a, "CI configured")["status"] == "met"
    assert _sig(a, "CI runs a test command")["status"] == "met"
    obs = _sig(a, "Observed test outcome on HEAD")
    assert obs["status"] == "met" and "pytest (3.11)" in obs["evidence"] and SHA[:7] in obs["evidence"]
    assert _sig(a, "License present")["status"] == "met"
    # score math: 11 signals, 1 unknown-free set; partial counts 0.5
    assert a["score"]["applicable"] == 12
    assert a["score"]["metPoints"] == 11.0  # 10 met + 2 partials at 0.5
    assert a["score"]["unknownSignals"] == []
    # suggestions are grounded in the actual evidence
    assert any("pin" in s["suggestion"].lower() and "1 of 2" in s["evidence"] for s in a["suggestions"])
    assert any("assertion mechanism" in s["suggestion"] and "test_edge.py" in s["evidence"] for s in a["suggestions"])
    assert not any("start a small automated test suite" in s["suggestion"].lower() for s in a["suggestions"])
    # coverage is described honestly
    cov = a["coverage"]
    assert cov["testFiles"] == 2 and cov["testFilesRead"] == 2 and cov["sourceFilesRead"] == 2
    assert a["limits"]["apiCallsUsed"] == 4  # meta + branch + tree + check-runs
    assert "never runs repository code" in a["scopeNote"]


def test_unknowns_never_scored_as_failures():
    """No README, no CI, no tests: those dependent signals are unknown, and the
    unobserved test outcome says Slate does not run tests - not zero points."""
    tree = {"truncated": False, "tree": [
        {"type": "blob", "path": "main.py", "size": 400},
        {"type": "blob", "path": "package.json", "size": 120},
    ]}
    meta = {**META, "description": "", "license": None}

    def get(url, timeout=15.0):
        if url.endswith("/repos/srt-dev/zipkit"):
            return meta
        if url.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/git/trees/" in url:
            return tree
        if "/check-runs" in url:
            return {"total_count": 0, "check_runs": []}
        if url.endswith("/status"):
            return {"state": "pending", "statuses": []}
        raise AssertionError(url)

    def text(url, timeout=20.0):
        if url.endswith("/package.json"):
            return '{"dependencies": {"left-pad": "^1.0.0"}}'
        return "// js\n"

    a = pr.analyze_repo("srt-dev/zipkit", get_json=get, get_text=text)
    assert _sig(a, "README present")["status"] == "not_met"
    assert _sig(a, "README has setup/run steps")["status"] == "unknown"  # excluded, not failed
    assert _sig(a, "Automated tests present")["status"] == "not_met"
    assert _sig(a, "Tests are substantive")["status"] == "unknown"
    assert _sig(a, "CI configured")["status"] == "not_met"
    assert _sig(a, "CI runs a test command")["status"] == "unknown"
    obs = _sig(a, "Observed test outcome on HEAD")
    assert obs["status"] == "unknown" and "Slate does not run tests" in obs["evidence"]
    assert _sig(a, "Dependencies pinned/locked")["status"] == "unknown"  # package.json pinning not judged
    assert set(a["score"]["unknownSignals"]) == {
        "README has setup/run steps", "README has usage examples",
        "Tests are substantive", "CI runs a test command",
        "Observed test outcome on HEAD", "Dependencies pinned/locked"}
    assert a["score"]["applicable"] == 6
    assert a["score"]["metPoints"] == 1.0  # deps declared only
    assert any("README.md" in s["suggestion"] for s in a["suggestions"])
    assert any("GitHub Actions" in s["suggestion"] for s in a["suggestions"])
    # stars/forks appear only as context, never in the score
    assert "stars" not in str(a["score"]).lower()


def test_bot_checks_are_not_test_evidence():
    a = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(check_runs=CHECK_RUNS_BOTS), get_text=fake_text)
    obs = _sig(a, "Observed test outcome on HEAD")
    assert obs["status"] == "unknown"
    assert "none is identifiable as a test job" in obs["evidence"]
    assert "stale-bot" in obs["evidence"]


def test_failing_ci_job_is_quoted():
    failing = {"total_count": 1, "check_runs": [
        {"name": "pytest", "status": "completed", "conclusion": "failure"}]}
    a = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(check_runs=failing), get_text=fake_text)
    obs = _sig(a, "Observed test outcome on HEAD")
    assert obs["status"] == "not_met" and "'pytest': failure" in obs["evidence"]
    assert any("publicly failing" in s["suggestion"] for s in a["suggestions"])


def test_framework_aware_test_detection():
    """No bare 'assert' keyword does not mean an empty test."""
    tree = {"truncated": False, "tree": [
        {"type": "blob", "path": "src/index.ts", "size": 900},
        {"type": "blob", "path": "src/index.test.ts", "size": 500},
        {"type": "blob", "path": "go/client_test.go", "size": 500},
    ]}

    def get(url, timeout=15.0):
        if url.endswith("/repos/srt-dev/zipkit"):
            return META
        if url.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/git/trees/" in url:
            return tree
        if "/check-runs" in url:
            return {"total_count": 0, "check_runs": []}
        if url.endswith("/status"):
            return {"state": "success", "statuses": [{"context": "ci/tests", "state": "success"}]}
        raise AssertionError(url)

    def text(url, timeout=20.0):
        if url.endswith("index.test.ts"):
            return "import {expect, test} from 'vitest'\ntest('adds', () => { expect(1+1).toBe(2) })\n"
        if url.endswith("client_test.go"):
            return "func TestDial(t *testing.T) { t.Error(\"boom\") }\n"
        return "// src\n"

    a = pr.analyze_repo("srt-dev/zipkit", get_json=get, get_text=text)
    sub = _sig(a, "Tests are substantive")
    assert sub["status"] == "met"
    assert "jest/vitest expect" in sub["evidence"] and "go testing" in sub["evidence"]
    obs = _sig(a, "Observed test outcome on HEAD")
    assert obs["status"] == "met" and "ci/tests" in obs["evidence"]  # commit-status fallback


def test_readme_heading_only_section_is_partial_not_met():
    """A '## Installation' heading with nothing under it must not earn a met."""
    empty_readme = "# proj\n\n## Installation\n\n## Usage\n\nuse it like this\n"

    def text(url, timeout=20.0):
        if url.endswith("/README.md"):
            return empty_readme
        return fake_text(url, timeout)

    a = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(), get_text=text)
    assert _sig(a, "README has setup/run steps")["status"] == "partial"
    assert "section is empty" in _sig(a, "README has setup/run steps")["evidence"]
    assert _sig(a, "README has usage examples")["status"] == "met"  # real content


def test_readme_subsection_content_counts():
    """Content under a deeper subsection (### Homebrew) belongs to its parent section."""
    sub_readme = "# proj\n\n## Installation\n\n### Homebrew\n\nbrew install proj\n\n## License\n"

    def text(url, timeout=20.0):
        if url.endswith("/README.md"):
            return sub_readme
        return fake_text(url, timeout)

    a = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(), get_text=text)
    assert _sig(a, "README has setup/run steps")["status"] == "met"


def test_build_config_is_not_a_dependency_declaration():
    """A lone makefile is build config: 'Dependencies declared' becomes an honest
    unknown (the project may have no external deps), never met - and Slate stops
    telling zero-dependency C projects to 'declare dependencies'."""
    tree = {"truncated": False, "tree": [
        {"type": "blob", "path": "README.md", "size": 300},
        {"type": "blob", "path": "makefile", "size": 80},
        {"type": "blob", "path": "main.c", "size": 400},
    ]}

    def get(url, timeout=15.0):
        if url.endswith("/repos/srt-dev/zipkit"):
            return META
        if url.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/git/trees/" in url:
            return tree
        if "/check-runs" in url:
            return {"total_count": 0, "check_runs": []}
        if url.endswith("/status"):
            return {"state": "pending", "statuses": []}
        raise AssertionError(url)

    def text(url, timeout=20.0):
        if url.endswith("/README.md"):
            return "# proj\n\n## Installation\n\nmake\n\n## Usage\n\n./proj\n"
        if url.endswith("/makefile"):
            return "all:\n\tgcc main.c\n"
        return "/* c */\n"

    a = pr.analyze_repo("srt-dev/zipkit", get_json=get, get_text=text)
    dec = _sig(a, "Dependencies declared")
    assert dec["status"] == "unknown"
    assert "build config is not a dependency declaration" in dec["evidence"]
    assert "makefile" in dec["evidence"]
    assert _sig(a, "Dependencies pinned/locked")["status"] == "unknown"
    assert not any("Declare dependencies" in s["suggestion"] for s in a["suggestions"])


# --- failure modes ------------------------------------------------------------

def test_private_repo_is_inaccessible_not_zero():
    def get(url, timeout=15.0):
        raise SlateError("repo_not_found", "That repository is not publicly accessible - it may be private, renamed or deleted.")
    out = pr.build_review(["srt-dev/secret", "srt-dev/zipkit"], get_json=get, get_text=fake_text)
    first = out["reviews"][0]
    assert first["status"] == "inaccessible" and "private" in first["reason"]
    assert "score" not in first  # inaccessible is not a zero score


def test_rate_limit_stops_pass_and_marks_rest():
    err = SlateError("github_rate_limited", "limit")
    state = {"n": 0}

    def get(url, timeout=15.0):
        state["n"] += 1
        if state["n"] <= 4:
            return fake_json()(url, timeout)
        raise err

    out = pr.build_review(["srt-dev/zipkit", "srt-dev/other", "srt-dev/third"], get_json=get, get_text=fake_text)
    assert out["reviews"][0]["status"] == "reviewed"
    assert out["reviews"][1]["errorCode"] == "github_rate_limited"
    assert out["reviews"][2]["status"] == "not_checked"
    assert out["rateLimited"] is True


def test_too_many_repos_rejected():
    with pytest.raises(SlateError) as e:
        pr.build_review(["a/b"] * 6, get_json=fake_json(), get_text=fake_text)
    assert e.value.code == "too_many_repos"


def test_cache_serves_repeat_view_and_flags_it():
    calls = []
    a1 = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(calls=calls), get_text=fake_text)
    n = len(calls)
    a2 = pr.analyze_repo("srt-dev/zipkit", get_json=fake_json(calls=calls), get_text=fake_text)
    assert a2["fromCache"] is True and len(calls) == n  # repeat view costs no API calls within the TTL
    assert a1["fromCache"] is False


def test_txt_render_is_honest():
    out = pr.build_review(["srt-dev/zipkit"], get_json=fake_json(), get_text=fake_text)
    txt = out["txt"]
    assert "Slate project review" in txt
    assert "Nothing was executed" in txt
    assert "unknown" in txt and "never counted against" in txt
    assert "pytest (3.11)" in txt


# --- HTTP layer ----------------------------------------------------------------

@pytest.fixture()
def c():
    return TestClient(create_app(SlateService()))


def test_scan_saved_resumes(c):
    c.post("/v1/resume", json={"text": "Asha Verma\nCode: https://github.com/asha-codes/zipkit\nSkills: Python\n"})
    found = c.post("/v1/projects/scan", json={}).json()
    assert found["repos"] == [{"owner": "asha-codes", "repo": "zipkit", "ref": "asha-codes/zipkit"}]
    assert found["usernames"] == []


def test_scan_pdf_endpoint(c):
    pdf = _pdf_with_link(uri="https://github.com/asha-codes/pdf-proj")
    res = c.post("/v1/projects/scan-pdf", files={"file": ("resume.pdf", pdf, "application/pdf")})
    assert res.status_code == 200 and res.json()["repos"][0]["ref"] == "asha-codes/pdf-proj"


def test_repos_endpoint(c, monkeypatch):
    def stub(username):
        pr.parse_github_username(username)  # keep the real validation behavior
        return {
            "username": "srt-dev",
            "repos": [{"name": "zipkit", "description": "d", "language": "Python", "stars": 1,
                       "pushedAt": "2026-11-01", "fork": False, "archived": False, "ref": "srt-dev/zipkit"}]}
    monkeypatch.setattr(pr, "list_user_repos", stub)
    res = c.post("/v1/projects/repos", json={"username": "srt-dev"})
    assert res.status_code == 200 and res.json()["repos"][0]["ref"] == "srt-dev/zipkit"
    res = c.post("/v1/projects/repos", json={"username": "!!bad!!"})
    assert res.status_code == 422


def test_review_endpoint_with_stubbed_module(c, monkeypatch):
    monkeypatch.setattr(pr, "build_review", lambda repos: {
        "reviews": [{"ref": repos[0], "status": "reviewed", "signals": [], "score": {"metPoints": 1, "applicable": 1, "unknownSignals": []},
                     "context": {}, "suggestions": [], "coverage": {}, "limits": {"apiCallsUsed": 4},
                     "url": "https://github.com/" + repos[0], "commit": SHA, "checkedAt": "t", "scopeNote": "n"}],
        "checkedAt": "t", "scopeNote": "n", "rateLimited": False, "txt": "review text"})
    res = c.post("/v1/projects/review", json={"repos": ["srt-dev/zipkit"]})
    assert res.status_code == 200 and res.json()["txt"] == "review text"
    res = c.post("/v1/projects/review", json={"repos": []})
    assert res.status_code == 422  # validation
