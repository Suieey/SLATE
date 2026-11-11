"""Tests for the match explanation fields (matchedSkills, missingSkills, reason).

Pure core tests: no fastapi needed. Run with the rest:
    python3 -m unittest discover -s tests -v
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService
from slate_core.jobs import match_score, skill_breakdown, match_reason, search_jobs

RESUME = """Asha Verma
asha@example.com
B.Tech Computer Science, IIITM Gwalior, 2027
Intern at ExampleCo (3 months)
Skills: Python, Git, Excel, communication
"""


class Breakdown(unittest.TestCase):
    def test_matched_and_missing_keep_job_order(self):
        matched, missing = skill_breakdown(["python", "git", "excel"],
                                           ["python", "sql", "excel", "statistics"])
        self.assertEqual(matched, ["python", "excel"])
        self.assertEqual(missing, ["sql", "statistics"])

    def test_case_insensitive_on_resume_side(self):
        matched, missing = skill_breakdown(["Python"], ["python", "sql"])
        self.assertEqual(matched, ["python"])
        self.assertEqual(missing, ["sql"])

    def test_no_resume_skills(self):
        matched, missing = skill_breakdown([], ["python", "sql"])
        self.assertEqual(matched, [])
        self.assertEqual(missing, ["python", "sql"])

    def test_no_resume_argument_at_all(self):
        matched, missing = skill_breakdown(None, ["python"])
        self.assertEqual((matched, missing), ([], ["python"]))

    def test_no_job_skills(self):
        self.assertEqual(skill_breakdown(["python"], []), ([], []))
        self.assertEqual(match_reason([], []),
                         "This listing names no required skills, so there is nothing to match against.")


class Reason(unittest.TestCase):
    def test_partial_match(self):
        self.assertEqual(match_reason(["python", "excel"], ["sql", "statistics"]),
                         "Matches 2 of 4 required skills: python, excel. Missing: sql, statistics.")

    def test_no_match(self):
        self.assertEqual(match_reason([], ["sql"]),
                         "Matches none of the 1 required skill. Missing: sql.")

    def test_full_match_omits_missing_clause(self):
        self.assertEqual(match_reason(["python"], []),
                         "Matches 1 of 1 required skill: python.")


class SearchJobsExplain(unittest.TestCase):
    SKILLS = ["python", "git", "excel", "communication"]

    def test_every_job_carries_explanation_fields(self):
        for j in search_jobs("", "", self.SKILLS):
            self.assertIn("matchedSkills", j)
            self.assertIn("missingSkills", j)
            self.assertIn("reason", j)

    def test_job_001_breakdown_and_score(self):
        j = next(x for x in search_jobs("", "", self.SKILLS) if x["jobId"] == "job_001")
        self.assertEqual(j["matchScore"], 0.5)
        self.assertEqual(j["matchedSkills"], ["python", "excel"])
        self.assertEqual(j["missingSkills"], ["sql", "statistics"])
        self.assertEqual(j["reason"],
                         "Matches 2 of 4 required skills: python, excel. Missing: sql, statistics.")

    def test_score_formula_unchanged(self):
        self.assertEqual(match_score(["python", "sql", "excel"],
                                     ["python", "sql", "excel", "statistics"]), 0.75)

    def test_deterministic_with_new_fields(self):
        a = search_jobs("analyst", "", self.SKILLS)
        b = search_jobs("analyst", "", self.SKILLS)
        self.assertEqual(a, b)

    def test_existing_filters_still_apply(self):
        self.assertEqual([j["jobId"] for j in search_jobs("", "indore", self.SKILLS)],
                         ["job_001", "job_004"])
        self.assertEqual(search_jobs("zzzz", "", self.SKILLS), [])


class ServiceLevel(unittest.TestCase):
    def test_service_jobs_includes_explanation(self):
        s = SlateService()
        rid = s.upload_resume(RESUME)["resumeId"]
        jobs = s.jobs("analyst", "", rid)["jobs"]
        self.assertTrue(jobs)
        self.assertIn("reason", jobs[0])
        self.assertIn("matchedSkills", jobs[0])

    def test_service_jobs_without_resume(self):
        s = SlateService()
        j = next(x for x in s.jobs("", "")["jobs"] if x["jobId"] == "job_001")
        self.assertEqual(j["matchedSkills"], [])
        self.assertEqual(j["missingSkills"], ["python", "sql", "excel", "statistics"])


if __name__ == "__main__":
    unittest.main()
