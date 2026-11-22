"""Synthetic localhost checks for the LeetCode company practice sheet page.
A local fixture server stands in for leetcode.com GraphQL and the MIT-licensed
community company-sheet CSVs; no live network, provider key, or real profile.
Fixture profile 'srt-dev' is synthetic; its recent-solve date is 2026-11-01.
Requires Playwright and Chromium. API_PYTHON may select the API virtualenv.
"""
import io,json,os,subprocess,tempfile,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
CSV=("problem_link,problem_name,num_occur\n"
 "https://leetcode.com/problems/two-sum/,Two Sum,14\n"
 "https://leetcode.com/problems/add-two-numbers/,Add Two Numbers,9\n"
 "https://leetcode.com/problems/trapping-rain-water/,Trapping Rain Water,3\n")
USER_CSV=("Difficulty,Title,Frequency,Acceptance Rate,Link,Topics\n"
 "EASY,Two Sum,100.0,0.5,https://leetcode.com/problems/two-sum,\"Array, Hash Table\"\n"
 "MEDIUM,Add Two Numbers,87.4,0.4,https://leetcode.com/problems/add-two-numbers,\"Linked List, Math\"\n")
PROFILE={"data":{"matchedUser":{"username":"srt-dev","profile":{"realName":"Sart Demo","ranking":123456},
 "submitStatsGlobal":{"acSubmissionNum":[{"difficulty":"All","count":42},{"difficulty":"Easy","count":20},{"difficulty":"Medium","count":18},{"difficulty":"Hard","count":4}]}},
 "recentAcSubmissionList":[{"title":"Two Sum","titleSlug":"two-sum","timestamp":"1793491200"}]}}
def pdf_with_link(uri):
 from pypdf import PdfWriter
 from pypdf.generic import DictionaryObject, NameObject, ArrayObject, RectangleObject, TextStringObject
 w=PdfWriter();w.add_blank_page(612,792)
 a=DictionaryObject();a.update({NameObject("/Type"):NameObject("/Annot"),NameObject("/Subtype"):NameObject("/Link"),NameObject("/Rect"):RectangleObject([0,0,10,10]),NameObject("/A"):DictionaryObject({NameObject("/S"):NameObject("/URI"),NameObject("/URI"):TextStringObject(uri)})})
 w.pages[0][NameObject("/Annots")]=ArrayObject([w._add_object(a)])
 b=io.BytesIO();w.write(b);return b.getvalue()
class Fx(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  body=json.dumps(PROFILE).encode();self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):
  if self.path.startswith("/commits"):body=b'[{"commit":{"committer":{"date":"2026-06-17T16:10:12Z"}}}]'
  elif self.path.startswith("/sheets/"):body=CSV.encode()
  else:body=b"404";self.send_response(404);self.send_header("Content-Length","3");self.end_headers();self.wfile.write(body);return
  self.send_response(200);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
