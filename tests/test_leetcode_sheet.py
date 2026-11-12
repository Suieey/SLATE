"""LeetCode company practice sheet feature. Synthetic fixtures only: every test
injects fake transports; nothing here touches leetcode.com or GitHub."""
import io
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from slate_api.app import create_app  # noqa: E402
from slate_core import SlateService  # noqa: E402
from slate_core import leetcode_sheet as lc  # noqa: E402
from slate_core.service import SlateError  # noqa: E402

# Built-in community compilation schema: problem_link,problem_name,num_occur
CSV_FIXTURE = (
    "problem_link,problem_name,num_occur\n"
    "https://leetcode.com/problems/two-sum/,Two Sum,14\n"
    "https://leetcode.com/problems/add-two-numbers/,Add Two Numbers,9\n"
    "https://leetcode.com/problems/trapping-rain-water/,Trapping Rain Water,3\n"
)
# Common alternate layout a user might upload
USER_CSV_FIXTURE = (
    "Difficulty,Title,Frequency,Acceptance Rate,Link,Topics\n"
    "EASY,Two Sum,100.0,0.5,https://leetcode.com/problems/two-sum,\"Array, Hash Table\"\n"
    "HARD,Trapping Rain Water,55.1,0.6,https://leetcode.com/problems/trapping-rain-water,\"DP, Stack\"\n"
)

PROFILE_PAYLOAD = {
    "data": {
        "matchedUser": {
            "username": "srt-dev",
            "profile": {"realName": "Sart Demo", "ranking": 123456},
            "submitStatsGlobal": {"acSubmissionNum": [
                {"difficulty": "All", "count": 42},
                {"difficulty": "Easy", "count": 20},
                {"difficulty": "Medium", "count": 18},
                {"difficulty": "Hard", "count": 4},
            ]},
        },
        "recentAcSubmissionList": [
            {"title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1793491200"},
        ],
    }
}
RECENT_DATE = "2026-11-01"  # 1793491200 UTC


@pytest.fixture(autouse=True)
def _no_cache():
    lc.reset_cache()
    yield
    lc.reset_cache()


def fake_post(url, payload, timeout=15.0):
    assert "graphql" in url
    return PROFILE_PAYLOAD


def fake_get(url, timeout=20.0):
    if "/commits" in url:
        return '[{"commit": {"committer": {"date": "2026-06-17T16:10:12Z"}}}]'
    return CSV_FIXTURE


# --- username discovery -----------------------------------------------------

def test_normalize_username_variants():
    assert lc.normalize_username("srt-dev") == "srt-dev"
    assert lc.normalize_username("https://leetcode.com/u/srt-dev/") == "srt-dev"
    assert lc.normalize_username("leetcode.com/profile/Srt_Dev99") == "Srt_Dev99"
    with pytest.raises(SlateError):
        lc.normalize_username("not a username!!")
    with pytest.raises(SlateError):
        lc.normalize_username("")


def test_extract_usernames_from_text():
    text = ("Links: https://leetcode.com/u/srt-dev/ and www.leetcode.com/u/srt-dev/ "
            "plus https://leetcode.com/problems/two-sum/ and https://leetcode.com/bare-name")
    names = lc.extract_leetcode_usernames(text)
    assert "srt-dev" in names and "bare-name" in names
    assert "problems" not in names  # site sections are not usernames
    assert names.count("srt-dev") == 1  # deduped


def _pdf_with_link(uri=None):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, ArrayObject, RectangleObject, TextStringObject
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    if uri:
        annot = DictionaryObject()
        annot.update({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): RectangleObject([0, 0, 10, 10]),
            NameObject("/A"): DictionaryObject({
                NameObject("/S"): NameObject("/URI"),
                NameObject("/URI"): TextStringObject(uri),
            }),
        })
        writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annot)])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_pdf_link_annotation_carries_username():
    """The common resume case: 'LeetCode' text hyperlinked, URL not visible.
    A low-text PDF would make extract_pdf_text raise; the annotation must still win."""
    pdf = _pdf_with_link(uri="https://leetcode.com/u/hidden-handle/")
    assert lc.extract_pdf_leetcode_usernames(pdf) == ["hidden-handle"]


