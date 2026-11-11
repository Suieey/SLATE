"""Roadmap quality: every skill has real resources with links, gaps cite listing evidence."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.roadmap import build_roadmap  # noqa: E402
from slate_core.sample_data import JOBS, KNOWN_SKILLS, LEARNING  # noqa: E402

PARSED = {"name": "Asha Verma", "skills": ["python", "git"], "education": [], "experience": []}

def test_every_known_skill_has_a_learning_entry_with_a_resource():
    for skill in KNOWN_SKILLS:
        title, resources, weeks = LEARNING.get(skill, (None, [], 0))
        assert title, f"no LEARNING entry for {skill}"
        assert resources, f"no resources for {skill}"
        assert weeks >= 1

def test_resources_carry_verified_links_or_actions():
    for skill, (_, resources, _) in LEARNING.items():
        for r in resources:
            assert " - http" in r or r.startswith("Practice:"), f"{skill}: resource has no link/action: {r}"

def test_roadmap_why_cites_listing_evidence():
    ms = build_roadmap(PARSED, "Data Analyst")
    assert ms, "expected milestones for Data Analyst gaps"
    m = re.search(r"appears in (\d+) of (\d+)", ms[0]["why"])
    assert m and int(m.group(1)) >= 1 and int(m.group(2)) == len([j for j in JOBS if "data analyst" in j["title"].lower()])

def test_roadmap_orders_by_demand_then_alphabetical():
    ms = build_roadmap({"name": "X", "skills": [], "education": [], "experience": []}, "Machine Learning Engineer")
    assert [m["skill"] for m in ms] == ["python", "pytorch", "sql", "statistics"]  # equal demand -> alphabetical
    assert all(m["resources"] and m["etaWeeks"] >= 1 for m in ms)

def test_unknown_role_still_empty():
    assert build_roadmap(PARSED, "Underwater Basket Weaver") == []
