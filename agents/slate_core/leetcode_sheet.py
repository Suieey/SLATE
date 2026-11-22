"""LeetCode company practice sheet feature.

Finds a user's public LeetCode profile (from a resume link or typed username),
reads ONLY what LeetCode's public profile interface exposes, and builds a
company practice sheet from a question list the app is permitted to use:

- the built-in community compilation Msharma1212/leetcode-company-wise-problems
  (MIT-licensed, attribution shown on every sheet), or
- a sheet the user uploads themselves (their own data, their responsibility).

Honesty invariants (do not weaken):
- Slate's verified public reads return solved COUNTS per difficulty and up to
  the 20 most recent accepted submissions. Slate does not have the user's full
  solved history. A question absent from the recent list is "not in recent
  public solves" - it is never reported as "unsolved" or "not practiced".
- Every sheet carries its data source, the source's last-update date when
  known, and the time Slate fetched it.
- Tests inject fake transports; the default transport hits the live public
  endpoints only on an explicit user action.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .service import SlateError

LEETCODE_GRAPHQL_URL = os.getenv("SLATE_LEETCODE_GRAPHQL_URL", "https://leetcode.com/graphql")
COMPANY_SHEET_BASE_URL = os.getenv(
    "SLATE_COMPANY_SHEET_BASE_URL",
    "https://raw.githubusercontent.com/Msharma1212/leetcode-company-wise-problems/main/leetcode-company-wise-problems-main/companies",
)
COMPANY_SHEET_COMMITS_URL = os.getenv(
    "SLATE_COMPANY_SHEET_COMMITS_URL",
    "https://api.github.com/repos/Msharma1212/leetcode-company-wise-problems/commits",
)
COMPANY_SHEET_COMMITS_PATH_PREFIX = os.getenv(
    "SLATE_COMPANY_SHEET_COMMITS_PATH_PREFIX",
    "leetcode-company-wise-problems-main/companies/",
)
COMPANY_SHEET_SOURCE_URL = "https://github.com/Msharma1212/leetcode-company-wise-problems"
COMPANY_SHEET_ATTRIBUTION = "MIT-licensed community compilation (Msharma1212/leetcode-company-wise-problems)"
COMPANIES_JSON = Path(__file__).resolve().parent / "data" / "leetcode_companies.json"

SHEET_ROW_LIMIT = 30
RECENT_LIMIT = 20  # verified cap of the public recent-accepted route

STATUS_RECENT = "recently_solved"
STATUS_UNKNOWN = "not_in_recent_public_solves"

SCOPE_NOTE = (
    "Slate reads LeetCode's public profile data: solved counts and up to the %d most recent "
    "accepted submissions. Slate does not have your full solved history, so questions outside "
    "that recent window are marked 'not in recent public solves' - which does not mean they "
    "are unsolved."
) % RECENT_LIMIT

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,29}$")
_LC_LINK_RE = re.compile(
    r"leetcode\.com/(?:u|profile)/([A-Za-z0-9][A-Za-z0-9_-]{0,29})",
    re.IGNORECASE,
)
_LC_BARE_RE = re.compile(
    r"leetcode\.com/([A-Za-z0-9][A-Za-z0-9_-]{0,29})(?![\w/-])",
    re.IGNORECASE,
)
_BARE_BLOCKLIST = {
    "problems", "problemset", "contest", "discuss", "explore", "interview",
    "assessment", "premium", "store", "support", "playground", "accounts",
    "session", "api", "graphql", "u", "profile", "list", "studyplan",
    "progress", "submissions", "tag", "company",
}

MAX_SHEET_CSV_BYTES = 2_000_000

_CACHE: dict = {}
_CACHE_MAX_ENTRIES = 512  # bounded memory: oldest quarter evicted when full
_CACHE_TTL = {"profile": 300, "csv": 6 * 3600, "csv_date": 6 * 3600}


def _cached(kind: str, key: str, producer):
    now = time.time()
    hit = _CACHE.get((kind, key))
    if hit and now - hit[0] < _CACHE_TTL[kind]:
        return hit[1]
    value = producer()
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        for k, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_MAX_ENTRIES // 4]:
            _CACHE.pop(k, None)
    _CACHE[(kind, key)] = (now, value)
    return value


def reset_cache():
    _CACHE.clear()


# --- Transports (injectable in tests) -------------------------------------

def http_post_json(url: str, payload: dict, timeout: float = 15.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/",
            "User-Agent": "Slate practice-sheet feature (public profile lookup)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _AuthStrippingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward an Authorization header to a non-GitHub-API host.

    urllib's default redirect handling copies the original request's headers
    to the redirect target, so a token meant for api.github.com would leak to
    any host a redirect points at. Strip Authorization on every redirect
    unless the redirect target is api.github.com itself.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urllib.parse.urlsplit(new.full_url).netloc.lower() != "api.github.com":
            if new.has_header("Authorization"):
                new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_AuthStrippingRedirectHandler())


def http_get_text(url: str, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "Slate practice-sheet feature"}
    # Optional token only for the GitHub API (shared-IP 60/hr unauthenticated
    # budget); never sent to any other host, never logged, and stripped again
    # if a redirect ever points anywhere else.
    if urllib.parse.urlsplit(url).netloc.lower() == "api.github.com":
        _tok = os.getenv("SLATE_GITHUB_TOKEN")
        if _tok:
            headers["Authorization"] = "Bearer " + _tok
    req = urllib.request.Request(url, headers=headers)
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# --- Username discovery -----------------------------------------------------

def normalize_username(raw: str) -> str:
    """Accept a bare username or any leetcode.com profile URL; return the username."""
    s = (raw or "").strip()
    if not s:
        raise SlateError("invalid_username", "Enter a LeetCode username or profile link.")
    m = _LC_LINK_RE.search(s)
    if m:
        s = m.group(1)
    else:
        s = s.split("?")[0].split("#")[0].strip().strip("/").split("/")[-1]
    if not USERNAME_RE.match(s):
        raise SlateError(
            "invalid_username",
            "That does not look like a LeetCode username. Use the profile link, e.g. https://leetcode.com/u/your-name/",
        )
    return s


def extract_leetcode_usernames(text: str):
    """All distinct LeetCode usernames linked from free text, in order of appearance."""
    if not text:
        return []
    found, seen = [], set()
    for match in _LC_LINK_RE.finditer(text):
        name = match.group(1)
        if name.lower() not in seen:
            seen.add(name.lower())
            found.append(name)
    for match in _LC_BARE_RE.finditer(text):
        name = match.group(1)
        if name.lower() in _BARE_BLOCKLIST or name.lower() in seen:
            continue
        seen.add(name.lower())
        found.append(name)
    return found


def extract_pdf_link_uris(data: bytes):
    """URIs hidden in PDF link annotations (a hyperlink on a name or icon carries
    the LeetCode URL without any visible text)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SlateError("resume_unreadable", "PDF support (pypdf) is not installed on this server.")
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = reader.pages
    except Exception as e:
        raise SlateError("resume_unreadable", f"Could not read this PDF: {e}")
    uris = []
    for page in pages:
        try:
            annots = page.get("/Annots") or []
        except Exception:
            continue
        for ref in annots:
            try:
                annot = ref.get_object()
                action = annot.get("/A")
                uri = (action.get("/URI") if action else None) or annot.get("/URI")
                if uri:
                    uris.append(str(uri))
            except Exception:
                continue
    return uris


