"""Evidence-linked grounding for LLM drafts. Heuristic, fail-closed on citations.

The idea: the model is asked to tag every content line with the source block(s)
it draws from, and this module then checks those claims mechanically.

What it catches:
- lines with no source citation at all (fail closed)
- citations pointing at source blocks that do not exist
- numbers in the draft that do not appear in the cited sources
- capitalized names (employers, institutes, products) that do not appear in the
  cited sources
- lines whose content words mostly do not appear in the cited sources
  (prefix-matched, so "internship" matches "Intern")

What it still CANNOT catch (be honest about this):
- qualifier inflation on a sourced term ("advanced Excel" when "Excel" is sourced)
- paraphrase-level exaggeration that keeps sourced words
- a line that cites a real block but twists its meaning
- heavy but legitimate rewording can false-flag; that is why the human review
  step is structural and these violations block approval, not generation.
A pass means "every line cites sources and stays within them mechanically",
never "true".
"""
import re

STOP = set("""a an and are as at be but by for from had has have i in into is it its
me my of on or our so than that the their them then there these they this those to
up us very was we were what when which who will with you your also over such each
more most other some any all can could would should not no do does did done""".split())

MIN_OVERLAP = 0.5


def source_blocks(resume_text: str, job: dict) -> dict:
    """Deterministic factual source blocks: S1..Sn are the resume's own lines,
    J is the job posting. The prompt and the checker both use exactly these."""
    blocks = {}
    n = 0
    for line in (resume_text or "").splitlines():
        line = line.strip()
        if line:
            n += 1
            blocks[f"S{n}"] = line
    if job:
        blocks["J"] = "{} at {} ({}). Skills wanted: {}.".format(
            job.get("title", ""), job.get("company", ""), job.get("location", ""),
            ", ".join(job.get("skills", [])))
    return blocks


def build_grounded_prompt(blocks: dict) -> str:
    src = "\n".join(f"[{k}] {v}" for k, v in blocks.items())
    return (
        "You tailor a resume using ONLY the numbered source blocks below. Hard rules:\n"
        "1. Every statement must come from a source block. Never add skills, tools, "
        "employers, projects, metrics, durations, responsibilities or qualities that "
        "are not written in a block. You may reorder and lightly reword only.\n"
        "2. End EVERY content line with the tag of each block it uses, like [S2] or [J]. "
        "A line with no source must not be written at all.\n"
        "3. Do not use Markdown: no #, ##, **, *, no bullets with '-'. Plain lines only.\n"
        "4. Output exactly two sections: a line 'RESUME' then the tailored resume, then "
        "a line 'COVER NOTE' then a 2-4 sentence cover note.\n\n"
        "Example of the format (for made-up blocks):\n"
        "RESUME\n"
        "Intern at ExampleCo, 3 months [S3]\n"
        "Skills: Python, Git [S4]\n"
        "COVER NOTE\n"
        "I am applying for the Data Analyst role at ExampleCo [J]\n"
        "I worked with Python and Git during my internship [S3][S4]\n\n"
        f"SOURCE BLOCKS:\n{src}"
    )


def _content_words(text: str) -> list:
    return [w for w in re.findall(r"[a-z]+", text.lower())
            if len(w) >= 4 and w not in STOP]


def _overlap_ok(line: str, evidence: str) -> bool:
    words = _content_words(line)
    if not words:
        return True  # nothing checkable (short line, headers, name)
    ev = {w[:6] for w in re.findall(r"[a-z]+", evidence.lower())}
    hits = sum(1 for w in words if w[:6] in ev)
    return hits / len(words) >= MIN_OVERLAP


def check_grounding(text: str, blocks: dict, allow_job: bool = True) -> list:
    """Return human-readable violations for draft text against the source blocks.
    allow_job=False is for the resume section: the job posting is not a fact
    about the candidate, so a [J] citation there is always a violation."""
    problems = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.upper() in ("RESUME", "COVER NOTE"):
            continue
        cited = re.findall(r"\[(S\d+|J)\]", line)
        body = re.sub(r"\[(?:S\d+|J)\]", "", line).strip()
        if not body:
            continue
        if not allow_job and "J" in cited:
            problems.append(f"job posting cited as a resume fact: '{body[:60]}'")
            continue
        if not cited:
            problems.append(f"line has no source citation: '{body[:60]}'")
            continue
        bad = [c for c in cited if c not in blocks]
        if bad:
            problems.append(f"line cites unknown source {bad}: '{body[:60]}'")
            continue
        evidence = " ".join(blocks[c] for c in cited)
        ev_low = re.sub(r"\s+", " ", evidence.lower())
        for num in re.findall(r"\d+(?:\.\d+)?", body):
            if not re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d])", ev_low):
                problems.append(f"number '{num}' is not in the cited sources: '{body[:60]}'")
        for name in re.findall(r"(?:^|(?<=[.\s]))([A-Z][A-Za-z0-9&.+]{2,}(?: [A-Z][A-Za-z0-9&.+]+)*)", body):
            if name.lower() in STOP:
                continue
            if name.lower() not in ev_low:
                problems.append(f"name '{name}' is not in the cited sources: '{body[:60]}'")
        if not _overlap_ok(body, evidence):
            problems.append(f"line is not grounded in the cited sources: '{body[:60]}'")
    return problems


def strip_tags(text: str) -> str:
    """Display text without the [S#]/[J] citation markers (any case, comma lists)."""
    return re.sub(r"\s*\[(?:S\d+|J)(?:\s*,\s*(?:S\d+|J))*\]", "", text or "", flags=re.IGNORECASE)
