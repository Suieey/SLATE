"""Page navigation, saved context restore and account isolation. Local synthetic only."""
import os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright,TimeoutError as PlaywrightTimeout
ROOT=Path(__file__).resolve().parents[1]
SOURCE='Blake Example\nEducation\nDiploma in Nursing, Community College, 2024\nWork Experience\nStaff nurse, City Hospital\nSkills\nWound care'
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH='1',SLATE_STATE_URL='sqlite:///'+tmp+'/state.db',GEMINI_API_KEY='',LLM_API_KEY='')
 proc=subprocess.Popen([os.environ.get('API_PYTHON',os.sys.executable),'-m','uvicorn','agents.slate_api.app:app','--host','127.0.0.1','--port','8024'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:urllib.request.urlopen('http://127.0.0.1:8024/v1/config',timeout=1);break
   except Exception:time.sleep(.1)
  # Onboarding gate: this check's synthetic users have already made the one-time
  # setup decision (empty confirmed profile), so sign-in lands on the page under test.
  for _email in ['first@example.com', 'second@example.com']:
      _req=urllib.request.Request("http://127.0.0.1:8024/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
      urllib.request.urlopen(_req,timeout=5).read()
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
   for width in (1440,390):
    page=browser.new_page(viewport={'width':width,'height':1000});page.set_default_timeout(5000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8024/resume');page.locator('#devmail').fill('first@example.com');page.locator('#devgo').click()
    page.wait_for_function('selectionKey!==null');assert page.locator('#s1').is_visible() and not page.locator('#targetWorkspace').is_visible()
    page.locator('#resume').fill(SOURCE);page.locator('#parse').click();page.wait_for_function('rid!==null');resume=page.evaluate('rid');assert 'Blake Example' in page.locator('#context-source').text_content(), (width,page.locator('#context-source').text_content(),page.locator('#parsed').inner_text());assert page.locator('#source-empty').is_hidden()
    page.locator('a[data-part="targets"]').first.click();assert page.url.endswith('/targets') and not page.locator('#s1').is_visible()
    page.locator('#targettitle').fill('Staff nurse');page.locator('#targettext').fill('Wound care required.');page.locator('#savetarget').click();page.wait_for_function('tid!==null');target=page.evaluate('tid');assert page.locator('#context-target').text_content()=='Staff nurse'
    page.reload();page.wait_for_function('rid!==null&&tid!==null');assert page.evaluate('rid')==resume and page.evaluate('tid')==target
    page.locator('#drafttarget').click();page.wait_for_url('**/draft');page.wait_for_function('did!==null');draft=page.evaluate('did');assert page.locator('#context-draft').text_content()==draft;assert SOURCE in page.locator('#dres').input_value()
    page.locator('#approve').click();page.wait_for_function('document.querySelector("#status").textContent==="approved"');page.reload();page.wait_for_function('did!==null');assert page.evaluate('did')==draft and page.locator('#status').inner_text()=='approved'
    with page.expect_download() as dl:page.locator('#export').click()
    assert SOURCE in Path(dl.value.path()).read_text()
    # Switching parts keeps editor text; reload warns rather than losing it silently.
    edited=page.locator('#dnote').input_value()+' Contact me for details.';page.locator('#dnote').fill(edited);assert 'Unsaved edits' in page.locator('#context-draft-note').text_content()
    page.locator('a[data-part="resume"]').first.click();page.locator('a[data-part="draft"]').first.click();assert page.locator('#dnote').input_value()==edited and page.locator('#export').is_disabled()
    dialogs=[]
    def dismiss(dialog):dialogs.append(dialog.type);dialog.dismiss()
    page.on('dialog',dismiss)
    try:page.reload(timeout=1000)
    except PlaywrightTimeout:pass
    assert 'beforeunload' in dialogs and page.locator('#dnote').input_value()==edited
    page.remove_listener('dialog',dismiss);page.on('dialog',lambda d:d.accept());page.reload();page.wait_for_function('did!==null');assert page.locator('#dnote').input_value()!=edited
    # Persisted IDs must not leak to a different signed-in user.
    page.locator('#out').click();page.locator('#devmail').fill('second@example.com');page.locator('#devgo').click();page.wait_for_function('selectionKey!==null');assert page.evaluate('rid===null&&tid===null&&did===null');assert SOURCE not in page.locator('#dres').input_value();assert page.locator('#context-source').text_content()=='No source selected';assert page.locator('#context-target').text_content()=='No target selected';assert page.locator('#context-draft').text_content()=='No saved draft'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'horizontal overflow'
    assert not errors,errors;page.close()
   browser.close();print('Separate part routes, live saved-context restore, exact approval/download, unsaved navigation/reload warning and cross-account isolation passed at 1440/390.')
 finally:proc.terminate();proc.wait(timeout=5)
