"""Synthetic localhost checks for the GitHub project review page.
A local fixture server stands in for the public GitHub API and raw content
hosts; no live network, no real account, no real repository. Fixture repo
'srt-dev/zipkit' and its files are synthetic. Requires Playwright and Chromium.
API_PYTHON may select the API virtualenv.
"""
import io,json,os,subprocess,tempfile,threading,time,urllib.parse,urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
SHA="abc123def4567890abc123def4567890abc12345"
META={"full_name":"srt-dev/zipkit","description":"tiny zip library","default_branch":"main",
 "stargazers_count":7,"forks_count":2,"open_issues_count":1,"created_at":"2026-01-02T00:00:00Z",
 "pushed_at":"2026-11-01T00:00:00Z","fork":False,"archived":False,"license":{"spdx_id":"MIT"}}
TREE={"truncated":False,"tree":[
 {"type":"blob","path":"README.md","size":900},
 {"type":"blob","path":"requirements.txt","size":60},
 {"type":"blob","path":".github/workflows/ci.yml","size":200},
 {"type":"blob","path":"zipkit/core.py","size":3200},
 {"type":"blob","path":"tests/test_core.py","size":800},
 {"type":"blob","path":"tests/test_edge.py","size":500}]}
FILES={"README.md":"# zipkit\n\n## Installation\n\npip install zipkit\n\n## Usage\n\nzipkit.compress(src)\n",
 "requirements.txt":"requests==2.31.0\nclick>=8.0\n",
 ".github/workflows/ci.yml":"name: ci\non: [push]\njobs:\n  test:\n    steps:\n      - run: pytest -q\n",
 "zipkit/core.py":"# code\n",
 "tests/test_core.py":"def test_compress():\n    assert compress(b'x')\n",
 "tests/test_edge.py":"def test_placeholder():\n    pass\n"}
CHECK_RUNS={"total_count":1,"check_runs":[{"name":"pytest (3.11)","status":"completed","conclusion":"success"}]}
USER_REPOS=[{"name":"zipkit","full_name":"srt-dev/zipkit","description":"tiny zip library","language":"Python",
 "stargazers_count":7,"pushed_at":"2026-11-01T00:00:00Z","fork":False,"archived":False}]
def pdf_with_link(uri):
 from pypdf import PdfWriter
 from pypdf.generic import DictionaryObject, NameObject, ArrayObject, RectangleObject, TextStringObject
 w=PdfWriter();w.add_blank_page(612,792)
 a=DictionaryObject();a.update({NameObject("/Type"):NameObject("/Annot"),NameObject("/Subtype"):NameObject("/Link"),NameObject("/Rect"):RectangleObject([0,0,10,10]),NameObject("/A"):DictionaryObject({NameObject("/S"):NameObject("/URI"),NameObject("/URI"):TextStringObject(uri)})})
 w.pages[0][NameObject("/Annots")]=ArrayObject([w._add_object(a)])
 b=io.BytesIO();w.write(b);return b.getvalue()
class Fx(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def _json(self,obj):
  body=json.dumps(obj).encode();self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  path=urllib.parse.urlsplit(self.path).path
  if path=="/api/users/srt-dev/repos":return self._json(USER_REPOS)
  if path=="/api/repos/srt-dev/zipkit":return self._json(META)
  if path=="/api/repos/srt-dev/zipkit/branches/main":return self._json({"commit":{"sha":SHA}})
  if path.startswith("/api/repos/srt-dev/zipkit/git/trees/"):return self._json(TREE)
  if "/check-runs" in path:return self._json(CHECK_RUNS)
  if path.endswith("/status"):return self._json({"state":"pending","statuses":[]})
  if path.startswith("/raw/srt-dev/zipkit/"+SHA+"/"):
   rel=urllib.parse.unquote(path[len("/raw/srt-dev/zipkit/"+SHA+"/"):])
   if rel in FILES:
    body=FILES[rel].encode();self.send_response(200);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body);return
  body=b"404";self.send_response(404);self.send_header("Content-Length","3");self.end_headers();self.wfile.write(body)
