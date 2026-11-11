# Shared API Contracts (DRAFT)

Status: draft proposal for team review. Not approved, not implemented. Stack-neutral on purpose - describes data shapes, not frameworks.

The website and the CLI both talk to the backend through these shapes, so we define them once here. Change a contract only through a PR that updates its consumers.

## Conventions

- JSON bodies, camelCase field names.
- All routes are versioned under `/v1`.
- Errors use one shape everywhere:

```json
{ "error": { "code": "resume_not_found", "message": "No resume with that id." } }
```

- Auth is an open question (see below). Until decided, requests are local-only sample data.

## Endpoints

### 1. Resume

`POST /v1/resume` - upload and parse a resume.

Response:

```json
{
  "resumeId": "res_123",
  "parsed": {
    "name": "A Kumar",
    "skills": ["python", "sql"],
    "education": [{ "degree": "B.Tech", "institute": "IIITM", "year": 2027 }],
    "experience": [{ "title": "Intern", "org": "ExampleCo", "months": 3 }]
  }
}
```

### 2. Job matches

`GET /v1/jobs?query=analyst&location=indore`

```json
{
  "jobs": [{
    "jobId": "job_456",
    "title": "Data Analyst",
    "company": "ExampleCo",
    "location": "Indore",
    "matchScore": 0.67,
    "matchedSkills": ["python", "sql"],
    "missingSkills": ["statistics"],
    "reason": "Matches 2 of 3 required skills: python, sql. Missing: statistics.",
    "freshness": "active",
    "deadline": "2026-11-30",
    "url": "https://..."
  }]
}
```

`matchScore` is 0-1, computed by the matching agent. Sample listings are fine until a real jobs source is chosen.

`matchedSkills`, `missingSkills` and `reason` explain the score: which of the listing's required skills the resume has, which it lacks, and one plain sentence combining the two. They are additive - older consumers can ignore them. Without a `resumeId`, `matchedSkills` is empty and `missingSkills` lists every required skill.

`freshness` is the listing's freshness state, one of `active`, `stale`, `no_longer_listed`, `unknown`, `closed` (see slate_core/jobs_curation.py for exact meanings). It is additive and never removes a listing from the response; a date-only, timezone-naive or unparseable deadline never marks a listing `closed`. While the sample data is the source, `active` describes the demo fixture only: the static sample list counts as the demo source's latest refresh, so it is not evidence that a real employer's posting is open. The `location` filter is normalized on both sides - case- and whitespace-insensitive, common city aliases match (`Bangalore` finds `Bengaluru`), and every place named in a multi-city label ("Bengaluru, Mumbai") matches. A label starting with `Remote` keeps its region restriction: "Remote, India" is matched only by that full label, never by a plain `Remote` search.

Skill matching ignores case and surrounding whitespace on both the resume and the listing. A skill a listing repeats counts once, and `matchScore` is computed from the same matched/missing split as `reason`, so they always agree.

### 3. Tailoring

`POST /v1/tailor` with `{ "resumeId": "res_123", "jobId": "job_456" }`

```json
{
  "draftId": "draft_789",
  "tailoredResume": "...",
  "coverNote": "...",
  "status": "draft"
}
```

A tailor result is always a draft. Nothing leaves the system without the approval flow below.

### 4. Roadmap

`POST /v1/roadmap` with `{ "resumeId": "res_123", "targetRole": "Data Analyst" }`

```json
{
  "milestones": [{
    "title": "SQL fundamentals",
    "why": "Gap for target role",
    "resources": ["..."],
    "etaWeeks": 2
  }]
}
```

### 5. Mock interview

`POST /v1/interview/mock` accepts `{ "targetRole": "Data Analyst", "mode": "text", "resumeId": "res_123" }`; `mode` may be `text` or `voice`, and `resumeId` is optional. The authenticated service scopes the resume to the verified user and sends only bounded structured resume facts to the server-side Gemini coach. The response includes `sessionId`, `firstQuestion`, `carriedFromEarlier`, `mode`, `aiPowered`, and `coachMode`.

