"""Regression: a GitHub token must never leak past a redirect.

urllib's default redirect handler copies the original request headers -
including Authorization - onto the redirect target. http_get_text attaches
SLATE_GITHUB_TOKEN only for api.github.com, but without a stripping handler
any redirect from the API to another host would forward the bearer token.
These tests use only loopback servers and a fake token.
"""
import http.server
import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import leetcode_sheet as lc  # noqa: E402

FAKE_TOKEN = "fake-bearer-not-a-real-token"


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen_auth = None

    def _record(self):
        type(self).seen_auth = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = _record
    do_POST = _record

    def log_message(self, *args):
        pass


class _Redirector(http.server.BaseHTTPRequestHandler):
    target = None

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", type(self).target)
        self.end_headers()

    def log_message(self, *args):
        pass


def _serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_token_never_sent_to_non_github_host(monkeypatch):
    monkeypatch.setenv("SLATE_GITHUB_TOKEN", FAKE_TOKEN)
    _Recorder.seen_auth = None
    srv = _serve(_Recorder)
    try:
        url = f"http://127.0.0.1:{srv.server_port}/anything"
        assert lc.http_get_text(url) == "ok"
        assert _Recorder.seen_auth is None
    finally:
        srv.shutdown()


def test_authorization_stripped_on_cross_host_redirect():
    _Recorder.seen_auth = None
    dst = _serve(_Recorder)
    _Redirector.target = f"http://127.0.0.1:{dst.server_port}/echo"
    src = _serve(_Redirector)
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{src.server_port}/redir",
            headers={"Authorization": "Bearer " + FAKE_TOKEN},
        )
        with lc._OPENER.open(req, timeout=5) as resp:
            assert resp.read() == b"ok"
        assert _Recorder.seen_auth is None, (
            "Authorization header leaked across a cross-host redirect"
        )
    finally:
        src.shutdown()
        dst.shutdown()
