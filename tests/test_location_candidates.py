"""location_candidates: every place a label names; Remote region kept whole."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.jobs_curation import location_candidates, normalize_location


class Candidates(unittest.TestCase):
    def test_all_cities_kept(self):
        self.assertEqual(location_candidates("Pune, Mumbai"), ["pune", "mumbai"])

    def test_slash_and_semicolon_split_and_aliases_apply_per_part(self):
        self.assertEqual(location_candidates("Bangalore/Bombay; Gurgaon"),
                         ["bengaluru", "mumbai", "gurugram"])

    def test_new_delhi_is_delhi(self):
        self.assertEqual(location_candidates("New Delhi"), ["delhi"])

    def test_remote_region_restriction_is_kept(self):
        self.assertEqual(location_candidates("Remote, US"), ["remote, us"])
        self.assertNotEqual(location_candidates("Remote, US"), location_candidates("Remote, India"))
        self.assertEqual(location_candidates("Remote"), ["remote"])

    def test_duplicates_removed_order_kept(self):
        self.assertEqual(location_candidates("Pune, pune , Mumbai"), ["pune", "mumbai"])

    def test_non_string_and_empty_are_safe(self):
        self.assertEqual(location_candidates(None), [])
        self.assertEqual(location_candidates(5), [])
        self.assertEqual(normalize_location(5), "")

    def test_normalize_location_still_returns_first_city(self):
        self.assertEqual(normalize_location("Bangalore, Mumbai"), "bengaluru")
        self.assertEqual(normalize_location("Pune/Mumbai"), "pune")



if __name__ == "__main__":
    unittest.main()
