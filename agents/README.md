# agents

Agent logic lives here: resume, job matching, tailoring, roadmap, mock interview, approval gate. Proposed: Python + LangGraph. One module per agent; prompts, tools, and workflows kept separate. Structure only - no code yet.

### Qualification section boundaries

Known Skills, Projects, References and Interests/Hobbies headings (including
supported skills-heading translations) do not supply structured degree/work
history or pass degree claims. This includes explicit inline colon headings.
A recognized education/employment heading resumes literal history parsing,
including the headings already supported by the section-review preview.
Original text remains unchanged. This is conservative section filtering, not
semantic credential verification: unfamiliar headings, headerless documents,
role words within actual history and ambiguous degree phrases remain limited.
Saved parses are not rewritten; explicitly reparse the original source.


### Resume extraction limits

Skill extraction is independent of the five sample job requirements. It combines
bounded literal skill/alias matches with concise, explicitly labeled skills lists.
Unknown listed phrases are kept as candidates, not silently discarded because a
job fixture does not use them. `skillEvidence` records the phrase and extraction
path; `parseWarnings` makes review necessary. This is not a semantic proficiency
assessment. Supported section labels include a few non-English variants; this
is not general multilingual resume understanding or translation.

Narrative-only unknown skills, scanned-image PDF OCR, robust multi-column order,
general school/degree normalization and non-tech work-history extraction are not
solved. Explicit parenthesized `(Tip: ...)` template instructions are excluded
from resume parsing, but never from draft claim checking. The claim checker still
cannot validate arbitrary open-vocabulary claims or paraphrases semantically.

Job scores remain exact skill overlap against five analyst/tech sample fixtures,
not resume quality, employability, or a career recommendation. No new retail jobs
were invented to make a score look better. Data Analyst remains a fixed demo
roadmap, not an inferred target role. Existing saved parses are immutable snapshots:
re-upload/reparse to use updated extraction, without silently changing old drafts.

Negative, aspirational and explicitly instructional English contexts are flagged in
`uncertainSkills`, not counted as skill evidence without review. A separate
positive mention can support the same candidate. Context rules are conservative,
not general semantic negation detection in every language. This filter applies
only when parsing a resume; draft claim checks still detect all known mentions.

### Draft save input snapshots

The main review editor records the exact text submitted with a successful save.
Typing while Save is in flight is preserved but remains unsaved/dirty; approve
and export stay disabled until that later text is separately saved. This avoids
showing later unsaved words as if they were the server's saved draft. Existing
source/account/draft response guards still apply. Synthetic browser checks cover
unchanged text and either field changing during a delayed save.


### Review/correct skill candidates

The classic page lets a signed-in user edit a short skill list and explicitly
confirm it. Saving calls `POST /v1/resume/{rid}/skills/review` with `skills` and
strict boolean `confirm:true`. This creates a new resume ID. Source phrase
records remain distinct from user-provided additions; none is independently
verified competence. Additions are explicit self-reported statements in a labeled
source addendum for this new version, never silently attributed to the PDF.
Original text and prior parsed versions remain intact. Existing approved drafts
bound to the corrected parent or its ancestor versions are reset to draft; rejected drafts and
other users/resume IDs are untouched. New drafts require their own approval.
The same claim and AI evidence checks still run. A self-reported skill does not
establish employment, qualifications, durations, metrics or professional ability.

Literal education/work-history section previews now distinguish recognized
source sections needing review from unrecognized sections. Empty structured
arrays do not mean the person has no qualifications or experience. These previews
are bounded excerpts, not complete document reconstruction; general multi-column
and qualification normalization remain unfinished. Stored review snapshots and
metadata survive the existing per-user persistence path, subject to its current
single-process and privacy limitations. No public sharing is performed.

### Reopen saved versions

Classic UI can load the signed-in user's newest100resume summaries and reopen
a selected immutable version after reload or restart. Per-user DB state must be
configured for restart durability; in-memory mode remains ephemeral. Reopening
shows original uploaded text separately from reviewed self-reported skill data,
not a fabricated edited PDF. It does not reparse or approve drafts. Source-bound
job/draft/roadmap results are cleared when switching versions, and stale delayed
job/draft responses are discarded. This is not full draft/history/account-data
management or pagination; retention/delete/export policy remains future work.

### AI preview literal warning text

AI/source-linked warnings and API errors are displayed as literal text, not
interpreted HTML. The same escaping applies to draft identifiers and login
messages; job choices use native text options. The existing draft Markdown
renderer still escapes source text before adding its own limited tags.
`python scripts/check_ai_literal_ui.py` checks inert markup in warnings/flags,
approval errors, generation errors and parse errors, without provider calls.
This closes these rendering paths, not every possible XSS or browser risk.


### Browser session-state checks

Classic and AI pages clear private source/draft/approval display when sign-in
expires or a new sign-in is accepted. They discard late successes, HTTP errors,
401s and network errors from an earlier token/source epoch. Reauthentication
never automatically replays a mutation. An already-submitted server operation
may still complete for the original account; UI cancellation is not rollback.
This does not add token revocation, server sessions or protect against XSS.

Optional synthetic browser check: install Playwright and Chromium in a local
test environment, then run `python scripts/check_session_ui.py`. Use
`CHROME_PATH` for a different Chromium binary and `API_PYTHON` if the app's
Python environment is different. It starts a temporary dev-auth server and
SQLite DB, tests both pages against eight delayed account-switch cases, and
calls no models/providers. This is not enabled in CI.

### Concurrent snapshot writes

Authenticated SQL-backed requests use atomic document compare-and-set when
saving. If another process changed the same user's snapshot since it was
loaded, the losing request returns409`state_conflict`, without overwriting the
winner. Reopen the latest version before deliberately retrying. Automatic retry
is avoided because a request may already have called a model. A conflict can
therefore consume a model request without saving its output.

