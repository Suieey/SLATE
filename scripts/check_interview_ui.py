"""Synthetic localhost interview checks. No live provider or actual mic/camera.
Requires Playwright and Chromium. API_PYTHON may select the API virtualenv.
"""
import json,os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH='1',SLATE_STATE_URL='sqlite:///'+tmp+'/state.db',GEMINI_API_KEY='',LLM_API_KEY='')
 proc=subprocess.Popen([os.environ.get('API_PYTHON',os.sys.executable),'-m','uvicorn','agents.slate_api.app:app','--host','127.0.0.1','--port','8021'],cwd=ROOT,env=env,stdout=open('/tmp/interview-server.log','w'),stderr=subprocess.STDOUT)
 try:
  for _ in range(100):
   try:urllib.request.urlopen('http://127.0.0.1:8021/v1/config',timeout=1);break
   except Exception:time.sleep(.1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),args=['--no-sandbox'])
   def page():
    p=browser.new_page();p.set_default_timeout(4000);p.on('pageerror',lambda e:errors.append(str(e)));p.goto('http://127.0.0.1:8021/interview');p.locator('#devEmail').fill('first@example.com');p.locator('#devSignIn').click();return p
   errors=[]
   print('typed begin',flush=True)
   p=page();p.locator('#role').fill('Human Resources');p.locator('#start').click();p.locator('#session').wait_for(state='visible');assert 'Fallback' in p.locator('#coachMode').inner_text()
   p.locator('#submit').click();assert 'Enter or dictate' in p.locator('#sessionStatus').inner_text()
   p.locator('#answer').fill('I checked the employee complaint against company policy and documented each step.');p.locator('#submit').click();p.wait_for_function('document.querySelector("#liveReview").textContent.includes("Score:")')
   assert p.locator('#answer').input_value()==''
   # Report failure after a successful end is recoverable, without resubmitting answers.
   p.route('**/v1/interview/*/feedback',lambda r:r.fulfill(status=503,content_type='application/json',body='{"error":{"message":"synthetic report unavailable"}}'))
   p.locator('#endInterview').click();p.wait_for_function('document.querySelector("#sessionStatus").textContent.includes("synthetic report unavailable")')
   assert p.locator('#submit').is_disabled() and p.locator('#endInterview').inner_text()=='Retry report'
   p.unroute('**/v1/interview/*/feedback');p.locator('#endInterview').click();p.locator('#results').wait_for(state='visible');assert 'employee complaint' in p.locator('#details').inner_text()
   p.screenshot(path='/tmp/slate-interview-report.png',full_page=True);p.locator('#again').click();assert p.locator('#question').inner_text()=='' and not p.locator('#submit').is_disabled();p.close()
   # Each data operation ignores late success/error/401 on account switch.
   print('typed complete',flush=True)
   for action in ('start','answer','end','feedback'):
    for status in (200,500,401):
     print(action,status,flush=True);p=page()
     if action!='start':p.locator('#start').click();p.locator('#session').wait_for(state='visible')
     delayed=[];pattern={'start':'**/v1/interview/mock','answer':'**/v1/interview/*/answer','end':'**/v1/interview/*/end','feedback':'**/v1/interview/*/feedback'}[action]
     p.route(pattern,lambda r:delayed.append(r))
     if action=='answer':p.locator('#answer').fill('PRIVATE FIRST ACCOUNT');p.locator('#submit').click()
     elif action=='start':p.locator('#start').click()
     else:p.locator('#endInterview').click()
     p.wait_for_timeout(80);assert delayed,action
     p.locator('#signout').click();p.locator('#devEmail').fill('second@example.com');p.locator('#devSignIn').click()
     delayed[0].fulfill(status=status,content_type='application/json',body=json.dumps({'sessionId':'STALE','firstQuestion':'PRIVATE FIRST ACCOUNT','carriedFromEarlier':[],'summary':'PRIVATE FIRST ACCOUNT','error':{'message':'PRIVATE FIRST ACCOUNT'}}))
     p.wait_for_timeout(60);assert p.evaluate('sid') is None;assert p.evaluate('token()')=='dev:second@example.com';assert 'PRIVATE FIRST ACCOUNT' not in p.locator('body').inner_text();p.close()
   print('stale complete',flush=True)
   # Active 401 recovers sign in. No automatic retry.
   p=page();p.route('**/v1/interview/mock',lambda r:r.fulfill(status=401,content_type='application/json',body='{}'));p.locator('#start').click();p.locator('#devEmail').wait_for();assert 'expired' in p.locator('#authMessage').inner_text();p.close()
   print('401 complete',flush=True)
   # Explicit typed fallback if mic denied / recognition unsupported; camera denied.
   p=page();p.add_init_script('Object.defineProperty(navigator.mediaDevices,"getUserMedia",{value:async()=>{throw new Error("denied")}});window.SpeechRecognition=undefined;window.webkitSpeechRecognition=undefined;window.speechSynthesis=undefined;')
   p.reload();p.locator('#start').click();p.locator('#session').wait_for(state='visible');p.locator('#mic').click();assert 'not supported' in p.locator('#sessionStatus').inner_text();p.locator('.camfold').evaluate('e=>e.open') or p.locator('.camfold > summary').click();p.locator('#cameraToggle').click();p.wait_for_function('document.querySelector("#cameraStatus").textContent.includes("denied")');p.close()
   p=page();p.evaluate('navigator.mediaDevices.getUserMedia=async()=>{throw new Error("denied")}; window.speechSynthesis=undefined');p.locator('#mode').select_option('voice');p.locator('#start').click();p.wait_for_function('document.querySelector("#audioStatus").textContent.includes("unavailable")');p.locator('#answer').fill('I compared test results with the source records and checked SQL.');p.locator('#submit').click();p.wait_for_function('document.querySelector("#liveReview").textContent.includes("Score:")');p.locator('#endInterview').click();p.locator('#results').wait_for(state='visible');p.close()
   print('denied complete',flush=True)
   # Late media permission is closed after sign out, never attached to the next account.
   for kind in ('audio','video'):
    p=page();p.evaluate('()=>{window.mediaResolve=null;window.stopped=false;window.mediaRequests=0;navigator.mediaDevices.getUserMedia=()=>{window.mediaRequests++;return new Promise(r=>window.mediaResolve=r)}}')
    if kind=='audio':p.locator('#mode').select_option('voice')
    p.locator('#start').click();p.locator('#session').wait_for(state='visible')
    if kind=='video':
     p.locator('.camfold').evaluate('e=>e.open') or p.locator('.camfold > summary').click();p.locator('#cameraToggle').click();p.evaluate('()=>{void toggleCamera()}');assert p.evaluate('window.mediaRequests')==1
    p.wait_for_function('window.mediaResolve!==null');p.locator('#signout').click();p.locator('#devEmail').fill('second@example.com');p.locator('#devSignIn').click()
    p.evaluate('window.mediaResolve({getTracks:()=>[{stop:()=>window.stopped=true}]})');p.wait_for_function('window.stopped');assert p.evaluate('audioStream===null&&cameraStream===null');p.close()
   p=page();p.evaluate('()=>{window.doneCount=0;Object.defineProperty(window,"speechSynthesis",{value:{cancel:()=>{},speak:u=>window.lastUtterance=u},configurable:true});speak("Synthetic prompt",()=>window.doneCount++);window.lastUtterance.onend();window.lastUtterance.onerror()}');assert p.evaluate('window.doneCount')==1;p.close()
   assert not errors,errors
   browser.close();print('Interview typed/adaptive/end/report retry, 12 stale response cases, active401, denied/unsupported device and 2 late permission cleanup cases passed.')
 finally:proc.terminate();proc.wait(timeout=5)
