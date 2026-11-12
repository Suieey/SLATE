"""Regression tests for the explain-reply format robustness fix.

The guard itself is unchanged: a bullet still needs tags that name real source
blocks and every number/name in it must appear in the cited blocks. These tests
pin which reply FORMATS the reader now tolerates (numbered lists, comma tags,
lowercase tags, bold) and which CONTENT failures still discard (unsupported
counts, unsupported names, unknown tags, no tags).

Pure core tests, no fastapi:
    python3 -m pytest tests/test_explain_format.py -q
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.ai_service import AISlateService, explain_finish
from slate_core.service import SlateError
from slate_core.llm import MockLLM

RESUME = """Aarav Mehta
Email: aarav.mehta@example.com | Phone: +91 90000 00000 | Indore, India
B.Tech Computer Science, Example Institute of Technology, 2022-2026
Software Intern, DemoSoft Labs, Jun 2025 - Aug 2025
Built a Flask API for inventory tracking used by 3 internal teams
Wrote unit tests raising coverage from 40% to 78%
Skills: Python, JavaScript, Flask, SQL, Git, HTML, CSS"""


class ExplainFormat(unittest.TestCase):
    def setUp(self):
        self.svc = AISlateService()
        r = self.svc.upload_resume(RESUME)
        self.prep = self.svc.explain_prepare(r["resumeId"], client=MockLLM())

    def finish(self, reply):
        return explain_finish(self.prep, reply)

    # --- formats that must now survive (grounded content, variant markup) ---
    def test_numbered_list_passes(self):
        out = self.finish("1. Python, Flask and SQL are listed as skills [S7]\n"
                          "2. Contact details are present [S2]")
        self.assertEqual(out["explanation"],
                         ["Python, Flask and SQL are listed as skills",
                          "Contact details are present"])

    def test_comma_tags_pass_and_display_clean(self):
        out = self.finish("- Contact details are present [S1, S2]")
        self.assertEqual(out["explanation"], ["Contact details are present"])
        self.assertEqual([s["id"] for s in out["items"][0]["sources"]], ["S1", "S2"])

    def test_lowercase_tags_pass(self):
        out = self.finish("- Python and Flask are listed [s7]")
        self.assertEqual(out["explanation"], ["Python and Flask are listed"])

    def test_bold_markers_removed(self):
        out = self.finish("- **Python**, Flask and SQL are listed as skills [S7]")
        self.assertEqual(out["explanation"], ["Python, Flask and SQL are listed as skills"])

    def test_grounded_numbers_still_pass(self):
        out = self.finish("- Coverage grew from 40% to 78% in tests [S6]")
        self.assertEqual(out["explanation"], ["Coverage grew from 40% to 78% in tests"])

    # --- content failures must STILL discard (fail-closed guard unchanged) ---
    def test_unsupported_count_dropped(self):
        out = self.finish("- The parser found 7 skills [S7]\n"
                          "- Contact details are present [S2]")
        self.assertEqual(out["explanation"], ["Contact details are present"])

    def test_all_unsupported_counts_discards_everything(self):
        with self.assertRaises(SlateError) as ctx:
            self.finish("- 3 skills are clearly present [S7]\n- 1 email is listed [S2]")
        self.assertEqual(ctx.exception.code, "ai_explanation_unusable")

    def test_unsupported_name_dropped(self):
        out = self.finish("- Skills include Python and Docker [S7]\n"
                          "- Contact details are present [S2]")
        self.assertEqual(out["explanation"], ["Contact details are present"])

    def test_unknown_tag_dropped(self):
        out = self.finish("- Python is listed [S99]\n- Contact details are present [S2]")
        self.assertEqual(out["explanation"], ["Contact details are present"])

    def test_no_tags_discards_everything(self):
        with self.assertRaises(SlateError) as ctx:
            self.finish("- Python is listed as a skill\n- Contact details are present")
        self.assertEqual(ctx.exception.code, "ai_explanation_unusable")

    # --- prompt contract ---
    def test_prompt_forbids_numbered_bullets_and_unsourced_facts(self):
        self.assertIn("Do not number the bullets", self.prep["prompt"])
        self.assertIn("Never write a number, count, or name that is not", self.prep["prompt"])


if __name__ == "__main__":
    unittest.main()
