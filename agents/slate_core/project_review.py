"""GitHub project review feature.

Finds a user's public GitHub projects (from resume links or typed input), reads
ONLY what GitHub's public interface exposes, and produces an evidence-based
engineering review with a transparent signal rubric and grounded suggestions.

Honesty invariants (do not weaken):
- STATIC REVIEW ONLY. Slate reads README, dependency manifests, CI configs,
  test files and a byte-capped sample of source files. It never clones,
  installs, or executes repository code. A "met" signal means the evidence was
  found in the files; it does not prove code quality or correctness.
- Tests are read, not run. "Tests pass" is only ever reported when a named CI
  job conclusion is publicly observable on the analyzed commit, and then the
  job name and conclusion are quoted. Otherwise the outcome is UNKNOWN.
- Unknown is never zero. Private/deleted repos, unreadable files, rate-limit
  truncation and unobservable CI exclude that signal from the denominator and
  list it as unknown - they never count as failure.
- Stars/forks/activity are context, never rubric points.
- SSRF defense: user input can only select a GitHub owner/repo. The server
  fetches only the configured GitHub API and raw-content hosts, follows no
  redirect to any other host, and validates every path segment.
- Tests inject fake transports; the default transport hits the live public
  GitHub endpoints only on an explicit user action.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .service import SlateError

GITHUB_API_BASE = os.getenv("SLATE_GITHUB_API_BASE", "https://api.github.com").rstrip("/")
GITHUB_RAW_BASE = os.getenv("SLATE_GITHUB_RAW_BASE", "https://raw.githubusercontent.com").rstrip("/")

MAX_REPOS_PER_PASS = 5
MAX_CONTENT_BYTES_PER_REPO = 300_000
MAX_README_BYTES = 40_000
MAX_WORKFLOW_BYTES = 20_000
MAX_MANIFEST_BYTES = 20_000
MAX_TEST_FILE_BYTES = 20_000
MAX_SOURCE_FILE_BYTES = 30_000
MAX_TEST_FILES_READ = 12
MAX_SOURCE_FILES_READ = 12

CACHE_TTL_SECONDS = 600  # a cached view is served for 10 min; a refresh re-reads GitHub (costs API calls)

OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

_GH_REPO_LINK_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9][A-Za-z0-9._-]{0,99})",
    re.IGNORECASE,
)
_GH_PROFILE_LINK_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)(?![\w/.-])",
    re.IGNORECASE,
)
_PROFILE_BLOCKLIST = {
    "features", "topics", "marketplace", "pricing", "explore", "login", "join",
    "signup", "settings", "notifications", "about", "contact", "security",
    "site", "apps", "collections", "trending", "new", "organizations",
    "enterprise", "search", "sponsors", "customer-stories", "readme",
    "copilot", "education", "stars", "issues", "pulls", "codespaces",
}

MANIFEST_NAMES = {
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Gemfile", "composer.json", "pubspec.yaml", "Package.swift", "mix.exs",
}
# build config, NOT a dependency declaration - never satisfies "Dependencies declared"
BUILD_CONFIG_NAMES = {"makefile", "gnumakefile", "cmakelists.txt"}
LOCKFILE_NAMES = {
    "requirements.lock", "poetry.lock", "Pipfile.lock", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml", "go.sum", "Cargo.lock", "Gemfile.lock",
    "composer.lock", "pubspec.lock",
}
README_RE = re.compile(r"^readme(\.\w+)?$", re.IGNORECASE)
WORKFLOW_RE = re.compile(r"^\.github/workflows/[^/]+\.(yml|yaml)$", re.IGNORECASE)
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|spec|__tests__|testdata)/|(^|/)(test_|spec_)|"
    r"(_test|_spec|\.test|\.spec|\.tests)\.\w+$|Test\.(java|kt)$|_test\.go$",
    re.IGNORECASE,
)
SOURCE_RE = re.compile(
    r"\.(py|js|jsx|ts|tsx|mjs|c|cc|cpp|cxx|h|hpp|java|kt|go|rs|rb|php|cs|swift|scala|dart|lua|sh)$",
    re.IGNORECASE,
)
ENTRY_POINT_NAMES = {
    "main.py", "app.py", "__main__.py", "manage.py", "index.js", "index.ts",
    "main.js", "main.ts", "server.js", "server.ts", "main.go", "main.rs",
    "Main.java", "Program.cs", "main.c", "main.cpp",
}

# assertion / verification mechanisms per ecosystem (absence in a sampled test
# file means "style not detected - manual check", never "empty test")
ASSERTION_MECHANISMS = {
    "python assert": re.compile(r"\bassert\s+[^=]"),
    "unittest asserts": re.compile(r"\bself\.assert\w+\s*\("),
    "pytest raises": re.compile(r"\bpytest\.raises\b"),
    "hypothesis (property-based)": re.compile(r"\bfrom hypothesis\b|\bimport hypothesis\b|@given\("),
    "jest/vitest expect": re.compile(r"\bexpect\s*\("),
    "chai should": re.compile(r"\bshould\b[.\s]|\bchai\b"),
    "fast-check (property-based)": re.compile(r"\bfast-check\b|\bfc\.(assert|property)"),
    "node assert": re.compile(r"\bassert\.(strictEqual|deepStrictEqual|equal|ok|throws)\s*\("),
    "snapshot": re.compile(r"toMatchSnapshot|assertSnapshot|snapshottest"),
    "go testing": re.compile(r"\bt\.(Error|Errorf|Fatal|Fatalf)\s*\("),
    "rust asserts": re.compile(r"\bassert(_eq|_ne)?!\s*\("),
    "java/junit asserts": re.compile(r"\b(Assertions?\.)?(assertEquals|assertTrue|assertFalse|assertThrows|assertThat)\s*\("),
    "ruby rspec/minitest": re.compile(r"\bexpect\s*\(.*\)\s*\.to\b|\bassert(_equal)?\s"),
}
TEST_FUNCTION_RES = [
    re.compile(r"^\s*def\s+(test_\w+)\s*\(", re.MULTILINE),                      # python
    re.compile(r"^\s*(?:it|test)\s*\(\s*['\"`]([^'\"`]+)['\"`]", re.MULTILINE),  # js/ts
    re.compile(r"^\s*func\s+(Test\w+)\s*\(", re.MULTILINE),                      # go
    re.compile(r"#\[test\]"),                                                    # rust
    re.compile(r"^\s*@Test\b", re.MULTILINE),                                    # java/kotlin
    re.compile(r"^\s*def\s+(test\w*)\b", re.MULTILINE),                          # ruby
]
TEST_COMMAND_RE = re.compile(
    r"\b(pytest|py\.test|unittest|nosetests|npm\s+test|yarn\s+test|pnpm\s+test|"
    r"npx\s+(jest|vitest|mocha)|jest\b|vitest\b|mocha\b|go\s+test|cargo\s+test|"
    r"mvn\s+(test|verify)|gradle(w)?\s+test|bundle\s+exec\s+rspec|rspec\b|"
    r"phpunit|dotnet\s+test|mix\s+test)\b",
    re.IGNORECASE,
)
README_SETUP_HEADING_RE = re.compile(
    r"^#{1,4}\s.*(install|setup|getting\s*started|quick\s*start|quickstart|build|run\b|usage)",
    re.IGNORECASE | re.MULTILINE,
)
README_USAGE_HEADING_RE = re.compile(
    r"^#{1,4}\s.*(usage|example|how\s+to\s+use|getting\s*started|quick\s*start)",
    re.IGNORECASE | re.MULTILINE,
)
TEST_JOB_NAME_RE = re.compile(r"test|pytest|jest|vitest|mocha|spec|unittest|rspec|phpunit", re.IGNORECASE)

SCOPE_NOTE = (
    "Static review of PUBLIC GitHub files at one pinned commit. Slate reads README, "
    "dependency, CI and test files plus a byte-capped sample of source; it never runs "
    "repository code. A met signal means the evidence was found in the files - it is not "
    "a judgement of overall code quality or correctness. 'Tests pass' is only reported "
    "when a named CI job outcome is publicly visible, and then it is quoted. Signals "
    "Slate could not check are listed as unknown, never scored as failures."
)

_CACHE: dict = {}
_CACHE_MAX_ENTRIES = 256  # bounded memory: oldest quarter evicted when full


def reset_cache():
    _CACHE.clear()


# --- Transports (injectable in tests) ----------------------------------------

class _HostGuard(urllib.request.HTTPRedirectHandler):
    """Follow redirects only between the configured GitHub hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc.lower() not in _allowed_hosts():
            raise urllib.error.HTTPError(req.full_url, code, "redirect to disallowed host", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _allowed_hosts() -> set:
    return {
        urllib.parse.urlsplit(GITHUB_API_BASE).netloc.lower(),
        urllib.parse.urlsplit(GITHUB_RAW_BASE).netloc.lower(),
    }


def _open(url: str, timeout: float):
    if urllib.parse.urlsplit(url).netloc.lower() not in _allowed_hosts():
        raise SlateError("github_unavailable", "Internal error: unexpected fetch host.")
    headers = {
        "User-Agent": "Slate project-review feature (public repo read)",
        "Accept": "application/vnd.github+json",
    }
    # Optional: a token raises the shared-IP rate budget (60/hr unauthenticated,
    # which a shared hosting egress IP can exhaust) and is never logged.
    _tok = os.getenv("SLATE_GITHUB_TOKEN")
    if _tok:
        headers["Authorization"] = "Bearer " + _tok
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_HostGuard())
    return opener.open(req, timeout=timeout)