`POST /v1/interview/{sessionId}/answer` accepts `{ "text": "...", "deliveryMetrics": {...} }`; deliveryMetrics is optional and contains bounded numeric features derived locally from the microphone recording (speaking rate, pause ratio/count, filler count, volume variation, estimated pitch range). Raw audio is not uploaded. The response returns `done:false`, `nextQuestion`, `isFollowUp`, `evaluation`, and `aiPowered`. Evaluation separates content score/feedback from delivery score/feedback when voice metrics are available. Gemini can chain contextual follow-ups; there is no fixed question count or automatic completion.

`POST /v1/interview/{sessionId}/end` explicitly ends the session and returns its final feedback. Answers after this endpoint returns are rejected with409. The UI must not end the session merely because a question bank is exhausted.

`GET /v1/interview/{sessionId}/feedback` returns a summary, average content score, weak areas, strengths, improvements, per-answer reviews, delivery reviews, transcript reference, mode, ended state, and coach mode (`gemini`, `mixed`, or `deterministic_fallback`). Model errors or missing Gemini configuration fall back to deterministic content evaluation and a clearly labeled rule-based delivery estimate. Browser voice mode uses speech recognition, local audio feature extraction and speech synthesis where supported; typed answers remain available. The optional camera is a local live preview only: video is not uploaded, stored, or analyzed for face, emotion, or personality.

Interview memory must persist: a later session can reference earlier feedback through `transcriptRef`.

### 6. Approval gate

`POST /v1/approvals` with `{ "draftId": "draft_789", "decision": "approve" }` (or `"reject"`).

Rules:
- Only an approved draft can be used outside the app.
- If a draft is edited after approval, the old approval is invalid. Editing creates a new `draftId` that needs its own approval.
- Approvals are enforced by the backend, never by hiding buttons in a client.

## Open questions

- Auth: how do web and cli identify the user to the backend? (token header is the likely answer, undecided)
- Pagination for `/v1/jobs` once a real source exists.
- File upload format for resumes (PDF only, or DOCX too).

## Additive resume skill review (authenticated adapter)

`POST /v1/resume/{resumeId}/skills/review` accepts
`{"skills":["python","sql"],"confirm":true}`. `confirm` must be an explicit
boolean true. At most64short skill strings are accepted. The signed-in user's
store owns the parent ID; another user's same-looking ID never selects it.
Response: `{"resumeId":"res_new","parsed":{...},"invalidatedDraftIds":[...]}`.

This is a new immutable resume version. `parsed.skillReview` records parent and
original IDs plus `user_reviewed_not_independently_verified` status. Original
source text remains intact. Existing extracted `skillEvidence.source` stays
`known_phrase`, `explicit_skill_list` or `legacy_parse`; `reviewStatus` becomes
`user_confirmed`. Newly supplied skills use `source:user_statement` and
`reviewStatus:user_provided_not_source_extracted`, and are included in a clearly
labeled user-statement addendum for the new version. Reconfirming does not turn
`user_statement` into document extraction. User authorship is not verification.

Only reviewed skills drive matches/drafts for the new ID. Claim checks still
apply; source corrections do not establish work history/degrees/durations or
silently approve output. Approved drafts bound to the corrected parent or its
ancestors revert to draft with content/source IDs preserved. Rejected drafts and
unrelated resume lineages/users remain untouched. Invalid input/confirmation
makes no changes. A new draft requires explicit version-bound approval.

`parsed.sectionReview` has `education` and `experience`, each with `status`,
`sourceLines` and `note`. `source_section_needs_review` means a supported literal
section heading/excerpt was found, not that qualifications were verified or fully
structured. `not_recognized` does not mean the person has no qualifications or
experience. Previews are bounded and can miss unfamiliar layouts. Existing
structured education/experience arrays retain their limited extraction semantics.

Classic web UI consumes these additive fields and exposes review. CLI and AI-page
review editing are not implemented; existing older consumers may ignore them.

