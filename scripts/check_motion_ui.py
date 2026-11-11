"""Synthetic browser checks for route motion, selection geometry and reduced motion.
No real accounts, credentials, resume files or provider/model calls.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, SLATE_DEV_AUTH='1', SLATE_STATE_URL='sqlite:///'+tmp+'/state.db', GEMINI_API_KEY='', LLM_API_KEY='')
    proc = subprocess.Popen([os.environ.get('API_PYTHON', os.sys.executable), '-m', 'uvicorn', 'agents.slate_api.app:app', '--host', '127.0.0.1', '--port', '8026'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen('http://127.0.0.1:8026/v1/config', timeout=1)
                break
            except Exception:
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH', '/usr/bin/google-chrome'), args=['--no-sandbox'])
            for width in (1440, 390, 320):
                page = browser.new_page(viewport={'width':width, 'height':1000})
                page.route('https://fonts.googleapis.com/**', lambda r:r.abort())
                page.route('https://fonts.gstatic.com/**', lambda r:r.abort())
                errors = []
                page.on('pageerror', lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:8026/resume')
                page.locator('.nav.motion-ready').wait_for()
                page.wait_for_timeout(600)
                page.locator('[data-part="targets"]').first.click()
                page.wait_for_timeout(40)
                assert page.evaluate('document.getAnimations().some(a=>a.playState==="running")'), 'No live motion'
                # A rapid second navigation must cancel old animations and settle on the new page.
                page.evaluate('routePage("draft");routePage("roadmap")')
                page.wait_for_timeout(650)
                assert page.url.endswith('/roadmap') and page.locator('#s4').is_visible()
                assert not page.locator('#s3').is_visible()
                assert page.evaluate('''(()=>{const a=document.querySelector('.nlink.active').getBoundingClientRect(),b=document.querySelector('.nav-indicator').getBoundingClientRect();return ['x','y','width','height'].every(k=>Math.abs(a[k]-b[k])<1)})()'''), 'Selection not aligned'
                page.locator('[data-part="resume"]').first.focus()
                assert page.locator('[data-part="resume"]').first.evaluate('e=>e===document.activeElement')
                page.keyboard.press('Enter')
                page.wait_for_timeout(40)
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_timeout(40)
                assert not page.evaluate('document.getAnimations().some(a=>a.playState==="running")'), 'Runtime motion preference ignored'
                for part in ('resume', 'targets', 'draft', 'comparisons', 'roadmap'):
                    page.evaluate('(part)=>routePage(part)', part)
                    assert not page.evaluate('document.getAnimations().some(a=>a.playState==="running")')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (width,part,page.evaluate('Array.from(document.querySelectorAll("body *")).filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.className,e.id,e.getBoundingClientRect().right]).slice(0,12)'))
                for part in ('interview', 'ai'):
                    page.goto('http://127.0.0.1:8026/'+part)
                    page.locator('.nav.motion-ready').wait_for()
                    assert not page.evaluate('document.getAnimations().some(a=>a.playState==="running")')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors, errors
                page.close()
            browser.close()
        print('Live route motion, rapid-navigation cancellation, keyboard selection, indicator geometry, runtime reduced motion and seven-route overflow checks passed at 1440/390/320.')
    finally:
        proc.terminate()
        proc.wait(timeout=5)
