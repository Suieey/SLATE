"""Tests for wiring the curation helpers into job search.

Covers the normalized location filter and the additive freshness field on
search results. Pure core tests: no fastapi needed.
    python3 -m unittest discover -s tests -v
"""
import os, sys, unittest
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import jobs as J
from slate_core.jobs_curation import ACTIVE, CLOSED
from slate_core.sample_data import JOBS as SAMPLE_JOBS

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

FAKE = [
    {"jobId": "j_blr", "title": "Backend Intern", "company": "Acme", "location": "Bengaluru",
     "deadline": "2026-12-01", "url": "https://example.com/a", "skills": ["python"]},
    {"jobId": "j_multi", "title": "Analyst", "company": "Beta", "location": "Pune, Maharashtra",
     "deadline": "2026-12-01", "url": "https://example.com/b", "skills": ["sql"]},
    {"jobId": "j_remote", "title": "Designer", "company": "Cato", "location": "Remote",
     "deadline": "2026-12-01", "url": "https://example.com/c", "skills": ["figma"]},
    {"jobId": "j_dual", "title": "SRE", "company": "Duo", "location": "Bengaluru, Mumbai",
     "deadline": "2026-12-01", "url": "https://example.com/d", "skills": ["docker"]},
]


def with_jobs(jobs):
    """Swap the listing source for one test, restoring it after."""
    class Ctx:
        def __enter__(self):
            self.old = J.JOBS
            J.JOBS = jobs
        def __exit__(self, *exc):
            J.JOBS = self.old
    return Ctx()


class LocationFilter(unittest.TestCase):
    def test_alias_matches_canonical_city(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Bangalore", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_blr", "j_dual"])

    def test_case_and_whitespace_insensitive(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="  bengaluru ", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_blr", "j_dual"])

    def test_first_city_of_multi_region_label(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="pune", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_multi"])

    def test_second_city_of_multi_city_label_matches(self):
        # A listing posted for two cities must not go invisible in the second.
        with with_jobs(FAKE):
            out = J.search_jobs(location="mumbai", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_dual"])

    def test_alias_applies_to_every_named_place(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Bombay", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_dual"])

    def test_region_part_of_label_matches(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Maharashtra", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_multi"])

    def test_remote_stays_its_own_label(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Remote", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_remote"])

    def test_remote_with_region_keeps_its_restriction(self):
        # "Remote, India" is a region-restricted remote posting: a plain
        # Remote search must not claim it.
        fake = [dict(FAKE[2], jobId="j_rin", location="Remote, India")]
        with with_jobs(fake):
            out = J.search_jobs(location="Remote", now=NOW)
        self.assertEqual(out, [])

    def test_remote_region_matches_its_exact_label(self):
        fake = [dict(FAKE[2], jobId="j_rin", location="Remote, India")]
        with with_jobs(fake):
            out = J.search_jobs(location="remote, india", now=NOW)
        self.assertEqual([x["jobId"] for x in out], ["j_rin"])

    def test_remote_is_never_matched_by_a_place(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Indore", now=NOW)
        self.assertEqual(out, [])

    def test_display_location_is_not_rewritten(self):
        with with_jobs(FAKE):
            out = J.search_jobs(location="Bangalore", now=NOW)
        self.assertEqual(out[0]["location"], "Bengaluru")

    def test_empty_location_returns_everything(self):
        with with_jobs(FAKE):
            out = J.search_jobs(now=NOW)
        self.assertEqual(len(out), 4)


class FreshnessField(unittest.TestCase):
    def test_results_carry_freshness(self):
        out = J.search_jobs(now=NOW)
        self.assertTrue(out)
        for x in out:
            self.assertIn("freshness", x)

    def test_sample_listings_are_active(self):
        # Date-only deadlines are unknown evidence, never a close.
        out = J.search_jobs(now=NOW)
        for x in out:
            self.assertEqual(x["freshness"], ACTIVE)

    def test_confidently_past_deadline_closes(self):
        past = (NOW - timedelta(days=2)).isoformat()
        fake = [dict(FAKE[0], deadline=past)]
        with with_jobs(fake):
            out = J.search_jobs(now=NOW)
        self.assertEqual(out[0]["freshness"], CLOSED)

    def test_future_deadline_stays_active(self):
        future = (NOW + timedelta(days=2)).isoformat()
        fake = [dict(FAKE[0], deadline=future)]
        with with_jobs(fake):
            out = J.search_jobs(now=NOW)
        self.assertEqual(out[0]["freshness"], ACTIVE)

    def test_date_only_deadline_never_closes(self):
        fake = [dict(FAKE[0], deadline="2020-01-01")]
        with with_jobs(fake):
            out = J.search_jobs(now=NOW)
        self.assertEqual(out[0]["freshness"], ACTIVE)

    def test_naive_deadline_never_closes(self):
        fake = [dict(FAKE[0], deadline="2020-01-01T00:00:00")]
        with with_jobs(fake):
            out = J.search_jobs(now=NOW)
        self.assertEqual(out[0]["freshness"], ACTIVE)

    def test_closed_listings_are_not_dropped(self):
        past = (NOW - timedelta(days=2)).isoformat()
        fake = [dict(FAKE[0], deadline=past)]
        with with_jobs(fake):
            out = J.search_jobs(now=NOW)
        self.assertEqual(len(out), 1)

    def test_now_defaults_to_current_time(self):
        # No `now` passed: still works and carries the field.
        out = J.search_jobs()
        self.assertTrue(all("freshness" in x for x in out))

    def test_sample_suite_untouched_by_now(self):
        # Deterministic: same now, same output.
        a = J.search_jobs(now=NOW)
        b = J.search_jobs(now=NOW)
        self.assertEqual(a, b)


class SourceIdentity(unittest.TestCase):
    def test_demo_listings_get_demo_source_identity(self):
        listing = J._as_listing(SAMPLE_JOBS[0])
        self.assertEqual((listing["source"], listing["sourceId"]),
                         ("mock", SAMPLE_JOBS[0]["jobId"]))

    def test_listing_with_own_source_keeps_it(self):
        j = dict(FAKE[0], source="greenhouse", sourceId="123")
        listing = J._as_listing(j)
        self.assertEqual((listing["source"], listing["sourceId"]), ("greenhouse", "123"))


if __name__ == "__main__":
    unittest.main()
