"""Pasted job targets and source-preserving drafts. Additive, pure, deterministic.

A pasted job description is a PRIVATE user-provided target: not a live-verified
listing, not a feed entry, not employer-confirmed. This module never fetches,
never calls a model, and never treats target text as applicant evidence.

Integration surface (agreed with the core integrator):

- snapshot_target(title, organization, raw_text, source_url="") -> dict
    Validates and snapshots a pasted target: title/company/rawText/sourceUrl/
    skills/sourceKind/sourceSha256 (plus additive notes). Raw text is stored
    exactly as supplied, hashed (SHA-256), provenance user_pasted_not_verified.
    Strict ValueError validation. The integrator assigns the per-user target
    id and persists; nothing here invents ids, global stores or coupling.

- source_preserving_content(original_text, reviewed_skill_evidence, target=None) -> dict
    -> tailoredResume/coverNote/outputMode (+ additive binding metadata).
    The tailoredResume BASELINE is the original source byte-exact, followed
    only by a clearly labeled addendum of reviewed user_statement skills
    (self-reported, not document extraction). Target title/company/raw text
    stay OUT of tailoredResume and coverNote; target context is UI display
    metadata only. The cover note is neutral: no new qualification, project
    or employment claims.

Export-gate binding (the integrator owns the gate; this module grants no
bypass): the server recomputes the baseline by calling this same pure builder
with the immutable inputs it bound at draft creation (original_text + the
reviewed user_statement entries). Only a byte-identical recomputed baseline
(baselineSha256 match) is exempt from edited-content claim gates. Any text
appended after the baseline, and the coverNote, go through the normal claim
checks. A changed original means a new resume version, never an in-place edit.
"""
import hashlib
import unicodedata
from urllib.parse import urlsplit

from .skills import skill_evidence

TITLE_MAX = 120
ORG_MAX = 160
RAW_TEXT_MAX = 20_000
SOURCE_URL_MAX = 2_000
MAX_REVIEWED_SKILLS = 64

PROVENANCE_USER_PASTED = "user_pasted_not_verified"
OUTPUT_MODE = "source_preserving_draft_not_rewrite"

ADDENDUM_BEGIN = "-----BEGIN USER-PROVIDED SKILL STATEMENTS (self-reported, not document extraction)-----"
ADDENDUM_END = "-----END USER-PROVIDED SKILL STATEMENTS-----"

_USER_STATEMENT_LABEL = "user statement (self-reported, not extracted from the document, not independently verified)"


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bad_controls(value, allow=()):
    return any(unicodedata.category(ch).startswith("C") and ch not in allow for ch in value)


def _clean_label(value, field, max_len, required):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required.")
    if len(value) > max_len:
        raise ValueError(f"{field} must be at most {max_len} characters.")
    # One-line display labels: no controls, no invisible format characters.
    if _bad_controls(value):
        raise ValueError(f"{field} must not contain control or invisible characters.")
    return value


