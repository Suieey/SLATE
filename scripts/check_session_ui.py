"""Manual synthetic browser regression. Requires playwright + installed Chromium.
Run from repo root: python scripts/check_session_ui.py
Uses dev auth on localhost, a temporary SQLite DB, no provider/model calls.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

def make_pdf(lines) -> bytes:
    """Minimal one-page PDF with real extractable text (Helvetica, no compression)."""
    def esc(t): return t.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    ops = ["BT /F1 12 Tf 14 TL 72 720 Td"] + [f"({esc(l)}) Tj T*" for l in lines] + ["ET"]
    stream = "\n".join(ops).encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
            b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream)]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return bytes(out)


ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, SLATE_DEV_AUTH='1', SLATE_STATE_URL='sqlite:///'+tmp+'/state.db')
    proc = subprocess.Popen([os.environ.get("API_PYTHON", os.sys.executable), '-m', 'uvicorn', 'agents.slate_api.app:app', '--host', '127.0.0.1', '--port', '8014'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen('http://127.0.0.1:8014/v1/config')
                break
            except Exception:
                time.sleep(.1)
        # Onboarding gate: this check's synthetic users have already made the one-time
        # setup decision (empty confirmed profile), so sign-in lands on the page under test.
        for _email in ['first@example.com', 'second@example.com', 'context@example.com', 'pdf-context@example.com', 'save-snapshot@example.com', 'source-edit@example.com', 'fixture@example.com']:
            _req=urllib.request.Request("http://127.0.0.1:8014/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
            urllib.request.urlopen(_req,timeout=5).read()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH', '/usr/bin/google-chrome'), args=['--no-sandbox'])
            for path in ('/', '/ai'):
                for result in ('success', 'error', 'unauthorized', 'network'):
                    page = browser.new_page();page.on('dialog',lambda d:d.accept())
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto('http://127.0.0.1:8014'+path)
                    page.locator('#devmail').fill('first@example.com')
                    page.locator('#devgo').click()
                    page.locator('#resume').fill('PRIVATE FIRST ACCOUNT\nSkills: Python, SQL')
                    page.locator('#parse').click()
                    page.wait_for_function('document.querySelector("#parsed").textContent.length>0')
                    delayed = []
                    endpoint = '**/v1/tailor' if path == '/' else '**/v1/tailor/ai'
                    page.route(endpoint, lambda route: delayed.append(route))
                    if path == '/':
                        page.evaluate('routePage("comparisons")');page.locator('[data-j]').first.click()
                    else:
                        page.locator('#gen').click()
                    page.wait_for_timeout(50)
                    assert delayed
                    page.route('**/v1/force401', lambda route: route.fulfill(status=401, content_type='application/json', body='{"error":{"message":"Expired"}}'))
                    expr = "api('GET','/force401').catch(()=>{})" if path == '/' else "api('/force401','GET').catch(()=>{})"
                    page.evaluate(expr)
                    page.locator('#devmail').wait_for()
                    assert page.locator('#resume').input_value() == ''
                    assert page.locator('#parsed').inner_text() == ''
                    assert page.locator('#dres').input_value() == '' if path == '/' else page.locator('#dres').inner_text() == ''
                    page.locator('#devmail').fill('second@example.com')
                    page.locator('#devgo').click()
                    if result == 'network':
                        delayed[0].abort()
                    else:
                        status = {'success': 200, 'error': 500, 'unauthorized': 401}[result]
                        delayed[0].fulfill(status=status, content_type='application/json', body=json.dumps({'draftId':'STALE','tailoredResume':'PRIVATE FIRST ACCOUNT','coverNote':'OLD','skillGaps':[], 'error':{'message':'OLD FAILURE'}}))
                    page.wait_for_timeout(80)
                    assert page.evaluate('token()') == 'dev:second@example.com'
                    assert 'PRIVATE FIRST ACCOUNT' not in page.locator('body').inner_text()
                    assert 'OLD FAILURE' not in page.locator('body').inner_text()
                    assert page.evaluate('did' if path == '/' else 'draftId') is None
                    assert not errors, errors
                    if path == '/' and result == 'success':
                        page.screenshot(path=os.environ.get('SESSION_SCREENSHOT', '/tmp/slate-session-clean.png'), full_page=True)
                    page.close()
            for path in ('/', '/ai'):
                for late_status in (200, 500):
                    page = browser.new_page();page.on('dialog',lambda d:d.accept())
                    page.goto('http://127.0.0.1:8014'+path)
                    page.locator('#devmail').fill('context@example.com')
                    page.locator('#devgo').click()
                    page.locator('#resume').fill('Alex Example\nSkills: Python, SQL, Excel, communication')
                    page.locator('#parse').click()
                    page.wait_for_function('document.querySelector("#parsed").textContent.length>0')
                    delayed = []
                    page.route('**/v1/approvals', lambda route: delayed.append(route))
                    if path == '/ai':
                        counter = [0]
                        def synthetic_ai(route):
                            counter[0] += 1
                            route.fulfill(status=200,content_type='application/json',body=json.dumps({'draftId':'synthetic_'+str(counter[0]),'tailoredResume':'Synthetic draft','coverNote':'Synthetic note','requiresApproval':True,'violations':[]}))
                        page.route('**/v1/tailor/ai', synthetic_ai)
                    def generate():
                        if path == '/':page.evaluate('routePage("comparisons")');page.locator('[data-j]').first.click()
                        else:page.locator('#gen').click()
                    generate()
                    page.wait_for_function('did!==null' if path == '/' else 'draftId!==null')
                    old = page.evaluate('did' if path == '/' else 'draftId')
                    page.locator('#approve').click()
                    page.wait_for_timeout(50)
                    assert delayed
                    generate()
                    page.wait_for_function(('did' if path == '/' else 'draftId')+'!=='+json.dumps(old))
                    delayed[0].fulfill(status=late_status,content_type='application/json',body=json.dumps({'status':'approved','error':{'message':'OLD APPROVAL FAILURE'}}))
                    page.wait_for_timeout(60)
                    assert page.locator('#status').inner_text() == 'draft'
                    assert 'OLD APPROVAL FAILURE' not in page.locator('body').inner_text()
                    assert 'approved in this demo' not in page.locator('body').inner_text()
                    if path == '/':
                        current = page.evaluate('did')
                        assert page.request.get('http://127.0.0.1:8014/v1/drafts/'+current+'/export',headers={'Authorization':'Bearer dev:context@example.com'}).status == 403
                    page.close()
            page = browser.new_page();page.on('dialog',lambda d:d.accept())
            page.goto('http://127.0.0.1:8014/')
            page.locator('#devmail').fill('pdf-context@example.com')
            page.locator('#devgo').click()
            page.locator('#resume').fill('Alex Example\nSkills: Python, communication')
            page.locator('#parse').click()
            page.wait_for_function('document.querySelector("#parsed").textContent.includes("Alex Example")')
            page.locator('#stage-results .stg-back').click()  # review stage -> intake, deliberate path
            page.locator('#uploadzone').click()
            page.wait_for_selector('#stage-consent.on')
            page.locator('#aiack').click()
            page.locator('#pdffile').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':make_pdf(['Blake Example','Skills: SQL, communication'])})
            page.wait_for_function('document.querySelector("#parsed").textContent.includes("Blake Example")')
            assert 'Blake Example' in page.locator('#resume').input_value()
            assert 'Alex Example' not in page.locator('#resume').input_value()
            page.locator('#stage-results .stg-back').click()  # review stage -> intake before re-parsing
            page.locator('#parse').click()
            page.wait_for_function('rid==="res_003"')
            assert 'Blake Example' in page.locator('#parsed').inner_text()
            page.screenshot(path=os.environ.get('CONTEXT_SCREENSHOT','/tmp/slate-context-corrected.png'),full_page=True)
            page.close()
            for path in ('/', '/ai'):
                for pending_parse in (False, True):
                    page = browser.new_page();page.on('dialog',lambda d:d.accept())
                    page.goto('http://127.0.0.1:8014'+path)
                    page.locator('#devmail').fill('source-edit@example.com')
                    page.locator('#devgo').click()
                    page.locator('#resume').fill('Alex Example\nSkills: Python, SQL, communication')
                    held = []
                    if pending_parse:
                        page.route('**/v1/resume', lambda route: held.append(route))
                    page.locator('#parse').click()
                    if pending_parse:
                        page.wait_for_timeout(50)
                        assert held
                    else:
                        page.wait_for_function('rid!==null' if path=='/' else 'resumeId!==null')
                        if path=='/':
                            page.evaluate('routePage("comparisons")');page.locator('[data-j]').first.click()
                            page.wait_for_function('did!==null')
                        else:
                            page.route('**/v1/tailor/ai',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'draftId':'synthetic','tailoredResume':'Alex Example','coverNote':'Synthetic note','requiresApproval':True,'violations':[]})))
                            page.locator('#gen').click()
                            page.wait_for_function('draftId!==null')
                    page.evaluate('routePage("resume")') if path=='/' else None
                    if path=='/':
                        # stage flow: return to intake from whichever stage is showing
                        if page.locator('#stage-results.on').count(): page.locator('#stage-results .stg-back').click()
                        elif page.locator('#stage-processing.on').count(): page.locator('#stage-processing .stg-back').click()
                    page.locator('#resume').fill('Blake Example\nSkills: wound care, patient assessment')
                    if pending_parse:
                        response = held[0].fetch()
                        held[0].fulfill(response=response)
                        page.wait_for_timeout(60)
                    assert page.evaluate('rid===null && did===null' if path=='/' else 'resumeId===null && draftId===null')
                    assert 'Source text changed' in (page.locator('#stage-note').inner_text() if path=='/' else page.locator('#parsed').inner_text())
                    assert 'off' in page.locator('#s2').get_attribute('class').split()
                    assert 'off' in page.locator('#s3').get_attribute('class').split()
                    assert 'Blake Example' in page.locator('#resume').input_value()
                    assert page.locator('#dres').input_value()=='' if path=='/' else page.locator('#dres').inner_text()==''
                    if path=='/':assert page.locator('#skillreview').is_hidden()
                    # A fresh deliberate parse binds the newly visible text.
                    page.unroute('**/v1/resume')
                    page.locator('#parse').click()
                    page.wait_for_function('rid!==null' if path=='/' else 'resumeId!==null')
                    if path=='/':assert 'Blake Example' in page.locator('#parsed').inner_text()
                    page.close()
            print("4 source-input context cases passed")
            # Loading an externally supplied fragment must never create/approve
            # anything, even in an already signed-in browser.
            for fragment in ('demo', 'demo-approve', 'demo-reject'):
                page = browser.new_page();page.on('dialog',lambda d:d.accept())
                page.add_init_script("sessionStorage.setItem('slate_token','dev:fixture@example.com')")
                writes = []
                def record_write(request):
                    if request.method == 'POST': writes.append(request.url)
                page.on('request', record_write)
                page.goto('http://127.0.0.1:8014/ai#'+fragment)
                page.get_by_text('Signed in as fixture@example.com', exact=False).wait_for()  # unified label shows the dev account
                page.wait_for_timeout(200)
                assert not writes, writes
                page.close()
            # Saving must bind the clean baseline to the submitted payload,
            # never text typed while the save response is in flight.
            for changed in (None, 'dres', 'dnote'):
                page = browser.new_page();page.on('dialog',lambda d:d.accept())
                page.goto('http://127.0.0.1:8014/')
                page.locator('#devmail').fill('save-snapshot@example.com')
                page.locator('#devgo').click()
                page.locator('#resume').fill('Alex Example\nSkills: Python, SQL, Excel, communication')
                page.locator('#parse').click()
                page.wait_for_function('document.querySelector("#parsed").textContent.includes("Alex Example")')
                page.evaluate('routePage("comparisons")');page.locator('[data-j]').first.click()
                page.wait_for_function('did!==null')
                submitted_res = page.locator('#dres').input_value()
                submitted_note = page.locator('#dnote').input_value()+' Saved change.'
                page.locator('#dnote').fill(submitted_note)
                held = []
                page.route('**/v1/drafts/*/edit', lambda route: held.append(route))
                page.locator('#edit').click()
                page.wait_for_timeout(50)
                assert len(held) == 1
                if changed:
                    page.locator('#'+changed).fill(page.locator('#'+changed).input_value()+' Later unsaved change.')
                response = held[0].fetch()
                held[0].fulfill(response=response)
                page.wait_for_function('document.querySelector("#dmsg").textContent.includes("Saved as a new draft")')
                assert page.locator('#approve').is_disabled() == bool(changed)
                assert page.locator('#edit').is_disabled() == (changed is None)
                # Server approval/export confirms precisely which payload saved.
                did = page.evaluate('did')
                headers = {'Authorization':'Bearer dev:save-snapshot@example.com'}
                assert page.request.post('http://127.0.0.1:8014/v1/approvals',headers=headers,data={'draftId':did,'decision':'approve'}).status == 200
                exported = page.request.get('http://127.0.0.1:8014/v1/drafts/'+did+'/export',headers=headers).json()
                assert exported['tailoredResume'] == submitted_res
                assert exported['coverNote'] == submitted_note
                page.close()
            browser.close()
        print('8 account-switch + 4 same-source draft + 1 PDF source + 3 URL-fragment + 3 in-flight save snapshot cases passed; server stopped')
    finally:
        proc.terminate()
        proc.wait(timeout=10)