def extract_pdf_leetcode_usernames(data: bytes, text: str = ""):
    """Usernames from a resume PDF: hyperlink annotations first, then visible text."""
    from .resume import extract_pdf_text

    names, seen = [], set()

    def add(candidate):
        try:
            name = normalize_username(candidate)
        except SlateError:
            return
        if name.lower() not in seen and name.lower() not in _BARE_BLOCKLIST:
            seen.add(name.lower())
            names.append(name)

    for uri in extract_pdf_link_uris(data):
        if "leetcode.com" in uri.lower():
            add(uri)
    if text:
        visible = text
    else:
        try:
            visible = extract_pdf_text(data) or ""
        except Exception:
            visible = ""  # annotation links above are still valid on their own
    for name in extract_leetcode_usernames(visible):
        add(name)
    return names


# --- Live public profile ----------------------------------------------------

_PROFILE_QUERY = """query ($username: String!) {
  matchedUser(username: $username) {
    username
    profile { realName ranking }
    submitStatsGlobal { acSubmissionNum { difficulty count } }
  }
  recentAcSubmissionList(username: $username, limit: %d) {
    title
    titleSlug
    timestamp
  }
}""" % RECENT_LIMIT


def fetch_public_profile(username: str, post=http_post_json) -> dict:
    """Public LeetCode data for a username: solved counts and up to RECENT_LIMIT
    most recent accepted submissions (the verified public surface)."""
    username = normalize_username(username)

    def produce():
        try:
            payload = post(LEETCODE_GRAPHQL_URL, {"query": _PROFILE_QUERY, "variables": {"username": username}})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise SlateError(
                "leetcode_unavailable",
                "Could not reach LeetCode's public profile service. Check the connection and try again.",
            ) from e
        if not isinstance(payload, dict) or "data" not in payload:
            raise SlateError("leetcode_unavailable", "LeetCode returned an unexpected response. Try again.")
        data = payload.get("data") or {}
        user = data.get("matchedUser")
        if not user:
            raise SlateError(
                "profile_not_found",
                "No public LeetCode profile found for that username. Check the spelling or paste the exact profile link.",
            )
        counts = {"all": 0, "easy": 0, "medium": 0, "hard": 0}
        for row in ((user.get("submitStatsGlobal") or {}).get("acSubmissionNum") or []):
            key = str(row.get("difficulty", "")).lower()
            if key in counts:
                counts[key] = int(row.get("count") or 0)
        recents = []
        for sub in data.get("recentAcSubmissionList") or []:
            try:
                day = datetime.fromtimestamp(int(sub.get("timestamp") or 0), tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError):
                day = None
            recents.append({
                "title": sub.get("title") or "",
                "slug": sub.get("titleSlug") or "",
                "date": day,
            })
        return {
            "username": user.get("username") or username,
            "realName": ((user.get("profile") or {}).get("realName")) or "",
            "ranking": (user.get("profile") or {}).get("ranking"),
            "solved": counts,
            "recentAccepted": recents,
            "profileUrl": "https://leetcode.com/u/" + urllib.parse.quote(user.get("username") or username) + "/",
            "scopeNote": SCOPE_NOTE,
        }

    return _cached("profile", username.lower(), produce)


