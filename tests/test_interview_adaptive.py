import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from slate_core.interview import InterviewStore, GeminiInterviewCoach
from slate_core.llm import MockLLM
from slate_core.service import SlateService
from slate_core.ai_service import AISlateService
from slate_core.llm import GeminiLLM


def test_gemini_coach_parses_question_and_evaluation():
    model = MockLLM(
        '{"question":"Explain a project where you used Python.","topic":"Python projects"}'
    )
    coach = GeminiInterviewCoach(model)
    question = coach.first_question("Data Analyst", {"skills": ["python"]}, [])
    assert "Python" in question


def test_interview_store_adapts_and_allows_one_followup_per_main_question():
    class Coach:
        def __init__(self):
            self.calls = 0

        def first_question(self, role, resume, past):
            assert role == "Data Analyst"
            assert resume["skills"] == ["python"]
            return "Describe a Python project."

        def evaluate_answer(self, role, question, answer, resume, history, followup_used):
            self.calls += 1
            if not followup_used:
                return {
                    "score": 2, "feedback": "Give a measurable result.",
                    "strengths": ["Relevant example"], "improvements": ["Add impact"],
                    "follow_up_question": "What changed after your work?",
                    "next_question": "How would you validate a dataset?",
                    "topic": "Python projects"
                }
            return {
                "score": 4, "feedback": "Clearer with a result.",
                "strengths": ["Specific result"], "improvements": [],
                "follow_up_question": None,
                "next_question": "How would you validate a dataset?",
                "topic": "Python projects"
            }

    store = InterviewStore(coach=Coach())
    started = store.start("Data Analyst", [], {"skills": ["python"]}, "voice")
    assert started["aiPowered"] is True
    first = store.answer(started["sessionId"], "I built a dashboard.")
    assert first["isFollowUp"] is True
    second = store.answer(started["sessionId"], "It reduced manual work by half.")
    assert second["isFollowUp"] is False
    assert second["nextQuestion"] == "How would you validate a dataset?"
    fb = store.feedback(started["sessionId"])
    assert fb["averageScore"] == 3
    assert fb["mode"] == "voice"
    assert fb["weakAreas"] == ["Python projects", "interview still in progress"]
    assert fb["ended"] is False
    ended = store.end(started["sessionId"])
    assert ended["weakAreas"] == ["Python projects"]
    assert ended["ended"] is True


def test_deterministic_fallback_remains_available():
    store = InterviewStore()
    started = store.start("Data Analyst", [])
    result = store.answer(started["sessionId"], "short")
    assert result["evaluation"]["score"] == 1
    assert result["done"] is False
    feedback = store.feedback(started["sessionId"])
    assert feedback["coachMode"] == "deterministic_fallback"
    assert feedback["weakAreas"]


def test_service_accepts_resume_context_and_voice_mode():
    service = SlateService()
    resume = service.upload_resume(
        "Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\n"
        "Intern at ExampleCo (3 months)\nSkills: Python, Git, Excel\n"
    )
    started = service.start_interview("Data Analyst", "voice", resume["resumeId"])
    session = service.interviews._sessions[started["sessionId"]]
    assert session["mode"] == "voice"
    assert "python" in session["resume_context"]["skills"]


def test_legacy_saved_interview_session_is_upgraded():
    store = InterviewStore()
    store._sessions["int_old"] = {
        "role": "Data Analyst",
        "questions": ["Explain SQL joins.", "How do you clean data?"],
        "answers": ["short"], "carried": [],
    }
    result = store.answer("int_old", "I would inspect nulls, duplicates, and invalid types.")
    assert result["done"] is False
    ended = store.end("int_old")
    assert ended["ended"] is True
    feedback = store.feedback("int_old")
    assert feedback["answeredCount"] == 2
    assert feedback["coachMode"] == "deterministic_fallback"


def test_interview_continues_past_fallback_question_bank_until_explicit_end():
    store = InterviewStore()
    started = store.start("Data Analyst", [])
    session = store._sessions[started["sessionId"]]
    total = len(session["fallback_questions"]) + 3
    for index in range(total):
        result = store.answer(started["sessionId"], "I would investigate the problem, validate the data, and explain the outcome.")
        assert result["done"] is False
    assert store.feedback(started["sessionId"])["ended"] is False
    final = store.end(started["sessionId"])
    assert final["ended"] is True
    assert final["answeredCount"] == total
    try:
        store.answer(started["sessionId"], "one more answer")
        assert False, "ended interview must reject further answers"
    except ValueError as exc:
        assert str(exc) == "interview_ended"


def test_interviewer_can_chain_multiple_followups():
    class ProbingCoach:
        def __init__(self):
            self.count = 0

        def first_question(self, role, resume, past):
            return "Tell me about a project."

        def evaluate_answer(self, role, question, answer, resume, history, followup_used, delivery_metrics=None):
            self.count += 1
            return {
                "score": 3, "feedback": "Probe the detail.",
                "strengths": [], "improvements": [],
                "follow_up_question": f"Probe {self.count}?" if self.count < 3 else None,
                "next_question": "How would you validate the result?",
                "topic": "Project"
            }

    store = InterviewStore(coach=ProbingCoach())
    sid = store.start("Data Analyst", [])["sessionId"]
    one = store.answer(sid, "I built a dashboard.")
    two = store.answer(sid, "I used Python.")
    three = store.answer(sid, "I measured accuracy.")
    assert one["isFollowUp"] is True
    assert two["isFollowUp"] is True
    assert three["isFollowUp"] is False
    assert three["nextQuestion"] == "How would you validate the result?"


