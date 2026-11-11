"""Regression tests: tailoring must use the same skill matching as the match
explanation (PR #14 made scoring case/whitespace-insensitive and dedupe repeats;
the tailor draft and claim check must agree with it)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.tailor import build_draft, check_claims

RESUME_TEXT = ("Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
               "Intern at ExampleCo (3 months)\nSkills: Python, Git, Excel, communication")


class TailorMatching(unittest.TestCase):
    def test_capitalized_job_skill_is_matched_not_a_gap(self):
        d = build_draft({"name": "A", "skills": ["python"], "experience": [], "education": []},
                        {"title": "Backend Engineer", "company": "C", "skills": ["Python", "FastAPI"]})
        self.assertEqual(d["claims"], ["Python"])
        self.assertEqual(d["gaps"], ["FastAPI"])

    def test_repeated_and_messy_job_skills_count_once(self):
        d = build_draft({"name": "A", "skills": [" PYTHON "], "experience": [], "education": []},
                        {"title": "T", "company": "C", "skills": ["python", "Python", " sql "]})
        self.assertEqual(d["claims"], ["python"])
        self.assertEqual(d["gaps"], ["sql"])

    def test_check_claims_ignores_case_and_whitespace(self):
        parsed = {"skills": ["python", "sql"]}
        self.assertEqual(check_claims(parsed, ["Python", " sql "]), [])
        self.assertEqual(check_claims(parsed, ["Ruby"]), ["Ruby"])


class EndToEndConsistency(unittest.TestCase):
    def test_jobs_explanation_and_tailor_draft_agree(self):
        import slate_core.jobs as J
        from slate_core import SlateService
        saved = J.JOBS
        J.JOBS = [{"jobId": "jx", "title": "Backend Engineer", "company": "C",
                   "location": "Indore", "deadline": "2026-12-01", "url": "u",
                   "skills": ["Python", "FastAPI"]}]
        try:
            svc = SlateService()
            rid = svc.upload_resume(RESUME_TEXT)["resumeId"]
            job = next(x for x in svc.jobs("", "", rid)["jobs"] if x["jobId"] == "jx")
            d = svc.tailor(rid, "jx")
            self.assertEqual(job["matchedSkills"], d["claimsChecked"])
            self.assertEqual(job["missingSkills"], d["skillGaps"])
        finally:
            J.JOBS = saved


if __name__ == "__main__":
    unittest.main()
