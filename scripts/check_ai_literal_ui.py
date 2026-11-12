"""Synthetic inert-markup browser regressions. No model/provider calls.
Run from repo root: API_PYTHON=/path/to/python python scripts/check_ai_literal_ui.py
Requires Playwright and Chromium. Uses temporary local SQLite state.
"""
import os,subprocess,time,urllib.request,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as d:
 p=subprocess.Popen([os.environ.get('API_PYTHON',os.sys.executable),'-m','uvicorn','agents.slate_api.app:app','--host','127.0.0.1','--port','8017'],cwd=ROOT,env=dict(os.environ,SLATE_DEV_AUTH='1',SLATE_STATE_URL='sqlite:///'+d+'/state.db'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:8017/v1/config');break
   except Exception:time.sleep(.1)
  # Onboarding gate: this check's synthetic users have already made the one-time
  # setup decision (empty confirmed profile), so sign-in lands on the page under test.
  for _email in ['fixture@example.com']:
      _req=urllib.request.Request("http://127.0.0.1:8017/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
      urllib.request.urlopen(_req,timeout=5).read()
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),args=['--no-sandbox']);page=b.new_page(viewport={'width':1100,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   import json
   page.goto('http://127.0.0.1:8017/ai');page.locator('#devmail').fill('fixture@example.com');page.locator('#devgo').click()
   marker='<span data-untrusted-marker="yes">literal warning</span>'
   page.locator('#resume').fill('Alex Example\nSkills: Python, SQL, communication')
   page.locator('#parse').click();page.wait_for_function('document.querySelector("#job").options.length>0')
   page.route('**/v1/tailor/ai',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'draftId':'fixture','tailoredResume':marker,'coverNote':'Synthetic note','requiresApproval':True,'flaggedClaims':[marker],'violations':[marker]})))
   page.locator('#gen').click();page.wait_for_function('draftId!==null')
   assert page.locator('[data-untrusted-marker]').count()==0
   assert marker in page.locator('#flags').inner_text()
   assert marker in page.locator('#dres').inner_text()
   assert page.locator('#s3').bounding_box()['y']<page.locator('.composer').bounding_box()['y']
   for width in (390,320):
    page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Populated AI canvas overflow'
   page.set_viewport_size({'width':1100,'height':1100})
   # Approval errors quote draft/source data too: display them literally.
   page.route('**/v1/approvals',lambda route:route.fulfill(status=422,content_type='application/json',body=json.dumps({'error':{'message':marker}})))
   page.locator('#approve').click();page.wait_for_function('document.querySelector("#decision").textContent.includes("literal warning")')
   assert marker in page.locator('#decision').inner_text()
   assert page.locator('[data-untrusted-marker]').count()==0
   # Generation failures and resume-parse failures use separate display paths.
   page.unroute('**/v1/tailor/ai')
   page.route('**/v1/tailor/ai',lambda route:route.fulfill(status=422,content_type='application/json',body=json.dumps({'error':{'message':marker}})))
   page.locator('#gen').click();page.wait_for_function('document.querySelector("#genmsg").textContent.includes("literal warning")')
   assert marker in page.locator('#genmsg').inner_text()
   page.route('**/v1/resume',lambda route:route.fulfill(status=422,content_type='application/json',body=json.dumps({'error':{'message':marker}})))
   page.locator('#parse').click();page.wait_for_function('document.querySelector("#parsed").textContent.includes("literal warning")')
   assert marker in page.locator('#parsed').inner_text()
   assert page.locator('[data-untrusted-marker]').count()==0
   page.screenshot(path=os.environ.get('LITERAL_UI_SCREENSHOT','/tmp/slate-ai-literal-ui.png'),full_page=True)
   assert not errors,errors
   b.close()
 finally:p.terminate();p.wait(10)
print('AI warning/flag, approval-error, generation-error and parse-error literal-text checks passed; server stopped')