def http_get_json(url: str, timeout: float = 15.0):
    """JSON GET against the GitHub API host; maps public failure modes honestly."""
    try:
        with _open(url, timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        remaining = e.headers.get("x-ratelimit-remaining") if e.headers else None
        if e.code == 404:
            raise SlateError(
                "repo_not_found",
                "That repository is not publicly accessible - it may be private, renamed or deleted.",
            ) from e
        if e.code in (401, 403, 429) and (remaining == "0" or e.code == 429):
            raise SlateError(
                "github_rate_limited",
                "GitHub's public request limit is reached for now. Results that were already loaded are shown; try the rest again later.",
            ) from e
        if e.code in (401, 403):
            raise SlateError(
                "github_rate_limited",
                "GitHub refused the request (public access limit). Results already loaded are shown; try again later.",
            ) from e
        raise SlateError("github_unavailable", "Could not reach GitHub's public API. Try again.") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise SlateError("github_unavailable", "Could not reach GitHub's public API. Check the connection and try again.") from e


def http_get_text(url: str, timeout: float = 20.0) -> str:
    try:
        with _open(url, timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SlateError("repo_not_found", "A file that should exist at the pinned commit was not found.") from e
        raise SlateError("github_unavailable", "Could not read a file from GitHub. Try again.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SlateError("github_unavailable", "Could not read a file from GitHub. Check the connection and try again.") from e


# --- Input parsing / validation ----------------------------------------------

def parse_repo_ref(value: str):
    """Strict public-GitHub owner/repo parsing. Accepts 'owner/repo' or a
    github.com URL (extra path segments like /tree/... are ignored). Rejects
    every other host, userinfo, ports and IP literals."""
    s = (value or "").strip()
    if not s:
        raise SlateError("invalid_repo", "Enter a GitHub repository link, e.g. https://github.com/owner/repo")
    if "@" in s.split("/")[0:1][0] or s.lower().startswith(("javascript:", "data:", "file:")):
        raise SlateError("invalid_repo", "That is not a public GitHub repository link.")
    s = s.split("#")[0].split("?")[0].strip()
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE).strip().strip("/")
    if s.lower().startswith("github.com/"):
        s = s[len("github.com/"):]
    elif "github.com" in s.lower():
        # host-like but not plain github.com (subdomain, userinfo, port...) - reject
        raise SlateError("invalid_repo", "Only plain https://github.com/owner/repo links are supported.")
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        raise SlateError("invalid_repo", "Need both owner and repository name, e.g. https://github.com/owner/repo")
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not OWNER_RE.match(owner) or not REPO_RE.match(repo):
        raise SlateError("invalid_repo", "That does not look like a GitHub owner/repository name.")
    return owner, repo


def parse_github_username(value: str) -> str:
    s = (value or "").strip()
    if not s:
        raise SlateError("invalid_github_username", "Enter a GitHub username or profile link.")
    s = s.split("#")[0].split("?")[0].strip()
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE).strip().strip("/")
    if s.lower().startswith("github.com/"):
        s = s[len("github.com/"):]
    elif "github.com" in s.lower():
        raise SlateError("invalid_github_username", "Only plain https://github.com/username links are supported.")
    name = s.split("/")[0]
    if not OWNER_RE.match(name):
        raise SlateError("invalid_github_username", "That does not look like a GitHub username.")
    return name


def extract_github_links(text: str) -> dict:
    """Ordered, de-duplicated repo refs and profile usernames from free text."""
    repos, users, seen_repos, seen_users = [], [], set(), set()
    if not text:
        return {"repos": repos, "usernames": users}
    for m in _GH_REPO_LINK_RE.finditer(text):
        owner, repo = m.group(1), m.group(2)
        if repo.lower().endswith(".git"):
            repo = repo[:-4]
        if owner.lower() in _PROFILE_BLOCKLIST or repo.lower() in _PROFILE_BLOCKLIST:
            continue
        if not REPO_RE.match(repo):
            continue
        key = (owner.lower(), repo.lower())
        if key not in seen_repos:
            seen_repos.add(key)
            repos.append({"owner": owner, "repo": repo, "ref": "%s/%s" % (owner, repo)})
    for m in _GH_PROFILE_LINK_RE.finditer(text):
        name = m.group(1)
        if name.lower() in _PROFILE_BLOCKLIST or name.lower() in seen_users:
            continue
        seen_users.add(name.lower())
        users.append(name)
    return {"repos": repos, "usernames": users}


def extract_pdf_github_links(data: bytes, text: str = "") -> dict:
    """GitHub links from a resume PDF: hyperlink annotations first (a link can
    hide behind an icon or name), then visible text."""
    from .leetcode_sheet import extract_pdf_link_uris
    from .resume import extract_pdf_text

    repos, users, seen_repos, seen_users = [], [], set(), set()

    def merge(found):
        for r in found["repos"]:
            key = (r["owner"].lower(), r["repo"].lower())
            if key not in seen_repos:
                seen_repos.add(key)
                repos.append(r)
        for u in found["usernames"]:
            if u.lower() not in seen_users:
                seen_users.add(u.lower())
                users.append(u)

    for uri in extract_pdf_link_uris(data):
        if "github.com" in uri.lower():
            merge(extract_github_links(uri))
    visible = text
    if not visible:
        try:
            visible = extract_pdf_text(data) or ""
        except Exception:
            visible = ""  # annotation links above are still valid on their own
    merge(extract_github_links(visible))
    return {"repos": repos, "usernames": users}


# --- Live public reads ---------------------------------------------------------

def _api(path: str) -> str:
    return GITHUB_API_BASE + path


def _raw(owner: str, repo: str, sha: str, path: str) -> str:
    return "%s/%s/%s/%s/%s" % (
        GITHUB_RAW_BASE,
        urllib.parse.quote(owner), urllib.parse.quote(repo), urllib.parse.quote(sha),
        "/".join(urllib.parse.quote(seg) for seg in path.split("/")),
    )


class _Budget:
    """Counts GitHub API calls (raw file reads are not API-rate-limited)."""

    def __init__(self):
        self.api_calls = 0
        self.raw_reads = 0
        self.content_bytes = 0


def list_user_repos(username: str, get_json=http_get_json) -> dict:
    name = parse_github_username(username)
    try:
        payload = get_json(_api("/users/%s/repos?per_page=100&sort=pushed" % urllib.parse.quote(name)))
    except SlateError as e:
        if e.code == "repo_not_found":
            raise SlateError("github_user_not_found",
                             "No public GitHub profile found for that username. Check the spelling.") from e
        raise
    if not isinstance(payload, list):
        raise SlateError("github_unavailable", "GitHub returned an unexpected response. Try again.")
    repos = []
    for r in payload:
        if not isinstance(r, dict):
            continue
        repos.append({
            "name": r.get("name") or "",
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "stars": r.get("stargazers_count") or 0,
            "pushedAt": (r.get("pushed_at") or "")[:10],
            "fork": bool(r.get("fork")),
            "archived": bool(r.get("archived")),
            "ref": (r.get("full_name") or "").strip(),
        })
    return {"username": name, "repos": [r for r in repos if r["ref"]]}


def _resolve_head(owner: str, repo: str, get_json, budget: _Budget):
    budget.api_calls += 1
    meta = get_json(_api("/repos/%s/%s" % (urllib.parse.quote(owner), urllib.parse.quote(repo))))
    branch = meta.get("default_branch") or "main"
    budget.api_calls += 1
    head = get_json(_api("/repos/%s/%s/branches/%s" % (
        urllib.parse.quote(owner), urllib.parse.quote(repo), urllib.parse.quote(branch))))
    sha = ((head.get("commit") or {}).get("sha")) or ""
    if not sha:
        raise SlateError("github_unavailable", "Could not resolve the repository's latest commit.")
    return meta, branch, sha


def _classify_tree(tree_payload: dict):
    files = []
    for entry in (tree_payload.get("tree") or []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path") or ""
        files.append({"path": path, "size": int(entry.get("size") or 0)})
    readmes = [f for f in files if README_RE.match(f["path"].split("/")[-1]) and "/" not in f["path"]]
    workflows = [f for f in files if WORKFLOW_RE.match(f["path"])]
    manifests = [f for f in files if f["path"].split("/")[-1] in MANIFEST_NAMES and "/" not in f["path"]]
    build_configs = [f["path"] for f in files
                     if f["path"].split("/")[-1].lower() in BUILD_CONFIG_NAMES and "/" not in f["path"]]
    lockfiles = [f["path"] for f in files if f["path"].split("/")[-1] in LOCKFILE_NAMES and "/" not in f["path"]]
    tests = [f for f in files if TEST_PATH_RE.search(f["path"]) and SOURCE_RE.search(f["path"])]
    sources = [f for f in files if SOURCE_RE.search(f["path"]) and not TEST_PATH_RE.search(f["path"])]
    return {
        "files": files, "readmes": readmes, "workflows": workflows,
        "manifests": manifests, "build_configs": build_configs, "lockfiles": lockfiles, "tests": tests, "sources": sources,
        "truncated": bool(tree_payload.get("truncated")),
    }


def _fetch_capped(get_text, url, cap: int, budget: _Budget):
    budget.raw_reads += 1
    text = get_text(url)
    data = text[: cap // 1]
    budget.content_bytes += min(len(text), cap)
    return data


def _detect_test_mechanisms(text: str):
    found = [name for name, rx in ASSERTION_MECHANISMS.items() if rx.search(text)]
    funcs = 0
    for rx in TEST_FUNCTION_RES:
        funcs += len(rx.findall(text))
    return found, funcs


def _signal(name: str, status: str, evidence: str):
    """status: met | partial | not_met | unknown (unknown is excluded from scoring)."""
    return {"name": name, "status": status, "evidence": evidence}


def _section_has_content(text: str, heading_re) -> tuple:
    """(heading_found, has_content): a heading only counts when at least one
    non-empty, non-heading line follows it inside the section. A deeper
    (sub)heading continues the section; a same-or-higher level heading ends it.
    Line-based: regex alternations can end a match mid-heading."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if heading_re.match(line):
            level = len(line) - len(line.lstrip("#"))
            for s in lines[i + 1:]:
                st = s.strip()
                hm = re.match(r"^(#{1,6})\s", st)
                if hm and len(hm.group(1)) <= level:
                    break
                if st and not hm:
                    return True, True
            return True, False
    return False, False


def _readme_section_signal(name, readme_text, heading_re, readme_path):
    found, content = _section_has_content(readme_text, heading_re)
    if found and content:
        return _signal(name, "met", "section with content found in " + readme_path)
    if found:
        return _signal(name, "partial", "section heading present in " + readme_path + " but the section is empty")
    return _signal(name, "not_met", "no matching section heading found in " + readme_path)


def analyze_repo(owner: str, repo: str = None, get_json=http_get_json, get_text=http_get_text) -> dict:
    """Full static review of one public repo at its pinned head commit.
    Accepts ('owner', 'repo') or a single 'owner/repo' / URL value."""
    owner, repo = parse_repo_ref("%s/%s" % (owner, repo) if repo else owner)
    cache_key = "%s/%s" % (owner.lower(), repo.lower())
    now = time.time()
    hit = _CACHE.get(("analysis", cache_key))
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        cached = dict(hit[1])
        cached["fromCache"] = True
        return cached

    budget = _Budget()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta, branch, sha = _resolve_head(owner, repo, get_json, budget)

    budget.api_calls += 1
    tree_payload = get_json(_api("/repos/%s/%s/git/trees/%s?recursive=1" % (
        urllib.parse.quote(owner), urllib.parse.quote(repo), urllib.parse.quote(sha))))
    tree = _classify_tree(tree_payload if isinstance(tree_payload, dict) else {})

    # observed CI outcomes on this exact commit
    check_runs, statuses = [], []
    try:
        budget.api_calls += 1
        payload = get_json(_api("/repos/%s/%s/commits/%s/check-runs?per_page=50" % (
            urllib.parse.quote(owner), urllib.parse.quote(repo), urllib.parse.quote(sha))))
        for c in (payload.get("check_runs") or []):
            if isinstance(c, dict) and c.get("status") == "completed":
                check_runs.append({"name": c.get("name") or "", "conclusion": c.get("conclusion") or ""})
        if not check_runs:
            budget.api_calls += 1
            payload = get_json(_api("/repos/%s/%s/commits/%s/status" % (
                urllib.parse.quote(owner), urllib.parse.quote(repo), urllib.parse.quote(sha))))
            for s in (payload.get("statuses") or []):
                if isinstance(s, dict):
                    statuses.append({"name": s.get("context") or "", "conclusion": s.get("state") or ""})
    except SlateError:
        pass  # CI observation is best-effort; absence is reported as unknown

    # --- content reads (byte-capped, prioritized: docs -> config -> tests -> source)
    coverage = {"filesRead": [], "treeTruncated": tree["truncated"]}

    readme_text, readme_path = "", ""
    if tree["readmes"]:
        readme_path = tree["readmes"][0]["path"]
        readme_text = _fetch_capped(get_text, _raw(owner, repo, sha, readme_path), MAX_README_BYTES, budget)
        coverage["filesRead"].append(readme_path)

    manifest_texts = {}
    for f in tree["manifests"][:4]:
        manifest_texts[f["path"]] = _fetch_capped(
            get_text, _raw(owner, repo, sha, f["path"]), MAX_MANIFEST_BYTES, budget)
        coverage["filesRead"].append(f["path"])

    workflow_texts = {}
    for f in tree["workflows"][:4]:
        workflow_texts[f["path"]] = _fetch_capped(
            get_text, _raw(owner, repo, sha, f["path"]), MAX_WORKFLOW_BYTES, budget)
        coverage["filesRead"].append(f["path"])

    test_reads = []
    for f in tree["tests"][:MAX_TEST_FILES_READ]:
        if budget.content_bytes >= MAX_CONTENT_BYTES_PER_REPO:
            break
        text = _fetch_capped(get_text, _raw(owner, repo, sha, f["path"]), MAX_TEST_FILE_BYTES, budget)
        mechs, funcs = _detect_test_mechanisms(text)
        test_reads.append({"path": f["path"], "mechanisms": mechs, "testFunctions": funcs, "bytes": len(text)})
        coverage["filesRead"].append(f["path"])

    def _source_priority(f):
        name = f["path"].split("/")[-1]
        return (0 if name in ENTRY_POINT_NAMES else 1, -f["size"])

    source_reads = 0
    for f in sorted(tree["sources"], key=_source_priority)[:MAX_SOURCE_FILES_READ]:
        if budget.content_bytes >= MAX_CONTENT_BYTES_PER_REPO:
            break
        _fetch_capped(get_text, _raw(owner, repo, sha, f["path"]), MAX_SOURCE_FILE_BYTES, budget)
        source_reads += 1
        coverage["filesRead"].append(f["path"])

    # --- signals
    signals = []

    # Documentation
    has_readme = bool(readme_path)
    signals.append(_signal(
        "README present", "met" if has_readme else "not_met",
        readme_path if has_readme else "no README file at the repository root"))
    if has_readme:
        signals.append(_readme_section_signal("README has setup/run steps", readme_text, README_SETUP_HEADING_RE, readme_path))
        signals.append(_readme_section_signal("README has usage examples", readme_text, README_USAGE_HEADING_RE, readme_path))
    else:
        signals.append(_signal("README has setup/run steps", "unknown", "no README to read"))
        signals.append(_signal("README has usage examples", "unknown", "no README to read"))
    signals.append(_signal(
        "GitHub repo description (metadata)", "met" if (meta.get("description") or "").strip() else "not_met",
        "description is set" if (meta.get("description") or "").strip() else "the GitHub repo description metadata is empty"))

    # Dependencies: a dependency manifest declares deps; build config (Makefile
    # and friends) does NOT - a project with only build config may genuinely
    # have no external dependencies, so that case is unknown, not met/not_met.
    has_manifest = bool(manifest_texts)
    if has_manifest:
        signals.append(_signal("Dependencies declared", "met", ", ".join(manifest_texts)))
    elif tree["build_configs"]:
        signals.append(_signal(
            "Dependencies declared", "unknown",
            "only build config found (%s) - build config is not a dependency declaration; the project may have no external dependencies"
            % ", ".join(tree["build_configs"])))
    else:
        signals.append(_signal(
            "Dependencies declared", "not_met",
            "no recognized dependency manifest (requirements.txt, package.json, go.mod, ...)"))
    if has_manifest:
        pinned, unpinned, lock = 0, 0, bool(tree["lockfiles"])
        req = manifest_texts.get("requirements.txt")
        if req is not None:
            lines = [l.strip() for l in req.splitlines() if l.strip() and not l.strip().startswith("#")]
            pinned = sum(1 for l in lines if "==" in l)
            unpinned = len(lines) - pinned
            if lock or (lines and unpinned == 0):
                status = "met"
            elif pinned:
                status = "partial"
            else:
                status = "not_met"
            evidence = "%d of %d requirements pinned with ==%s" % (
                pinned, len(lines), "; lockfile " + tree["lockfiles"][0] if lock else "; no lockfile")
        elif lock:
            status, evidence = "met", "lockfile " + tree["lockfiles"][0]
        else:
            status, evidence = "unknown", "no lockfile found; pinning inside %s not checked by Slate" % ", ".join(manifest_texts)
        signals.append(_signal("Dependencies pinned/locked", status, evidence))
    elif tree["build_configs"]:
        signals.append(_signal("Dependencies pinned/locked", "unknown",
                               "build config is not a dependency manifest; pinning not assessed"))
    else:
        signals.append(_signal("Dependencies pinned/locked", "unknown", "no dependency manifest to check"))

    # Tests
    n_test_files = len(tree["tests"])
    signals.append(_signal(
        "Automated tests present", "met" if n_test_files else "not_met",
        ("%d test files found (%d read)" % (n_test_files, len(test_reads))) if n_test_files else "no test files detected by path conventions"))
    if n_test_files:
        if not test_reads:
            signals.append(_signal("Tests are substantive", "unknown",
                                   "test files exist but none could be read within the byte budget"))
        else:
            total_funcs = sum(t["testFunctions"] for t in test_reads)
            no_mech = [t["path"] for t in test_reads if not t["mechanisms"]]
            mech_names = sorted({m for t in test_reads for m in t["mechanisms"]})
            if total_funcs and not no_mech:
                status = "met"
            elif total_funcs or len(no_mech) < len(test_reads):
                status = "partial"
            else:
                status = "not_met"
            evidence = "%d test functions across %d sampled files; mechanisms: %s%s" % (
                total_funcs, len(test_reads), ", ".join(mech_names) or "none detected",
                ("; no assertion mechanism detected in: " + ", ".join(no_mech[:4])) if no_mech else "")
            signals.append(_signal("Tests are substantive", status, evidence))
    else:
        signals.append(_signal("Tests are substantive", "unknown", "no test files to read"))

    # CI
    n_workflows = len(tree["workflows"])
    signals.append(_signal(
        "CI configured", "met" if n_workflows else "not_met",
        ", ".join(wf.split("/")[-1] for wf in workflow_texts) if n_workflows else "no .github/workflows/ files"))
    if n_workflows:
        test_workflows = [p for p, t in workflow_texts.items() if TEST_COMMAND_RE.search(t)]
        signals.append(_signal(
            "CI runs a test command", "met" if test_workflows else "not_met",
            ("test command found in " + ", ".join(p.split("/")[-1] for p in test_workflows)) if test_workflows
            else "no recognizable test command (pytest, npm test, go test, ...) in the workflow files"))
    else:
        signals.append(_signal("CI runs a test command", "unknown", "no CI workflow to inspect"))

    observed = [(c["name"], c["conclusion"]) for c in check_runs] + [
        (s["name"], s["conclusion"]) for s in statuses]
    test_jobs = [(n, c) for n, c in observed if TEST_JOB_NAME_RE.search(n or "")]
    if test_jobs:
        failing = [(n, c) for n, c in test_jobs if c in ("failure", "timed_out", "cancelled")]
        passing = [(n, c) for n, c in test_jobs if c == "success"]
        if failing:
            status = "not_met"
        elif passing:
            status = "met"
        else:
            status = "unknown"
        evidence = "; ".join("job '%s': %s" % (n, c) for n, c in test_jobs[:5]) + " (on commit " + sha[:7] + ")"
    elif observed:
        status = "unknown"
        evidence = "checks ran on this commit (%s) but none is identifiable as a test job" % ", ".join(
            "'%s': %s" % (n, c) for n, c in observed[:4])
    else:
        status = "unknown"
        evidence = "no publicly visible CI job outcome on this commit - Slate does not run tests"
    signals.append(_signal("Observed test outcome on HEAD", status, evidence))

    # Licensing
    license_id = ((meta.get("license") or {}) or {}).get("spdx_id") or ""
    signals.append(_signal(
        "License present", "met" if license_id and license_id != "NOASSERTION" else "not_met",
        ("license: " + license_id) if license_id and license_id != "NOASSERTION" else "no license detected by GitHub"))

    # --- scoring: met=1, partial=0.5, not_met=0; unknown excluded and listed
    applicable = [s for s in signals if s["status"] != "unknown"]
    unknown = [s for s in signals if s["status"] == "unknown"]
    met_points = sum(1.0 if s["status"] == "met" else 0.5 if s["status"] == "partial" else 0.0
                     for s in applicable)
    score = {"metPoints": met_points, "applicable": len(applicable),
             "unknownSignals": [s["name"] for s in unknown]}

    # --- suggestions, each grounded in the signal evidence
    suggestions = []
    by_name = {s["name"]: s for s in signals}

    def suggest(signal_name, text):
        s = by_name.get(signal_name)
        if s and s["status"] in ("not_met", "partial"):
            suggestions.append({"signal": signal_name, "suggestion": text, "evidence": s["evidence"]})

    suggest("README present",
            "Add a README.md at the repo root: what the project does, how to run it, and a usage example.")
    suggest("README has setup/run steps",
            "Add a '## Installation' / '## Run' section with the exact commands a stranger would need.")
    suggest("README has usage examples",
            "Add a '## Usage' section with a concrete example (command or screenshot).")
    suggest("GitHub repo description (metadata)",
            "Set the one-line GitHub repo description - it is the first thing a visitor sees.")
    suggest("Dependencies declared",
            "Declare dependencies in a standard manifest (requirements.txt / pyproject.toml / package.json / go.mod).")
    if by_name.get("Dependencies pinned/locked", {}).get("status") in ("not_met", "partial"):
        suggestions.append({
            "signal": "Dependencies pinned/locked",
            "suggestion": "Pin dependency versions (== in requirements.txt) or commit a lockfile so builds are reproducible.",
            "evidence": by_name["Dependencies pinned/locked"]["evidence"],
        })
    suggest("Automated tests present",
            "Start a small automated test suite (e.g. tests/test_*.py with pytest) covering the core path.")
    if by_name.get("Tests are substantive", {}).get("status") in ("not_met", "partial"):
        ev = by_name["Tests are substantive"]["evidence"]
        suggestions.append({
            "signal": "Tests are substantive",
            "suggestion": "Some test files show no recognizable assertion mechanism - verify these tests actually check behavior.",
            "evidence": ev,
        })
    suggest("CI configured",
            "Add a GitHub Actions workflow (.github/workflows/) that runs your tests on every push.")
    suggest("CI runs a test command",
            "The existing workflow does not run a recognizable test command - add a step that runs the test suite.")
    if by_name.get("Observed test outcome on HEAD", {}).get("status") == "not_met":
        suggestions.append({
            "signal": "Observed test outcome on HEAD",
            "suggestion": "A test job is publicly failing on the latest commit - fix it before showing the repo.",
            "evidence": by_name["Observed test outcome on HEAD"]["evidence"],
        })
    suggest("License present",
            "Add a LICENSE file (e.g. MIT or Apache-2.0) so others know how they may use the code.")

    languages = {}
    for f in tree["sources"]:
        ext = f["path"].rsplit(".", 1)[-1].lower() if "." in f["path"] else ""
        if ext:
            languages[ext] = languages.get(ext, 0) + 1
    top_languages = sorted(languages.items(), key=lambda kv: -kv[1])[:4]

    result = {
        "ref": "%s/%s" % (owner, repo),
        "url": "https://github.com/%s/%s" % (owner, repo),
        "commit": sha,
        "branch": branch,
        "checkedAt": checked_at,
        "fromCache": False,
        "cacheNote": "results refresh after %d minutes; refreshing re-reads GitHub." % (CACHE_TTL_SECONDS // 60),
        "context": {
            "description": meta.get("description") or "",
            "stars": meta.get("stargazers_count") or 0,
            "forks": meta.get("forks_count") or 0,
            "openIssues": meta.get("open_issues_count") or 0,
            "createdAt": (meta.get("created_at") or "")[:10],
            "pushedAt": (meta.get("pushed_at") or "")[:10],
            "languages": top_languages,
            "fork": bool(meta.get("fork")),
            "archived": bool(meta.get("archived")),
        },
        "signals": signals,
        "score": score,
        "suggestions": suggestions,
        "coverage": {
            "filesTotal": len(tree["files"]),
            "sourceFiles": len(tree["sources"]),
            "testFiles": n_test_files,
            "testFilesRead": len(test_reads),
            "sourceFilesRead": source_reads,
            "filesRead": coverage["filesRead"],
            "contentBytesRead": budget.content_bytes,
            "treeTruncated": tree["truncated"],
        },
        "limits": {"apiCallsUsed": budget.api_calls, "rawReads": budget.raw_reads},
        "scopeNote": SCOPE_NOTE,
    }
    if len(_CACHE) >= _CACHE_MAX_ENTRIES:
        for k, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_MAX_ENTRIES // 4]:
            _CACHE.pop(k, None)
    _CACHE[("analysis", cache_key)] = (now, result)
    return result


def build_review(repo_inputs, get_json=http_get_json, get_text=http_get_text) -> dict:
    """Review up to MAX_REPOS_PER_PASS repos. A repo that fails (private, deleted,
    unreadable) becomes an honest per-repo entry; hitting GitHub's rate limit
    stops the pass and marks the remaining repos not checked."""
    if not repo_inputs:
        raise SlateError("invalid_repo", "Pick at least one repository to review.")
    if len(repo_inputs) > MAX_REPOS_PER_PASS:
        raise SlateError("too_many_repos",
                         "Review up to %d repositories at a time (GitHub's public request limit is shared)." % MAX_REPOS_PER_PASS)
    reviews, rate_limited = [], False
    for value in repo_inputs:
        if rate_limited:
            reviews.append({"ref": str(value)[:120], "status": "not_checked",
                            "reason": "not checked - GitHub's public request limit was reached during this pass"})
            continue
        try:
            analysis = analyze_repo(str(value), get_json=get_json, get_text=get_text)
            analysis["status"] = "reviewed"
            reviews.append(analysis)
        except SlateError as e:
            code = e.code
            message = e.message
            if code == "github_rate_limited":
                rate_limited = True
            reviews.append({"ref": str(value)[:120], "status": "inaccessible" if code in (
                "repo_not_found", "invalid_repo") else "error",
                "errorCode": code, "reason": message})
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "reviews": reviews,
        "checkedAt": checked_at,
        "scopeNote": SCOPE_NOTE,
        "rateLimited": rate_limited,
        "txt": render_txt(reviews, checked_at),
    }


def render_txt(reviews, checked_at: str) -> str:
    lines = [
        "Slate project review",
        "Checked: %s (UTC)" % checked_at,
        "",
        "How to read this review:",
        "- Static review of public files at one pinned commit per repo. Nothing was executed.",
        "- 'met' means the evidence was found in the files; it does not prove code quality.",
        "- 'unknown' means Slate could not check that signal - it is never counted against the project.",
        "- Test outcomes are only quoted when a CI job result is publicly visible.",
        "",
    ]
    for r in reviews:
        lines.append("=" * 60)
        lines.append(r.get("ref") or "(unknown repo)")
        if r.get("status") != "reviewed":
            lines.append("  %s" % (r.get("reason") or "not reviewed"))
            lines.append("")
            continue
        ctx = r["context"]
        lines.append("  %s | commit %s | checked %s%s" % (
            r["url"], r["commit"][:7], r["checkedAt"], " (cached)" if r.get("fromCache") else ""))
        lines.append("  context: %d stars, %d forks, pushed %s, languages: %s" % (
            ctx["stars"], ctx["forks"], ctx["pushedAt"] or "?",
            ", ".join(ext for ext, _ in ctx["languages"]) or "unknown"))
        sc = r["score"]
        lines.append("  engineering signals: %.1f of %d applicable met%s" % (
            sc["metPoints"], sc["applicable"],
            ("; unknown (not scored): " + ", ".join(sc["unknownSignals"])) if sc["unknownSignals"] else ""))
        for s in r["signals"]:
            lines.append("    [%s] %s - %s" % (s["status"].upper().replace("_", " "), s["name"], s["evidence"]))
        cov = r["coverage"]
        lines.append("  coverage: read %d files (%d of %d source, %d of %d tests), %d KB%s" % (
            len(cov["filesRead"]), cov["sourceFilesRead"], cov["sourceFiles"],
            cov["testFilesRead"], cov["testFiles"], cov["contentBytesRead"] // 1024,
            "; tree listing TRUNCATED - review is partial" if cov["treeTruncated"] else ""))
        if r["suggestions"]:
            lines.append("  suggestions:")
            for sug in r["suggestions"]:
                lines.append("    - %s (evidence: %s)" % (sug["suggestion"], sug["evidence"]))
        lines.append("")
    return "\n".join(lines)