fx=HTTPServer(("127.0.0.1",0),Fx);threading.Thread(target=fx.serve_forever,daemon=True).start()
FXPORT=fx.server_address[1]
with tempfile.TemporaryDirectory() as tmp:
 env=dict(os.environ,SLATE_DEV_AUTH="1",SLATE_STATE_URL="sqlite:///"+tmp+"/state.db",GEMINI_API_KEY="",LLM_API_KEY="",
  SLATE_LEETCODE_GRAPHQL_URL="http://127.0.0.1:%d/graphql"%FXPORT,
  SLATE_COMPANY_SHEET_BASE_URL="http://127.0.0.1:%d/sheets"%FXPORT,
  SLATE_COMPANY_SHEET_COMMITS_URL="http://127.0.0.1:%d/commits"%FXPORT,
  SLATE_COMPANY_SHEET_COMMITS_PATH_PREFIX="companies/")
 proc=subprocess.Popen([os.environ.get("API_PYTHON",os.sys.executable),"-m","uvicorn","agents.slate_api.app:app","--host","127.0.0.1","--port","8022"],cwd=ROOT,env=env,stdout=open("/tmp/practice-server.log","w"),stderr=subprocess.STDOUT)
 try:
  for _ in range(100):
   try:urllib.request.urlopen("http://127.0.0.1:8022/v1/config",timeout=1);break
   except Exception:time.sleep(.1)
  # Onboarding gate: this check's synthetic users have already made the one-time
  # setup decision (empty confirmed profile), so sign-in lands on the page under test.
  for _email in ['first@example.com', 'second@example.com']:
      _req=urllib.request.Request("http://127.0.0.1:8022/v1/profile",data=b'{"answers":{},"confirm":true}',headers={"Authorization":"Bearer dev:"+_email,"Content-Type":"application/json"},method="POST")
      urllib.request.urlopen(_req,timeout=5).read()
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH","/usr/bin/google-chrome"),args=["--no-sandbox"])
   errors=[]
   def page(width=1280,height=800):
    p=browser.new_page(viewport={"width":width,"height":height});p.set_default_timeout(5000);p.on("pageerror",lambda e:errors.append(str(e)));p.goto("http://127.0.0.1:8022/practice");p.locator("#devEmail").fill("first@example.com");p.locator("#devSignIn").click();p.locator("#signout").wait_for(state="visible");return p
   def stage_on(p,name):return p.evaluate("document.getElementById('stage-%s').classList.contains('on')&&!document.getElementById('stage-%s').classList.contains('hidden')"%(name,name))
   print("stage flow: profile",flush=True)
   p=page()
   assert stage_on(p,"profile") and not stage_on(p,"company") and not stage_on(p,"results")
   # Sidebar rail position at a normal desktop viewport: fixed rail at top-left.
   box=p.locator(".topbar").bounding_box()
   assert box["x"]==0 and box["y"]==0 and box["width"]==204,box
   p.locator("#lcInput").fill("https://leetcode.com/u/srt-dev/");p.locator("#lookup").click()
   p.locator("#profileCard").wait_for(state="visible")
   assert p.locator("#pName").inner_text()=="srt-dev · Sart Demo"
   assert p.locator("#cAll").inner_text()=="42" and p.locator("#cHard").inner_text()=="4"
   assert "does not have your full solved history" in p.locator("#scopeNote").inner_text()
   assert stage_on(p,"profile")  # still one stage: the card lives inside stage 1
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s30-practice-profile.png")
   print("stage flow: company + back",flush=True)
   p.locator("#confirmProfile").click()
   assert p.evaluate("document.activeElement.id")=="company"
   assert stage_on(p,"company") and not stage_on(p,"profile") and not stage_on(p,"results")
   assert p.locator("#confirmedNote").inner_text()=="Profile: srt-dev"
   p.locator("#company").fill("amaz")
   p.wait_for_function("document.querySelectorAll('#companyList option').length>0")
   assert "Amazon" in p.locator("#companyList").inner_html()
   p.locator("#company").fill("Amazon")
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s31-practice-company.png")
   p.locator("#backToProfile").click()  # Back preserves state
   assert stage_on(p,"profile") and p.locator("#profileCard").is_visible()
   p.locator("#confirmProfile").click()
   assert p.locator("#company").input_value()=="Amazon"
   print("stage flow: results",flush=True)
   p.locator("#build").click()
   p.locator("#sheetRows .qrow").first.wait_for(state="visible")
   assert p.evaluate("document.activeElement.id")=="sheetHead"
   assert stage_on(p,"results") and not stage_on(p,"company")
   banner=p.locator("#sheetBanner").inner_text()
   assert "may still mean solved" in banner and "Msharma1212" in banner and "2026-06-17" in banner
   assert "does not have your full solved history" not in banner  # disclaimer shown once, in stage 1
   assert p.locator(".qrow").count()==3
   assert p.locator(".qstat.recent").count()==1 and p.locator(".qstat.unknown").count()==2
   assert "Recently solved · 2026-11-01" in p.locator(".qrow").first.inner_text()
   assert "Showing 3 of 3 Amazon questions" in p.locator("#sheetSummary").inner_text()
   assert p.locator(".dtag").count()==0  # community data carries no difficulty; nothing invented
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s32-practice-results.png")
   print("results back preserves sheet state",flush=True)
   p.locator("#backToCompany").click()
   assert stage_on(p,"company") and p.locator("#company").input_value()=="Amazon"
   p.locator("#build").click();p.locator("#sheetRows .qrow").first.wait_for(state="visible")
   print("txt download",flush=True)
   with p.expect_download() as dl:p.locator("#downloadTxt").click()
   dl.value.save_as("/tmp/s33-practice-sheet.txt")
   txt=open("/tmp/s33-practice-sheet.txt").read()
   assert "Slate practice sheet - Amazon" in txt and "Not in recent public solves" in txt and "may still be solved" in txt and "MIT-licensed community compilation" in txt and "2026-06-17" in txt
   print("dark theme",flush=True)
   p.locator("#theme-toggle").click();p.wait_for_timeout(700)
   p.screenshot(path="/tmp/s34-practice-dark.png")
   p.locator("#theme-toggle").click();p.close()
   print("mobile viewport",flush=True)
   p=page(width=390,height=844)
   mbox=p.locator(".topbar").bounding_box()
   assert mbox["x"]==0 and mbox["y"]==0 and mbox["width"]==390,mbox  # top bar, not a rail
   p.locator("#lcInput").fill("srt-dev");p.locator("#lookup").click();p.locator("#profileCard").wait_for(state="visible")
   p.locator("#confirmProfile").click();p.locator("#company").fill("Amazon");p.locator("#build").click()
   p.locator("#sheetRows .qrow").first.wait_for(state="visible")
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s35-practice-mobile.png",full_page=True);p.close()
   print("upload own CSV",flush=True)
   p=page();p.locator("#lcInput").fill("srt-dev");p.locator("#lookup").click();p.locator("#profileCard").wait_for(state="visible")
   p.locator("#confirmProfile").click()
   csv_path="/tmp/synthetic-own-sheet.csv";open(csv_path,"w").write(USER_CSV)
   p.set_input_files("#csvScan",csv_path);p.locator("#buildFromCsv").click()
   p.locator("#sheetRows .qrow").first.wait_for(state="visible")
   assert "Uploaded by you" in p.locator("#sheetBanner").inner_text()
   assert p.locator(".qrow").count()==2 and p.locator(".dtag").count()==2  # user schema carries difficulty
   p.wait_for_timeout(700);p.screenshot(path="/tmp/s36-practice-owncsv.png");p.close()
   print("scan saved resumes",flush=True)
   p=page()
   p.evaluate("fetch('/v1/resume',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+sessionStorage.getItem('slate_token')},body:JSON.stringify({text:'Asha Verma\\nProfiles: https://leetcode.com/u/srt-dev/\\nSkills: Python, Git, SQL, Excel, Tableau'})})")
   p.locator("#scanSaved").click()
   p.wait_for_function("document.querySelectorAll('#foundList .foundchip').length===1")
   p.locator("#foundList .foundchip").first.click()
   p.locator("#profileCard").wait_for(state="visible");p.close()
   print("pdf annotation scan",flush=True)
   p=page()
   pdf_path="/tmp/synthetic-resume-link.pdf";open(pdf_path,"wb").write(pdf_with_link("https://leetcode.com/u/pdf-handle/"))
   p.set_input_files("#pdfScan",pdf_path);p.locator("#scanPdf").click()
   p.wait_for_function("document.querySelectorAll('#foundList .foundchip').length===1")
   assert "pdf-handle" in p.locator("#foundList").inner_text();p.close()
   print("unknown company",flush=True)
   p=page();p.locator("#lcInput").fill("srt-dev");p.locator("#lookup").click();p.locator("#profileCard").wait_for(state="visible")
   p.locator("#confirmProfile").click();p.locator("#company").fill("zzzz-not-a-company");p.locator("#build").click()
   p.wait_for_function("document.querySelector('#buildStatus').textContent.includes('No prebuilt question sheet')")
   assert stage_on(p,"company");p.close()
   print("invalid username",flush=True)
   p=page();p.locator("#lcInput").fill("  spaces not allowed  ");p.locator("#lookup").click()
   p.wait_for_function("document.querySelector('#lookupStatus').textContent.includes('does not look like a LeetCode username')");p.close()
   print("stale profile response ignored after sign out",flush=True)
   p=page();delayed=[]
   p.route("**/v1/practice/profile",lambda r:delayed.append(r))
   p.locator("#lcInput").fill("srt-dev");p.locator("#lookup").click()
   p.wait_for_timeout(80);assert delayed
   p.locator("#signout").click();p.locator("#devEmail").fill("second@example.com");p.locator("#devSignIn").click();p.locator("#signout").wait_for(state="visible")
   delayed[0].fulfill(status=200,content_type="application/json",body=json.dumps({"username":"PRIVATE","realName":"PRIVATE","ranking":1,"solved":{"all":1,"easy":1,"medium":0,"hard":0},"recentAccepted":[],"profileUrl":"https://leetcode.com/u/PRIVATE/","scopeNote":"PRIVATE"}))
   p.wait_for_timeout(120)
   assert not p.locator("#profileCard").is_visible() and "PRIVATE" not in p.locator("body").inner_text()
   assert p.evaluate("token()")=="dev:second@example.com" and stage_on(p,"profile");p.close()
   assert not errors,errors
   browser.close();print("Practice sheet UI: staged flow/back-state/rail+mobile position/company suggest/results/txt/dark/own-CSV/scan-saved/scan-pdf/unknown-company/invalid-username/stale-response cases passed.")
 finally:
  proc.terminate();proc.wait(timeout=5);fx.shutdown()
