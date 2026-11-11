"""Synthetic abuse/privacy regressions; never stores or deletes user data."""
import asyncio
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from slate_api.app import create_authenticated_app
from slate_api.request_limits import RequestBodyLimit
import slate_api.request_limits as limits
from slate_core.auth import DevAuth
from slate_core.user_store import MemUserStore
from slate_core.resume import (extract_pdf_text, parse_resume, ParseError,
                               MAX_PDF_BYTES, MAX_PDF_PAGES, MAX_RESUME_CHARS)
from test_pdf_resume import make_pdf, LINES


def exercise(events, headers=(), method="POST", path="/v1/resume", budget=32):
    sent, seen, reads = [], [], []
    async def receive():
        reads.append(1)
        return events.pop(0)
    async def send(event): sent.append(event)
    async def downstream(scope, receive, send): seen.append(await receive())
    with patch.object(limits, "MAX_JSON_BODY_BYTES", budget), patch.object(limits, "MAX_PDF_BODY_BYTES", budget):
        asyncio.run(RequestBodyLimit(downstream)({"type": "http", "method": method, "path": path,
                                                  "headers": list(headers)}, receive, send))
    return sent, seen, len(reads)


def test_declared_oversized_body_rejected_before_read_or_parser():
    sent, seen, reads = exercise([], [(b"content-length", b"33")])
    assert sent[0]["status"] == 413
    assert reads == 0 and seen == []
    assert json.loads(sent[1]["body"])["error"]["code"] == "request_too_large"


def test_chunked_or_lying_length_cannot_bypass_actual_byte_limit():
    for headers in [(), [(b"content-length", b"1")]]:
        sent, seen, reads = exercise([{"type": "http.request", "body": b"a"*20, "more_body": True},
                                      {"type": "http.request", "body": b"b"*20, "more_body": True},
                                      {"type": "http.request", "body": b"c"*100} ], headers)
        assert sent[0]["status"] == 413 and seen == [] and reads == 2
        assert b"aaaa" not in sent[1]["body"]


def test_body_at_boundary_replayed_without_corruption():
    sent, seen, reads = exercise([{"type": "http.request", "body": b"a"*15, "more_body": True},
                                  {"type": "http.request", "body": b"b"*17}])
    assert sent == [] and seen[0]["body"] == b"a"*15+b"b"*17 and reads == 2


@pytest.mark.parametrize("length", [b"invalid", b"-1"])
def test_invalid_lengths_rejected(length):
    sent, seen, reads = exercise([], [(b"content-length", length)])
    assert sent[0]["status"] == 400 and seen == [] and reads == 0


def test_disconnect_does_not_call_parser_or_send_late_response():
    sent, seen, reads = exercise([{"type": "http.disconnect"}])
    assert sent == seen == [] and reads == 1


def test_total_upload_deadline_stops_slow_body():
    sent, called = [], []
    async def receive(): await asyncio.sleep(1)
    async def send(e): sent.append(e)
    async def app(*args): called.append(True)
    with patch.object(limits, "BODY_READ_SECONDS", .001):
        asyncio.run(RequestBodyLimit(app)({"type": "http", "method": "POST", "path": "/v1/resume", "headers": []}, receive, send))
    assert sent[0]["status"] == 408 and called == []


def test_real_multipart_oversize_does_not_reach_pdf_decoder():
    client = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    with patch("slate_api.app.extract_pdf_text") as decoder:
        response = client.post("/v1/resume/pdf", files={"file": ("synthetic.pdf", b"x"*(MAX_PDF_BYTES+70_000), "application/pdf")},
                               headers={"Authorization": "Bearer dev:synthetic@example.com"})
    assert response.status_code == 413 and not decoder.called


def test_per_file_limit_still_applies_inside_allowed_multipart_envelope():
    client = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    with patch("slate_api.app.extract_pdf_text") as decoder:
        response = client.post("/v1/resume/pdf", files={"file": ("synthetic.pdf", b"x"*(MAX_PDF_BYTES+1), "application/pdf")},
                               headers={"Authorization": "Bearer dev:synthetic@example.com"})
    assert response.status_code == 422 and not decoder.called


def test_page_limit_checked_before_any_page_extraction():
    class Page:
        def extract_text(self): raise AssertionError("must not decode pages over limit")
    class Reader:
        is_encrypted = False
        pages = [Page()]*(MAX_PDF_PAGES+1)
    with patch("pypdf.PdfReader", return_value=Reader()):
        with pytest.raises(ParseError, match="20 max"):
            extract_pdf_text(b"synthetic PDF container")


def test_extracted_text_budget_stops_before_later_pages():
    calls = []
    class Page:
        def extract_text(self):
            calls.append(1)
            return "x"*(MAX_RESUME_CHARS//2)
    class Reader:
        is_encrypted = False
        pages = [Page()]*5
    with patch("pypdf.PdfReader", return_value=Reader()):
        with pytest.raises(ParseError, match="200,000"):
            extract_pdf_text(b"synthetic PDF container")
    assert len(calls) == 2


def test_core_text_limit_and_nested_malformed_template_notes():
    with pytest.raises(ParseError, match="200,000"):
        parse_resume("x"*(MAX_RESUME_CHARS+1))
    # Keep malformed guidance/content; processing no longer rescans each nested tip.
    parsed = parse_resume("Alex Example\n" + "(Tip: "*3000 + "\nSkills: Python")
    assert "python" in parsed["skills"]


def test_normal_pdf_and_auth_behavior_unchanged():
    client = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    files = {"file": ("synthetic.pdf", make_pdf(LINES), "application/pdf")}
    assert client.post("/v1/resume/pdf", files=files).status_code == 401
    response = client.post("/v1/resume/pdf", files=files, headers={"Authorization": "Bearer dev:synthetic@example.com"})
    assert response.status_code == 200 and "python" in response.json()["parsed"]["skills"]


@pytest.mark.parametrize("path", [".local-state/slate.db", "slate_state.db", "slate_state.db-wal", "private.sqlite", "private.sqlite3-shm", "uploads/resume.pdf"])
def test_private_runtime_paths_are_ignored_without_touching_them(path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "check-ignore", "--no-index", path], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_runtime_database_or_upload_is_tracked():
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    assert not any(p.startswith((".local-state/", "uploads/")) or p.endswith((".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")) for p in tracked)
