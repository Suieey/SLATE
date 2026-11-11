# MVP Acceptance Criteria (DRAFT)

Status: draft for team review. Defines what "done" means for the 24-hour build.

Depends on the API contracts in `contracts/`. This spec follows those shapes; if a contract changes, update this document with it.

Product surfaces: website, CLI, and mobile frontend are all required. How much depth fits the 24-hour window across all three is unresolved and is the owner's scoping call, not decided in this doc.

MVP feature scope: resume parse, job matches, tailoring, approval gate, roadmap, mock interview. Everything below must be demo-able end to end at the end of the build window.

## A. Resume upload and parse

- Upload a sample resume (PDF) from the web UI.
- Backend returns the parsed fields (name, skills, education, experience) in the contract shape.
- The parsed result is visible in the UI.
- An unsupported or broken file returns the standard error shape, not a crash.

## B. Job matches

- A role/location query returns job cards with title, company, location, matchScore (0-1), deadline, and link.
- Sample listings are acceptable for the MVP.
- Same input gives the same scores (deterministic demo).
- An empty or nonsense query returns an empty list or the standard error, not a crash.

## C. Tailoring

- Choosing a resume plus a job returns tailoredResume and coverNote as a draft.
- The UI labels it clearly as a draft.
- There is no path that exports or sends an unapproved draft.

## D. Approval gate

- Approve and reject actions on a draft are recorded by the backend.
- Editing an approved draft invalidates the approval (new draftId).
- A rejected draft cannot be used.
- Enforcement holds even when the client is bypassed (verify with a direct API call, not just by hiding UI buttons).

## E. Roadmap

- Given a resume and target role, returns ordered milestones with title, why, resources, and etaWeeks.
- Milestones trace back to actual skill gaps in the parsed resume.

## F. Mock interview

- Starting a session returns a sessionId; text-based Q&A works.
- The feedback endpoint returns summary, weakAreas, and transcriptRef.
- A later session can reference earlier feedback, showing memory persists across sessions.

## G. CLI and mobile parity

- The CLI and the mobile frontend are required surfaces, same as the website: each calls the same /v1 endpoints for at least resume parse and job matches.
- Depth beyond that within the build window is part of the unresolved scoping call noted above.

## Demo checkpoint

One continuous flow works without restarts or manual fixes:

upload resume -> see matches -> tailor a resume -> approve it -> generate roadmap -> run a mock interview -> read feedback.

## Open questions

- Which sample resumes and job listings do we preload for the demo?
- How do we reset demo data between runs?
- How much CLI and mobile depth is realistic inside 24 hours alongside the website?