# --- Company sheets -----------------------------------------------------------

def load_company_names() -> list:
    try:
        return json.loads(COMPANIES_JSON.read_text("utf-8"))
    except (OSError, ValueError):
        return []


def search_companies(query: str, limit: int = 20) -> list:
    q = (query or "").strip().lower()
    names = load_company_names()
    if not q:
        return []
    starts = [n for n in names if n.lower().startswith(q)]
    contains = [n for n in names if q in n.lower() and not n.lower().startswith(q)]
    return (starts + contains)[:limit]


def match_company(query: str):
    """Exact (case-insensitive) company match, or a SlateError with suggestions."""
    q = (query or "").strip()
    if not q:
        raise SlateError("company_not_found", "Enter the company you are applying to.")
    for name in load_company_names():
        if name.lower() == q.lower():
            return name
    suggestions = search_companies(q, 5)
    hint = (" Did you mean: " + ", ".join(suggestions) + "?") if suggestions else ""
    raise SlateError(
        "company_not_found",
        "No prebuilt question sheet found for \"%s\".%s" % (q, hint),
    )


def _row(link, title, frequency, difficulty="", topics=""):
    m = re.search(r"/problems/([a-z0-9-]+)/?", link or "")
    slug = m.group(1) if m else ""
    try:
        freq = float(frequency or 0)
    except (TypeError, ValueError):
        freq = 0.0
    return {
        "title": (title or "").strip(),
        "slug": slug,
        "difficulty": (difficulty or "").strip().title(),
        "frequency": freq,
        # Canonical link built from the validated slug only. A raw CSV link is
        # never passed through: a crafted sheet could otherwise plant a
        # javascript: (or lookalike-host) href that renders clickable.
        "link": ("https://leetcode.com/problems/" + slug + "/") if slug else "",
        "topics": (topics or "").strip(),
    }


