"""Atomic authenticated snapshot writes. SQLite exercised, Postgres not run."""
import json
import multiprocessing as mp
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.service import SlateService
from slate_core.user_store import SqlUserStore, UserSnapshot, WriteConflict
from slate_core.auth import DevAuth
from slate_api.app import create_authenticated_app

A='Alex Example\nSkills: Python, communication'
B='Blake Example\nSkills: SQL, communication'


def worker(url, barrier, queue, text):
    store=SqlUserStore(url)
    svc=SlateService(UserSnapshot(store,'same-user'))
    barrier.wait(timeout=15)
    try:
        svc.upload_resume(text)
        queue.put('saved')
    except WriteConflict:
        queue.put('conflict')


@pytest.mark.parametrize("preexisting",[False,True])
def test_two_process_initial_or_existing_write_cannot_silently_overwrite(tmp_path,preexisting):
    url=f'sqlite:///{tmp_path}/state.db'
    store=SqlUserStore(url)
    if preexisting:SlateService(UserSnapshot(store,'same-user')).upload_resume(A)
    ctx=mp.get_context('spawn');barrier=ctx.Barrier(2);queue=ctx.Queue()
    procs=[ctx.Process(target=worker,args=(url,barrier,queue,t)) for t in (A,B)]
    for p in procs:p.start()
    for p in procs:p.join(20)
    try:
        assert all(not p.is_alive() and p.exitcode==0 for p in procs)
        assert sorted(queue.get(timeout=2) for _ in procs)==['conflict','saved']
        assert len(store.load('same-user')['resumes'])==1+int(preexisting)
        # A fresh deliberate retry sees the winner and allocates a new ID.
        SlateService(UserSnapshot(store,'same-user')).upload_resume('Retry Example\nSkills: Python, SQL')
        assert len(store.load('same-user')['resumes'])==2+int(preexisting)
    finally:
        for p in procs:
            if p.is_alive():p.terminate();p.join(5)


def test_two_loaded_existing_snapshots_detect_conflict(tmp_path):
    store=SqlUserStore(f'sqlite:///{tmp_path}/state.db')
    SlateService(UserSnapshot(store,'a')).upload_resume(A)
    x=SlateService(UserSnapshot(store,'a'));y=SlateService(UserSnapshot(store,'a'))
    x.upload_resume(B)
    with pytest.raises(WriteConflict):y.upload_resume('Stale Example\nSkills: Excel, teamwork')
    assert list(store.load('a')['resumes'])==['res_001','res_002']
    assert store.load('a')['resumes']['res_002']['name']=='Blake Example'


def test_multiple_saves_same_snapshot_and_other_user(tmp_path):
    store=SqlUserStore(f'sqlite:///{tmp_path}/state.db')
    a=SlateService(UserSnapshot(store,'a'));b=SlateService(UserSnapshot(store,'b'))
    a.upload_resume(A);b.upload_resume(B);a.upload_resume(B)
    assert len(store.load('a')['resumes'])==2
    assert len(store.load('b')['resumes'])==1


def test_raw_json_format_preserved_in_compare_token(tmp_path):
    store=SqlUserStore(f'sqlite:///{tmp_path}/state.db')
    SlateService(UserSnapshot(store,'a')).upload_resume(A)
    with store.engine.begin() as c:
        c.execute(store._text('UPDATE slate_user_state SET doc=:d WHERE user_id=:u'),{'u':'a','d':json.dumps(store.load('a'),indent=2)})
    SlateService(UserSnapshot(store,'a')).upload_resume(B)
    assert len(store.load('a')['resumes'])==2


def test_deleted_state_cannot_be_resurrected_by_stale_snapshot(tmp_path):
    store=SqlUserStore(f'sqlite:///{tmp_path}/state.db')
    SlateService(UserSnapshot(store,'a')).upload_resume(A)
    stale=SlateService(UserSnapshot(store,'a'));store.delete('a')
    with pytest.raises(WriteConflict):stale.upload_resume(B)
    assert store.load('a') is None


def test_api_conflict_is_sanitized_and_does_not_retry(tmp_path):
    class Conflicting(SqlUserStore):
        attempts=0
        def save_if_current(self,*args):
            self.attempts+=1
            raise WriteConflict('internal SQL/private content must not leak')
    store=Conflicting(f'sqlite:///{tmp_path}/state.db')
    c=TestClient(create_authenticated_app(DevAuth(),store))
    r=c.post('/v1/resume',headers={'Authorization':'Bearer dev:a@example.com'},json={'text':A})
    assert r.status_code==409
    assert r.json()['error']['code']=='state_conflict'
    assert 'Nothing from this request was saved' in r.json()['error']['message']
    assert 'private content' not in r.text
    assert store.attempts==1
    assert store.load('dev:a@example.com') is None


def test_stale_approval_cannot_override_new_review(tmp_path):
    store=SqlUserStore(f'sqlite:///{tmp_path}/state.db')
    svc=SlateService(UserSnapshot(store,'a'))
    rid=svc.upload_resume('Alex Example\nSkills: Python, SQL, Excel, communication')['resumeId']
    did=svc.tailor(rid,'job_001')['draftId']
    stale=SlateService(UserSnapshot(store,'a'))
    fresh=SlateService(UserSnapshot(store,'a'))
    fresh.review_resume_skills(rid,['Python'],True)
    with pytest.raises(WriteConflict):stale.decide(did,'approve')
    saved=store.load('a')
    assert saved['drafts'][did]['status']=='draft'
    assert len(saved['resumes'])==2
