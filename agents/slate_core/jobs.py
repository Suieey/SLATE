"""Explainable job discovery and ranking.

Scores describe textual skill coverage and search relevance, not employability,
qualification, or probability of getting an interview.
"""
import math
import re
from datetime import datetime, timezone

from .sample_data import JOBS
from .skills import SKILL_ALIASES
from .jobs_curation import (DEADLINE_PASSED, PRESENT, classify_freshness,
                            deadline_passed, location_candidates, normalize_location)

DEMO_SOURCE = "mock"


def _norm(skill):
    return re.sub(r"\s+", " ", str(skill or "").strip().casefold())


_ALIAS_TO_CANONICAL = {
    _norm(alias): canonical
    for canonical, aliases in SKILL_ALIASES.items()
    for alias in (canonical, *aliases)
}


def canonical_skill(skill):
    """Map known spelling/product aliases to one parser vocabulary key."""
    key = _norm(skill)
    return _ALIAS_TO_CANONICAL.get(key, key)


def skill_breakdown(resume_skills, job_skills):
    """Return matched/missing listing terms using known skill aliases."""
    if isinstance(resume_skills, str):
        resume_skills = [resume_skills]
    have = {canonical_skill(s) for s in (resume_skills or []) if canonical_skill(s)}
    matched, missing, seen = [], [], set()
    for skill in job_skills or []:
        key = canonical_skill(skill)
        if not key or key in seen:
            continue
        seen.add(key)
        shown = skill.strip() if isinstance(skill, str) else skill
        (matched if key in have else missing).append(shown)
    return matched, missing


def match_score(resume_skills, job_skills) -> float:
    """Legacy unweighted skill-coverage ratio; not an overall fit score."""
    matched, missing = skill_breakdown(resume_skills, job_skills)
    total = len(matched) + len(missing)
    return round(len(matched) / total, 2) if total else 0.0


def _weighted_skill_score(resume_skills, job_skills, corpus):
    """IDF-weighted coverage: rarer, more discriminative skills count more."""
    if isinstance(resume_skills, str):
        resume_skills = [resume_skills]
    have = {canonical_skill(s) for s in (resume_skills or []) if canonical_skill(s)}
    required = []
    for skill in job_skills or []:
        key = canonical_skill(skill)
        if key and key not in required:
            required.append(key)
    if not required:
        return 0.0
    docs = max(1, len(corpus))
    weights = {}
    for key in required:
        frequency = sum(
            1 for listing in corpus
            if key in {canonical_skill(s) for s in listing.get("skills", [])}
        )
        weights[key] = math.log(1 + docs / (1 + frequency)) + 1.0
    denominator = sum(weights.values())
    return round(sum(weights[k] for k in required if k in have) / denominator, 4)


def _query_relevance(query, title, skills):
    """Small deterministic lexical relevance signal for the user's role query."""
    tokens = [t for t in re.findall(r"[a-z0-9+#.]+", _norm(query)) if len(t) > 1]
    if not tokens:
        return 0.0
    title_text = _norm(title)
    skill_text = " ".join(_norm(s) for s in skills or [])
    title_hits = sum(1 for token in tokens if token in title_text)
    any_hits = sum(1 for token in tokens if token in title_text or token in skill_text)
    return round((0.8 * title_hits + 0.2 * any_hits) / len(tokens), 4)


def match_reason(matched, missing) -> str:
    total = len(matched) + len(missing)
    if total == 0:
        return "This listing names no required skills, so there is nothing to compare."
    noun = "skill" if total == 1 else "skills"
    if not matched:
        return f"Matches none of the {total} required {noun}. Missing: {', '.join(missing)}."
    reason = f"Matches {len(matched)} of {total} required {noun}: {', '.join(matched)}."
    if missing:
        reason += f" Missing: {', '.join(missing)}."
    return reason


