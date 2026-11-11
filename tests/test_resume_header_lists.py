"""Synthetic header/layout coverage without semantic name or skill claims."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.resume import parse_resume
from slate_core.service import SlateService

@pytest.mark.parametrize('header',['RESUME','Résumé','Curriculum Vitae','CV','Bio-data'])
def test_document_title_is_not_candidate_name(header):
    p=parse_resume(header+'\nAlex Example\nSkills: Python, SQL')
    assert p['name']=='Alex Example'
    assert p['nameEvidence']=={'status':'header_candidate_not_verified','sourceText':'Alex Example'}

@pytest.mark.parametrize('name',["Anne-Marie O'Neil",'José Silva','李 明','आरव सिंह','A. Example'])
def test_name_header_supports_literal_non_latin_and_punctuation(name):
    assert parse_resume('CV\nFull name: '+name+'\nSkills: Python')['name']==name


def test_contact_before_name_and_explicit_name_label():
    p=parse_resume('RESUME\nEmail: alex@example.com\n+91 90000 00000\nName: Alex Example\nSkills: Python')
    assert p['name']=='Alex Example'

@pytest.mark.parametrize('body',['Skills\nPython\nSQL','Education\nExample College','Career Objective\nSeeking a new role','42 Example Street\nAlex Example'])
def test_does_not_hunt_beyond_first_content_for_a_person(body):
    p=parse_resume('RESUME\n'+body)
    assert p['name']=='Unknown'
    assert p['nameEvidence']['status']=='not_recognized'

@pytest.mark.parametrize('heading,items',[
 ('Skills',['Wound care','Medication administration','Patient assessment']),
 ('Technical Skills',['Kubernetes','Terraform','Rust']),
 ('Compétences',['soins infirmiers','gestion des stocks']),
 ('कौशल',['ग्राहक सेवा','लेखा']),
 ('技能',['客户服务','库存管理']),
])
def test_plain_list_visible_for_review_but_not_counted(heading,items):
    p=parse_resume('Alex Example\n'+heading+'\n'+'\n'.join(items)+'\nEducation\nExample College')
    assert p['skills']==[]
    candidates={x['skill']:x for x in p['uncertainSkills']}
    assert set(candidates)=={x.casefold() for x in items}
    assert all(e['source']=='ambiguous_plain_skills_block' for e in candidates.values())
    assert all('not counted without review' in e['reason'] for e in candidates.values())


def test_reviewed_plain_item_stays_user_statement_not_extraction():
    s=SlateService();r=s.upload_resume('Alex Example\nSkills\nWound care\nInventory management')
    assert r['parsed']['skills']==[]
    v=s.review_resume_skills(r['resumeId'],['wound care'],True)
    assert v['parsed']['skillEvidence'][0]['source']=='user_statement'
    assert s.get_resume(v['resumeId'])['sourceText']=='Alex Example\nSkills\nWound care\nInventory management'


def test_bullet_prose_continuation_does_not_become_plain_list_candidates():
    p=parse_resume('Alex Example\nSkills\n• Communication skills shown by feedback from\nsupervisors\nteam members\nEducation\nExample College')
    assert not any(e['source']=='ambiguous_plain_skills_block' for e in p['uncertainSkills'])


def test_single_plain_line_and_unknown_colon_heading_not_promoted():
    p=parse_resume('Alex Example\nSkills\nWound care\nAdditional information:\nCity Hospital\nCommunity School')
    assert p['skills']==[] and p['uncertainSkills']==[]


def test_known_positive_skill_remains_counted_alongside_review_candidates():
    p=parse_resume('Alex Example\nSkills\nPython\nWound care\nInventory management')
    assert p['skills']==['python']
    assert {e['skill'] for e in p['uncertainSkills']}=={'wound care','inventory management'}


def test_plain_candidates_bounded():
    p=parse_resume('Alex Example\nSkills\n'+'\n'.join('custom skill '+str(i) for i in range(90)))
    assert len(p['uncertainSkills'])==64


@pytest.mark.parametrize('heading',['Compétences','कौशल','技能','Formation','शिक्षा','教育','Expérience','अनुभव','工作经历'])
def test_supported_non_latin_or_localized_section_is_not_name_after_title(heading):
    p=parse_resume('CV\n'+heading+'\nCommunity support service')
    assert p['name']=='Unknown' and p['nameEvidence']['status']=='not_recognized'