### Saved resume selection (authenticated adapter)

`GET /v1/resume` returns `{totalCount,resumes:[{resumeId,name,reviewStatus,
parentResumeId,skillCount}]}` newest first, at most100summaries. It includes no
full source text. Older IDs remain stored and can still be opened by known ID;
UI pagination is not implemented. `GET /v1/resume/{resumeId}` returns
`{resumeId,parsed,sourceText,sourceTextKind}` only from the verified user's store.
`sourceTextKind:original_uploaded_text_not_user_addendum` makes clear the text
box shows the original upload, even for a reviewed version. `parsed` retains
reviewed skill statements/provenance. Reads never reparse, mutate, or approve
anything. Unknown IDs are404, unauthenticated requests401. No global index or
cross-user ID lookup exists. Classic UI clears all source-bound derived results
when reopening, creating or reviewing a version and ignores late job/draft
responses for a previous source. It exposes newest100versions only.

### Concurrent authenticated SQL state

Any state-writing endpoint can return409`state_conflict` when another request
changed the same user's stored document after this one loaded it. No changes
from the conflicting snapshot are persisted. Reopen latest state and choose
whether to retry; the server does not replay automatically. Upstream model
work already done is not rolled back. This is document-value conflict detection,
not a revision/event ledger. Unauthenticated fixture mode, memory stores and
legacy single-snapshot helpers do not gain multiprocess guarantees.

### PDF source text in upload response

`POST /v1/resume/pdf` also returns `sourceText` and
`sourceTextKind:original_uploaded_text_not_user_addendum`, so the classic editor
can replace a previous typed source with the actual PDF extraction. These are
additive fields, not an edited PDF or independently verified qualifications.
The current draft display is separately bound to draft identity/generation:
late decisions from a prior draft must not label a newer draft approved.

### Header and plain-list review metadata

New parses add `nameEvidence:{status,sourceText}`. A
`header_candidate_not_verified` is a literal header heuristic, not authenticated
identity. `not_recognized` has null sourceText and name Unknown. Additive
`uncertainSkills` entries can use `source:ambiguous_plain_skills_block` for short
unbulleted unknown phrases. They remain outside parsed.skills/matching until an
explicit user review adds them as user_statement. Consumers should not treat
uncertainSkills as extracted competence. Existing saved parses need explicit
reparse, not an automatic migration.

## Private pasted targets (additive; fixture routes unchanged)
- `POST /v1/targets`: `{title, organization?, rawText, sourceUrl?, parentTargetId?}`. `rawText` is preserved as supplied; source URL is display-only, never fetched. Returns immutable `target` with UUID `targetId`, `sourceKind=user_pasted_not_verified`, raw-text SHA-256 and `invalidatedDraftIds`. Revising a target creates a new version and clears approvals for its ancestor target versions. The old snapshots remain unchanged and may be explicitly reviewed again.
- `GET /v1/targets`, `GET /v1/targets/{targetId}`: only the authenticated user's saved targets. These are not feed results or verified employer listings.
- `POST /v1/tailor/target`: `{resumeId,targetId}`. Returns an unapproved `source_preserving_draft_not_rewrite` bound to the exact saved resume version, original-source SHA-256 and target snapshot. Job requirements stay target context, never applicant evidence. Original source is retained literally, including details the parser does not structure. This mode is not a formatted full CV or a generative rewrite.
- Existing edit, approval and download routes apply. Original-source block changes are rejected in this mode; reparse edited original text to make a new resume version. Appended notes and the cover note keep ordinary claim checks. Every successful draft edit creates a new unapproved version; source skill review and target revision clear ancestor approvals. Export rechecks the saved version, hashes and target binding, then labels pasted target context separately from applicant source.
- Known-phrase checks do not verify facts, job validity, all requirements, licenses, employers, or semantic truth. Unknown requirements remain visible in raw target text, with no fit score. No application is sent. AI tailoring remains the existing fixture-only opt-in path.