def test_delivery_metrics_get_a_separate_rule_based_score_without_gemini():
    store = InterviewStore()
    sid = store.start("Data Analyst", [], mode="voice")["sessionId"]
    metrics = {
        "durationSeconds": 42.0, "wordsPerMinute": 132,
        "pauseRatio": 0.22, "pauseCount": 3, "fillerCount": 1,
        "meanVolume": 0.08, "volumeVariation": 0.02
    }
    result = store.answer(sid, "I designed a clear dashboard and validated the source data.", metrics)
    assert result["evaluation"]["deliveryScore"] is not None
    assert "Rule-based estimate" in result["evaluation"]["deliveryFeedback"]
    assert 1 <= result["evaluation"]["deliveryScore"] <= 5
    report = store.end(sid)
    assert report["averageDeliveryScore"] == result["evaluation"]["deliveryScore"]


def test_human_relations_role_gets_hr_questions_and_specific_fallback_feedback():
    store = InterviewStore()
    started = store.start("human relations", [])
    sid = started["sessionId"]
    first = started["firstQuestion"].lower()
    assert "hiring manager" in first
    assert "project" not in first

    result = store.answer(sid, "I would first clarify the role requirements with the manager, agree on essential criteria, document the decision, and use the same criteria for every candidate.")
    assert result["isFollowUp"] is True
    assert "criteria" in result["nextQuestion"].lower()
    assert any("selection criteria" in item.lower() or "candidate evaluation" in item.lower()
               for item in result["evaluation"]["improvements"])


def test_fallback_question_bank_does_not_loop_after_three_questions():
    store = InterviewStore()
    started = store.start("Human Relations", [])
    sid = started["sessionId"]
    asked = [started["firstQuestion"]]
    answer = "I would listen to each person, establish the facts, check the relevant policy, agree practical next steps, document the decision, and follow up to make sure the issue is resolved. " * 4
    for _ in range(15):
        result = store.answer(sid, answer)
        next_question = result["nextQuestion"]
        assert next_question not in asked
        asked.append(next_question)
    assert len(set(asked)) == 16
    assert all("project you built" not in q.lower() for q in asked)



def test_interview_history_is_scoped_to_the_same_role():
    store = InterviewStore()
    hr = store.start("Human Relations", [])
    store.answer(hr["sessionId"], "short")
    store.end(hr["sessionId"])

    assert store.past_feedback("Applied Scientist") == []
    assert store.past_feedback("Human Resources")
    applied = store.start("Applied Scientist", store.past_feedback("Applied Scientist"))
    assert "Last time this was weak" not in applied["firstQuestion"]
    assert any(term in applied["firstQuestion"].lower()
               for term in ("dataset", "model", "machine-learning", "machine learning", "training"))
    assert applied["carriedFromEarlier"] == []


def test_interview_history_still_carries_forward_for_the_same_role():
    store = InterviewStore()
    first = store.start("Applied Scientist", [])
    store.answer(first["sessionId"], "short")
    store.end(first["sessionId"])

    history = store.past_feedback("Applied Scientist")
    assert history
    second = store.start("Applied Scientist", history)
    assert second["carriedFromEarlier"]
    assert "Last time this was weak:" in second["firstQuestion"]


def test_fallback_scoring_does_not_reward_long_irrelevant_answers():
    question = "How would you evaluate an imbalanced classification model using precision and recall?"
    irrelevant = ("I am passionate about learning, teamwork, communication, and taking responsibility. "
                  "I always try my best, stay positive, and work hard with everyone on the team. " * 3)
    review = InterviewStore._fallback_review("Applied Scientist", question, irrelevant)
    assert review["score"] == 1
    assert "does not clearly address" in review["feedback"]


def test_fallback_scoring_rewards_relevant_actions_and_evidence_not_length_alone():
    question = "How would you evaluate an imbalanced classification model using precision and recall?"
    answer = "I compared precision and recall on the validation set and chose a threshold based on false-negative cost."
    review = InterviewStore._fallback_review("Applied Scientist", question, answer)
    assert review["score"] == 3
    assert "concrete action" in " ".join(review["strengths"])


def test_interview_report_preserves_the_exact_candidate_answer():
    store = InterviewStore()
    sid = store.start("Data Analyst", [])["sessionId"]
    exact_answer = "I queried the sales table, removed duplicate rows, and checked totals against the source report."
    store.answer(sid, exact_answer)
    report = store.end(sid)
    assert report["answerReviews"][0]["answer"] == exact_answer


def test_gemini_does_not_reuse_the_generic_groq_llm_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "groq-key-not-a-gemini-key")
    assert GeminiLLM().api_key == ""


def test_groq_only_configuration_does_not_enable_gemini_interview_coach(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "groq-key-not-a-gemini-key")
    service = AISlateService()
    assert service.interviews.coach is None


def test_gemini_key_enables_interview_coach(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    service = AISlateService()
    assert isinstance(service.interviews.coach, GeminiInterviewCoach)