def test_pdf_visible_text_link():
    pdf = _pdf_with_link()
    names = lc.extract_pdf_leetcode_usernames(pdf, text="Profiles: https://leetcode.com/u/visible-one/")
    assert names == ["visible-one"]


def test_pdf_without_links():
    assert lc.extract_pdf_leetcode_usernames(_pdf_with_link()) == []


# --- profile fetch ------------------------------------------------------------

def test_profile_success():
    p = lc.fetch_public_profile("srt-dev", post=fake_post)
    assert p["username"] == "srt-dev" and p["solved"] == {"all": 42, "easy": 20, "medium": 18, "hard": 4}
    assert p["recentAccepted"][0]["slug"] == "two-sum" and p["recentAccepted"][0]["date"] == RECENT_DATE
    assert "does not have your full solved history" in p["scopeNote"]


def test_profile_not_found():
    with pytest.raises(SlateError) as e:
        lc.fetch_public_profile("ghost", post=lambda u, p, timeout=15.0: {"data": {"matchedUser": None, "recentAcSubmissionList": []}})
    assert e.value.code == "profile_not_found"


def test_profile_network_error():
    def boom(url, payload, timeout=15.0):
        raise urllib.error.URLError("down")
    with pytest.raises(SlateError) as e:
        lc.fetch_public_profile("srt-dev", post=boom)
    assert e.value.code == "leetcode_unavailable"


# --- company sheets -----------------------------------------------------------

def test_company_match_and_suggestions():
    assert lc.match_company("amazon") == "Amazon"
    with pytest.raises(SlateError) as e:
        lc.match_company("amzn-typo")
    assert e.value.code == "company_not_found"
    assert any("amazon" in s.lower() for s in lc.search_companies("amaz"))


def test_parse_community_csv():
    rows = lc.parse_community_csv(CSV_FIXTURE)
    assert [r["slug"] for r in rows] == ["two-sum", "add-two-numbers", "trapping-rain-water"]
    assert rows[0]["frequency"] == 14 and rows[0]["difficulty"] == ""  # community data has no difficulty


def test_parse_user_csv_both_layouts():
    a = lc.parse_user_csv(CSV_FIXTURE)
    b = lc.parse_user_csv(USER_CSV_FIXTURE)
    assert a[0]["slug"] == "two-sum" and b[0]["slug"] == "two-sum"
    assert b[0]["difficulty"] == "Easy" and b[1]["topics"] == "DP, Stack"
    with pytest.raises(SlateError) as e:
        lc.parse_user_csv("foo,bar\n1,2\n")
    assert e.value.code == "sheet_unreadable"


# --- sheet build: the honesty contract ---------------------------------------

def test_sheet_marks_only_recent_as_solved():
    profile = lc.fetch_public_profile("srt-dev", post=fake_post)
    sheet = lc.build_sheet(profile, lc.parse_community_csv(CSV_FIXTURE))
    by_slug = {r["slug"]: r for r in sheet["rows"]}
    assert by_slug["two-sum"]["status"] == lc.STATUS_RECENT and by_slug["two-sum"]["solvedDate"] == RECENT_DATE
    assert by_slug["add-two-numbers"]["status"] == lc.STATUS_UNKNOWN
    # The unknown label must never claim the question is unsolved.
    rendered = lc.render_txt(profile, "Amazon", lc.COMPANY_SHEET_ATTRIBUTION, sheet,
                             {"fetchedAt": "2026-11-12", "dataDate": "2026-06-17"})
    assert "unsolved" not in rendered.lower() or "may still be solved" in rendered
    assert "Not in recent public solves" in rendered
    assert "does not have your full solved history" in rendered
    assert "MIT-licensed community compilation" in rendered and "2026-06-17" in rendered


def test_sheet_empty_recent_window_is_honest():
    payload = {"data": {**PROFILE_PAYLOAD["data"], "recentAcSubmissionList": []}}
    profile = lc.fetch_public_profile("srt-dev", post=lambda u, p, timeout=15.0: payload)
    sheet = lc.build_sheet(profile, lc.parse_community_csv(CSV_FIXTURE))
    assert sheet["recentlySolvedShown"] == 0 and sheet["recentWindowSize"] == 0
    assert all(r["status"] == lc.STATUS_UNKNOWN for r in sheet["rows"])


