# cli

Command-line client for Slate. It calls the same `/v1` API as the website - no Slate logic lives here,
so CLI and website stay in parity by construction. Python 3.10+, stdlib only.

Start the API first (see docs/demo.md), then from the repo root:

    python cli/slate.py --prompt-token parse path/to/resume.txt      # or a .pdf
    python cli/slate.py --prompt-token jobs --resume-id res_001
    python cli/slate.py --prompt-token tailor --resume-id res_001 --job-id job_002
    python cli/slate.py --prompt-token approve --draft-id draft_001  # or: reject
    python cli/slate.py --prompt-token export --draft-id draft_001   # approved drafts only
    python cli/slate.py --prompt-token roadmap --resume-id res_001 --target-role "Data Analyst"
    python cli/slate.py --prompt-token interview --target-role "Data Analyst"

Server default is http://127.0.0.1:8000; override with `--server URL` or `SLATE_API_URL`.
The server requires bearer authentication. `--prompt-token` reads a token with
hidden terminal input; it is not saved. Alternatively set SLATE_AUTH_TOKEN in
the command environment. Never put real tokens in command arguments, source
files, screenshots or chat. Local synthetic test token: dev:cli-fixture@example.com
(works only with the explicit loopback-only dev server, not real Google auth).

For a real Google server you must already have a current ID token issued to
that server's configured client id. This CLI does NOT acquire Google tokens or
refresh them. Missing/expired tokens produce an actionable401 error and no
request is automatically retried. Reauthenticate, then retry deliberately.
There is no new credential bypass or alternate identity scheme.

Credentials are refused over non-local plain HTTP and on redirects. Sample
jobs and rule-based claim checks remain, not live sourcing or fact checking.
