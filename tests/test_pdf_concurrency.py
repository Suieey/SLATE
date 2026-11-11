"""Bounded isolated regression for the PDF route's blocking per-user lock."""
import asyncio
import inspect
import io
import multiprocessing as mp
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from starlette.requests import Request
from slate_core.auth import DevAuth,AuthError
from slate_core.user_store import MemUserStore
from slate_api.app import create_authenticated_app
import slate_api.app as api_module


def pdf_route(app):
    routes=list(app.routes)
    for r in list(routes):
        if hasattr(r,'original_router'):routes.extend(r.original_router.routes)
    return next(r.endpoint for r in routes if getattr(r,'path','')=='/v1/resume/pdf')


def request(auth=True):
    return Request({'type':'http','method':'POST','path':'/v1/resume/pdf','headers':[(b'authorization',b'Bearer dev:fixture@example.com')] if auth else []})


class DelayedUpload:
    def __init__(self):self.file=self
    def read(self,n):
        assert n==5_000_001
        time.sleep(.05)
        return b'synthetic test bytes'


def run_race(queue):
    store=MemUserStore()
    route=pdf_route(create_authenticated_app(DevAuth(),store))
    api_module.extract_pdf_text=lambda data:'Alex Example\nSkills: Python, communication'
    # This extra coroutine reproduces the previous async UploadFile.read path.
    class Upload(DelayedUpload):
        async def read(self,*args):
            await asyncio.sleep(.05)
            return b'synthetic test bytes'
        def __init__(self):self.file=DelayedUpload()
    async def call():
        if inspect.iscoroutinefunction(route):return await route(request(),Upload())
        return await asyncio.to_thread(route,request(),Upload())
    async def all_calls():
        tick=asyncio.create_task(asyncio.sleep(.02))
        results=await asyncio.gather(call(),call())
        assert tick.done()
        queue.put([r['resumeId'] for r in results])
    asyncio.run(all_calls())


def test_simultaneous_pdf_routes_do_not_deadlock_event_loop():
    ctx=mp.get_context('spawn');q=ctx.Queue();p=ctx.Process(target=run_race,args=(q,))
    p.start();p.join(5)
    try:
        assert not p.is_alive(),'PDF requests deadlocked the event loop'
        assert p.exitcode==0
        assert sorted(q.get(timeout=1))==['res_001','res_002']
    finally:
        if p.is_alive():p.terminate();p.join(5)


def test_pdf_is_sync_and_authenticates_before_reading():
    import pytest
    route=pdf_route(create_authenticated_app(DevAuth(),MemUserStore()))
    assert not inspect.iscoroutinefunction(route)
    class Forbidden:
        @property
        def file(self):raise AssertionError('unauthenticated read')
    with pytest.raises(AuthError):route(request(False),Forbidden())


def test_pdf_sized_read_rejects_oversize_before_decode(monkeypatch):
    import pytest
    from slate_core.service import SlateError
    route=pdf_route(create_authenticated_app(DevAuth(),MemUserStore()))
    class Upload:
        file=io.BytesIO(b'x'*5_000_002)
    monkeypatch.setattr(api_module,'extract_pdf_text',lambda data: (_ for _ in ()).throw(AssertionError('decoder called')))
    with pytest.raises(SlateError,match='too large'):route(request(),Upload())
