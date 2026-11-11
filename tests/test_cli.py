"""CLI parity: the cli/ surface drives the same /v1 endpoints as the website."""
import contextlib, io, os, re, sys, threading, time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cli"))
from slate_api.app import create_authenticated_app  # noqa: E402
from slate_core.auth import DevAuth
from slate_core.user_store import MemUserStore
import slate  # noqa: E402  (cli/slate.py)

PORT = 8137
SERVER = f"http://127.0.0.1:{PORT}"
RESUME = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
          "Intern at ExampleCo (3 months)\nSkills: Python, Git, Excel, communication\n")

@pytest.fixture(scope="module", autouse=True)
def server():
    import uvicorn
    srv = uvicorn.Server(uvicorn.Config(create_authenticated_app(DevAuth(), MemUserStore()), host="127.0.0.1", port=PORT, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started
    yield
    srv.should_exit = True

@pytest.fixture(autouse=True)
def auth_token(monkeypatch):
    monkeypatch.setenv("SLATE_AUTH_TOKEN", "dev:cli-fixture@example.com")

def run_cli(*argv, stdin=""):
    out = io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out):
            slate.main(["--server", SERVER, *argv])
    finally:
        sys.stdin = old
    return out.getvalue()

def test_parse_jobs_tailor_approve_export(tmp_path):
    path = str(tmp_path / "resume.txt")
    with open(path, "w") as f:
        f.write(RESUME)
    o = run_cli("parse", path)
    rid = re.search(r"resumeId: (res_\d+)", o).group(1)
    assert "Asha Verma" in o and "python" in o

    o = run_cli("jobs", "--resume-id", rid)
    jid = re.search(r"(job_\d+)", o).group(1)
    assert "score" in o

    o = run_cli("tailor", "--resume-id", rid, "--job-id", jid)
    did = re.search(r"draftId: (draft_\d+)", o).group(1)
    assert "draft only" in o

    assert "approved" in run_cli("approve", "--draft-id", did)
    o = run_cli("export", "--draft-id", did)
    assert "approved tailored resume" in o

def test_export_rejected_draft_fails(tmp_path):
    path = str(tmp_path / "resume.txt")
    with open(path, "w") as f:
        f.write(RESUME)
    rid = re.search(r"resumeId: (res_\d+)", run_cli("parse", path)).group(1)
    jid = re.search(r"(job_\d+)", run_cli("jobs", "--resume-id", rid)).group(1)
    did = re.search(r"draftId: (draft_\d+)", run_cli("tailor", "--resume-id", rid, "--job-id", jid)).group(1)
    assert "rejected" in run_cli("reject", "--draft-id", did)
    with pytest.raises(SystemExit):
        run_cli("export", "--draft-id", did)

def test_roadmap_and_interview(tmp_path):
    path = str(tmp_path / "resume.txt")
    with open(path, "w") as f:
        f.write(RESUME)
    rid = re.search(r"resumeId: (res_\d+)", run_cli("parse", path)).group(1)
    o = run_cli("roadmap", "--resume-id", rid, "--target-role", "Data Analyst")
    assert re.search(r"1\. .*\(\d+ wk\)", o)

    answers = "I used Python to clean csv exports at my internship.\n" * 6
    o = run_cli("interview", "--target-role", "Data Analyst", stdin=answers)
    assert "sessionId:" in o and "feedback:" in o and "transcriptRef:" in o


def test_missing_and_rejected_token_are_actionable_without_leaking(monkeypatch,capsys):
    for value in (None, "invalid-sensitive-fixture"):
        if value is None: monkeypatch.delenv("SLATE_AUTH_TOKEN",raising=False)
        else: monkeypatch.setenv("SLATE_AUTH_TOKEN",value)
        with pytest.raises(SystemExit): run_cli("jobs")
        err=capsys.readouterr().err
        assert "sign-in is missing or expired" in err
        assert "invalid-sensitive-fixture" not in err
        assert "not retried" in err

def test_hidden_token_overrides_env_and_does_not_echo(monkeypatch,capsys):
    monkeypatch.setenv("SLATE_AUTH_TOKEN","invalid")
    monkeypatch.setattr(slate.getpass,"getpass",lambda _:"dev:hidden-fixture@example.com")
    assert "sample listings" in run_cli("--prompt-token","jobs")
    assert "hidden-fixture" not in capsys.readouterr().err

def test_per_user_cli_isolation(tmp_path,monkeypatch):
    path=tmp_path/"resume.txt";path.write_text(RESUME)
    rid=re.search(r"resumeId: (res_\d+)",run_cli("parse",str(path))).group(1)
    did=re.search(r"draftId: (draft_\d+)",run_cli("tailor","--resume-id",rid,"--job-id","job_001")).group(1)
    monkeypatch.setenv("SLATE_AUTH_TOKEN","dev:other-cli@example.com")
    with pytest.raises(SystemExit):run_cli("approve","--draft-id",did)

def test_pdf_upload_passes_bearer(tmp_path):
    path=tmp_path/"bad.pdf";path.write_bytes(b"%PDF broken fixture")
    # Auth must succeed before the parser returns its expected422, not401.
    err=io.StringIO()
    with contextlib.redirect_stderr(err), pytest.raises(SystemExit):run_cli("parse",str(path))
    assert "sign-in is missing" not in err.getvalue()
    assert "error:" in err.getvalue()

def test_refuse_credentials_over_remote_plain_http(monkeypatch,capsys):
    with pytest.raises(SystemExit):slate.main(["--server","http://example.invalid","jobs"])
    assert "require HTTPS" in capsys.readouterr().err
