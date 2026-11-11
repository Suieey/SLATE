"""Synthetic retail-resume equivalents only; no supplied PDF or personal data."""
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
from slate_core.resume import parse_resume, find_skills, extract_pdf_text
from slate_core.skills import SKILL_ALIASES
from slate_core.sample_data import KNOWN_SKILLS
from slate_core.jobs import search_jobs
from slate_core.claims import validate
from slate_core.auth import DevAuth
from slate_core.user_store import MemUserStore
from slate_api.app import create_authenticated_app
from test_pdf_resume import make_pdf

RETAIL = """Alex Example
Career Objective
Seeking customer service work in a sports retail environment.
(Tip: List Python and SQL only if you have used them. Include qualifications
(bachelor or master) if relevant.)
Key Skills
Customer service demonstrated by serving visitors in a club canteen.
Numeracy skills for cash handling tasks.
Highly developed communications skills.
Strong ability to work as part of a team.
Demonstrated organisation skills through completing assignments on time.
Able to take responsibility and solve problems.
Education
Community Secondary College - Year 11
Work Experience
Customer service volunteer at a club canteen.
Handled cash including operating a cash register.
Leadership Roles
Assistant Coach for junior players.
"""
EXPECTED = {"customer service", "cash handling", "numeracy", "communication",
            "teamwork", "organisation", "responsibility", "problem solving",
            "leadership", "coaching"}


def test_retail_resume_is_not_collapsed_to_one_fixture_skill():
    parsed = parse_resume(RETAIL)
    assert set(parsed["skills"]) == EXPECTED
    assert {e["skill"] for e in parsed["skillEvidence"]} == EXPECTED
    assert all(e["matchedText"] for e in parsed["skillEvidence"])
    assert parsed["parseWarnings"]
    assert parsed["education"] == []  # limited education parser, not invented degrees


def test_parser_vocabulary_is_not_the_job_fixture_vocabulary():
    assert set(KNOWN_SKILLS) <= set(SKILL_ALIASES)
    assert "customer service" in SKILL_ALIASES
    assert "customer service" not in KNOWN_SKILLS


@pytest.mark.parametrize("text, expected", [
    ("CUSTOMER\nSERVICE and cash\u00a0handling", {"customer service", "cash handling"}),
    ("Problem\u2011solving; organizational skills; teamwork", {"problem solving", "organisation", "teamwork"}),
    ("Postgres, React.js, C++ and Amazon Web Services", {"postgresql", "react", "c++", "aws"}),
    ("GitHub, JavaScript and cashiering", {"javascript"}),
    ("Maths, English, Business Management, Sport", set()),
])
def test_aliases_line_wraps_spelling_and_boundaries(text, expected):
    assert set(find_skills(text)) == expected


def test_only_explicit_tip_notes_are_removed_from_parsing():
    parsed = parse_resume("Alex Example\nSkills: Python (beginner), Git\n(Tip: Include SQL.)")
    assert parsed["skills"] == ["git", "python"]
    # Do not swallow real sections after an unmatched parenthesis.
    assert "python" in parse_resume("Alex Example\n(Tip: incomplete\nSkills: Python")["skills"]


def test_draft_cannot_hide_unsupported_claim_inside_a_tip_note():
    parsed = parse_resume("Alex Example\nSkills: Python and Git")
    assert "customer service" in find_skills("(Tip: customer service)")
    assert any("customer service" in v for v in validate(parsed, "Python and Git", "(Tip: customer service)"))


def test_expanded_skills_do_not_fabricate_a_retail_job_or_raise_fixture_score():
    parsed = parse_resume(RETAIL)
    jobs = search_jobs(resume_skills=parsed["skills"])
    assert len(jobs) == 5
    assert jobs[0]["title"] == "Business Analyst"
    assert jobs[0]["matchScore"] == 0.25
    assert jobs[0]["matchedSkills"] == ["communication"]
    assert all("customer service" not in j["title"].lower() for j in jobs)


def test_synthetic_pdf_upload_matches_text_and_keeps_per_user_auth():
    pdf = make_pdf(RETAIL.splitlines())
    assert "Customer service" in extract_pdf_text(pdf)
    client = TestClient(create_authenticated_app(DevAuth(), MemUserStore()))
    files = {"file": ("synthetic-retail.pdf", pdf, "application/pdf")}
    assert client.post("/v1/resume/pdf", files=files).status_code == 401
    response = client.post("/v1/resume/pdf", files=files, headers={"Authorization": "Bearer dev:synthetic-a@example.com"})
    assert response.status_code == 200
    assert set(response.json()["parsed"]["skills"]) == EXPECTED
    rid = response.json()["resumeId"]
    other = client.get("/v1/jobs", params={"resumeId": rid}, headers={"Authorization": "Bearer dev:synthetic-b@example.com"})
    assert other.status_code == 404


