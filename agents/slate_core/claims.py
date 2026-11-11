"""Deterministic claim validation for draft text. Fail closed.

What it does check (rule based, not semantic):
- skills: any known skill named in the draft must be on the parsed resume
- numbers: "N years/months" of experience must not exceed the resume's total experience;
  percentages and GPA/CGPA values must appear in the original resume text
- degrees: a degree named in the draft (B.Tech, M.Tech, MBA, PhD, ...) must appear in the resume text
What it does NOT check: paraphrased or implied claims, employers or projects named in free text,
job titles, tone. A draft that passes is "no rule-detectable unsupported claim", not "verified true".
"""
import re
from .resume import find_skills, qualification_lines

DEGREES = ["b.tech", "btech", "m.tech", "mtech", "mba", "ph.d", "phd", "bca", "mca", "b.sc", "m.sc", "bachelor", "master"]

def _norm(s: str) -> str:
    return re.sub(r"[\s]+", " ", s.lower())

def total_months(parsed: dict) -> int:
    return sum(e.get("months") or 0 for e in parsed.get("experience", []))

def validate(parsed: dict, resume_text: str, *texts: str) -> list:
    """Return a list of human-readable violations; empty list means no rule-detectable problem."""
    problems = []
    body = "\n".join(t for t in texts if t)
    low, src = _norm(body), _norm(resume_text)
    for s in find_skills(body):
        if s not in parsed["skills"]:
            problems.append(f"skill '{s}' is not on the resume")
    have_months = total_months(parsed)
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(years?|yrs?|months?)", low):
        months = float(n) * (12 if unit.startswith(("y",)) else 1)
        if months > have_months:
            problems.append(f"experience claim '{n} {unit}' exceeds the resume's {have_months} months")
    for num in re.findall(r"(\d+(?:\.\d+)?)\s*%", low):
        if not re.search(r"(?<![\d.])" + re.escape(num) + r"\s*%", src):
            problems.append(f"percentage '{num}%' is not in the resume")
    for num in re.findall(r"c?gpa[^0-9]{0,12}(\d+(?:\.\d+)?)", low):
        if not re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d])", src):
            problems.append(f"GPA value '{num}' is not in the resume")
    degree_src = _norm("\n".join(qualification_lines(resume_text)))
    for d in DEGREES:
        if re.search(r"(?<![a-z.])" + re.escape(d) + r"(?![a-z])", low) and not re.search(r"(?<![a-z.])" + re.escape(d) + r"(?![a-z])", degree_src):
            problems.append(f"degree '{d}' is not on the resume")
    return problems
