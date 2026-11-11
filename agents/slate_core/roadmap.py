from .sample_data import JOBS, LEARNING

def build_roadmap(parsed: dict, target_role: str) -> list:
    """Milestones for skills the target role wants and the resume lacks, biggest-demand first."""
    role = target_role.lower().strip()
    jobs = [j for j in JOBS if role in j["title"].lower()]
    if not jobs:
        return []
    have = set(parsed["skills"])
    count = {}
    for j in jobs:
        for s in j["skills"]:
            if s not in have:
                count[s] = count.get(s, 0) + 1
    ordered = sorted(count, key=lambda s: (-count[s], s))
    out = []
    for s in ordered:
        title, resources, weeks = LEARNING.get(s, (f"Learn {s}", [], 2))
        out.append({"title": title,
                    "why": f"Gap for target role: '{s}' appears in {count[s]} of {len(jobs)} {target_role} sample listings but not on your resume.",
                    "resources": resources, "etaWeeks": weeks, "skill": s})
    return out
