"""Adaptive mock interviews with a deterministic fallback.

The store is deliberately provider-agnostic. Authenticated serving attaches a
GeminiInterviewCoach; framework-free tests and offline demos keep the fallback.
Only serializable session data is persisted.
"""
import json
import re

from .sample_data import INTERVIEW_QUESTIONS


def _json_object(raw):
    """Accept JSON returned bare or inside a Markdown code fence."""
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The interview model did not return a JSON object.")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("The interview model returned an invalid object.")
    return value


def _strings(value, limit=5):
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:240] for item in value
            if isinstance(item, (str, int, float)) and str(item).strip()][:limit]


def _role_key(role):
    """Canonical role identity used to keep coaching history within one role."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(role or "").lower()).strip()
    aliases = {
        "hr": "human resources", "human relation": "human resources",
        "human relations": "human resources", "human resource": "human resources",
        "human resources": "human resources", "hr generalist": "human resources",
        "hr executive": "human resources", "human resource management": "human resources",
    }
    return aliases.get(normalized, normalized)


def _role_questions(role):
    """Resolve common role-name variants without silently treating HR as a tech role."""
    normalized = _role_key(role)
    if normalized == "human resources":
        return list(INTERVIEW_QUESTIONS["Human Resources"])
    for key, questions in INTERVIEW_QUESTIONS.items():
        if key == "default":
            continue
        if re.sub(r"[^a-z0-9]+", " ", key.lower()).strip() == normalized:
            return list(questions)
    return list(INTERVIEW_QUESTIONS["default"])


def _question_seen(candidate, asked):
    """Reject exact repeats and near-identical wording from a model or fallback."""
    words = set(re.findall(r"[a-z0-9]+", str(candidate or "").lower()))
    if not words:
        return True
    for previous in asked:
        prior = set(re.findall(r"[a-z0-9]+", str(previous or "").lower()))
        if words == prior:
            return True
        if len(words & prior) / max(1, len(words | prior)) >= 0.82:
            return True
    return False


def _role_relevant(role, question):
    """Catch obvious cross-domain drift before a question reaches the candidate."""
    normalized = str(role or "").lower()
    if any(term in normalized for term in ("human", "hr", "people", "personnel")):
        q = str(question or "").lower()
        technical_project_terms = ("python", "sql query", "write code", "software project",
                                   "built a project", "programming", "debugging")
        hr_context_terms = ("employee", "hiring", "recruit", "candidate", "workplace",
                            "manager", "conflict", "onboarding", "policy", "people",
                            "complaint", "performance", "fairness", "team", "retention")
        if any(term in q for term in technical_project_terms) and not any(term in q for term in hr_context_terms):
            return False
    return True


def _fallback_next_question(session):
    """Select an unused prompt; after the bank, vary the scenario rather than loop."""
    asked = session.get("questions", [])
    bank = session.get("fallback_questions") or INTERVIEW_QUESTIONS["default"]
    for question in bank:
        if not _question_seen(question, asked):
            return question
    role = session.get("role", "this role")
    angles = [
        "Consider the same responsibility when you have very limited time.",
        "Now consider a case where the people involved strongly disagree.",
        "How would your approach change if the first solution did not work?",
        "What would you do if important information was missing?",
        "How would you handle this if the decision affected several stakeholders?",
        "What would you measure afterwards to check whether your approach worked?",
        "How would you explain your decision to someone who disagreed with it?",
        "What risks would you look for before taking action?",
    ]
    index = max(0, len(asked) - len(bank))
    base = bank[index % len(bank)]
    angle = angles[index % len(angles)]
    candidate = f"{angle} {base}"
    # This suffix guarantees a distinct prompt even after all angle/base pairs.
    generation = index // len(angles) + 1
    if generation > 1:
        candidate = f"{candidate} (alternative scenario {generation})"
    return candidate


class GeminiInterviewCoach:
    """Uses the existing LLMClient interface; the API key stays server-side."""

    def __init__(self, client=None):
        if client is None:
            from .llm import GeminiLLM
            client = GeminiLLM()
        self.client = client

    def first_question(self, role, resume_context, past_feedback):
        prompt = (
            "Act as a skilled human hiring interviewer who understands the actual work of the target role. "
            "Ask exactly one concise, natural, role-specific opening question. "
            "Do not use generic software-project questions unless the target role is a software/technical role. "
            "For HR or human-relations roles, focus on recruitment, employee relations, conflict handling, "
            "confidentiality, onboarding, policy, performance processes, fairness and stakeholder communication. "
            "Use resume facts only when relevant; never assume experience that is not listed. "
            "If prior weak areas exist, revisit one naturally. Return ONLY JSON: "
            '{"question":"...","topic":"..."}.\n\n'
            f"TARGET ROLE: {role}\n"
            f"RESUME FACTS (may be empty): {json.dumps(resume_context or {}, ensure_ascii=False)}\n"
            f"PRIOR WEAK AREAS: {json.dumps(past_feedback, ensure_ascii=False)}"
        )
        data = _json_object(self.client.generate(prompt))
        question = data.get("question")
        if (not isinstance(question, str) or not question.strip()
                or not _role_relevant(role, question)):
            raise ValueError("The interview model did not provide a role-relevant question.")
        return question.strip()[:1000]

    def evaluate_answer(self, role, question, answer, resume_context,
                        history, followup_used, delivery_metrics=None):
        prompt = (
            "You are a thoughtful, role-specialist human interviewer reviewing one candidate answer. "
            "Evaluate whether the answer addresses the exact question and demonstrates sound judgement for the TARGET ROLE. "
            "Do not use a generic rubric across unrelated professions. For HR/human-relations roles, assess fairness, "
            "confidentiality, listening, policy awareness, documentation, practical judgement, employee impact and "
            "appropriate escalation; do not reward irrelevant technical-project detail. "
            "Do not invent candidate achievements or treat resume claims as verified. "
            "Score strictly using this calibrated rubric; never reward answer length or confidence alone: "
            "1 = irrelevant, incorrect, or does not answer the question; "
            "2 = partially relevant but vague, unsupported, or missing a workable action; "
            "3 = relevant and mostly sound, with an identifiable approach but limited detail, rationale, or evidence; "
            "4 = accurate, role-specific actions with clear reasoning and a credible result, validation, or trade-off; "
            "5 = exceptional depth: technically/professionally accurate, well-prioritised, nuanced, and supported by strong evidence or measurable impact. "
            "Do not award 4 or 5 without concrete role-specific actions AND evidence. Do not award 5 for a merely complete answer. "
            "If the answer does not address the question, score 1 even if it is long. "
            "Give feedback tied to specific details in the answer. "
            "Improvements MUST be concrete: name what was missing, why it matters in this role, and what detail/action "
            "the candidate should add. Avoid vague advice such as 'make the impact explicit' unless you say what impact "
            "to quantify or explain. "
            "Ask a follow-up only when it naturally arises from something the candidate actually said or omitted. "
            "A follow-up must refer to a specific detail, ambiguity, decision or consequence in their answer; "
            "never ask an unrelated stock question or repeat an earlier question. You may chain follow-ups, but "
            "do not probe merely for the sake of it. If no meaningful probe remains, set follow_up_question to null. "
            "Always propose a distinct next main question that has not appeared in the transcript. "
            "Evaluate voice delivery separately from content when metrics are supplied. "
            "Do not infer personality, emotion, honesty, or suitability from voice. "
            "Assess only observable mechanics such as pace, pauses, filler words, "
            "volume consistency, and pitch variation. Return ONLY JSON with keys: "
            "score, feedback, strengths, improvements, follow_up_question, "
            "next_question, topic, delivery_score, delivery_feedback, "
            "delivery_strengths, delivery_improvements. "
            "Use arrays for strengths/improvements; strings for other text.\n\n"
            f"TARGET ROLE: {role}\n"
            f"RESUME FACTS: {json.dumps(resume_context or {}, ensure_ascii=False)}\n"
            f"RECENT TRANSCRIPT: {json.dumps(history[-12:], ensure_ascii=False)}\n"
            f"QUESTIONS ALREADY ASKED (do not repeat or paraphrase): {json.dumps([x.get('question', '') for x in history], ensure_ascii=False)}\n"
            f"CURRENT QUESTION: {question}\n"
            f"CANDIDATE ANSWER: {answer}\n"
            f"FOLLOW-UP ALREADY USED FOR THIS QUESTION: {str(bool(followup_used)).lower()}\n"
            f"VOICE DELIVERY METRICS (null if unavailable): {json.dumps(delivery_metrics, ensure_ascii=False)}"
        )
        data = _json_object(self.client.generate(prompt))
        try:
            score = int(data.get("score", 3))
        except (TypeError, ValueError):
            score = 3
        score = max(1, min(5, score))
        try:
            delivery_score = int(data.get("delivery_score", 3)) if delivery_metrics else None
        except (TypeError, ValueError):
            delivery_score = 3 if delivery_metrics else None
        if delivery_score is not None:
            delivery_score = max(1, min(5, delivery_score))
        followup = data.get("follow_up_question")
        next_question = data.get("next_question")
        if isinstance(followup, str) and not _role_relevant(role, followup):
            followup = None
        if isinstance(next_question, str) and not _role_relevant(role, next_question):
            next_question = None
        return {
            "score": score,
            "feedback": str(data.get("feedback") or "Answer evaluated.").strip()[:1200],
            "strengths": _strings(data.get("strengths")),
            "improvements": _strings(data.get("improvements")),
            "follow_up_question": followup.strip()[:1000] if isinstance(followup, str) and followup.strip() else None,
            "next_question": next_question.strip()[:1000] if isinstance(next_question, str) and next_question.strip() else None,
            "topic": str(data.get("topic") or "").strip()[:120],
            "delivery_score": delivery_score,
            "delivery_feedback": str(data.get("delivery_feedback") or "").strip()[:1000] if delivery_metrics else "",
            "delivery_strengths": _strings(data.get("delivery_strengths")) if delivery_metrics else [],
            "delivery_improvements": _strings(data.get("delivery_improvements")) if delivery_metrics else [],
        }


class InterviewStore:
    def __init__(self, coach=None):
        self._sessions = {}
        self._n = 0
        self.coach = coach

    @staticmethod
    def _clean_delivery_metrics(value):
        if not isinstance(value, dict):
            return None
        bounds = {
            "durationSeconds": (0, 600), "wordsPerMinute": (0, 600),
            "pauseRatio": (0, 1), "pauseCount": (0, 500),
            "fillerCount": (0, 200), "meanVolume": (0, 1),
            "volumeVariation": (0, 1), "medianPitchHz": (50, 500),
            "pitchRangeHz": (0, 500),
        }
        cleaned = {}
        for key, (low, high) in bounds.items():
            raw = value.get(key)
            if raw is None:
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if number == number:
                cleaned[key] = round(max(low, min(high, number)), 3)
        return cleaned or None

    @staticmethod
    def _fallback_review(role, question, answer, allow_followup=True):
        """Conservative offline rubric: relevance and evidence matter more than length."""
        words = re.findall(r"[a-z0-9]+", str(answer or "").lower())
        low_q, low_a = str(question or "").lower(), str(answer or "").lower()
        stop = {"what", "how", "why", "when", "where", "which", "who", "would", "could",
                "should", "your", "you", "the", "and", "for", "with", "from", "that",
                "this", "have", "had", "was", "were", "are", "been", "being", "tell",
                "describe", "about", "time", "think", "most", "important", "part"}
        q_terms = {w for w in re.findall(r"[a-z0-9]+", low_q) if len(w) > 2 and w not in stop}
        a_terms = set(words)
        matched = sorted(q_terms & a_terms)
        action_terms = {"built", "analysed", "analyzed", "tested", "checked", "measured",
                        "compared", "decided", "implemented", "investigated", "validated",
                        "created", "designed", "prioritised", "prioritized", "resolved",
                        "documented", "reviewed", "used", "identified", "presented",
                        "reduced", "improved", "increased", "delivered", "chose"}
        evidence_terms = {"result", "results", "because", "therefore", "reduced", "increased",
                          "improved", "accuracy", "precision", "recall", "percent", "users",
                          "minutes", "hours", "days", "revenue", "cost", "feedback", "metric",
                          "measured", "from", "to"}
        has_action = bool(a_terms & action_terms)
        has_evidence = bool(a_terms & evidence_terms) or bool(re.search(r"\b\d+(?:\.\d+)?%?\b", low_a))
        is_hr = any(term in str(role).lower() for term in ("human", "hr", "people", "personnel"))
        if is_hr:
            if any(term in low_q for term in ("confidential", "sensitive", "complaint", "unfair treatment")):
                focus = "Address confidentiality limits, objective fact-finding, restricted information sharing, documentation and appropriate escalation."
                probe = "What would you tell the employee about confidentiality, and what would make you escalate the concern?"
            elif any(term in low_q for term in ("hiring", "recruit", "candidate", "vacancy", "interview")):
                focus = "Specify job-related selection criteria, agreement with the hiring manager, structured evaluation and consistent documentation."
                probe = "Which two selection criteria would you make mandatory, and how would you score each candidate consistently?"
            else:
                focus = "Identify the relevant HR policy, the people you would consult, the facts you would document and the follow-up you would own."
                probe = "What policy or evidence would guide your next step, and who would you involve?"
        else:
            focus = "State the role-specific method or decision, explain why you chose it, and give evidence (a metric, comparison, test result or concrete outcome) that supports the result."
            probe = "Which specific step or decision in your answer had the greatest effect, and what evidence supports that?"
        # No answer earns a high score just for being long. Fallback cannot award 5/5.
        if len(words) < 8 or not matched:
            score = 1
            feedback = ("The answer is too short to assess." if len(words) < 8 else
                        "The answer does not clearly address the key subject of the question.")
            improvements = [focus]
        elif not has_action:
            score = 2
            feedback = "The answer mentions the topic but does not identify a concrete action or decision you took."
            improvements = ["Describe the specific action you took and why it was appropriate.", focus]
        elif not has_evidence:
            score = 2 if len(words) < 35 else 3
            feedback = "The answer identifies an action, but gives no clear evidence or outcome to show whether it worked."
            improvements = ["Add a verifiable outcome, metric, comparison or feedback that demonstrates the result.", focus]
        elif len(words) < 45:
            score = 3
            feedback = "The answer includes a relevant action and some evidence, but the reasoning or result needs more detail."
            improvements = ["Explain the trade-off behind your decision and make the outcome more specific.", focus]
        else:
            score = 4
            feedback = "The answer is relevant and includes an action and supporting evidence. The reasoning and impact could still be examined more deeply."
            improvements = ["Clarify the trade-off you considered and what you would improve next time."]
        strengths = []
        if matched:
            strengths.append("Addressed question terms: " + ", ".join(matched[:4]) + ".")
        if has_action:
            strengths.append("Identified at least one concrete action.")
        if has_evidence:
            strengths.append("Included an outcome or evidence signal.")
        followup = probe if allow_followup and len(words) < 85 else None
        return {"score": score, "feedback": feedback, "strengths": strengths,
                "improvements": improvements, "follow_up_question": followup,
                "next_question": None, "topic": str(question)[:120]}

    def start(self, target_role: str, past_feedback: list,
              resume_context=None, mode="text") -> dict:
        self._n += 1
        sid = f"int_{self._n:03d}"
        qs = _role_questions(target_role)
        carried = list(dict.fromkeys(w for f in past_feedback for w in f.get("weakAreas", [])
                                     if w not in {"interview still in progress", "unanswered questions"}))
        for w in reversed(carried):
            qs.insert(0, f"Last time this was weak: {w}. Try again.")
        first = qs[0]
        ai_powered = False
        coach_error = (None if self.coach is not None else
                       "Gemini is not configured for interview coaching. Set GEMINI_API_KEY in the repository-root .env and restart the server.")
        if self.coach is not None:
            try:
                first = self.coach.first_question(target_role, resume_context, carried)
                ai_powered = True
            except Exception as exc:
                coach_error = str(exc)[:500]
        self._sessions[sid] = {
            "role": target_role, "mode": mode, "questions": [first],
            "fallback_questions": qs, "main_index": 0,
            "current_question": first, "current_is_followup": False,
            "followup_used": False, "followup_count": 0,
            "answers": [], "transcript": [], "reviews": [],
            "carried": carried, "resume_context": resume_context or {},
            "ai_powered": ai_powered, "model_turns": 1 if ai_powered else 0,
            "fallback_turns": 0, "coach_error": coach_error,
            "done": False, "ended": False,
        }
        return {"sessionId": sid, "firstQuestion": first,
                "carriedFromEarlier": carried, "mode": mode,
                "aiPowered": ai_powered,
                "coachMode": "gemini" if ai_powered else "deterministic_fallback",
                "coachError": coach_error}

    def _upgrade_legacy_session(self, session):
        """Upgrade sessions persisted by the pre-adaptive interview store in place."""
        if "current_question" in session:
            return
        questions = list(session.get("questions", []))
        answers = list(session.get("answers", []))
        reviews, transcript = [], []
        for question, answer in zip(questions, answers):
            review = self._fallback_review(
                session["role"], question, answer,
                allow_followup=(session.get("followup_count", 0) == 0))
            topic = question.split(":")[0].replace("Last time this was weak", "").strip()
            review["topic"] = topic or question[:120]
            review["question"] = question
            review["answer"] = answer
            review["isFollowUp"] = False
            reviews.append(review)
            transcript.append({"question": question, "answer": answer, "isFollowUp": False})
        session.update({
            "fallback_questions": questions,
            "main_index": len(answers),
            "max_main_questions": len(questions),
            "current_question": questions[len(answers)] if len(answers) < len(questions) else None,
            "followup_used": False, "transcript": transcript, "reviews": reviews,
            "resume_context": {}, "mode": "text", "ai_powered": False,
            "model_turns": 0, "fallback_turns": len(answers),
            "coach_error": "This saved interview predates Gemini diagnostics; its original provider error is unavailable.",
            "done": len(answers) >= len(questions),
        })

    def answer(self, sid: str, text: str, delivery_metrics=None) -> dict:
        s = self._sessions.get(sid)
        if s is None:
            raise KeyError("session_not_found")
        self._upgrade_legacy_session(s)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("answer_empty")
        if s.get("ended") or s.get("done"):
            raise ValueError("interview_ended")

        question = s["current_question"]
        answer = text.strip()[:20000]
        metrics = self._clean_delivery_metrics(delivery_metrics)
        review = None
        if self.coach is not None:
            try:
                try:
                    review = self.coach.evaluate_answer(
                        s["role"], question, answer, s["resume_context"],
                        s["transcript"], s.get("followup_count", 0) > 0, metrics)
                except TypeError:
                    # Backward compatibility for injected coaches using the old interface.
                    review = self.coach.evaluate_answer(
                        s["role"], question, answer, s["resume_context"],
                        s["transcript"], s.get("followup_count", 0) > 0)
                if not isinstance(review, dict):
                    review = None
            except Exception as exc:
                s["coach_error"] = str(exc)[:500]
                review = None
        if review is None:
            review = self._fallback_review(
                s["role"], question, answer,
                allow_followup=(s.get("followup_count", 0) == 0))
            if metrics:
                wpm = float(metrics.get("wordsPerMinute", 0) or 0)
                pause_ratio = float(metrics.get("pauseRatio", 0) or 0)
                fillers = int(metrics.get("fillerCount", 0) or 0)
                words = max(1, len(answer.split()))
                delivery_score = 3
                if 100 <= wpm <= 170:
                    delivery_score += 1
                elif wpm < 70 or wpm > 210:
                    delivery_score -= 1
                if fillers / words > 0.06:
                    delivery_score -= 1
                if pause_ratio > 0.55 or pause_ratio < 0.03:
                    delivery_score -= 1
                review.update({
                    "delivery_score": max(1, min(5, delivery_score)),
                    "delivery_feedback": "Rule-based estimate from pace, pauses, filler-word frequency and volume activity. Treat this as coaching guidance, not a personality or confidence assessment.",
                    "delivery_strengths": [],
                    "delivery_improvements": ["Aim for a steady, conversational pace" if wpm < 100 or wpm > 170 else "Maintain this speaking pace",
                                              "Reduce repeated filler words" if fillers / words > 0.06 else "Keep filler words limited"],
                })
            s["fallback_turns"] += 1
        else:
            s["model_turns"] += 1
            s["ai_powered"] = True
            s["coach_error"] = None

        is_followup = bool(s.get("current_is_followup"))
        normalized = {
            "score": max(1, min(5, int(review.get("score", 3)))),
            "feedback": str(review.get("feedback") or "").strip(),
            "strengths": _strings(review.get("strengths")),
            "improvements": _strings(review.get("improvements")),
            "topic": str(review.get("topic") or "").strip()[:120],
            "deliveryScore": review.get("delivery_score"),
            "deliveryFeedback": str(review.get("delivery_feedback") or "").strip(),
            "deliveryStrengths": _strings(review.get("delivery_strengths")),
            "deliveryImprovements": _strings(review.get("delivery_improvements")),
            "deliveryMetrics": metrics,
            "answer": answer,
        }
        s["transcript"].append({"question": question, "answer": answer,
                                "isFollowUp": is_followup,
                                "deliveryMetrics": metrics})
        s["answers"].append(answer)
        s["reviews"].append({**normalized, "question": question,
                             "isFollowUp": is_followup})

        asked_questions = [item.get("question", "") for item in s["transcript"]]
        followup = review.get("follow_up_question")
        if (isinstance(followup, str) and followup.strip()
                and not _question_seen(followup, asked_questions)):
            s["followup_used"] = True
            s["followup_count"] = s.get("followup_count", 0) + 1
            s["current_question"] = followup.strip()[:1000]
            s["current_is_followup"] = True
            s["questions"].append(s["current_question"])
            return {"done": False, "nextQuestion": s["current_question"],
                    "isFollowUp": True, "evaluation": normalized,
                    "aiPowered": s["ai_powered"]}

        s["main_index"] += 1
        s["followup_used"] = False
        s["followup_count"] = 0
        s["current_is_followup"] = False
        next_question = review.get("next_question")
        if (not isinstance(next_question, str) or not next_question.strip()
                or _question_seen(next_question, asked_questions)):
            next_question = _fallback_next_question(s)
        s["current_question"] = next_question.strip()[:1000]
        s["questions"].append(s["current_question"])
        return {"done": False, "nextQuestion": s["current_question"],
                "isFollowUp": False, "evaluation": normalized,
                "aiPowered": s["ai_powered"]}

    def end(self, sid: str) -> dict:
        s = self._sessions.get(sid)
        if s is None:
            raise KeyError("session_not_found")
        self._upgrade_legacy_session(s)
        s["ended"] = True
        s["done"] = True
        return self.feedback(sid)

    def feedback(self, sid: str) -> dict:
        s = self._sessions.get(sid)
        if s is None:
            raise KeyError("session_not_found")
        self._upgrade_legacy_session(s)
        reviews = s.get("reviews", [])
        weak = []
        strengths, improvements = [], []
        for item in reviews:
            topic = item.get("topic") or item["question"].split(":")[0]
            if item.get("score", 3) <= 2:
                weak.append(topic.strip() or item["question"])
            strengths.extend(item.get("strengths", []))
            improvements.extend(item.get("improvements", []))
        if not s.get("ended") and not s.get("done") and len(s["answers"]) < len(s["questions"]):
            weak.append("interview still in progress")
        scores = [r["score"] for r in reviews]
        average = round(sum(scores) / len(scores), 1) if scores else 0
        delivery_scores = [r["deliveryScore"] for r in reviews
                           if isinstance(r.get("deliveryScore"), (int, float))]
        average_delivery = (round(sum(delivery_scores) / len(delivery_scores), 1)
                            if delivery_scores else None)
        mode = ("gemini" if s["ai_powered"] and not s["fallback_turns"] else
                "mixed" if s["ai_powered"] else "deterministic_fallback")
        fb = {
            "summary": f"{len(s['answers'])} answer(s) recorded; average answer score {average}/5.",
            "weakAreas": list(dict.fromkeys(weak)),
            "transcriptRef": sid,
            "averageScore": average,
            "averageDeliveryScore": average_delivery,
            "strengths": list(dict.fromkeys(strengths))[:8],
            "improvements": list(dict.fromkeys(improvements))[:8],
            "answerReviews": reviews,
            "answeredCount": len(s["answers"]),
            "mode": s.get("mode", "text"),
            "aiPowered": bool(s["ai_powered"]),
            "coachMode": mode,
            "coachError": s.get("coach_error"),
            "ended": bool(s.get("ended")),
        }
        s["feedback"] = fb
        return fb

    def past_feedback(self, role=None) -> list:
        """Return coaching history only from the same target role."""
        target = _role_key(role) if role else None
        return [
            s["feedback"] for s in self._sessions.values()
            if "feedback" in s and (target is None or _role_key(s.get("role")) == target)
        ]