def _clean_url(source_url):
    if source_url in (None, ""):
        return ""
    if not isinstance(source_url, str):
        raise ValueError("source_url must be text.")
    url = source_url.strip()
    if len(url) > SOURCE_URL_MAX:
        raise ValueError(f"source_url must be at most {SOURCE_URL_MAX} characters.")
    if _bad_controls(url) or any(ch.isspace() for ch in url):
        raise ValueError("source_url must not contain whitespace or control characters.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("source_url must be an absolute http(s) URL.")
    return url


def snapshot_target(title, organization, raw_text, source_url=""):
    """Validate and snapshot a user-pasted job target. Raises ValueError.

    The returned dict is JSON-serializable and additive-safe. `skills` is a
    bounded known-vocabulary mention list only: unknown requirements stay
    visible as raw text and are never declared absent, complete or covered.
    """
    title = _clean_label(title, "title", TITLE_MAX, required=True)
    company = _clean_label(organization, "organization", ORG_MAX, required=False)
    if not isinstance(raw_text, str):
        raise ValueError("raw_text must be text.")
    if not raw_text.strip():
        raise ValueError("raw_text must be nonempty.")
    if len(raw_text) > RAW_TEXT_MAX:
        raise ValueError(f"raw_text must be at most {RAW_TEXT_MAX} characters.")
    if _bad_controls(raw_text, allow="\t\n\r"):
        raise ValueError("raw_text must not contain control characters.")
    url = _clean_url(source_url)
    mentions = skill_evidence(raw_text)[:MAX_REVIEWED_SKILLS]
    return {
        "title": title,
        "company": company,
        "rawText": raw_text,
        "sourceUrl": url,
        "skills": sorted({m["skill"] for m in mentions}),
        "skillMentions": mentions,
        "sourceKind": PROVENANCE_USER_PASTED,
        "sourceSha256": _sha256(raw_text),
        "verifiedStatus": "unknown_not_employer_verified",
        "requirementStatus": "unknown_requirements_kept_as_raw_text_not_assessed",
        "skillsNote": ("Known-vocabulary phrases seen in the pasted text only. "
                       "Not a complete, verified or employer-confirmed requirement list."),
    }


def split_baseline(tailored_resume):
    """Split a baseline into its original text and optional addendum.

    Returns {"originalText": str, "addendum": str | None}, or None when the
    markers are ambiguous (fail closed). The integrator still recomputes and
    compares the whole baseline; this is a display/inspection helper only.
    """
    if not isinstance(tailored_resume, str):
        return None
    marker = "\n\n" + ADDENDUM_BEGIN + "\n"
    if tailored_resume.count(ADDENDUM_BEGIN) > 1 or tailored_resume.count(ADDENDUM_END) > 1:
        return None
    if marker in tailored_resume:
        original, rest = tailored_resume.split(marker, 1)
        if not rest.endswith("\n" + ADDENDUM_END):
            return None
        return {"originalText": original, "addendum": rest[: -len("\n" + ADDENDUM_END)]}
    if ADDENDUM_BEGIN in tailored_resume or ADDENDUM_END in tailored_resume:
        return None
    return {"originalText": tailored_resume, "addendum": None}


def source_preserving_content(original_text, reviewed_skill_evidence, target=None):
    """Build the source-preserving deterministic baseline. Raises ValueError.

    original_text is the user's literal resume source, embedded byte-exact.
    reviewed_skill_evidence is the resume version's reviewed skill evidence
    entries (dicts with a nonempty `skill` string). Only entries whose source
    is user_statement are appended, clearly labeled; document-sourced skills
    are already carried by the byte-exact original and are not duplicated.
    target, when given, is a snapshot_target dict: it is validated for
    integrity (rawText vs sourceSha256) and bound by hash in the metadata,
    but its title/company/raw text are never embedded in the draft body or
    cover note.
    """
    if not isinstance(original_text, str) or not original_text.strip():
        raise ValueError("original_text must be nonempty text.")
    if not isinstance(reviewed_skill_evidence, list) or len(reviewed_skill_evidence) > MAX_REVIEWED_SKILLS:
        raise ValueError(f"reviewed_skill_evidence must be a list of at most {MAX_REVIEWED_SKILLS} entries.")
    user_statements, seen = [], set()
    for entry in reviewed_skill_evidence:
        if not isinstance(entry, dict) or not isinstance(entry.get("skill"), str) or not entry["skill"].strip():
            raise ValueError("Each reviewed skill entry must be a dict with a nonempty skill string.")
        if entry.get("source") == "user_statement" and entry["skill"] not in seen:
            seen.add(entry["skill"])
            user_statements.append(entry)
    if ADDENDUM_BEGIN in original_text or ADDENDUM_END in original_text:
        raise ValueError("original_text must not contain the reserved addendum markers.")

    target_hash = ""
    if target is not None:
        if not isinstance(target, dict):
            raise ValueError("target must be a snapshot_target dict.")
        for key in ("title", "rawText", "sourceSha256"):
            if not isinstance(target.get(key), str) or not target[key]:
                raise ValueError(f"target is missing a nonempty {key}.")
        if _sha256(target["rawText"]) != target["sourceSha256"]:
            raise ValueError("target rawText does not match its sourceSha256; refusing a tampered snapshot.")
        target_hash = target["sourceSha256"]

    original_hash = _sha256(original_text)
    baseline = original_text
    if user_statements:
        lines = [ADDENDUM_BEGIN,
                 "The skills below were typed in by the user as their own statements.",
                 "They are self-reported, not extracted from the document, and not independently verified."]
        for entry in user_statements:
            line = f"- {entry['skill']} - {_USER_STATEMENT_LABEL}"
            evidence = entry.get("matchedText")
            if isinstance(evidence, str) and evidence.strip() and evidence.strip() != entry["skill"]:
                line += f" (as entered: \"{evidence.strip()}\")"
            lines.append(line)
        lines.append(ADDENDUM_END)
        baseline = original_text + "\n\n" + "\n".join(lines)

    note = "Hello, I would like to apply for this role. My resume is included exactly as written."
    if user_statements:
        note += " Skills I added myself are listed separately and labeled as my own statements."

    return {
        "tailoredResume": baseline,
        "coverNote": note,
        "outputMode": OUTPUT_MODE,
        "originalSha256": original_hash,
        "baselineSha256": _sha256(baseline),
        "targetSha256": target_hash,
        "labels": {
            "targetProvenance": PROVENANCE_USER_PASTED,
            "targetRoleInDraft": "ui_display_metadata_only_not_applicant_evidence_not_claim_source",
            "sourceFacts": "not_independently_verified",
            "requirementCoverage": "not_assessed_raw_text_kept_in_target_record_only",
            "presentation": "source_preserving_draft_not_ai_rewrite_not_full_cv_formatting",
        },
        "exportGate": {
            "baselineSha256": _sha256(baseline),
            "originalSha256": original_hash,
            "addendumBegin": ADDENDUM_BEGIN,
            "addendumEnd": ADDENDUM_END,
            "recompute": ("source_preserving_content(original_text, reviewed_skill_evidence)"
                          "['tailoredResume'] with the immutable inputs bound at draft creation"),
            "exemption": "byte-identical recomputed baseline only (baselineSha256 match)",
            "normalGates": "any text appended after the baseline, and the coverNote",
            "note": ("A changed original means a new resume version, never an in-place edit; "
                     "this module grants no export-gate bypass."),
        },
    }
