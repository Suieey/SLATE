"""Qualification extraction must not turn denials/goals into history."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.resume import parse_resume
from slate_core.service import SlateService

@pytest.mark.parametrize('line',[
 'No bachelor degree. I plan to pursue Master at Example University in 2027.',
 'I do not have a B.Tech qualification, Example College, 2026',
 'Seeking analyst at ExampleCo',
 'I want to become an engineer at ExampleCo',
 'Never worked as developer at ExampleCo (12 months)',
 'Instruction: Intern at ExampleCo (6 months)',
])
def test_ambiguous_line_is_not_structured_qualification(line):
    p=parse_resume('Alex Example\n'+line+'\nSkills: Python, communication')
    assert p['education']==[] and p['experience']==[]

@pytest.mark.parametrize('heading',['Career Objective','Career Goals','Learning Goals','Job Requirements','Required Qualifications','Example Experience','Instructions','Tips'])
def test_goal_or_instruction_section_does_not_promote_following_line(heading):
    text='Alex Example\n'+heading+'\nAnalyst at FutureCo (12 months)\nBachelor, Future College, 2027\nWork Experience\nIntern at ActualCo (3 months)\nEducation\nB.Tech, Actual College, 2025'
    p=parse_resume(text)
    assert p['experience']==[{'title':'Intern','org':'ActualCo','months':3}]
    assert p['education']==[{'degree':'B.TECH','institute':'Actual College, 2025','year':2025}]


def test_draft_does_not_restate_aspirational_job_or_denied_degree():
    text='Alex Example\nCareer Objective\nSeeking analyst at FutureCo\nNo bachelor degree\nSkills\nPython, SQL, communication'
    s=SlateService();r=s.upload_resume(text);d=s.tailor(r['resumeId'],'job_001')
    assert 'FutureCo' not in d['tailoredResume']
    assert 'Education:' not in d['tailoredResume']
    assert 'Experience:' not in d['tailoredResume']
    # Literal original source is preserved, not erased to hide uncertainty.
    assert s.get_resume(r['resumeId'])['sourceText']==text


def test_real_history_around_separate_uncertain_lines_survives():
    p=parse_resume('Alex Example\nEducation\nB.Tech, Actual College, 2025\nI want to pursue Master in 2027\nWork Experience\nIntern at ActualCo (3 months)\nNever developer at OtherCo\nSkills: Python')
    assert len(p['education'])==1 and p['education'][0]['year']==2025
    assert p['experience']==[{'title':'Intern','org':'ActualCo','months':3}]


@pytest.mark.parametrize('source',[
 'No bachelor degree',
 'I want to pursue Master in 2027',
 'Required Qualifications\nB.Tech',
 'Career Objective\nMBA',
])
def test_degree_word_in_uncertain_source_does_not_allow_claim(source):
    from slate_core.claims import validate
    text='Alex Example\n'+source+'\nSkills: Python, communication'
    p=parse_resume(text)
    degree=next(d for d in ['bachelor','Master','B.Tech','MBA'] if d.casefold() in source.casefold())
    assert any('degree' in v for v in validate(p,text,'Education: '+degree))


def test_positive_degree_mention_remains_eligible_for_literal_claim_check():
    from slate_core.claims import validate
    text='Alex Example\nEducation\nBachelor, Actual College, 2025\nSkills: Python'
    assert not validate(parse_resume(text),text,'Education: Bachelor')


def test_template_tip_and_review_skill_addendum_are_not_degree_evidence():
    from slate_core.claims import validate
    source='Alex Example\nSkills: Python\n(Tip: Include Bachelor if appropriate.)'
    assert any('degree' in x for x in validate(parse_resume(source),source,'Education: Bachelor'))
    s=SlateService();rid=s.upload_resume('Alex Example\nSkills: Python, communication')['resumeId']
    reviewed=s.review_resume_skills(rid,['Python','Bachelor'],True)['resumeId']
    assert any('degree' in x for x in validate(s._resume(reviewed),s._texts[reviewed],'Education: Bachelor'))
