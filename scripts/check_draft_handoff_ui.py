"""Synthetic saved draft recovery/download browser test, no provider calls."""
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
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),args=['--no-sandbox']);page=b.new_page(viewport={'width':1100,'height':1100});page.on('dialog',lambda d:d.accept());errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto('http://127.0.0.1:8017/');page.locator('#devmail').fill('fixture@example.com');page.locator('#devgo').click()
   import json
   import json
   page.locator('#resume').fill('Alex Example\nSkills: Python, SQL, Excel, communication')
   page.locator('#parse').click();page.wait_for_function('document.querySelector("#parsed").textContent.includes("Alex Example")')
   page.evaluate('routePage("comparisons")');page.get_by_role('button',name='Tailor',exact=True).first.click()
   page.wait_for_function('document.querySelector("#dres").value.length>0')
   old=page.evaluate('did')
   exact_res=page.locator('#dres').input_value();exact_note=page.locator('#dnote').input_value()
   page.locator('#approve').click();page.wait_for_function('document.querySelector("#status").textContent==="approved"')
   page.reload();page.wait_for_function('document.querySelector("#saveddrafts").options.length>1')
   page.locator('#draft-library').evaluate('e=>e.open') or page.locator('#draft-library > summary').click();page.locator('#saveddrafts').select_option(old);page.locator('#opendraft').click()
   page.wait_for_function('did!==null')
   assert page.locator('#status').inner_text()=='approved'
   assert page.locator('#dres').input_value()==exact_res and page.locator('#dnote').input_value()==exact_note
   assert page.locator('#resume').input_value()=='Alex Example\nSkills: Python, SQL, Excel, communication'
   with page.expect_download() as pending:page.locator('#export').click()
   download=pending.value
   text=Path(download.path()).read_text()
   assert exact_res in text and exact_note in text
   assert 'Source version: res_001' in text and 'not a full original CV' in text and 'Original source SHA-256:' in text
   assert download.suggested_filename=='slate-'+old+'.txt'
   page.screenshot(path=os.environ.get('HANDOFF_SCREENSHOT','/tmp/slate-draft-handoff.png'),full_page=True)
   page.locator('#dnote').fill(exact_note+' Edited version.')
   page.locator('#edit').click();page.wait_for_function('did!=='+json.dumps(old))
   current=page.evaluate('did');assert page.locator('#status').inner_text()=='draft'
   assert page.request.get('http://127.0.0.1:8017/v1/drafts/'+old+'/download',headers={'Authorization':'Bearer dev:fixture@example.com'}).status==403
   assert page.request.get('http://127.0.0.1:8017/v1/drafts/'+current+'/download',headers={'Authorization':'Bearer dev:fixture@example.com'}).status==403
   page.reload();page.wait_for_function('document.querySelector("#saveddrafts").options.length>1')
   page.locator('#draft-library').evaluate('e=>e.open') or page.locator('#draft-library > summary').click();page.locator('#saveddrafts').select_option(current);page.locator('#opendraft').click();page.wait_for_function('did!==null')
   assert page.locator('#status').inner_text()=='draft'
   assert page.locator('#dnote').input_value()==exact_note+' Edited version.'
   # A download started before further typing must not hand off a version
   # different from the words now visible in the editor.
   page.locator('#approve').click();page.wait_for_function('document.querySelector("#status").textContent==="approved"')
   pending_download=[];downloads=[];page.on('download',lambda d:downloads.append(d))
   page.route('**/v1/drafts/'+current+'/download',lambda route:pending_download.append(route))
   page.locator('#export').click();page.wait_for_timeout(50);assert pending_download
   page.locator('#dnote').fill(exact_note+' New unsaved words.')
   response=pending_download[0].fetch();pending_download[0].fulfill(response=response)
   page.wait_for_function('document.querySelector("#dmsg").textContent.includes("Unsaved changes")')
   assert not downloads
   page.unroute('**/v1/drafts/'+current+'/download')
   # Late opened draft from the prior account must not populate another login.
   held=[];page.route('**/v1/drafts/'+old,lambda route:held.append(route))
   page.locator('#draft-library').evaluate('e=>e.open') or page.locator('#draft-library > summary').click();page.locator('#saveddrafts').select_option(old);page.locator('#opendraft').click();page.wait_for_timeout(50)
   assert held
   page.evaluate('recoverSignIn()');page.locator('#devmail').fill('other@example.com');page.locator('#devgo').click()
   held[0].fulfill(status=200,content_type='application/json',body=json.dumps({'draftId':old,'private':'OLD PRIVATE'}))
   page.wait_for_timeout(70)
   assert page.evaluate('did===null') and page.locator('#dres').input_value()==''
   assert 'OLD PRIVATE' not in page.locator('body').inner_text()
   assert not errors,errors
   b.close()
 finally:p.terminate();p.wait(10)
print('Exact artifact download, reload/reopen, edited approval reset and account-switch cases passed; server stopped')