def mention_reason(matched, missing) -> str:
    total = len(matched) + len(missing)
    if total == 0:
        return ("No known skills were extracted from this posting's text, "
                "so there is nothing to compare.")
    noun = "skill" if total == 1 else "skills"
    base = (f"Resume mentions {len(matched)} of {total} {noun} literally named "
            f"in the posting text")
    base += f": {', '.join(matched)}." if matched else "."
    return base + " Extracted text mentions, not the employer's required-skill list."


def _as_listing(j) -> dict:
    return {"source": j.get("source", DEMO_SOURCE),
            "sourceId": j.get("sourceId", j["jobId"]),
            "company": j["company"], "title": j["title"], "location": j["location"],
            "deadline": j.get("deadline"), "updatedAt": j.get("updatedAt")}


def freshness(j, now) -> str:
    listing = _as_listing(j)
    if deadline_passed(listing["deadline"], now):
        return classify_freshness(listing, DEADLINE_PASSED, now)
    return classify_freshness(listing, PRESENT, now)


def _role_context(parsed_resume, job):
    """A cautionary keyword-family context, never a relevance score."""
    if not parsed_resume:
        return None
    from .role_fit import INSUFFICIENT, MISMATCH, role_fit_review
    review = role_fit_review(parsed_resume, job.get("title", ""), job.get("skills", []))
    if review["kind"] == MISMATCH:
        return {"kind": "different_keyword_family",
                "note": "The resume and role show different keyword families. This may be an intentional career transition; it is not a rejection or fit verdict."}
    if review["kind"] == INSUFFICIENT:
        return {"kind": "insufficient_evidence",
                "note": "There is not enough keyword evidence to compare role families."}
    return {"kind": "shared_keyword_family",
            "note": "The resume and role share a broad keyword family; this is not proof of qualification."}


def search_jobs(query: str = "", location: str = "", resume_skills=None, now=None,
                listings=None, parsed_resume=None) -> list:
    now = now or datetime.now(timezone.utc)
    corpus = JOBS if listings is None else listings
    q, loc = _norm(query), normalize_location(location)
    out = []
    for job in corpus:
        title = _norm(job.get("title", ""))
        skill_text = " ".join(_norm(s) for s in job.get("skills", []))
        if q and q not in title and q not in skill_text:
            continue
        if loc and loc not in location_candidates(job.get("location", "")):
            continue
        matched, missing = skill_breakdown(resume_skills, job.get("skills", []))
        reason = mention_reason(matched, missing) if job.get("skillsKind") else match_reason(matched, missing)
        coverage = match_score(resume_skills or [], job.get("skills", []))
        weighted = _weighted_skill_score(resume_skills or [], job.get("skills", []), corpus)
        query_score = _query_relevance(q, title, job.get("skills", []))
        # Skill coverage dominates; role-query relevance only breaks close matches.
        ranking = round((0.85 * weighted + 0.15 * query_score) if q else weighted, 4)
        reasons = []
        if matched:
            reasons.append("Recognized skill overlap: " + ", ".join(matched[:5]))
        if missing:
            reasons.append("Not found in the resume's recognized skill list: " + ", ".join(missing[:5]))
        if q and query_score:
            reasons.append("Role-query terms appear in the title or listing skills.")
        if not matched:
            reasons.append("No recognized skill overlap; ranking is based on the role query only.")
        item = {"jobId": job["jobId"], "title": job["title"], "company": job["company"],
                "location": job["location"], "matchScore": coverage,
                "skillCoverageScore": coverage, "weightedSkillScore": weighted,
                "queryRelevance": query_score, "rankingScore": ranking,
                "rankingReasons": reasons,
                "matchedSkills": matched, "missingSkills": missing,
                "reason": reason, "roleContext": _role_context(parsed_resume, job),
                "freshness": freshness(job, now),
                "deadline": job.get("deadline"), "url": job["url"]}
        for key in ("source", "sourceId", "companyBoard", "skillsKind", "fetchedAt", "updatedAt"):
            if job.get(key) is not None:
                item[key] = job[key]
        out.append(item)
    return sorted(out, key=lambda x: (-x["rankingScore"], -x["matchScore"], x["jobId"]))


def get_job(job_id: str):
    return next((j for j in JOBS if j["jobId"] == job_id), None)