fx=HTTPServer(("127.0.0.1",0),Fx);threading.Thread(target=fx.serve_forever,daemon=True).start()
FXPORT=fx.server_address[1]
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH="1",SLATE_STATE_URL="sqlite:///"+tmp+"/state.db",GEMINI_API_KEY="",LLM_API_KEY="",
  SLATE_GITHUB_API_BASE="http://127.0.0.1:%d/api"%FXPORT,
  SLATE_GITHUB_RAW_BASE="http://127.0.0.1:%d/raw"%FXPORT)
 proc=subprocess.Popen([os.environ.get("API_PYTHON",os.sys.executable),"-m","uvicorn","agents.slate_api.app:app","--host","127.0.0.1","--port","8023"],cwd=ROOT,env=env,stdout=open("/tmp/projects-server.log","w"),stderr=subprocess.STDOUT)
 try:
  for _ in range(100):
   try:urllib.request.urlopen("http://127.0.0.1:8023/v1/config",timeout=1);break
   except Exception:time.sleep(.1)
  # Onboarding gate: this check's synthetic user has already made the one-time
  # setup decision (empty confirmed profile), so sign-in lands on the page under test.
  for _email in ['first@example.com']:
      _req=urllib.request.Request("http://127.0.0.1:8023/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
      urllib.request.urlopen(_req,timeout=5).read()
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH","/usr/bin/google-chrome"),args=["--no-sandbox"])
   errors=[]
   def page(width=1280,height=800):
    p=browser.new_page(viewport={"width":width,"height":height});p.set_default_timeout(8000);p.on("pageerror",lambda e:errors.append(str(e)));p.goto("http://127.0.0.1:8023/projects");p.locator("#devEmail").fill("first@example.com");p.locator("#devSignIn").click();p.locator("#signout").wait_for(state="visible");return p
   def stage_on(p,name):return p.evaluate("document.getElementById('stage-%s').classList.contains('on')&&!document.getElementById('stage-%s').classList.contains('hidden')"%(name,name))
   def wait_text(p,sel,text):p.wait_for_function("([s,t])=>document.querySelector(s)&&document.querySelector(s).textContent.includes(t)",arg=[sel,text])
   print("nav + stage flow: links",flush=True)
   p=page()
   assert stage_on(p,"links") and not stage_on(p,"results")
   nav=p.locator(".nav").inner_text()
   assert "Project review" in nav and "Practice sheet" in nav
   print("scan saved resumes (empty)",flush=True)
   p.locator("#scanSaved").click()
   wait_text(p,"#linkStatus","No GitHub link found")
   print("scan PDF with hidden annotation link",flush=True)
   scanpdf=os.path.join(tmp,"scan.pdf");open(scanpdf,"wb").write(pdf_with_link("https://github.com/srt-dev/zipkit"))
   p.locator("#pdfScan").set_input_files(scanpdf)
   p.locator("#scanPdf").click()
   p.locator(".foundchip").wait_for(state="visible")
   p.locator(".foundchip").first.click()
   assert "zipkit" in p.locator("#pickList").inner_text()
   print("manual input adds + dedupe + limit",flush=True)
   p.locator("#repoInput").fill("https://github.com/srt-dev/zipkit\nhttps://github.com/srt-dev/zipkit")
   p.locator("#addRepos").click()
   wait_text(p,"#linkStatus","Nothing new added")
   print("username list + picker",flush=True)
   p.locator("#ghUser").fill("srt-dev");p.locator("#listRepos").click()
   p.locator(".pickrow").wait_for(state="visible")
   assert "tiny zip library" in p.locator("#repoPicker").inner_text()
   p.locator(".pickrow input").first.check()
   assert p.locator("#pickList").inner_text().count("srt-dev/zipkit")==1  # already picked: no duplicate
   print("review render: signals, evidence, unknowns, suggestions",flush=True)
   p.locator("#review").click()
   p.locator("#reviewCards .repcard").wait_for(state="visible")
   assert stage_on(p,"results")
   card=p.locator("#reviewCards").inner_text()
   assert "srt-dev/zipkit" in card and "tiny zip library" in card
   assert "signals met 11 of 12 applicable" in card
   assert "MET" in card and "PARTIAL" in card
   assert "1 of 2 requirements pinned" in card
   assert "tests/test_edge.py" in card  # grounded suggestion names the file
   assert "job 'pytest (3.11)': success" in card and SHA[:7] in card
   assert "coverage: read 6 files" in card
   assert "GitHub API calls used: 4" in card
   assert "never runs repository code" in p.locator("#scopeNote").inner_text()
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s40-projects-desktop.png")
   print("txt download",flush=True)
   with p.expect_download() as dl:
    p.locator("#downloadTxt").click()
   path=dl.value.path();txt=open(path).read()
   assert "Slate project review" in txt and "Nothing was executed" in txt
   assert "pytest (3.11)" in txt and "tests/test_edge.py" in txt
   print("back navigation",flush=True)
   p.locator("#backToLinks").click();assert stage_on(p,"links")
   print("dark mode",flush=True)
   p2=page();p2.evaluate("document.documentElement.dataset.theme='dark'")
   p2.locator("#repoInput").fill("https://github.com/srt-dev/zipkit");p2.locator("#addRepos").click();p2.locator("#review").click()
   p2.locator("#reviewCards .repcard").wait_for(state="visible")
   p2.wait_for_timeout(600);p2.screenshot(path="/tmp/s40-projects-dark.png")
   print("mobile viewport",flush=True)
   pm=page(width=390,height=780)
   pm.locator("#repoInput").fill("https://github.com/srt-dev/zipkit");pm.locator("#addRepos").click();pm.locator("#review").click()
   pm.locator("#reviewCards .repcard").wait_for(state="visible")
   pm.wait_for_timeout(600);pm.screenshot(path="/tmp/s40-projects-mobile.png")
   assert not errors,errors
   print("ALL PROJECT REVIEW UI CHECKS PASSED (desktop, dark, mobile; zero JS errors)",flush=True)
 finally:
  proc.terminate()
