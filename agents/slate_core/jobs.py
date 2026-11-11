from datetime import datetime, timezone

from .sample_data import JOBS
from .jobs_curation import (DEADLINE_PASSED, PRESENT, classify_freshness,
                            deadline_passed, location_candidates, normalize_location)

# The sample listings stand in for a real source: their static list IS the demo
# source's latest complete refresh, so each one counts as observed present.
DEMO_SOURCE = "mock"

def _norm(skill):
    return str(skill).strip().lower()

def skill_breakdown(resume_skills, job_skills):
    """Split the job's required skills into (matched, missing) against the resume.

    Comparison ignores case and surrounding whitespace on both sides. A skill the
    listing repeats counts once; blanks are ignored. Both lists keep the job's own
    wording and first-seen order. Same input, same output.
    """
    if isinstance(resume_skills, str):
        resume_skills = [resume_skills]
    have = {_norm(s) for s in (resume_skills or []) if _norm(s)}
    matched, missing, seen = [], [], set()
    for s in job_skills or []:
        key = _norm(s)
        if not key or key in seen:
            continue
        seen.add(key)
        (matched if key in have else missing).append(s.strip() if isinstance(s, str) else s)
    return matched, missing

def match_score(resume_skills, job_skills) -> float:
    """Share of the job's distinct required skills the resume has, 0-1, rounded.
    Computed from skill_breakdown so score and explanation always agree."""
    matched, missing = skill_breakdown(resume_skills, job_skills)
    total = len(matched) + len(missing)
    return round(len(matched) / total, 2) if total else 0.0

def match_reason(matched, missing) -> str:
    """One plain sentence explaining the score from the skill breakdown."""
    total = len(matched) + len(missing)
    if total == 0:
        return "This listing names no required skills, so there is nothing to match against."
    noun = "skill" if total == 1 else "skills"
    if not matched:
        return f"Matches none of the {total} required {noun}. Missing: {', '.join(missing)}."
    reason = f"Matches {len(matched)} of {total} required {noun}: {', '.join(matched)}."
    if missing:
        reason += f" Missing: {', '.join(missing)}."
    return reason

def _as_listing(j) -> dict:
    """The curation shape for a stored listing. Identity is (source, sourceId);
    a listing that already carries its own source fields keeps them."""
    return {"source": j.get("source", DEMO_SOURCE),
            "sourceId": j.get("sourceId", j["jobId"]),
            "company": j["company"], "title": j["title"], "location": j["location"],
            "deadline": j.get("deadline"), "updatedAt": j.get("updatedAt")}

def freshness(j, now) -> str:
    """Freshness state for one listing at `now` (timezone-aware).

    A deadline closes a listing only when deadline_passed can prove it: a
    date-only, naive or unparseable deadline is unknown evidence and leaves
    the listing as observed. Listings are never dropped here - the state is
    surfaced for the caller to show."""
    listing = _as_listing(j)
    if deadline_passed(listing["deadline"], now):
        return classify_freshness(listing, DEADLINE_PASSED, now)
    return classify_freshness(listing, PRESENT, now)

def search_jobs(query: str = "", location: str = "", resume_skills=None, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    q, loc = (query or "").lower().strip(), normalize_location(location)
    out = []
    for j in JOBS:
        if q and q not in j["title"].lower() and not any(q in _norm(s) for s in j["skills"]):
            continue
        # Both sides normalized: common city aliases (Bangalore/Bengaluru) match,
        # every place named in a multi-city label counts, and a label starting
        # with Remote keeps its region restriction (see location_candidates).
        if loc and loc not in location_candidates(j["location"]):
            continue
        matched, missing = skill_breakdown(resume_skills, j["skills"])
        out.append({"jobId": j["jobId"], "title": j["title"], "company": j["company"],
                    "location": j["location"], "matchScore": match_score(resume_skills or [], j["skills"]),
                    "matchedSkills": matched, "missingSkills": missing,
                    "reason": match_reason(matched, missing),
                    "freshness": freshness(j, now),
                    "deadline": j["deadline"], "url": j["url"]})
    return sorted(out, key=lambda x: (-x["matchScore"], x["jobId"]))

def get_job(job_id: str):
    return next((j for j in JOBS if j["jobId"] == job_id), None)
