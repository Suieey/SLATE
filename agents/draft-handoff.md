# Saved draft recovery and approved text handoff

This closes two existing flow gaps. It does not turn the fixture summary into a
full original CV, add real job inventory, send applications or verify claims.

## Additive API

- `GET /v1/drafts`: newest 100 of this authenticated user's drafts, with
  totalCount, draftId, resumeId, jobId, status and aiGenerated. No draft bodies.
- `GET /v1/drafts/{draftId}`: exact stored content/status, bound source snapshot
  and original source text with separate review metadata, plus current rule
  warnings. Reading does not reparse, approve, migrate or mutate anything.
  AI drafts retain source citations and have grounding warnings recomputed.
- `GET /v1/drafts/{draftId}/download`: UTF-8 plain text attachment, only after the
  existing approval/export recheck passes on that exact saved draft. Unapproved
  drafts return 403, rejected/edited old approvals cannot download, rule or AI
  grounding failures block it. All routes retain authentication, per-user state
  isolation and no-store headers. Existing export JSON endpoint is unchanged.

The main page can list/open saved drafts after refresh. It shows the exact bound
source, original upload text, user skill review provenance, saved content and
current approval status. Reopening does not approve. AI drafts can be recovered
here too; citations are retained. Changes still create new unapproved versions.

The downloaded text labels the artifact an application draft, not a full
original CV. It includes draft/source IDs, an original-source SHA-256 fingerprint
(not identity verification), fixture-job notice and skill provenance, followed by
exact approved resume draft and cover note. It does not copy the full private
original source into the artifact. No automatic external sharing occurs.
The browser ignores downloads arriving after account/source/draft context changes
and refuses to download if visible editor text has unsaved changes.

## Verification

`tests/test_draft_recovery.py` covers read copies, read-without-approval, statuses,
rule/AI gates, source/provenance, SQLite restart, per-user API isolation, no-store
headers and newest-100 bounds. `scripts/check_draft_handoff_ui.py` uses synthetic
data and a temporary local SQLite database. It tests approval, reload/reopen,
actual TXT download contents, changed-version approval reset and late old-account
open responses. No provider or model call is needed.

Run from the repo root with the API dependencies and browser installed:

```
python -m pytest tests
API_PYTHON=/path/to/python python scripts/check_draft_handoff_ui.py
```

## Limits

History is still a snapshot store, not a revision/event ledger. List pagination,
retention/account deletion, PDF/DOCX layout fidelity, real job inventory and
provider/Postgres production validation remain outside this change. A download
is a local artifact, not evidence of an application being sent. Approving an old
historical draft is an explicit decision on that old source, not migration to a
newer source. Human approval and deterministic rules are not a fact check.
