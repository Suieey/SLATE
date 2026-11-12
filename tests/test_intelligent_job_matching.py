"""Explainable job matching and ranking tests. No network or model calls."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_core.jobs import search_jobs, skill_breakdown, match_score

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def listing(job_id, title, skills, **extra):
    item = {
        "jobId": job_id, "title": title, "company": "Example Co",
        "location": "Remote, India", "deadline": None,
        "url": "https://example.com/" + job_id, "skills": skills,
    }
    item.update(extra)
    return item


class SkillNormalization(unittest.TestCase):
    def test_known_aliases_match_canonical_resume_skills(self):
        matched, missing = skill_breakdown(
            ["PostgreSQL", "React"], ["postgres", "React.js", "Docker"]
        )
        self.assertEqual(matched, ["postgres", "React.js"])
        self.assertEqual(missing, ["Docker"])

    def test_duplicates_and_blanks_are_deduplicated_by_canonical_skill(self):
        matched, missing = skill_breakdown(
            ["python", " Python "], ["Python", "python", "", "SQL"]
        )
        self.assertEqual(matched, ["Python"])
        self.assertEqual(missing, ["SQL"])

    def test_legacy_skill_score_remains_a_plain_coverage_ratio(self):
        self.assertEqual(match_score(["PostgreSQL"], ["postgres", "Docker"]), 0.5)


class Ranking(unittest.TestCase):
    def test_rare_skill_coverage_outweighs_common_skill_only_overlap(self):
        corpus = [
            listing("a", "Backend Developer", ["python", "kubernetes"]),
            listing("b", "Python Developer", ["python"]),
        ]
        results = search_jobs(resume_skills=["python"], listings=corpus, now=NOW)
        self.assertEqual(results[0]["jobId"], "b")
        self.assertLess(results[1]["weightedSkillScore"], results[0]["weightedSkillScore"])
        self.assertEqual(results[0]["matchScore"], 1.0)

    def test_query_relevance_is_a_secondary_ranking_signal(self):
        corpus = [
            listing("a", "Python Developer", ["python", "sql"]),
            listing("b", "Backend Developer", ["python", "fastapi"]),
        ]
        results = search_jobs(
            query="backend developer", resume_skills=["python"], listings=corpus, now=NOW
        )
        self.assertEqual([r["jobId"] for r in results], ["b"])

    def test_aliases_affect_match_without_rewriting_listing_wording(self):
        corpus = [listing("a", "Backend Developer", ["postgres", "React.js"])]
        result = search_jobs(resume_skills=["PostgreSQL", "react"], listings=corpus, now=NOW)[0]
        self.assertEqual(result["matchedSkills"], ["postgres", "React.js"])
        self.assertEqual(result["missingSkills"], [])

    def test_rank_output_explains_its_signals(self):
        corpus = [listing("a", "Backend Developer", ["python", "fastapi"])]
        result = search_jobs(
            query="backend developer", resume_skills=["python"], listings=corpus, now=NOW
        )[0]
        self.assertIn("rankingScore", result)
        self.assertTrue(result["rankingReasons"])
        self.assertEqual(result["skillCoverageScore"], result["matchScore"])

    def test_cross_family_is_a_caution_not_an_automatic_rejection(self):
        corpus = [listing("a", "Mechanical Design Engineer", ["solidworks", "ansys"])]
        parsed = {"skills": ["python", "git"], "experience": [{"title": "Software Engineer"}]}
        result = search_jobs(
            resume_skills=parsed["skills"], parsed_resume=parsed, listings=corpus, now=NOW
        )[0]
        self.assertEqual(result["roleContext"]["kind"], "different_keyword_family")
        self.assertIn("career transition", result["roleContext"]["note"])

    def test_no_resume_does_not_invent_a_match_score(self):
        corpus = [listing("a", "Backend Developer", ["python"])]
        result = search_jobs(query="backend", listings=corpus, now=NOW)[0]
        self.assertEqual(result["matchScore"], 0.0)
        self.assertIn("role query only", " ".join(result["rankingReasons"]))


if __name__ == "__main__":
    unittest.main()
