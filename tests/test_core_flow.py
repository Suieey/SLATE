import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core import SlateService, SlateError

RESUME = """Asha Verma
asha@example.com
B.Tech Computer Science, IIITM Gwalior, 2027
Intern at ExampleCo (3 months)
Skills: Python, Git, Excel, communication
"""

class Flow(unittest.TestCase):
    def setUp(self):
        self.s = SlateService()
        self.rid = self.s.upload_resume(RESUME)["resumeId"]

    def test_a_parse(self):
        p = self.s.upload_resume(RESUME)["parsed"]
        self.assertEqual(p["name"], "Asha Verma")
        self.assertIn("python", p["skills"])
        self.assertEqual(p["education"][0]["year"], 2027)
        self.assertEqual(p["experience"][0]["org"], "ExampleCo")

    def test_a_broken_file_gives_error_shape(self):
        with self.assertRaises(SlateError) as c:
            self.s.upload_resume("")
        self.assertEqual(set(c.exception.to_dict()["error"]), {"code", "message"})

    def test_b_matches_deterministic_and_empty(self):
        a = self.s.jobs("analyst", resume_id=self.rid)
        b = self.s.jobs("analyst", resume_id=self.rid)
        self.assertEqual(a, b)
        self.assertTrue(all(0 <= j["matchScore"] <= 1 for j in a["jobs"]))
        self.assertEqual(self.s.jobs("zzzz")["jobs"], [])

    def test_c_d_approval_gate(self):
        d = self.s.tailor(self.rid, "job_001")
        self.assertEqual(d["status"], "draft")
        with self.assertRaises(SlateError) as c:   # no export of unapproved draft
            self.s.export_draft(d["draftId"])
        self.assertEqual(c.exception.code, "draft_not_approved")
        self.s.decide(d["draftId"], "approve")
        self.assertIn("coverNote", self.s.export_draft(d["draftId"]))
        new = self.s.edit_draft(d["draftId"], coverNote="Edited")
        self.assertNotEqual(new["draftId"], d["draftId"])
        with self.assertRaises(SlateError):        # edit invalidates: new draft not approved
            self.s.export_draft(new["draftId"])

    def test_d_rejected_cannot_be_used(self):
        d = self.s.tailor(self.rid, "job_001")
        self.s.decide(d["draftId"], "reject")
        with self.assertRaises(SlateError):
            self.s.decide(d["draftId"], "approve")
        with self.assertRaises(SlateError):
            self.s.export_draft(d["draftId"])

    def test_c_draft_claims_only_resume_skills(self):
        d = self.s.tailor(self.rid, "job_001")
        self.assertNotIn("sql", d["claimsChecked"])
        self.assertIn("sql", d["skillGaps"])

    def test_e_roadmap_traces_to_gaps(self):
        ms = self.s.roadmap(self.rid, "Data Analyst")["milestones"]
        self.assertIn("sql", [m["skill"] for m in ms])
        self.assertNotIn("python", [m["skill"] for m in ms])
        with self.assertRaises(SlateError):
            self.s.roadmap(self.rid, "Astronaut")

    def test_f_interview_memory(self):
        s1 = self.s.start_interview("Data Analyst")["sessionId"]
        self.s.answer_interview(s1, "short")
        fb = self.s.interview_feedback(s1)
        self.assertEqual(fb["transcriptRef"], s1)
        self.assertTrue(fb["weakAreas"])
        s2 = self.s.start_interview("Data Analyst")
        self.assertTrue(s2["carriedFromEarlier"])
        self.assertIn("Last time", s2["firstQuestion"])

    def test_unknown_ids(self):
        for fn in (lambda: self.s.tailor("res_999", "job_001"), lambda: self.s.tailor(self.rid, "job_999"),
                   lambda: self.s.decide("draft_999", "approve"), lambda: self.s.interview_feedback("int_999")):
            with self.assertRaises(SlateError):
                fn()

if __name__ == "__main__":
    unittest.main()
