"""Synthetic browser checks for process motion: real-wait scan lines, result
reveals, staggers, status settle, theme cross-fade and reduced-motion stillness.
No real accounts, credentials, resume files or provider/model calls; the one AI
route used here is intercepted and answered with synthetic JSON inside the check.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
RESUME = "Jordan Sample\njordan@example.com\nSkills: Python, SQL, communication\nExperience: Built data pipelines at Example Corp for 3 years."
running = 'document.getAnimations().some(a=>a.playState==="running")'

with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, SLATE_DEV_AUTH='1', SLATE_STATE_URL='sqlite:///'+tmp+'/state.db', GEMINI_API_KEY='', LLM_API_KEY='')
    proc = subprocess.Popen([os.environ.get('API_PYTHON', os.sys.executable), '-m', 'uvicorn', 'agents.slate_api.app:app', '--host', '127.0.0.1', '--port', '8029'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen('http://127.0.0.1:8029/v1/config', timeout=1)
                break
            except Exception:
                time.sleep(.1)
        # Onboarding gate: this check's synthetic users have already made the one-time
        # setup decision (empty confirmed profile), so sign-in lands on the page under test.
        for _email in ['motion@example.com', 'njordan@example.com']:
            _req=urllib.request.Request("http://127.0.0.1:8029/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
            urllib.request.urlopen(_req,timeout=5).read()
        assert urllib.request.urlopen('http://127.0.0.1:8029/motion.js', timeout=2).status == 200
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH', '/usr/bin/google-chrome'), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.route('https://fonts.googleapis.com/**', lambda r: r.abort())
            page.route('https://fonts.gstatic.com/**', lambda r: r.abort())
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))

            # Slow the real local parse so the real-wait scan line is observable.
            def slow_parse(route):
                time.sleep(1.2)
                route.fallback()
            page.route('**/v1/resume', slow_parse, times=1)

            page.goto('http://127.0.0.1:8029/resume')
            page.locator('.nav.motion-ready').wait_for()
            page.fill('#devmail', 'motion@example.com')
            page.click('#devgo')
            page.fill('#resume', RESUME)
            page.click('#parse')
            page.wait_for_selector('.motion-scan')  # scan tracks the real wait
            page.wait_for_selector('#parsed .chip')
            page.wait_for_timeout(120)
            assert page.evaluate(running), 'Result reveal and chip stagger should be running'
            page.wait_for_selector('.motion-scan', state='detached')
            page.wait_for_timeout(900)
            assert not page.evaluate(running), 'Reveals must be bounded'

            # Job rows stagger in after the (local) comparisons load.
            page.click('[data-part="comparisons"]')
            page.wait_for_selector('#jobs .job')
            assert page.evaluate(running), 'Job rows should stagger in'
            page.wait_for_timeout(1200)

            # Draft creation reveals the sheets; approval settles the status tag.
            page.locator('#jobs .job button').first.click()
            page.wait_for_selector('#s3:not(.off)')
            assert page.evaluate(running), 'Draft sheets should reveal'
            page.wait_for_timeout(1200)
            page.click('#approve')
            page.wait_for_function('document.getElementById("status").textContent==="approved"')
            assert page.evaluate(running), 'Status tag should settle'
            page.wait_for_timeout(900)

            # Roadmap milestones stagger in.
            page.click('[data-part="roadmap"]')
            page.click('#road')
            page.wait_for_selector('#roadlist li')
            assert page.evaluate(running), 'Roadmap items should stagger'
            page.wait_for_timeout(1500)

            # Theme toggle opens a short cross-fade window.
            page.click('#theme-toggle')
            assert page.locator('html.motion-theme').count() == 1, 'Theme cross-fade window missing'
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.wait_for_timeout(600)
            assert page.locator('html.motion-theme').count() == 0, 'Theme window must close'
            page.click('#theme-toggle')

            # Folded sections rise their content open.
            page.click('[data-part="resume"]')
            page.locator('#source-library > summary').click()
            assert page.evaluate(running), 'Fold content should rise open'
            page.wait_for_timeout(700)

            # Reduced motion: stillness, no scan, no reveals, no theme window.
            page.emulate_media(reduced_motion='reduce')
            page.reload()
            page.locator('.nav.motion-ready').wait_for()
            if page.locator('#devmail').count():
                page.fill('#devmail', 'motion@example.com')
                page.click('#devgo')
            if page.locator('#stage-results.on').count():
                page.click('#stage-results .stg-back')  # restored session opens the review stage; return to intake before editing
            page.fill('#resume', RESUME)
            page.click('#parse')
            page.wait_for_selector('#parsed .chip')
            assert page.locator('.motion-scan').count() == 0, 'No scan line under reduced motion'
            assert not page.evaluate(running), 'Reduced motion must stay still'
            page.click('#theme-toggle')
            assert page.locator('html.motion-theme').count() == 0, 'No theme window under reduced motion'
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.click('#theme-toggle')
            page.emulate_media(reduced_motion='no-preference')

            # Interview: session reveal, live feedback reveal, question change, report stagger.
            page.goto('http://127.0.0.1:8029/interview')
            page.locator('.nav.motion-ready').wait_for()
            if page.locator('#devEmail').count():
                page.fill('#devEmail', 'motion@example.com')
                page.click('#devSignIn')
            page.click('#start')
            page.wait_for_selector('#session:not(.hidden)')
            page.wait_for_timeout(900)
            page.fill('#answer', 'I led a small project: cleaned the data, built the report, and presented it weekly.')
            page.click('#submit')
            page.wait_for_function('document.getElementById("liveReview").textContent.includes("Score")')
            assert page.evaluate(running), 'Interview feedback should reveal'
            page.wait_for_timeout(1000)
            page.click('#endInterview')
            page.wait_for_selector('#results:not(.hidden)')
            assert page.evaluate(running), 'Interview report should stagger in'
            page.wait_for_timeout(1500)

            # AI draft page: provider call is intercepted with synthetic JSON.
            page.goto('http://127.0.0.1:8029/ai')
            page.locator('.nav.motion-ready').wait_for()
            if page.locator('#devmail').count():
                page.fill('#devmail', 'motion@example.com')
                page.click('#devgo')
            page.fill('#resume', RESUME)
            page.click('#parse')
            page.wait_for_selector('#s2:not(.off)')
            page.wait_for_timeout(600)
            def fake_ai(route):
                time.sleep(1.2)
                route.fulfill(status=200, content_type='application/json', body=json.dumps({
                    'draftId': 'SYNTH', 'requiresApproval': True,
                    'tailoredResume': 'Synthetic draft text for the motion check.',
                    'coverNote': 'Synthetic cover note.', 'flaggedClaims': [], 'violations': []}))
            page.route('**/v1/tailor/ai', fake_ai)
            page.route('**/v1/approvals', lambda route: route.fulfill(status=200, content_type='application/json', body=json.dumps({'status': 'approved'})))
            # The scan is asserted synchronously at click time: the mocked route sleeps
            # afterwards, so post-click polling would miss the scan's short life.
            assert page.evaluate("()=>{document.getElementById('gen').click();return !!document.querySelector('.motion-scan')}"), 'Scan line missing during the AI draft wait'
            page.wait_for_selector('#s3:not(.off)')
            assert page.evaluate(running), 'AI draft result should reveal'
            page.wait_for_timeout(1000)
            page.click('#approve')
            page.wait_for_function('document.getElementById("status").textContent==="approved"')
            page.wait_for_timeout(600)

            assert not errors, errors
            browser.close()
        print('Process motion checks passed: real-wait scans, reveals, staggers, status settle, theme cross-fade, fold rise, interview flow, mocked AI route, reduced-motion stillness.')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