def test_full_build_with_fakes():
    out = lc.build_practice_sheet("https://leetcode.com/u/srt-dev/", "amazon", post=fake_post, get=fake_get)
    assert out["company"] == "Amazon" and out["provenance"]["dataDate"] == "2026-06-17"
    assert out["provenance"]["attribution"] == lc.COMPANY_SHEET_ATTRIBUTION
    assert out["sheet"]["totalInList"] == 3
    assert "Slate practice sheet - Amazon" in out["txt"]


def test_build_from_uploaded_csv():
    out = lc.build_practice_sheet_from_csv("srt-dev", "MyTargetCo", USER_CSV_FIXTURE, post=fake_post)
    assert out["company"] == "MyTargetCo"
    assert out["provenance"]["attribution"] == "Uploaded by you" and out["provenance"]["dataDate"] is None
    assert "no source or freshness verification" in out["txt"]
    assert out["sheet"]["rows"][0]["difficulty"] == "Easy"  # user schema carries difficulty


# --- HTTP layer ---------------------------------------------------------------

@pytest.fixture()
def c():
    return TestClient(create_app(SlateService()))


def test_companies_endpoint(c):
    res = c.get("/v1/practice/companies", params={"q": "amaz"})
    assert res.status_code == 200 and "Amazon" in res.json()["companies"]


def test_scan_saved_resumes(c):
    rid = c.post("/v1/resume", json={"text": "Asha Verma\nProfiles: https://leetcode.com/u/asha-codes/\nSkills: Python\n"}).json()["resumeId"]
    found = c.post("/v1/practice/scan", json={}).json()["matches"]
    assert found and found[0]["resumeId"] == rid and found[0]["usernames"] == ["asha-codes"]


def test_scan_pdf_endpoint(c):
    pdf = _pdf_with_link(uri="https://leetcode.com/u/pdf-handle/")
    res = c.post("/v1/practice/scan-pdf", files={"file": ("resume.pdf", pdf, "application/pdf")})
    assert res.status_code == 200 and res.json()["usernames"] == ["pdf-handle"]


def test_profile_endpoint(c, monkeypatch):
    # The route imports the module function at call time, so patching the module works.
    real = lc.fetch_public_profile
    monkeypatch.setattr(lc, "fetch_public_profile", lambda username: real(username, post=fake_post))
    res = c.post("/v1/practice/profile", json={"username": "srt-dev"})
    assert res.status_code == 200 and res.json()["solved"]["all"] == 42
    res = c.post("/v1/practice/profile", json={"username": "!!bad!!"})
    assert res.status_code == 422  # invalid_username


def _sheet_result(username, company):
    return {
        "profile": {"username": username, "realName": "", "ranking": 1,
                    "solved": {"all": 42, "easy": 20, "medium": 18, "hard": 4},
                    "recentAccepted": [], "profileUrl": "https://leetcode.com/u/" + username + "/",
                    "scopeNote": "note"},
        "company": company or "Amazon",
        "sheet": {"rows": [], "totalInList": 3, "shown": 3, "recentlySolvedShown": 1, "recentWindowSize": 1},
        "provenance": {"sourceUrl": lc.COMPANY_SHEET_SOURCE_URL, "attribution": lc.COMPANY_SHEET_ATTRIBUTION,
                       "csvUrl": "x", "fetchedAt": "2026-11-12", "dataDate": "2026-06-17"},
        "txt": "sheet text",
    }


def test_sheet_endpoint_with_stubbed_module(c, monkeypatch):
    monkeypatch.setattr(lc, "build_practice_sheet", _sheet_result)
    res = c.post("/v1/practice/sheet", json={"username": "srt-dev", "company": "Amazon"})
    assert res.status_code == 200 and res.json()["txt"] == "sheet text"
    assert res.json()["provenance"]["dataDate"] == "2026-06-17"


def test_sheet_from_csv_endpoint(c, monkeypatch):
    monkeypatch.setattr(lc, "build_practice_sheet_from_csv", lambda u, comp, text, post=None: _sheet_result(u, comp or "Uploaded sheet"))
    res = c.post("/v1/practice/sheet-from-csv",
                 files={"file": ("mine.csv", USER_CSV_FIXTURE, "text/csv")},
                 data={"username": "srt-dev", "company": "MyTargetCo"})
    assert res.status_code == 200 and res.json()["company"] == "MyTargetCo"