def parse_community_csv(text: str) -> list:
    """Built-in MIT-licensed compilation schema: problem_link, problem_name, num_occur.
    num_occur is the sheet's reported occurrence count - no difficulty, no time window."""
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        rows.append(_row(raw.get("problem_link"), raw.get("problem_name"), raw.get("num_occur")))
    return [r for r in rows if r["title"] and r["slug"]]


def parse_user_csv(text: str) -> list:
    """A sheet the user uploads. Accepts the community schema above or the common
    Difficulty,Title,Frequency,Acceptance Rate,Link,Topics layout."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise SlateError("sheet_unreadable", "That CSV has no header row.")
    fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    rows = []
    if "problem_link" in fields and "problem_name" in fields:
        for raw in reader:
            rows.append(_row(raw.get(fields["problem_link"]), raw.get(fields["problem_name"]), raw.get(fields.get("num_occur", ""))))
    elif "title" in fields and "link" in fields:
        for raw in reader:
            rows.append(_row(raw.get(fields["link"]), raw.get(fields["title"]), raw.get(fields.get("frequency", "")),
                             raw.get(fields.get("difficulty", "")), raw.get(fields.get("topics", ""))))
    else:
        raise SlateError(
            "sheet_unreadable",
            "Unsupported CSV layout. Need problem_link,problem_name,num_occur or Difficulty,Title,Frequency,Link,Topics.",
        )
    rows = [r for r in rows if r["title"] and r["slug"]]
    if not rows:
        raise SlateError("sheet_unreadable", "No usable questions found in that CSV.")
    return rows


def _csv_url(company: str) -> str:
    return "%s/%s.csv" % (COMPANY_SHEET_BASE_URL, urllib.parse.quote(company))


def fetch_company_csv(company: str, get=http_get_text) -> str:
    url = _csv_url(company)

    def produce():
        try:
            return get(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SlateError("sheet_not_found", "The community sheet has no list for %s." % company) from e
            raise SlateError("sheet_unavailable", "Could not load the community question sheet. Try again.") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SlateError("sheet_unavailable", "Could not load the community question sheet. Try again.") from e

    return _cached("csv", company, produce)


def fetch_company_data_date(company: str, get=http_get_text):
    """Best-effort last-update date of the exact community CSV (None if unknown)."""
    url = "%s?path=%s&per_page=1" % (
        COMPANY_SHEET_COMMITS_URL,
        urllib.parse.quote(COMPANY_SHEET_COMMITS_PATH_PREFIX + company + ".csv"),
    )

    def produce():
        try:
            payload = json.loads(get(url, timeout=10.0))
            return payload[0]["commit"]["committer"]["date"][:10]
        except Exception:
            return None

    return _cached("csv_date", company, produce)


# --- Sheet building -----------------------------------------------------------

def build_sheet(profile: dict, rows: list, limit: int = SHEET_ROW_LIMIT) -> dict:
    """Merge a question list with the public profile. The ONLY solved signal is
    membership in the recent accepted list; everything else is honestly marked
    'not in recent public solves'."""
    recent_by_slug = {r["slug"]: r for r in profile.get("recentAccepted") or []}
    ordered = sorted(rows, key=lambda r: (-r["frequency"], r["title"].lower()))
    sheet_rows = []
    for row in ordered[:limit]:
        hit = recent_by_slug.get(row["slug"])
        sheet_rows.append({
            **row,
            "status": STATUS_RECENT if hit else STATUS_UNKNOWN,
            "solvedDate": (hit or {}).get("date"),
        })
    recent_count = sum(1 for r in sheet_rows if r["status"] == STATUS_RECENT)
    return {
        "rows": sheet_rows,
        "totalInList": len(rows),
        "shown": len(sheet_rows),
        "recentlySolvedShown": recent_count,
        "recentWindowSize": len(profile.get("recentAccepted") or []),
    }


def render_txt(profile: dict, company: str, source_label: str, sheet: dict, provenance: dict) -> str:
    solved = profile.get("solved") or {}
    lines = [
        "Slate practice sheet - %s" % company,
        "LeetCode profile: %s (%s)" % (profile.get("username"), profile.get("profileUrl")),
        "Public solved counts: %d total (Easy %d / Medium %d / Hard %d)"
        % (solved.get("all", 0), solved.get("easy", 0), solved.get("medium", 0), solved.get("hard", 0)),
        "",
        "How to read the status column:",
        "- 'Recently solved' = confirmed in your %d most recent PUBLIC accepted submissions." % RECENT_LIMIT,
        "- 'Not in recent public solves' = not in that recent window. It may still be solved;",
        "  Slate does not have your full solved history.",
        "",
        "Question data: %s, fetched %s%s."
        % (
            source_label,
            provenance.get("fetchedAt") or "unknown",
            (", source last updated " + provenance["dataDate"]) if provenance.get("dataDate") else "",
        ),
        "Showing %d of %d questions, ordered by the sheet's reported occurrence count."
        % (sheet["shown"], sheet["totalInList"]),
        "",
    ]
    for i, row in enumerate(sheet["rows"], 1):
        if row["status"] == STATUS_RECENT:
            status = "Recently solved" + (" on " + row["solvedDate"] if row.get("solvedDate") else "")
        else:
            status = "Not in recent public solves"
        diff = ("[%s] " % row["difficulty"].upper()) if row.get("difficulty") else ""
        lines.append(
            "%2d. %s%s - occurrences %s - %s\n    %s"
            % (i, diff, row["title"], ("%.1f" % row["frequency"]).rstrip("0").rstrip("."), status, row["link"])
        )
    lines.append("")
    return "\n".join(lines)


def _provenance(csv_url, data_date):
    return {
        "sourceUrl": COMPANY_SHEET_SOURCE_URL,
        "attribution": COMPANY_SHEET_ATTRIBUTION,
        "csvUrl": csv_url,
        "fetchedAt": datetime.now(timezone.utc).date().isoformat(),
        "dataDate": data_date,
    }


def build_practice_sheet(username: str, company_query: str,
                         post=http_post_json, get=http_get_text) -> dict:
    company = match_company(company_query)
    profile = fetch_public_profile(username, post=post)
    rows = parse_community_csv(fetch_company_csv(company, get=get))
    if not rows:
        raise SlateError("sheet_not_found", "The community sheet for %s is empty." % company)
    data_date = fetch_company_data_date(company, get=get)
    sheet = build_sheet(profile, rows)
    provenance = _provenance(_csv_url(company), data_date)
    source_label = COMPANY_SHEET_ATTRIBUTION + " - " + COMPANY_SHEET_SOURCE_URL
    return {
        "profile": profile,
        "company": company,
        "sheet": sheet,
        "provenance": provenance,
        "txt": render_txt(profile, company, source_label, sheet, provenance),
    }


def build_practice_sheet_from_csv(username: str, company_label: str, csv_text: str,
                                  post=http_post_json) -> dict:
    """Same sheet, built from a CSV the user uploaded. The label is the user's own
    naming; no community data or freshness claim is made."""
    label = (company_label or "").strip()[:120] or "Uploaded sheet"
    profile = fetch_public_profile(username, post=post)
    rows = parse_user_csv(csv_text)
    sheet = build_sheet(profile, rows)
    provenance = {
        "sourceUrl": None,
        "attribution": "Uploaded by you",
        "csvUrl": None,
        "fetchedAt": datetime.now(timezone.utc).date().isoformat(),
        "dataDate": None,
    }
    return {
        "profile": profile,
        "company": label,
        "sheet": sheet,
        "provenance": provenance,
        "txt": render_txt(profile, label, "a sheet you uploaded (no source or freshness verification)", sheet, provenance),
    }