This requires no schema migration. The comparison uses the exact stored JSON,
not a reserialized approximation. It is document-value conflict detection,
not an event/revision ledger. SQLite multiprocess insert/update races, stale
approval after review, deletion, and per-user independence have local tests.
Postgres was not run. Whole-document rewriting and database lock timeouts remain
limits; SQL operational failures are not automatically retried. The memory
store is still single-process/ephemeral, and legacy `SqlSnapshot` and direct
unconditional `SqlUserStore.save` are not the authenticated concurrency path.

### PDF route execution

PDF decoding runs in FastAPI's synchronous endpoint worker pool, including the
blocking per-user state lock and bounded file read. The previous async route
could hold that lock while yielding for a spooled-file read: a second request
could then block the event loop waiting for the same lock. A timed subprocess
regression covers two same-user PDF calls and event-loop progress. This does
not sandbox pypdf CPU/memory use or add request-body/page caps by itself; see
separate upload hardening PR29. On combining branches, preserve the synchronous
`file.file.read(5_000_001)` route and PR29's other upload/decoder limits.

### No URL-triggered mutations

The AI page no longer has `#demo`, `#demo-approve` or `#demo-reject`
automation. Opening a URL must not parse private text, call a model, or make a
candidate decision. Use the visible controls deliberately. The optional browser
script checks all three fragments in an already signed-in context and verifies
no POST requests occur. This is not general CSRF/XSS protection or proof that
every decision originated with a human.

### Edited resume source context

Typing in the original resume text detaches the parsed source and all derived
results on both pages. The edited text stays visible, but users must explicitly
parse it before reviewing skills or generating drafts. A late response from a
parse started before the edit cannot restore old source context. Saved server
versions are preserved; this does not cancel an already-submitted request or
remove saved data. Four synthetic browser cases cover each page after a parse
and while a parse is pending, plus deliberate fresh parsing of the new text.


### Same-source draft context

Classic and AI pages bind delayed draft/decision display updates to their draft
identity/generation, not only the source resume. A prior draft's delayed approval
or error cannot paint a newer draft from the same resume. PDF upload now replaces
the source editor with the original extraction rather than leaving unrelated
previously typed text. The optional browser check covers four same-source late
approval/error cases plus PDF -> reparse source consistency. AI draft responses
in these tests are synthetic browser fixtures; no model is called. Server-side
approval/export checks remain authoritative, not the UI badge.

### Qualification context limits

Degree/job-title phrases in negative, aspirational or recognized instructional
lines/sections are not promoted into structured education/work history. Degree
claim checks use the same conservative eligible-source lines, excluding explicit
template tips and review skill addenda. A self-reported skill named Bachelor is
not degree evidence. Original text and literal section previews stay available
for user review. Existing parsed snapshots are not silently migrated; reparse
the original source to apply new extraction rules.

These are English literal/context rules, not semantic qualification verification.
They can omit real history in mixed/negated sentences or unfamiliar sections;
incomplete credentials such as 'pursuing' are not treated as completed degrees.
General structured school/nontechnical work extraction, multilingual negation,
layout recovery and positive completion-status review remain open. No proof of
employment/degree authenticity follows from a positive phrase.

### Upload and local-state safety limits

POST/PUT/PATCH bodies are bounded before FastAPI's JSON/multipart parsing:
2 MB for JSON/other bodies; 5,000,000 bytes plus 64 KiB multipart overhead for
PDF uploads, with a 20-second total body-read deadline. The actual stream is
counted even when Content-Length is missing or dishonest. Oversized bodies
return a standard 413 error, slow bodies408. The PDF file itself is capped at
5,000,000 bytes,20 pages and200,000 extracted characters. Direct text parsing
has the same200,000-character cap. Failures do not create a new resume record.
These envelope limits can reject before authentication, by design; ordinary
allowed uploads still authenticate before PDF decoding/state access.

These are partial resource safeguards, not a PDF sandbox. PDF metadata/page-tree
loading and a single page's decompression/extraction still happen inside pypdf
before extracted-length checks. Hard CPU/memory isolation, connection/rate limits,
reverse-proxy request limits and an isolated parser worker remain future work.
Scanned-image OCR is not implemented. Do not expose local dev auth publicly.

`.local-state/`,SQLite database files and sidecars, and `uploads/` are ignored
by Git. This does not encrypt files, fix OS permissions, remove already tracked
files/history, or provide retention/account deletion/backups. The current branch
was checked for tracked runtime databases/uploads; none were found. No existing
state is deleted or rewritten by the ignore change. Keep local state private;
for an existing shared/tracked database, stop and review an explicit migration or
access change instead of blindly deleting files or rewriting history.

### Header candidates and ambiguous plain skill lists

Explicit document titles (Resume/CV/etc.) and obvious contact lines are skipped
in a bounded header scan. `nameEvidence` records a literal header candidate or
`not_recognized`; this does not verify identity or solve arbitrary names/layouts.
It does not search beyond the first unsupported content/section for a name.

A bounded initial skills block with at least two short unbulleted lines now
appears in `uncertainSkills` with `ambiguous_plain_skills_block` provenance.
These unknown phrases are NOT counted in matches/drafts. PDF extraction can lose
bullets, but short lines can also be prose/unknown sections, so the user must
review/add them intentionally. Added items remain user statements, not extracted
or verified skills. Existing positive known phrases keep their normal literal
candidate behavior. Wrapped continuations after bullet/inline prose are excluded.
Single lines, blank-separated lists and unfamiliar layouts can still be missed.
Previously saved parses are not silently migrated; reparse original source.
