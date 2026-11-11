"""Authenticated saved snapshot read contracts and source preservation."""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_api.app import create_authenticated_app
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore
from slate_core.service import SlateService

SOURCE='Alex Example\nSkills: Python and Git\nEducation\nExample Community School - Year 11'


def test_saved_versions_survive_restart_and_do_not_leak_between_users(tmp_path):
    url='sqlite:///'+str(tmp_path/'synthetic.sqlite')
    def client():return TestClient(create_authenticated_app(DevAuth(),SqlUserStore(url)))
    a={'Authorization':'Bearer dev:a@example.com'};b={'Authorization':'Bearer dev:b@example.com'}
    c=client();rid=c.post('/v1/resume',json={'text':SOURCE},headers=a).json()['resumeId']
    reviewed=c.post(f'/v1/resume/{rid}/skills/review',json={'skills':['python','sql'],'confirm':True},headers=a).json()['resumeId']
    c=client()
    assert c.get('/v1/resume').status_code==401
    assert c.get(f'/v1/resume/{rid}').status_code==401
    assert c.get('/v1/resume',headers=b).json()=={'totalCount':0,'resumes':[]}
    assert c.get(f'/v1/resume/{rid}',headers=b).status_code==404
    saved=c.get('/v1/resume',headers=a).json()
    assert saved['totalCount']==2
    assert [r['resumeId'] for r in saved['resumes']]==[reviewed,rid]
    # Index never ships full source/evidence; explicit open does.
    assert not any('sourceText' in r or 'parsed' in r for r in saved['resumes'])
    response=c.get(f'/v1/resume/{reviewed}',headers=a)
    assert response.headers['cache-control']=='no-store'
    opened=response.json()
    assert opened['sourceText']==SOURCE
    assert opened['sourceTextKind']=='original_uploaded_text_not_user_addendum'
    assert opened['parsed']['skills']==['python','sql']
    assert next(e for e in opened['parsed']['skillEvidence'] if e['skill']=='sql')['source']=='user_statement'
    assert c.get('/v1/resume/missing',headers=a).status_code==404


def test_list_is_bounded_newest_first_without_deleting_old_versions():
    s=SlateService()
    for _ in range(103):s.upload_resume(SOURCE)
    saved=s.list_resumes()
    assert saved['totalCount']==103 and len(saved['resumes'])==100
    assert saved['resumes'][0]['resumeId']=='res_103'
    assert s.get_resume('res_001')['sourceText']==SOURCE


def test_reading_or_mutating_returned_copy_cannot_rewrite_source_or_approve_draft():
    s=SlateService();rid=s.upload_resume(SOURCE)['resumeId'];d=s.tailor(rid,'job_002')['draftId']
    opened=s.get_resume(rid);opened['parsed']['skills'].append('sql')
    assert 'sql' not in s.get_resume(rid)['parsed']['skills']
    assert s.approvals.get(d)['status']=='draft'


def test_html_escapes_saved_values_and_guards_stale_source_results():
    html=(Path(__file__).resolve().parents[1]/'web'/'index.html').read_text()
    assert 'esc(r.name)' in html and 'esc(r.resumeId)' in html
    assert 'encodeURIComponent(selected)' in html
    assert 'if(generation!==sourceGeneration||requested!==rid)return' in html
    assert 'if(request!==sourceRequest)return' in html
    assert 'original upload, not added skill statements' in html
