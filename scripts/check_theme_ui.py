"""Local theme persistence, all-route overflow and keyboard switch checks."""
import os,subprocess,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH='1',SLATE_STATE_URL='sqlite:///'+tmp+'/state.db',GEMINI_API_KEY='',LLM_API_KEY='')
 proc=subprocess.Popen([os.environ.get('API_PYTHON',os.sys.executable),'-m','uvicorn','agents.slate_api.app:app','--host','127.0.0.1','--port','8027'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:urllib.request.urlopen('http://127.0.0.1:8027/v1/config',timeout=1);break
   except Exception:time.sleep(.1)
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/usr/bin/google-chrome'),args=['--no-sandbox'])
   for width in (1440,880,390,320):
    c=b.new_context(viewport={'width':width,'height':1000},color_scheme='dark',reduced_motion='reduce');p=c.new_page();p.route('https://fonts.googleapis.com/**',lambda r:r.abort());p.route('https://fonts.gstatic.com/**',lambda r:r.abort());errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    for part in ('resume','targets','draft','comparisons','roadmap','interview','ai'):
     p.goto('http://127.0.0.1:8027/'+part);p.locator('#theme-toggle').wait_for();assert p.locator('html').get_attribute('data-theme')=='dark';assert p.locator('#theme-toggle').get_attribute('aria-pressed')=='true';assert p.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,part)
     p.locator('#theme-toggle').focus();p.keyboard.press('Enter');assert p.locator('html').get_attribute('data-theme')=='light';p.reload();assert p.locator('html').get_attribute('data-theme')=='light';p.locator('#theme-toggle').click();assert p.locator('html').get_attribute('data-theme')=='dark'
     if width in (1440,390):p.screenshot(path=f'/tmp/slate-theme-{part}-{width}.png')
    assert not errors,errors;c.close()
   # Storage failures must not prevent an in-memory toggle.
   c=b.new_context(color_scheme='light');c.add_init_script("Storage.prototype.getItem=()=>{throw Error('disabled')};Storage.prototype.setItem=()=>{throw Error('disabled')}");p=c.new_page();p.goto('http://127.0.0.1:8027/resume');p.locator('#theme-toggle').click();assert p.locator('html').get_attribute('data-theme')=='dark';c.close()
   c=b.new_context(color_scheme='light');p=c.new_page();q=c.new_page();p.goto('http://127.0.0.1:8027/resume');q.goto('http://127.0.0.1:8027/interview');p.locator('#theme-toggle').click();q.wait_for_function("document.documentElement.dataset.theme==='dark'");c.close()
   # A stored preference must not be required for normal use.
   c=b.new_context(color_scheme='light');p=c.new_page();p.goto('http://127.0.0.1:8027/resume');assert p.locator('html').get_attribute('data-theme')=='light';c.close();b.close()
  print('System default, explicit light/dark persistence, cross-page navigation, keyboard toggle and seven-route overflow passed at 1440/880/390/320.')
 finally:proc.terminate();proc.wait(timeout=5)
