"""Synthetic localhost checks for the onboarding + profile pages.

Dev sign-in against a temporary sqlite state file; no network, provider key,
or real account. Users 'first@example.com' / 'second@example.com' are
synthetic. Requires Playwright and Chromium. API_PYTHON may select the API
virtualenv, CHROME_PATH the browser.
"""
import os, re, subprocess, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8025"

with tempfile.TemporaryDirectory() as tmp:
    env = dict(os.environ, SLATE_DEV_AUTH="1", SLATE_STATE_URL="sqlite:///" + tmp + "/state.db",
               GEMINI_API_KEY="", LLM_API_KEY="")
    proc = subprocess.Popen([os.environ.get("API_PYTHON", os.sys.executable), "-m", "uvicorn",
                             "agents.slate_api.app:app", "--host", "127.0.0.1", "--port", "8025"],
                            cwd=ROOT, env=env,
                            stdout=open("/tmp/onboarding-server.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE + "/v1/config", timeout=1)
                break
            except Exception:
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH", "/usr/bin/google-chrome"),
                                         args=["--no-sandbox"])
            errors = []

            def page(route="/"):
                p = browser.new_page(viewport={"width": 1280, "height": 800})
                p.set_default_timeout(8000)
                p.on("pageerror", lambda e: errors.append(str(e)))
                p.goto(BASE + route)
                return p

            def sign_in_dev(p, email):
                # practice/profile/onboarding pages share these ids
                p.locator("#devEmail").fill(email)
                p.locator("#devSignIn").click()

            print("first login: gate redirects to onboarding", flush=True)
            p = page("/practice")
            sign_in_dev(p, "first@example.com")
            p.wait_for_url("**/onboarding", wait_until="commit")
            p.locator("#stage-form").wait_for(state="visible")
            assert "one-time setup" in p.locator(".pagehead .sub").inner_text()
            p.wait_for_timeout(500)
            p.screenshot(path="/tmp/ob-1-firstlogin.png")

            print("onboarding: save answers, land on home, no redirect back", flush=True)
            p.locator("#ob-name").fill("Asha Verma")
            p.locator("#ob-email").fill("asha@example.com")
            p.locator("#ob-github").fill("github.com/asha-verma")
            p.locator("#save").click()
            p.wait_for_url(re.compile(r"127\.0\.0\.1:8025/$"), wait_until="commit")
            p.wait_for_timeout(1200)
            assert not p.url.endswith("/onboarding"), p.url

            print("profile page: answers shown, blanks are Not added", flush=True)
            p.goto(BASE + "/profile")
            p.locator("#ansRows").wait_for()
            rows = p.locator("#ansRows").inner_text()
            assert "Asha Verma" in rows and "asha@example.com" in rows
            assert "https://github.com/asha-verma" in rows  # normalized
            assert rows.count("Not added") == 4, rows
            assert "not independently verified" in p.locator("#profileNote").inner_text()
            p.wait_for_timeout(400)
            p.screenshot(path="/tmp/ob-2-profile-view.png")

            print("profile page: edit adds location", flush=True)
            p.locator("#editBtn").click()
            assert p.locator("#editPanel").is_visible()
            assert p.locator("#pf-name").input_value() == "Asha Verma"
            p.locator("#pf-location").fill("Gwalior")
            p.locator("#saveBtn").click()
            p.locator("#viewPanel").wait_for(state="visible")
            assert "Gwalior" in p.locator("#ansRows").inner_text()
            assert p.locator("#ansRows").inner_text().count("Not added") == 3

            print("dark mode renders on profile", flush=True)
            p.locator("#theme-toggle").click()
            assert p.evaluate("document.documentElement.dataset.theme") == "dark"
            p.wait_for_timeout(400)
            p.screenshot(path="/tmp/ob-3-profile-dark.png")

            print("second user: gated, empty, skip ends the redirect", flush=True)
            p.locator("#signout").click()
            sign_in_dev(p, "second@example.com")
            p.wait_for_timeout(500)
            p.goto(BASE + "/")  # home page uses its own dev ids
            if p.locator("#devmail").count():
                # not signed in on this tab flow path: sign in via home controls
                p.locator("#devmail").fill("second@example.com")
                p.locator("#devgo").click()
            p.wait_for_url("**/onboarding", wait_until="commit")
            p.locator("#stage-form").wait_for(state="visible")
            assert p.locator("#ob-name").input_value() == ""
            p.screenshot(path="/tmp/ob-4-second-user.png")
            p.locator("#skip").click()
            p.wait_for_url(re.compile(r"127\.0\.0\.1:8025/$"), wait_until="commit")
            p.goto(BASE + "/interview")  # skip was recorded: no more redirect
            p.wait_for_timeout(1200)
            assert p.url.endswith("/interview"), p.url
            p.goto(BASE + "/profile")
            p.locator("#ansRows").wait_for()
            rows2 = p.locator("#ansRows").inner_text()
            assert "Asha" not in rows2  # per-user isolation
            assert rows2.count("Not added") == 7, rows2
            assert "skipped setup" in p.locator("#profileNote").inner_text()

            print("returning user: no redirect, answers persist", flush=True)
            p2 = page("/")
            p2.locator("#devmail").fill("first@example.com")
            p2.locator("#devgo").click()
            p2.wait_for_timeout(1500)
            assert not p2.url.endswith("/onboarding"), p2.url
            p2.goto(BASE + "/profile")
            p2.locator("#ansRows").wait_for()
            assert "Asha Verma" in p2.locator("#ansRows").inner_text()

            assert not errors, errors
            print("OK: onboarding + profile UI checks passed, no JS errors", flush=True)
    finally:
        proc.terminate()
