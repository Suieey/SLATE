# Running the MVP demo locally

Needs Python 3.10+. From the repo root:

    python3 -m venv .venv && . .venv/bin/activate
    pip install fastapi uvicorn httpx pytest sqlalchemy python-multipart pypdf
    python -m pytest tests -q                                   # 83 tests at time of writing
    SLATE_DEV_AUTH=1 SLATE_STATE_URL=sqlite:///slate_state.db \
      uvicorn slate_api.app:app --app-dir agents --port 8000

Open http://localhost:8000 (the classic page) or http://localhost:8000/ai (opt-in AI draft page).
Both pages ask you to sign in first; in `SLATE_DEV_AUTH=1` mode enter any email - this is a local
dev identity so the multi-user behavior can be tried without any external account. It is NOT
security: never run a deployed server this way.

Every `/v1` call now needs a bearer token and only ever touches the signed-in user's own data:
resumes, drafts/approvals, interview sessions and roadmap are scoped per user and stored per user,
so two people can use the same server without seeing each other's data, and each person's data
survives a restart (with `SLATE_STATE_URL` set; unset = in-memory and lost on restart).

## Sign-in modes

The served app picks exactly one, from the environment:

| Env | Mode |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Real Google sign-in (verifies Google ID tokens server-side; needs `pip install google-auth`) |
| `SUPABASE_URL` + `SUPABASE_ANON_KEY` | Supabase Auth (managed variant; currently on hold) |
| `SLATE_DEV_AUTH=1` | Local dev identity, no security - local runs/tests only |
| none of the above | API stays up but `/v1` data calls answer 503 `auth_not_configured` |

A real provider always wins over the dev flag, so a misconfigured deploy cannot fall into dev sign-in.

## Which PR provides what

| PR | Provides |
| --- | --- |
| #5 | `agents/slate_core`: logic (stdlib only) and its tests |
| #6 | `agents/slate_api`: FastAPI `/v1` routes |
| #7 | server-side claim validation (rule based) |
| #12-#17 chain | snapshot persistence, PDF upload, demo reset, AI adapter + grounded AI drafts |
| this PR | per-user auth + per-user durable state, login UI on the AI page |
| #4 and #8 | Akarsh's Postgres docker + base server, and the DATABASE_URL leak fix. Separate app in `backend/`, not required for the demo above |

## Persistence and security, honestly

`SLATE_STATE_URL` takes any SQLAlchemy URL. Each user's state is one JSON document in a per-user row
(`slate_user_state`), rewritten after each change. Tested on SQLite (state survives a restart,
including approvals and interview memory). Postgres works through the same SQLAlchemy layer but the
hosted setup has not been run yet. Same-user concurrent requests are serialized by a per-user
process lock; that covers ONE process only - a multi-process deployment would need real row locking
and is not claimed. Input caps: 200 KB resume text, 5 MB PDF, 8 KB tokens.

Google sign-in (when configured) is stateless: the ID token is verified per request (signature,
issuer, audience, expiry via google-auth) and the user id is the token's `sub`. There is no session
store, so sign-out is client-side and a stolen token works until it expires (~1h, Google's clock).
The token lives in sessionStorage: any successful XSS on our pages could read it.

## Limits

Sample jobs only. The claim check is rule based and catches unsupported skills, inflated
years/months, unlisted percentages, GPA values and degrees; it does not catch paraphrase or invented
employers or projects. AI drafts add mechanical grounding checks (citations to resume/job blocks);
still not a fact check. Interview feedback is a word-count rule. Nothing is deployed.
