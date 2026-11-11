"""Synthetic localhost source/target workflow and stale-response browser checks.
No provider, real job feed, external sends, microphone or camera.
"""
import json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
SOURCE='Blake Example\nEducation\nDiploma in Nursing, Community College, 2024\nWork Experience\nStaff nurse, City Hospital\nSkills\nWound care\nMedication administration'
RAW='Staff nurse needed. Wound care and medication administration. <img src=x onerror=alert(1)> This is target text, not applicant evidence.'
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH='1',SLATE_STATE_URL='sqlite:///'+tmp+'/state.db',GEMINI_API_KEY='',LLM_API_KEY='')
 proc=subprocess.Popen([os.environ.get('API_PYTHON',os.sys.executable),'-m','uvicorn','agents.slate_api.app:app','--host','127.0.0.1','--port','8023'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:urllib.request.urlopen('http://127.0.0.1:8023/v1/config',timeout=1);break
   except Exception:time.sleep(.1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),args=['--no-sandbox'])
   errors=[]
   def page(width=1440):
    p=browser.new_page(viewport={'width':width,'height':1000});p.on('dialog',lambda d:d.accept());p.set_default_timeout(5000);p.on('pageerror',lambda e:errors.append(str(e)));p.goto('http://127.0.0.1:8023');p.locator('#devmail').fill('first@example.com');p.locator('#devgo').click();return p
   def source(p):
    p.evaluate('routePage("resume")');p.locator('#resume').fill(SOURCE);p.locator('#parse').click();p.wait_for_function('rid!==null')
   def target(p):
    p.evaluate('routePage("targets")');p.locator('#targettitle').fill('Staff nurse');p.locator('#target-metadata > summary').click();p.locator('#targetorg').fill('Pasted hospital name');p.locator('#targettext').fill(RAW);p.locator('#savetarget').click();p.wait_for_function('tid!==null')
   for width in (1440,390):
    p=page(width);source(p);target(p);old=p.evaluate('tid');p.locator('#drafttarget').click();p.wait_for_function('did!==null');did=p.evaluate('did');assert SOURCE in p.locator('#dres').input_value();assert RAW not in p.locator('#dres').input_value()
    p.locator('#approve').click();p.wait_for_function('document.querySelector("#status").textContent==="approved"')
    with p.expect_download() as dl:p.locator('#export').click()
    text=Path(dl.value.path()).read_text();assert SOURCE in text and RAW in text and 'user-pasted, not verified' in text
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'horizontal overflow';p.screenshot(path=f'/tmp/slate-target-workspace-{width}.png',full_page=True)
    p.evaluate('routePage("targets")');p.locator('#targettext').fill(RAW+'\nRevised shift requirement.');assert p.evaluate('did') is None and p.evaluate('tid') is None
    p.locator('#savetarget').click();p.wait_for_function('tid!==null');assert p.evaluate('tid')!=old
    status=p.evaluate('(async()=>await api("GET","/drafts/'+did+'"))()')['status'];assert status=='draft'
    # Historical draft reopens its bound target, never the newly typed target.
    p.evaluate('routePage("draft")');p.locator('#draft-library > summary').click();p.locator('#refreshdrafts').click();p.wait_for_function('Array.from(document.querySelector("#saveddrafts").options).length>1');p.locator('#saveddrafts').select_option(did);p.locator('#opendraft').click();p.wait_for_function('did==='+json.dumps(did));assert p.locator('#targettext').input_value()==RAW;assert p.evaluate('tid')==old
    p.locator('#dres').fill(p.locator('#dres').input_value().replace('City Hospital','Invented Employer'));p.locator('#edit').click();p.wait_for_function('document.querySelector("#dmsg").textContent.includes("preserved original source block")');assert p.locator('#export').is_disabled()
    p.reload();p.wait_for_function('document.body.textContent.includes("Signed in as")');p.evaluate('routePage("targets")');p.locator('#target-library > summary').click();p.locator('#refreshtargets').click();p.wait_for_function('document.querySelector("#savedtargets").options.length>1');p.close()
   # Late target save/open/generate replies after account switch are discarded.
   for action in ('save','open','draft'):
    for status in (200,401,500):
     p=page();source(p);target(p);target_id=p.evaluate('tid');delayed=[]
     pattern={'save':'**/v1/targets','open':'**/v1/targets/'+target_id,'draft':'**/v1/tailor/target'}[action]
     p.evaluate('routePage("targets")');p.route(pattern,lambda r:r.continue_() if action=='save' and r.request.method=='GET' else delayed.append(r))
     if action=='save':p.locator('#savetarget').click()
     elif action=='open':p.locator('#target-library > summary').click();p.locator('#savedtargets').select_option(target_id);p.locator('#opentarget').click()
     else:p.locator('#drafttarget').click()
     p.wait_for_timeout(50);assert delayed,action
     # Trigger real sign-in recovery rather than a page reload that would abort the request.
     p.route('**/v1/force401',lambda r:r.fulfill(status=401,content_type='application/json',body='{}'));p.evaluate('api("GET","/force401").catch(()=>{})');p.locator('#devmail').wait_for();p.locator('#devmail').fill('second@example.com');p.locator('#devgo').click()
     delayed[0].fulfill(status=status,content_type='application/json',body=json.dumps({'target':{'targetId':'STALE','title':'PRIVATE OLD TARGET'},'targetId':'STALE','draftId':'STALE','tailoredResume':'PRIVATE OLD SOURCE','error':{'message':'PRIVATE OLD TARGET'}}));p.wait_for_timeout(60)
     assert p.evaluate('token()')=='dev:second@example.com' and p.evaluate('tid') is None and p.evaluate('did') is None
     assert 'PRIVATE OLD' not in p.locator('body').inner_text() and p.locator('#targettext').input_value()=='';p.close()
   assert not errors,errors
   browser.close();print('Source-preserving target save/draft/approve/download, revision/reopen/immutable-source/reload at 2 widths and 9 stale account-response cases passed.')
 finally:proc.terminate();proc.wait(timeout=5)
