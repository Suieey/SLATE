"""Regression tests: skill matching must ignore case/whitespace on BOTH sides,
count a repeated required skill once, and keep score and explanation consistent."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.jobs import match_score, skill_breakdown, match_reason


class SkillNormalization(unittest.TestCase):
    def test_job_side_case_is_ignored(self):
        self.assertEqual(skill_breakdown(["python"], ["Python", "SQL"]), (["Python"], ["SQL"]))

    def test_resume_side_whitespace_is_ignored(self):
        self.assertEqual(skill_breakdown([" Python "], ["python"]), (["python"], []))

    def test_score_uses_same_normalization(self):
        self.assertEqual(match_score([" PYTHON"], ["Python", "sql"]), 0.5)

    def test_repeated_required_skill_counts_once(self):
        matched, missing = skill_breakdown(["python"], ["python", "Python", "sql"])
        self.assertEqual((matched, missing), (["python"], ["sql"]))
        self.assertEqual(match_score(["python"], ["python", "python", "sql"]), 0.5)

    def test_score_agrees_with_breakdown(self):
        job = ["Python", "python", "SQL", " excel "]
        have = ["python", "EXCEL"]
        m, x = skill_breakdown(have, job)
        self.assertEqual(match_score(have, job), round(len(m) / (len(m) + len(x)), 2))
        self.assertIn("2 of 3", match_reason(m, x))

    def test_blank_skills_are_ignored(self):
        self.assertEqual(skill_breakdown(["", "  "], ["python", ""]), ([], ["python"]))

    def test_bare_string_resume_is_one_skill_not_characters(self):
        self.assertEqual(skill_breakdown("python", ["python"]), (["python"], []))


if __name__ == "__main__":
    unittest.main()


class SearchQueryNormalization(unittest.TestCase):
    """The text query must follow the same case rules as skill scoring."""

    def test_lowercase_query_matches_capitalized_skill(self):
        import slate_core.jobs as J
        saved = J.JOBS
        J.JOBS = [{"jobId": "jx", "title": "Backend Engineer", "company": "C",
                   "location": "Indore", "deadline": "2026-12-01", "url": "u",
                   "skills": ["Python", "FastAPI"]}]
        try:
            self.assertEqual([j["jobId"] for j in J.search_jobs(query="python")], ["jx"])
        finally:
            J.JOBS = saved