def test_ui_labels_scores_as_fixture_overlap_not_resume_quality():
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text()
    assert "% skill overlap" in html
    assert "Retail and customer-service roles are not covered" in html
    assert "not resume-quality or employability scores" in html
    assert "Data Analyst is a fixed demo roadmap" in html
    assert "esc(e.matchedText)" in html
    assert "esc((p.parseWarnings||[])" in html


@pytest.mark.parametrize("heading, items", [
    ("Skills", ["wound care", "medication administration", "patient assessment"]),
    ("Technical Skills", ["Kubernetes", "Terraform", "Rust"]),
    ("Key Skills", ["welding", "CNC machining", "blueprint reading"]),
    ("Professional Skills", ["copyediting", "SEO", "storyboarding"]),
    ("Compétences", ["soins infirmiers", "gestion de stock"]),
    ("Habilidades", ["atención al cliente", "contabilidad"]),
    ("कौशल", ["ग्राहक सेवा", "लेखा"]),
    ("技能", ["客户服务", "库存管理"]),
])
def test_open_vocabulary_explicit_lists_are_not_tech_or_english_only(heading, items):
    text = "Alex Example\n" + heading + ": " + ", ".join(items) + "\nEducation\nExample College"
    parsed = parse_resume(text)
    for item in items:
        assert item.casefold() in parsed["skills"]
    assert "example college" not in parsed["skills"]
    assert any(e["source"] == "explicit_skill_list" for e in parsed["skillEvidence"])


def test_short_skill_bullets_and_section_boundaries():
    parsed = parse_resume("Alex Example\nSkills\n• wound care\n• medication administration\nExperience\nCity Hospital")
    assert parsed["skills"] == ["medication administration", "wound care"]


def test_prose_is_not_relabelled_as_arbitrary_skill():
    parsed = parse_resume("Alex Example\nSkills\nI am seeking a new role\nThis is a long narrative sentence describing past work and not a skill\nEducation\nExample School")
    assert parsed["skills"] == []


def test_unknown_skill_values_are_bounded_and_do_not_execute_markup():
    text = "Alex Example\nSkills: <script>alert(1)</script>, " + ", ".join("custom skill " + str(i) for i in range(100))
    parsed = parse_resume(text)
    assert len(parsed["skills"]) <= 64
    assert not any("script" in x for x in parsed["skills"])



def test_wrapped_skill_prose_does_not_turn_continuations_into_skills():
    parsed = parse_resume("Alex Example\nKey Skills\n• Numeracy skills for cash handling tasks proven by maths\nsubjects.\n• Communication skills shown by positive feedback from\nsupervisors after completing work experience.\n• Ability to work as part of a team since the\nage of eight.\nEducation\nExample College")
    assert set(parsed["skills"]) == {"cash handling", "numeracy", "communication", "teamwork"}


@pytest.mark.parametrize("sentence, skill", [
    ("No experience with SQL", "sql"),
    ("I have never used Python", "python"),
    ("I want to learn PostgreSQL", "postgresql"),
    ("Currently learning customer service", "customer service"),
    ("Seeking customer service work", "customer service"),
    ("Skills to learn:\nPython\nSQL", "python"),
    ("Job requirements:\nExcel and Tableau", "excel"),
    ("Skills: no wound care", "no wound care"),
])
def test_negative_aspirational_and_instructional_mentions_are_not_counted(sentence, skill):
    parsed = parse_resume("Alex Example\n" + sentence)
    assert skill not in parsed["skills"]
    assert skill in [e["skill"] for e in parsed["uncertainSkills"]]
    assert all(e["reason"] for e in parsed["uncertainSkills"])


def test_positive_evidence_elsewhere_can_support_an_aspirational_mention():
    parsed = parse_resume("Alex Example\nSeeking customer service work.\nWork Experience\nCustomer service volunteer at a canteen.")
    assert "customer service" in parsed["skills"]
    assert not any(e["skill"] == "customer service" for e in parsed["uncertainSkills"])


def test_open_vocabulary_candidates_do_not_allow_known_unsupported_claims():
    source = "Alex Example\nSkills: wound care, Rust\nNo experience with SQL"
    parsed = parse_resume(source)
    assert "wound care" in parsed["skills"]
    assert "sql" not in parsed["skills"]
    assert any("sql" in v for v in validate(parsed, source, "Skills: SQL, wound care"))
    assert any("postgresql" in v for v in validate(parsed, source, "I use Postgres"))


def test_instructional_section_stops_at_real_skill_heading():
    parsed = parse_resume("Alex Example\nRequired Skills:\nPython, SQL\nSkills: cash handling\nEducation\nExample School")
    assert parsed["skills"] == ["cash handling"]
    assert {e["skill"] for e in parsed["uncertainSkills"]} == {"python", "sql"}
