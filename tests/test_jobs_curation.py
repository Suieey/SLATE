"""Tests for listing dedupe and freshness semantics.

Pure core tests: no network, no fastapi.
    python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.jobs_curation import (
    ACTIVE, STALE, NO_LONGER_LISTED, UNKNOWN, CLOSED,
    PRESENT, MISSING_COMPLETE_REFRESH, FETCH_FAILED, SOURCE_CLOSED, DEADLINE_PASSED,
    listing_key, normalize_location, classify_freshness, cross_source_hint,
    deadline_passed,
)

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def listing(**kw):
    base = {"source": "greenhouse", "sourceId": "123", "title": "Data Analyst",
            "company": "ExampleCo", "location": "Bengaluru, India",
            "applyUrl": "https://www.exampleco.com/jobs/123",
            "updatedAt": "2026-11-01T10:00:00+00:00"}
    base.update(kw)
    return base


class Keys(unittest.TestCase):
    def test_key_is_source_plus_source_id(self):
        self.assertEqual(listing_key(listing()), ("greenhouse", "123"))

    def test_same_requisition_different_sources_are_different_keys(self):
        self.assertNotEqual(listing_key(listing()),
                            listing_key(listing(source="ashby", sourceId="123")))


class Locations(unittest.TestCase):
    def test_alias_collapses(self):
        self.assertEqual(normalize_location("Bangalore, India"), "bengaluru")
        self.assertEqual(normalize_location("Gurgaon"), "gurugram")
        self.assertEqual(normalize_location("Bombay"), "mumbai")

    def test_takes_first_segment_and_lowercases(self):
        self.assertEqual(normalize_location("Pune, Maharashtra, India"), "pune")
        self.assertEqual(normalize_location("Hyderabad; Remote, United States"), "hyderabad")

    def test_remote_is_not_rewritten(self):
        self.assertEqual(normalize_location("Remote, Canada"), "remote, canada")  # region restriction kept

    def test_empty(self):
        self.assertEqual(normalize_location(""), "")
        self.assertEqual(normalize_location(None), "")


class Freshness(unittest.TestCase):
    def test_present_and_recent_is_active(self):
        self.assertEqual(classify_freshness(listing(), PRESENT, NOW), ACTIVE)

    def test_present_but_old_is_stale(self):
        old = listing(updatedAt="2026-09-01T00:00:00+00:00")
        self.assertEqual(classify_freshness(old, PRESENT, NOW), STALE)

    def test_present_with_unparseable_date_is_active_not_stale(self):
        self.assertEqual(classify_freshness(listing(updatedAt=None), PRESENT, NOW), ACTIVE)
        self.assertEqual(classify_freshness(listing(updatedAt="garbage"), PRESENT, NOW), ACTIVE)

    def test_missing_after_complete_refresh_is_no_longer_listed_not_expired(self):
        self.assertEqual(classify_freshness(listing(), MISSING_COMPLETE_REFRESH, NOW),
                         NO_LONGER_LISTED)

    def test_fetch_failure_is_unknown(self):
        self.assertEqual(classify_freshness(listing(), FETCH_FAILED, NOW), UNKNOWN)

    def test_source_closure_and_past_deadline_are_closed(self):
        self.assertEqual(classify_freshness(listing(), SOURCE_CLOSED, NOW), CLOSED)
        self.assertEqual(classify_freshness(listing(), DEADLINE_PASSED, NOW), CLOSED)

    def test_unknown_observation_raises(self):
        with self.assertRaises(ValueError):
            classify_freshness(listing(), "vanished?", NOW)


class DeadlinePassed(unittest.TestCase):
    def test_aware_past_deadline_is_passed(self):
        self.assertIs(deadline_passed("2026-11-01T00:00:00+00:00", NOW), True)

    def test_aware_future_deadline_is_not_passed(self):
        self.assertIs(deadline_passed("2026-12-01T00:00:00+00:00", NOW), False)

    def test_offset_timezone_compared_correctly(self):
        # 2026-11-08 03:00 IST = 2026-11-07 21:30 UTC: still future at NOW (11-07 00:00 UTC)
        self.assertIs(deadline_passed("2026-11-08T03:00:00+05:30", NOW), False)

    def test_naive_deadline_is_unknown_not_guessed(self):
        self.assertIsNone(deadline_passed("2026-11-01T00:00:00", NOW))
        self.assertIsNone(deadline_passed("2026-11-01", NOW))

    def test_missing_or_garbage_is_unknown(self):
        self.assertIsNone(deadline_passed(None, NOW))
        self.assertIsNone(deadline_passed("", NOW))
        self.assertIsNone(deadline_passed("next Friday", NOW))


class CrossSourceHint(unittest.TestCase):
    def test_same_company_title_location_hints(self):
        a = listing()
        b = listing(source="ashby", sourceId="abc", title="Data Analyst",
                    location="Bangalore, India")  # alias per part; full location set must match
        hint = cross_source_hint(a, b)
        self.assertIn("possible duplicate", hint)
        self.assertIn("unverified", hint)

    def test_same_key_gives_no_hint(self):
        self.assertIsNone(cross_source_hint(listing(), listing()))

    def test_different_title_or_location_gives_no_hint(self):
        a = listing()
        self.assertIsNone(cross_source_hint(a, listing(source="ashby", sourceId="x",
                                                       title="Senior Data Analyst")))
        self.assertIsNone(cross_source_hint(a, listing(source="ashby", sourceId="x",
                                                       location="Pune")))


if __name__ == "__main__":
    unittest.main()
