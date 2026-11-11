import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService, SlateError

RESUME = """Asha Verma
B.Tech Computer Science, IIITM Gwalior, 2027
Intern at ExampleCo (3 months)
Skills: Python, Git, Excel. Scored 8.1 CGPA, 72% in class 12.
"""

class Claims(unittest.TestCase):
    def setUp(self):
        self.s = SlateService()
        self.rid = self.s.upload_resume(RESUME)["resumeId"]
        self.d = self.s.tailor(self.rid, "job_001")["draftId"]

    def reject(self, **upd):
        with self.assertRaises(SlateError) as c:
            self.s.edit_draft(self.d, **upd)
        self.assertEqual(c.exception.code, "unsupported_claim")
        return c.exception.message

    def test_supported_edit_is_accepted(self):
        new = self.s.edit_draft(self.d, coverNote="I know Python and Excel and finished a 3 month internship. 8.1 CGPA.")
        self.assertNotEqual(new["draftId"], self.d)

    def test_unsupported_skill(self):
        self.assertIn("'sql'", self.reject(coverNote="Strong in SQL and Python."))
        self.assertIn("'react'", self.reject(tailoredResume="Skills: React"))

    def test_inflated_experience(self):
        self.assertIn("exceeds", self.reject(coverNote="I have 3 years of experience."))
        self.assertIn("exceeds", self.reject(coverNote="6 months of industry work"))
        self.assertIn("exceeds", self.reject(coverNote="2+ yrs experience"))

    def test_numbers_not_in_resume(self):
        self.assertIn("percentage", self.reject(coverNote="Improved accuracy by 40%"))
        self.assertIn("GPA", self.reject(coverNote="CGPA 9.4"))
        self.assertIn("degree", self.reject(coverNote="MBA graduate"))

    def test_failed_edit_creates_no_draft(self):
        n = len(self.s.approvals._drafts)
        self.reject(coverNote="10 years of Java")
        self.assertEqual(len(self.s.approvals._drafts), n)

    def test_approve_and_export_revalidate(self):
        """Even if content is changed behind the service's back, approve and export fail closed."""
        self.s.approvals._drafts[self.d]["content"]["coverNote"] = "Expert in SQL"
        with self.assertRaises(SlateError):
            self.s.decide(self.d, "approve")
        self.s.approvals._drafts[self.d]["status"] = "approved"
        with self.assertRaises(SlateError):
            self.s.export_draft(self.d)

    def test_known_gaps_are_not_detected(self):
        """Documented limit: paraphrase and named employers are NOT caught by the rule check."""
        new = self.s.edit_draft(self.d, coverNote="I led engineering at Google.")
        self.assertTrue(new["draftId"])

if __name__ == "__main__":
    unittest.main()
