# SLATE

Placement preparation copilot.

## Status

Demo build. Job listings are sample fixtures, not live postings.

## License

MIT. See LICENSE for the copyright notice and license terms.

## Structure

- `agents/` - agent logic: resume, job matching, tailoring, roadmap, mock interview, approval gate
- `backend/` - API over the agents, database, approval enforcement
- `web/` - website, responsive for phone browsers
- `cli/` - terminal interface, calls the same backend API
- `contracts/` - shared request/response formats
- `tests/` - integration and safety checks
- `docs/` - setup guide, architecture, demo flow

## Stack (proposed, not locked)

Python + LangGraph agents, FastAPI backend, PostgreSQL. Next.js + TypeScript web. Python Typer CLI. Confirm before building on these.

## Workflow

Initial project setup lands on `main` once. After that, every change is a branch, then a pull request; the repo owner reviews and merges.

## Local mock interview

The dedicated interview screen is served by the existing FastAPI app at
`/interview`; it uses the same authenticated, per-user resume store as the
classic Slate page. It supports typed answers and browser speech-to-text
(Chrome/Edge support varies by platform and microphone permission). Speech
synthesis reads questions aloud where the browser supports it. Interviews are
continuous: Gemini can ask chained, contextual follow-ups and the session only
ends when the candidate selects **End interview**.

Voice mode records each answer locally in the browser and derives delivery
signals (speaking rate, pauses, filler words, volume variation and an estimated
pitch range). Only bounded numeric metrics are sent to the API with the answer;
raw audio is not uploaded or retained. Gemini can score answer content and
delivery separately. If Gemini is unavailable, delivery feedback is a clearly
labeled rule-based estimate. These are communication-coaching signals, not
personality, emotion, honesty or hiring-suitability assessments.

The optional webcam control provides a live, local self-preview. Video is not
uploaded, recorded or used for automated face/emotion analysis. Camera permission
is independent from microphone permission; the interview can continue without
either device.

The interview coach uses the existing `GeminiLLM` adapter. Set
`GEMINI_API_KEY` in the repository-root `.env` file (copy
`.env.example`); `GEMINI_MODEL` defaults to `gemini-3.8-flash`.
The API key stays on the server. Without a working Gemini key or when a model
call fails, the interview continues with deterministic fallback evaluation.
Feedback labels whether the session used Gemini, fallback, or a mixture.

For a local-only sign-in, `SLATE_DEV_AUTH=1` is also in the example env file.
This must never be enabled on a public deployment. The optional
`SLATE_STATE_URL=sqlite:///slate_state.db` keeps user data across restarts;
without it the memory store is ephemeral.

On Windows PowerShell, from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
# Edit .env and add your Gemini API key.
uvicorn slate_api.app:app --app-dir agents --reload
```

Open `http://127.0.0.1:8000/interview` to go straight to the interview, or
`http://127.0.0.1:8000` for the full Slate page. Keep the terminal running.

## Separate workspace pages

The local web app now has `/resume`, `/targets`, `/draft`, `/comparisons`,
`/roadmap`, `/interview` and `/ai`, with `/` opening the resume page. Resume,
target and draft navigation keeps the current unsaved editor text within the
workspace document. A reload or a move outside that document warns before
losing unsaved changes. Only saved source/target/draft selections are restored
after a reload, and they are re-read from the authenticated API. Selected ids
are kept in this tab's session storage under a token fingerprint, not shared
between accounts. Signing out clears the current tab's selected context.

The sample-comparison and Data Analyst roadmap pages remain demos. The AI
page remains a separate opt-in fixture flow with its own source input. The
interview page has its own role and saved-resume selection. No page navigation
starts a provider call, approves a draft, or sends an application.

Synthetic browser regressions: `scripts/check_pages_ui.py` covers page routes,
saved-context restore, approval/download, unsaved-edit behavior and account
isolation at desktop and mobile widths. Existing browser suites cover source,
target, draft handoff, literal output and interview behavior. These are local
checks, not proof of cloud deployment or actual microphone/provider operation.
