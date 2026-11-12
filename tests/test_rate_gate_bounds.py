"""The tracked-key map is hard-capped: a flood of fresh distinct keys fails
closed once pruning idle entries cannot bring the map back under the cap."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.rate_gate import RateGate  # noqa: E402
from slate_core.service import SlateError  # noqa: E402


def test_fresh_key_flood_fails_closed(monkeypatch):
    monkeypatch.setenv("SLATE_RATE_MAX_TRACKED", "10")
    monkeypatch.setenv("SLATE_RATE_FETCH_USER", "5")
    monkeypatch.setenv("SLATE_RATE_FETCH_GLOBAL", "100000")
    g = RateGate()
    for i in range(9):
        g.check("fetch", f"user-{i}")       # 10 keys: at, not over, the cap
    overflow = 0
    for i in range(9, 40):
        try:
            g.check("fetch", f"user-{i}")   # brand-new keys over the cap: refused
        except SlateError as e:
            assert e.code == "rate_limited"
            overflow += 1
    assert overflow > 0, "fresh keys must be refused once the cap is exceeded"
    assert len(g._hits) <= 11, f"map grew unbounded: {len(g._hits)}"
    g.check("fetch", "user-0")              # already-tracked key keeps working


def test_cap_recovers_after_window_slides(monkeypatch):
    monkeypatch.setenv("SLATE_RATE_MAX_TRACKED", "5")
    monkeypatch.setenv("SLATE_RATE_FETCH_USER", "50")
    monkeypatch.setenv("SLATE_RATE_FETCH_GLOBAL", "100000")
    g = RateGate()
    g.buckets["fetch"] = (50, 0.05, 100000)  # 50ms window for the test
    for i in range(4):
        g.check("fetch", f"user-{i}")       # 5 keys: at, not over, the cap
    time.sleep(0.08)                          # every entry now idle past window
    g.check("fetch", "fresh-1")               # 6 keys: next check prunes...
    g.check("fetch", "fresh-2")               # ...so new keys are accepted again
