"""User-reviewed skill snapshots. Self-report is not independent verification."""
import copy
import re
from .skills import normalized, skill_evidence


def reviewed_snapshot(parent, selected, confirmed):
    if confirmed is not True:
        raise ValueError("Confirm that these are your skill statements before saving.")
    if not isinstance(selected, list) or len(selected) > 64:
        raise ValueError("Choose at most 64 skills.")
    skills, evidence, seen = [], [], set()
    prior = {e['skill']: e for e in parent.get('skillEvidence', [])}
    for raw in selected:
        if not isinstance(raw, str):
            raise ValueError("Skills must be short text values.")
        value = normalized(raw.strip())
        if not value or len(value) > 70 or len(value.split()) > 5 or any(c in raw for c in '\n\r\x00<>'):
            raise ValueError("Use one short skill phrase per item, without markup or newlines.")
        aliases = skill_evidence(value)
        match = next((e for e in aliases if e['matchedText'] == value), None)
        skill = match['skill'] if match else value
        # Don't accept a known skill buried inside an arbitrary invented label.
        if aliases and not match and skill not in parent.get('skills', []):
            raise ValueError("Use the precise skill name, not a sentence containing a skill.")
        if skill in seen:
            continue
        seen.add(skill); skills.append(skill)
        if skill in parent.get('skills', []):
            record = copy.deepcopy(prior.get(skill, {'skill': skill, 'matchedText': skill, 'source': 'legacy_parse'}))
            record['reviewStatus'] = 'user_confirmed'
        else:
            record = {'skill': skill, 'matchedText': raw.strip(), 'source': 'user_statement',
                      'reviewStatus': 'user_provided_not_source_extracted'}
        evidence.append(record)
    parsed = copy.deepcopy(parent)
    parsed['skills'], parsed['skillEvidence'] = skills, evidence
    parsed['uncertainSkills'] = [e for e in parent.get('uncertainSkills', []) if e['skill'] not in seen]
    return parsed


def section_previews(text):
    """Show bounded literal lines for review, never invent structured credentials."""
    headings = {
        'education': {'education', 'qualifications', 'academic background', 'formation', 'educación', 'ausbildung', 'शिक्षा', '教育'},
        'experience': {'experience', 'work experience', 'employment', 'employment history', 'professional experience', 'expérience', 'experiencia', 'berufserfahrung', 'अनुभव', '工作经历'},
    }
    stops = set().union(*headings.values()) | {'skills', 'key skills', 'technical skills', 'projects', 'referees', 'references', 'leadership roles', 'interests', 'interests/hobbies', 'availability'}
    result = {key: {'status': 'not_recognized', 'sourceLines': [],
                    'note': 'No supported section heading recognized. This does not mean no qualifications or experience.'} for key in headings}
    active = None
    for line in text.splitlines():
        line = line.strip()
        label = line.casefold().rstrip(':：')
        found = next((key for key, names in headings.items() if label in names), None)
        if found:
            active = found
            result[found]['status'] = 'source_section_needs_review'
            result[found]['note'] = 'Literal source excerpt, not verified or fully structured. Review the original document.'
            continue
        if label in stops:
            active = None
        elif active and line and len(result[active]['sourceLines']) < 12:
            result[active]['sourceLines'].append(line[:240])
    return result
