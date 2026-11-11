"""Tailoring with a claim check: every skill the draft claims must come from the parsed resume."""
from .jobs import skill_breakdown, _norm

def build_draft(parsed: dict, job: dict) -> dict:
    # Same matching as the match explanation (jobs.py): case/whitespace ignored,
    # a repeated required skill counts once, the job's own wording is kept.
    matched, missing = skill_breakdown(parsed["skills"], job["skills"])
    name = parsed["name"]
    resume = [f"{name}", f"Target role: {job['title']} at {job['company']}", "",
              "Relevant skills: " + (", ".join(matched) if matched else "none listed yet")]
    for e in parsed["experience"]:
        resume.append(f"Experience: {e['title']}, {e['org']}")
    for e in parsed["education"]:
        resume.append(f"Education: {e['degree']}" + (f" ({e['year']})" if e["year"] else ""))
    note = (f"Hello {job['company']} team, I am applying for the {job['title']} role. "
            + (f"My background includes {', '.join(matched)}. " if matched else "")
            + "I would be glad to share more about my projects.")
    return {"tailoredResume": "\n".join(resume), "coverNote": note, "claims": matched, "gaps": missing}

def check_claims(parsed: dict, claims: list) -> list:
    """Return claims that are NOT backed by the resume (same normalization as matching)."""
    have = {_norm(s) for s in parsed["skills"]}
    return [c for c in claims if _norm(c) not in have]
