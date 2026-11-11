"""Non-history sections must not manufacture structured credentials."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.resume import parse_resume
from slate_core.claims import validate
from slate_core.service import SlateService

@pytest.mark.parametrize('heading',['Skills','Key Skills','Technical Skills','Compétences','कौशल','技能','Projects','Personal Projects','Academic Projects','References','Referees','Interests','Hobbies'])
def test_non_history_degree_and_title_mentions_not_promoted(heading):
    text='Alex Example\n'+heading+'\nMaster data management\nDeveloper at Demo Company (2 months)\nEducation\nB.Tech, Actual College, 2025\nWork Experience\nIntern at ActualCo (3 months)'
    p=parse_resume(text)
    assert p['education']==[{'degree':'B.TECH','institute':'Actual College, 2025','year':2025}]
    assert p['experience']==[{'title':'Intern','org':'ActualCo','months':3}]
    assert any('degree' in e for e in validate(p,text,'Education: Master'))

@pytest.mark.parametrize('line',['Skills: Master data management','Projects: Developer at Demo Company (2 months)','References：Engineer at ActualCo (12 months)'])
def test_inline_non_history_sections_are_excluded(line):
    p=parse_resume('Alex Example\n'+line)
    assert p['education']==[] and p['experience']==[]

@pytest.mark.parametrize('heading',['Formation','Educación','Ausbildung','शिक्षा','教育'])
def test_recognized_multilingual_education_resets_excluded_section(heading):
    p=parse_resume('Alex Example\nSkills\nMaster data management\n'+heading+'\nBachelor, Actual College, 2025')
    assert [e['degree'] for e in p['education']]==['BACHELOR']


def test_draft_and_review_keep_original_without_fake_history():
    text='Alex Example\nSkills\nMaster data management\nPython\nProjects\nDeveloper at Demo Company (2 months)'
    s=SlateService();r=s.upload_resume(text);d=s.tailor(r['resumeId'],'job_001')
    assert 'Education:' not in d['tailoredResume'] and 'Experience:' not in d['tailoredResume']
    assert s.get_resume(r['resumeId'])['sourceText']==text
