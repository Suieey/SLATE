#!/usr/bin/env python3
"""Slate CLI - talks to the same /v1 API as the website. No Slate logic lives here.

Usage:
    python cli/slate.py parse resume.txt|resume.pdf
    python cli/slate.py jobs [--query data] [--location Remote] [--resume-id res_001]
    python cli/slate.py tailor --resume-id res_001 --job-id job_002
    python cli/slate.py approve --draft-id draft_001   (or: reject)
    python cli/slate.py export --draft-id draft_001
    python cli/slate.py roadmap --resume-id res_001 --target-role "Data Analyst"
    python cli/slate.py interview --target-role "Data Analyst"

Server: --server URL or SLATE_API_URL (default http://127.0.0.1:8000).
Stdlib only.
"""
import argparse, contextvars, getpass, json, os, sys, urllib.error, urllib.parse, urllib.request

_AUTH_TOKEN = contextvars.ContextVar("slate_cli_auth", default=None)

def call(server, method, path, body=None, params=None, pdf_path=None):
    url = server.rstrip("/") + "/v1" + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    if pdf_path is not None:
        data = open(pdf_path, "rb").read()
        boundary = "----slate-cli-boundary"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{os.path.basename(pdf_path)}\"\r\nContent-Type: application/pdf\r\n\r\n").encode()
        req = urllib.request.Request(url, data=head + data + f"\r\n--{boundary}--\r\n".encode(), method=method,
                                     headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers={"content-type": "application/json"})
    token = _AUTH_TOKEN.get() or os.getenv("SLATE_AUTH_TOKEN", "")
    if token:
        host = urllib.parse.urlparse(server)
        if host.scheme != "https" and not (host.scheme == "http" and host.hostname in ("localhost", "127.0.0.1", "::1")):
            print("error: bearer credentials require HTTPS outside localhost", file=sys.stderr)
            sys.exit(1)
        req.add_header("Authorization", "Bearer " + token)
    # Do not forward a bearer credential to a redirected destination.
    class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if token:
                raise urllib.error.HTTPError(req.full_url, code, "authenticated redirect refused", headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    try:
        with urllib.request.build_opener(NoAuthRedirect()).open(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("error: sign-in is missing or expired. Obtain a current token for this server, then use --prompt-token or SLATE_AUTH_TOKEN. The request was not retried.", file=sys.stderr)
            sys.exit(1)
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = f"HTTP {e.code}"
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"error: cannot reach the Slate API at {server} ({e.reason}). Is it running?", file=sys.stderr)
        sys.exit(1)

def cmd_parse(a):
    if a.file.lower().endswith(".pdf"):
        r = call(a.server, "POST", "/resume/pdf", pdf_path=a.file)
    else:
        r = call(a.server, "POST", "/resume", {"text": open(a.file).read()})
    p = r["parsed"]
    print(f"resumeId: {r['resumeId']}")
    print(f"name: {p['name']}")
    print("skills: " + (", ".join(p["skills"]) or "none detected"))
    for e in p["education"]:
        print(f"education: {e['degree']} {e.get('institute') or ''} {e.get('year') or ''}".rstrip())
    for x in p["experience"]:
        print(f"experience: {x['title']} at {x['org']}" + (f" ({x['months']} months)" if x.get("months") else ""))

def cmd_jobs(a):
    r = call(a.server, "GET", "/jobs", params={"query": a.query, "location": a.location, "resumeId": a.resume_id})
    if not r["jobs"]:
        print("no matching sample jobs")
    for j in r["jobs"]:
        print(f"{j['jobId']}  {j['title']} - {j['company']} ({j['location']}) "
              f"score {round(j['matchScore'] * 100)}%  apply by {j['deadline']}  {j['url']}")
    print("note: sample listings; score = share of listing skills on the resume, not a good-match claim")

def cmd_tailor(a):
    r = call(a.server, "POST", "/tailor", {"resumeId": a.resume_id, "jobId": a.job_id})
    print(f"draftId: {r['draftId']}  (draft only - review and approve before any use)")
    print("skill gaps: " + (", ".join(r["skillGaps"]) or "none"))
    print("--- tailored resume ---\n" + r["tailoredResume"])
    print("--- cover note ---\n" + r["coverNote"])

def cmd_decide(a):
    r = call(a.server, "POST", "/approvals", {"draftId": a.draft_id, "decision": a.command})
    print(f"{a.draft_id}: {r['status']}")

def cmd_export(a):
    r = call(a.server, "GET", f"/drafts/{a.draft_id}/export")
    print("--- approved tailored resume ---\n" + r["tailoredResume"])
    print("--- approved cover note ---\n" + r["coverNote"])

def cmd_roadmap(a):
    r = call(a.server, "POST", "/roadmap", {"resumeId": a.resume_id, "targetRole": a.target_role})
    for i, m in enumerate(r["milestones"], 1):
        print(f"{i}. {m['title']} ({m['etaWeeks']} wk) - {m['why']}")
        for res in m.get("resources", []):
            print(f"   resource: {res}")

def cmd_interview(a):
    r = call(a.server, "POST", "/interview/mock", {"targetRole": a.target_role, "mode": "text"})
    sid = r["sessionId"]
    print(f"sessionId: {sid}")
    for c in r["carriedFromEarlier"]:
        print(f"(carried over: {c})")
    q = r["firstQuestion"]
    print("Type /end (or finish input) to end and get your report.")
    while True:
        print("\nQ: " + q)
        try:
            ans = input("> ")
        except EOFError:
            print("\n(no more input; ending interview and preparing feedback)")
            ans = "/end"
        if ans.strip().lower() == "/end":
            fb = call(a.server, "POST", f"/interview/{sid}/end", {})
            print("\nfeedback: " + fb["summary"])
            for w in fb["weakAreas"]:
                print("weak area: " + w)
            print(f"transcriptRef: {fb['transcriptRef']}")
            return
        r = call(a.server, "POST", f"/interview/{sid}/answer", {"text": ans})
        if r.get("done"):
            fb = call(a.server, "GET", f"/interview/{sid}/feedback")
            print("\nfeedback: " + fb["summary"])
            for w in fb["weakAreas"]:
                print("weak area: " + w)
            print(f"transcriptRef: {fb['transcriptRef']}")
            return
        q = r["nextQuestion"]

def main(argv=None):
    ap = argparse.ArgumentParser(prog="slate", description="Slate CLI over the /v1 API")
    ap.add_argument("--server", default=os.getenv("SLATE_API_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--prompt-token", action="store_true", help="Read bearer token with hidden terminal input (never a process argument)")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("parse"); p.add_argument("file"); p.set_defaults(f=cmd_parse)
    p = sub.add_parser("jobs"); p.add_argument("--query", default=""); p.add_argument("--location", default="")
    p.add_argument("--resume-id"); p.set_defaults(f=cmd_jobs)
    p = sub.add_parser("tailor"); p.add_argument("--resume-id", required=True); p.add_argument("--job-id", required=True)
    p.set_defaults(f=cmd_tailor)
    for name in ("approve", "reject"):
        p = sub.add_parser(name); p.add_argument("--draft-id", required=True); p.set_defaults(f=cmd_decide)
    p = sub.add_parser("export"); p.add_argument("--draft-id", required=True); p.set_defaults(f=cmd_export)
    p = sub.add_parser("roadmap"); p.add_argument("--resume-id", required=True)
    p.add_argument("--target-role", required=True); p.set_defaults(f=cmd_roadmap)
    p = sub.add_parser("interview"); p.add_argument("--target-role", required=True); p.set_defaults(f=cmd_interview)
    a = ap.parse_args(argv)
    value = getpass.getpass("Slate bearer token (hidden): ") if a.prompt_token else os.getenv("SLATE_AUTH_TOKEN", "")
    marker = _AUTH_TOKEN.set(value)
    try:
        a.f(a)
    finally:
        _AUTH_TOKEN.reset(marker)

if __name__ == "__main__":
    main()
