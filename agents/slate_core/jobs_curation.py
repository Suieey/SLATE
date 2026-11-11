"""Dedupe and freshness for job listings. Pure functions, source-independent.

Freshness vocabulary (deliberately precise):
    active            seen in the latest complete refresh and not past the stale cutoff
    stale             still listed, but older than the posted-age cutoff - age warning only
    no_longer_listed  absent after a successful COMPLETE refresh of its source;
                      means what it says, never "expired": the posting may have been
                      filled, paused, renamed or temporarily removed
    unknown           the last refresh failed or was partial - no evidence either way
    closed            source-confirmed closed, or an explicit application deadline
                      stated by the source has passed

Location rules: location_candidates() returns every place a label names (comma,
semicolon, slash separated, aliases per part); normalize_location() is the first
one only. A label starting with "remote" is kept whole so a region restriction is
never dropped. Limits: "Remote, US", "Remote - US" and "Remote (US)" are NOT treated
as equal, and no place database is used, so a region and a city cannot be told apart.
Duplicate hints compare the full candidate sets and stay silent when they differ,
because a missed hint is safer than conflating distinct listings.

Dedupe rule: a listing's identity is (source, sourceId). Two listings with the same
title, company and location can still be separate requisitions, so nothing is ever
merged automatically. Cross-source sameness is surfaced as an unverified hint only.
"""
import re
from datetime import datetime

ACTIVE = "active"
STALE = "stale"
NO_LONGER_LISTED = "no_longer_listed"
UNKNOWN = "unknown"
CLOSED = "closed"

# Refresh outcomes a source adapter can report for a stored listing.
PRESENT = "present"
MISSING_COMPLETE_REFRESH = "missing_after_complete_refresh"
FETCH_FAILED = "fetch_failed"
SOURCE_CLOSED = "source_closed"
DEADLINE_PASSED = "deadline_passed"

STALE_AFTER_DAYS = 30

_LOCATION_ALIASES = {
    "bangalore": "bengaluru",
    "gurgaon": "gurugram",
    "bombay": "mumbai",
    "new delhi": "delhi",
}


def listing_key(listing):
    """Stable identity: source + the source's own requisition id."""
    return (listing["source"], listing["sourceId"])


def location_candidates(location):
    """Every canonical place a listing's location label names, in order, no repeats.

    'Pune, Mumbai' -> ['pune', 'mumbai']; separators are comma, semicolon, slash.
    A label that starts with 'remote' is kept whole ('remote, us' stays distinct
    from 'remote, india') so a region restriction is never dropped. Non-strings
    and blanks give []. Use this for filtering and matching: a listing must be
    found by ANY city it names."""
    if not isinstance(location, str) or not location.strip():
        return []
    text = " ".join(location.lower().split())
    if text.startswith("remote"):
        return [text]
    out = []
    for part in re.split(r"[,;/]", text):
        part = part.strip()
        part = _LOCATION_ALIASES.get(part, part)
        if part and part not in out:
            out.append(part)
    return out


def normalize_location(location):
    """Canonical lowercase FIRST city (kept for compatibility); aliases collapse
    common variants. Prefer location_candidates() for filtering. 'Remote' stays
    its own label - never rewritten to a place."""
    cands = location_candidates(location)
    return cands[0] if cands else ""


def deadline_passed(deadline, now):
    """True only when a source-stated application deadline is confidently past.

    `now` must be timezone-aware. Returns None (unknown) for a missing,
    unparseable, date-only or timezone-NAIVE deadline: callers must not mark a
    listing closed on unknown evidence. A naive timestamp carries no timezone,
    so interpreting it would be a guess - the safe answer is unknown.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not deadline:
        return None
    try:
        then = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        return None
    return now > then


def _age_days(iso_ts, now):
    try:
        then = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    if then.tzinfo is None:
        # No timezone means the age cannot be known - same rule as deadlines in
        # deadline_passed(): never guess. Unknown age stays "active": the listing
        # was seen in the latest complete refresh.
        return None
    # Fractional days: flooring to whole days would keep a listing "active"
    # for up to a day past the stale cutoff.
    return (now - then).total_seconds() / 86400


def classify_freshness(listing, observed, now, stale_after_days=STALE_AFTER_DAYS):
    """Map a refresh observation to a freshness state. `listing` is the stored
    normalized listing, `now` a timezone-aware datetime for deterministic tests."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # DEADLINE_PASSED observations should come from deadline_passed() above so
    # timezone-naive or unparseable deadlines never reach here as "closed".
    if observed == SOURCE_CLOSED or observed == DEADLINE_PASSED:
        return CLOSED
    if observed == FETCH_FAILED:
        return UNKNOWN
    if observed == MISSING_COMPLETE_REFRESH:
        return NO_LONGER_LISTED
    if observed == PRESENT:
        age = _age_days(listing.get("updatedAt") or "", now)
        if age is not None and age > stale_after_days:
            return STALE
        return ACTIVE
    raise ValueError("unknown observation: %r" % (observed,))


def _canon(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def cross_source_hint(a, b):
    """Unverified sameness hint across sources, or None. Never merges, never
    drops a listing: callers keep both and may display the hint."""
    if a.get("source") is None or b.get("source") is None or a.get("source") == b.get("source"):
        return None  # same source: distinct sourceIds are distinct requisitions
    places_a, places_b = location_candidates(a.get("location")), location_candidates(b.get("location"))
    company_a, title_a = _canon(a.get("company")), _canon(a.get("title"))
    if (places_a and set(places_a) == set(places_b)
            and company_a and company_a == _canon(b.get("company"))
            and title_a and title_a == _canon(b.get("title"))):
        return ("possible duplicate of %s/%s (unverified - separate requisitions "
                "can share title and location)" % (b.get("source", "?"), b.get("sourceId", "?")))
    return None
