"""Facade returning the contract shapes (contracts/api-contracts.md), errors in one shape.

Built up feature by feature: shared error type and store plumbing, plus the
resume intake / skill review feature. Later slices add their own sections.
"""
import os  # interview feature: GEMINI_API_KEY check for the coach hook
import re
from . import jobs as J
from .resume import parse_resume, ParseError
from .tailor import build_draft
from .roadmap import build_roadmap
from .approvals import ApprovalStore
from .claims import validate

class SlateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}

class SlateService:
    """One entry point for the copilot core.

    store= is the persistence handoff: any object with load() -> dict | None and
    save(state: dict). State keys are resumes, texts and targets; the drafts and
    interview slices extend the load/save wiring for their own state.
    """
    def __init__(self, store=None, llm_client=None, feed=None):
        self._resumes = {}
        self._texts = {}
        self._targets = {}
        self._profile = None  # profile feature: confirmed answers, loaded below
        self.approvals = ApprovalStore()
        self._store = store
        # Jobs feed (feature 3): live public-board listings, lazily refreshed.
        # Injected in tests; the real one fetches only when live data is asked for.
        if feed is None:
            from .jobs_feed import default_feed
            feed = default_feed()  # shared process-wide: public, non-user data
        self._feed = feed
        # --- Interview feature ---
        from .interview import InterviewStore
        self.interviews = InterviewStore()
        # Gemini interview coaching only: attach when a client is injected
        # (tests) or GEMINI_API_KEY is set. LLM_API_KEY (Groq tailoring) must
        # never enable the interview coach. This base hook replaces the
        # temporary guarded attachment in ai_service.py.
        if llm_client is not None or os.getenv("GEMINI_API_KEY"):
            from .interview import GeminiInterviewCoach
            self.interviews.coach = GeminiInterviewCoach(llm_client)
        # --- End interview feature ---
        if store is not None:
            st = store.load()
            if st:
                self._resumes, self._texts = st["resumes"], st["texts"]
                self._targets = st.get("targets", {})
                self.approvals._drafts, self.approvals._n = st["drafts"], st["draftN"]
                # --- Interview feature ---
                self.interviews._sessions = st.get("sessions", {})
                self.interviews._n = st.get("sessionN", 0)
                # --- End interview feature ---
                # Profile feature: absent in documents stored before it existed.
                self._profile = st.get("profile")

    def reset_demo(self, confirm: str) -> dict:
        """Demo helper, gated by the API layer: wipe resumes and drafts so the demo can restart.

        Interview sessions belong to the interview feature and are intentionally kept.
        The confirmed profile is kept too: confirming answers once and reusing
        them across restarts is the point of the profile feature."""
        if confirm != "reset":
            raise SlateError("reset_not_confirmed", 'Send {"confirm": "reset"} to wipe the demo data.')
        self._resumes, self._texts = {}, {}
        self.approvals._drafts, self.approvals._n = {}, 0
        self._persist()
        return {"reset": True}

    def _persist(self):
        if self._store is not None:
            self._store.save({"resumes": self._resumes, "texts": self._texts,
                              "drafts": self.approvals._drafts, "draftN": self.approvals._n,
                              # --- Interview feature ---
                              "sessions": self.interviews._sessions, "sessionN": self.interviews._n,
                              # --- End interview feature ---
                              "targets": self._targets,
                              "profile": self._profile})

    def _resume(self, rid):
        r = self._resumes.get(rid)
        if r is None:
            raise SlateError("resume_not_found", "No resume with that id.")
        return r

    def _target_mentions(self, job_id, content=None) -> list:
        """Exact strings a draft may quote as target references, not claims.
        Resolved from the stored job id first; if the listing has expired from
        the feed cache, from the draft's own stored 'Target role:' line.
        Derived only from stored state, never from incoming edits."""
        job = None
        if job_id:
            job = J.get_job(job_id) or self._feed.lookup(job_id)
        if job:
            return [job.get("title", ""), job.get("company", "")]
        text = (content or {}).get("tailoredResume", "")
        m = re.search(r"^Target role: (.+) at (.+)$", text, re.M)
        return [m.group(1), m.group(2)] if m else []

    def _violations(self, resume_id, content, allowed_mentions=()) -> list:
        if content.get("outputMode") == "source_preserving_draft_not_rewrite":
            import hashlib
            from .targets import source_preserving_content
            target = self.get_target(content.get("targetId"))
            original = self.get_resume(resume_id)["sourceText"]
            if content.get("originalSourceSha256") != hashlib.sha256(original.encode("utf-8")).hexdigest() or content.get("targetSnapshot") != target:
                return ["Source or target version binding changed. Create a fresh draft."]
            try:
                rebuilt = source_preserving_content(original, self._resume(resume_id).get("skillEvidence", []), target)
            except ValueError as e:
                return ["Source preservation cannot be checked: " + str(e)]
            if any(content.get(key) != rebuilt[key] for key in ("baselineSha256", "originalSha256", "targetSha256")):
                return ["Source preservation hashes changed. Create a fresh draft."]
            baseline = rebuilt["tailoredResume"]
            body = content.get("tailoredResume", "")
            if not body.startswith(baseline):
                return ["The preserved original source block cannot be changed in this mode. Edit and parse the original resume to create a new source version."]
            # Only the byte-exact original/source-labelled builder block is
            # excluded. Appended notes and the cover note keep normal gates.
            return validate(self._resume(resume_id), self._texts[resume_id], body[len(baseline):], content.get("coverNote", ""), allowed_mentions=allowed_mentions)
        return validate(self._resume(resume_id), self._texts[resume_id],
                        content.get("tailoredResume", ""), content.get("coverNote", ""), allowed_mentions=allowed_mentions)

    def _check_draft(self, draft_id):
        d = self.approvals.get(draft_id)
        if d is None:
            raise SlateError("draft_not_found", "No draft with that id.")
        bad = self._violations(d["resumeId"], d["content"],
                               allowed_mentions=self._target_mentions(d.get("jobId"), d["content"]))
        if bad:
            raise SlateError("unsupported_claim", "Draft makes claims the resume does not support: " + "; ".join(bad))
        return d

    def _upload_resume(self, text) -> dict:
        try:
            parsed = parse_resume(text)
        except ParseError as e:
            raise SlateError("resume_unreadable", str(e))
        rid = f"res_{len(self._resumes) + 1:03d}"
        self._resumes[rid] = parsed
        self._texts[rid] = text
        return {"resumeId": rid, "parsed": parsed}

    def list_resumes(self):
        """Only this service's verified user's snapshots, newest first."""
        return {"totalCount": len(self._resumes), "resumes": [{"resumeId": rid, "name": parsed.get("name", "Unknown"),
                             "reviewStatus": parsed.get("skillReview", {}).get("status", "extracted_candidates"),
                             "parentResumeId": parsed.get("skillReview", {}).get("parentResumeId"),
                             "skillCount": len(parsed.get("skills", []))}
                            for rid, parsed in list(reversed(list(self._resumes.items())))[:100]]}

    def get_resume(self, resume_id):
        import copy
        parsed = self._resume(resume_id)
        original = parsed.get("skillReview", {}).get("originalResumeId", resume_id)
        return {"resumeId": resume_id, "parsed": copy.deepcopy(parsed),
                "sourceText": self._texts[original],
                "sourceTextKind": "original_uploaded_text_not_user_addendum"}

    def review_resume_skills(self, resume_id, skills, confirm=False):
        """A correction is a new immutable source snapshot, never silent reapproval."""
        from .resume_review import reviewed_snapshot
        parent = self._resume(resume_id)
        try:
            parsed = reviewed_snapshot(parent, skills, confirm)
        except ValueError as e:
            raise SlateError("invalid_skill_review", str(e))
        rid = f"res_{len(self._resumes) + 1:03d}"
        root_id = parent.get("skillReview", {}).get("originalResumeId", resume_id)
        original_text = self._texts[root_id]
        parsed["skillReview"] = {"parentResumeId": resume_id, "originalResumeId": root_id,
                               "status": "user_reviewed_not_independently_verified"}
        additions = [e["skill"] for e in parsed["skillEvidence"] if e["source"] == "user_statement"]
        # Additional claims are explicit user statements, not extracted PDF evidence.
        # Keep the original source snapshot intact. AI/draft gates still use the
        # new bound source, which labels the addendum and never implies work history.
        text = original_text + ("\n\nUser-provided skill statements (not independently verified):\nSkills: " + ", ".join(additions) if additions else "")
        self._resumes[rid], self._texts[rid] = parsed, text
        lineage, cursor = set(), resume_id
        while cursor and cursor not in lineage:
            lineage.add(cursor)
            cursor = self._resumes[cursor].get("skillReview", {}).get("parentResumeId")
        invalidated = []
        for did, draft in self.approvals._drafts.items():
            if draft["resumeId"] in lineage and draft["status"] == "approved":
                draft["status"] = "draft"
                invalidated.append(did)
        self._persist()
        return {"resumeId": rid, "parsed": parsed, "invalidatedDraftIds": invalidated}


    def jobs(self, query="", location="", resume_id=None, source=None) -> dict:
        parsed = self._resume(resume_id) if resume_id else None
        skills = parsed["skills"] if parsed else []
        if source in (None, "", "sample", "mock"):
            return {"jobs": J.search_jobs(query, location, skills, parsed_resume=parsed),
                    "sourceLabel": "sample_fixtures",
                    "rankingNote": "Sorted by recognized skill coverage and role-query relevance. Scores are textual signals, not qualification or hiring predictions."}
        if source != "live":
            raise SlateError("invalid_source",
                             "Unknown jobs source. Use 'live' for the public-board feed, or omit it for sample fixtures.")
        listings, status = self._feed.listings()
        return {"jobs": J.search_jobs(query, location, skills, listings=listings, parsed_resume=parsed),
                "sourceLabel": "live_public_boards",
                "rankingNote": "Sorted by recognized skill coverage and role-query relevance. Live posting skills are extracted text mentions, not verified requirements.",
                "feedStatus": status}

    def jobs_feed_status(self) -> dict:
        """Current feed status; refreshes boards that are due, never fabricates."""
        _, status = self._feed.listings()
        return status

    def create_target(self, title, organization, raw_text, source_url="", parent_target_id=None):
        import uuid
        from .targets import snapshot_target
        try:
            snapshot = snapshot_target(title, organization, raw_text, source_url)
        except ValueError as e:
            raise SlateError("invalid_target", str(e))
        if parent_target_id:
            self.get_target(parent_target_id)
        tid = "target_" + uuid.uuid4().hex
        snapshot.update(targetId=tid, parentTargetId=parent_target_id)
        self._targets[tid] = snapshot
        lineage, cursor = set(), parent_target_id
        while cursor and cursor not in lineage:
            lineage.add(cursor)
            cursor = self._targets[cursor].get("parentTargetId")
        invalidated = []
        for did, draft in self.approvals._drafts.items():
            if draft["content"].get("targetId") in lineage and draft["status"] == "approved":
                draft["status"] = "draft"
                invalidated.append(did)
        self._persist()
        return {"target": self.get_target(tid), "invalidatedDraftIds": invalidated}

    def get_target(self, target_id):
        import copy
        if target_id not in self._targets:
            raise SlateError("target_not_found", "No pasted target with that id.")
        return copy.deepcopy(self._targets[target_id])

    def list_targets(self):
        return {"totalCount": len(self._targets), "targets": [self.get_target(tid) for tid in list(reversed(self._targets))[:100]]}

    def tailor_target(self, resume_id, target_id, acknowledge_role_change=False):
        import hashlib
        from .targets import source_preserving_content
        parsed = self._resume(resume_id)
        target = self.get_target(target_id)
        # Same role-fit acknowledgment gate as the fixture tailor (title-only
        # family evidence for pasted targets; insufficient evidence is labeled).
        from .role_fit import MISMATCH, role_fit_review
        guard = role_fit_review(parsed, target["title"])
        if guard["kind"] == MISMATCH and not acknowledge_role_change:
            raise SlateError("role_change_needs_acknowledgment", guard["note"])
        original = self.get_resume(resume_id)["sourceText"]
        try:
            content = source_preserving_content(original, parsed.get("skillEvidence", []), target)
        except ValueError as e:
            raise SlateError("invalid_source_preservation", str(e))
        content.update(targetId=target_id, targetSnapshot=target,
                       originalSourceSha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
                       outputMode="source_preserving_draft_not_rewrite")
        if guard["kind"] == MISMATCH:
            content["roleChangeAcknowledgedByUser"] = True
            from .role_fit import acknowledged_review
            guard = acknowledged_review(guard)
        bad = self._violations(resume_id, content)
        if bad:
            raise SlateError("unsupported_claim", "Source-preserving draft failed checks: " + "; ".join(bad))
        did = self.approvals.create_draft(resume_id, target_id, content)
        self._persist()
        return {"draftId": did, **content, "status": "draft", "requiresApproval": True,
                "roleGuardrail": guard,
                "coverageNote": "Original source retained. Job requirements are user-pasted, not verified or fully parsed. No fit score or full CV rewrite is claimed."}


    def list_drafts(self):
        items = list(reversed(list(self.approvals._drafts.items())))
        return {"totalCount": len(items), "drafts": [
            {"draftId": did, "resumeId": d["resumeId"], "jobId": d["jobId"],
             "status": d["status"], "aiGenerated": bool(d["content"].get("aiGenerated"))}
            for did, d in items[:100]]}

    def get_draft(self, draft_id):
        import copy
        d = self.approvals.get(draft_id)
        if d is None:
            raise SlateError("draft_not_found", "No draft with that id.")
        return {"draftId": draft_id, "resumeId": d["resumeId"], "jobId": d["jobId"],
                "status": d["status"], "content": copy.deepcopy(d["content"]),
                "source": self.get_resume(d["resumeId"]),
                "violations": self._violations(d["resumeId"], d["content"])}

    def download_draft(self, draft_id):
        # The export gate rechecks exactly the stored approved version, including
        # AI grounding through the subclass. Never render live editor values.
        content = self.export_draft(draft_id)
        d = self.approvals.get(draft_id)
        parsed = self._resume(d["resumeId"])
        import hashlib
        original = self.get_resume(d["resumeId"])["sourceText"]
        source_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
        lines = ["Slate application draft (not a full original CV)",
                 "Draft: " + draft_id, "Source version: " + d["resumeId"],
                 "Original source SHA-256: " + source_hash,
                 ("Target: " + content["targetId"] + " (user-pasted, not verified)" if content.get("targetId") else "Job: " + d["jobId"] + " (sample fixture, not live-verified)"),
                 "Status: approved saved version", "",
                 "Human approval is not a fact check. Review before use.",
                 "Source skill provenance (not independent verification):"]
        for e in parsed.get("skillEvidence", []):
            lines.append(e["skill"] + ": " + e.get("source", "not_recorded") +
                         " / " + e.get("reviewStatus", "not_user_reviewed"))
        lines += ["", "RESUME DRAFT", content.get("tailoredResume", ""),
                  "", "COVER NOTE", content.get("coverNote", "")]
        if content.get("targetId"):
            target = self.get_target(content["targetId"])
            lines += ["", "PASTED TARGET CONTEXT - NOT APPLICANT EVIDENCE",
                      "Title: " + target["title"], "Organization: " + target.get("company", ""),
                      "Source kind: " + target["sourceKind"], "Target SHA-256: " + target["sourceSha256"],
                      "User-supplied URL (not fetched or verified): " + target.get("sourceUrl", ""),
                      "Raw pasted text:", target["rawText"]]
        return "\n".join(lines) + "\n"

    def _tailor(self, resume_id, job_id, acknowledge_role_change=False) -> dict:
        parsed = self._resume(resume_id)
        # Fixture listings first, then the feed cache: a live listing can be
        # tailored while it is in the current cache (same claim/freshness rules).
        job = J.get_job(job_id) or self._feed.lookup(job_id)
        if job is None:
            raise SlateError("job_not_found", "No job with that id.")
        # Role-fit guardrail: a recognized resume/target family mismatch needs an
        # explicit user acknowledgment BEFORE any draft exists. Career switches
        # stay possible; they are just never blind. Insufficient family evidence
        # is labeled, never treated as fit (role_fit.py owns the states).
        from .role_fit import MISMATCH, role_fit_review
        guard = role_fit_review(parsed, job["title"], job.get("skills"))
        if guard["kind"] == MISMATCH and not acknowledge_role_change:
            raise SlateError("role_change_needs_acknowledgment", guard["note"])
        d = build_draft(parsed, job, self._profile)
        bad = self._violations(resume_id, d, allowed_mentions=[job["title"], job["company"]])
        if bad:  # generated drafts must pass the same check as edited ones
            raise SlateError("unsupported_claim", "Generated draft failed claim check: " + "; ".join(bad))
        content = {"tailoredResume": d["tailoredResume"], "coverNote": d["coverNote"]}
        if guard["kind"] == MISMATCH:
            content["roleChangeAcknowledgedByUser"] = True
            from .role_fit import acknowledged_review
            guard = acknowledged_review(guard)
        did = self.approvals.create_draft(resume_id, job_id, content)
        return {"draftId": did, "tailoredResume": d["tailoredResume"], "coverNote": d["coverNote"],
                "status": "draft", "claimsChecked": d["claims"], "skillGaps": d["gaps"],
                "profileGaps": d["profileGaps"],
                "roleGuardrail": guard}

    # --- Profile feature ---
    def get_profile(self) -> dict:
        """This user's confirmed profile answers and the fields still unknown."""
        from .profile import profile_view
        return profile_view(self._profile)

    def profile_suggestions(self, resume_id) -> dict:
        """Literal candidates from one uploaded resume. Review candidates only:
        they become answers only when the user confirms them via save_profile."""
        from .profile import suggest_from_text
        parsed = self._resume(resume_id)
        return {"resumeId": resume_id,
                "suggestions": suggest_from_text(self._texts[resume_id], parsed),
                "suggestionsKind": "literal_candidates_from_resume_not_confirmed"}

    def save_profile(self, answers, confirm: bool) -> dict:
        """Store the user's answers only after explicit confirmation.

        Unanswered fields stay unknown (get_profile lists them); nothing is
        filled from guesses, parsed text, or job descriptions.
        """
        from .profile import FIELDS, normalize_answers
        if not confirm:
            raise SlateError("profile_not_confirmed",
                             "Profile answers are saved only after you confirm them. Send confirm: true.")
        try:
            normalized = normalize_answers(answers)
        except ValueError as e:
            raise SlateError("invalid_profile", str(e))
        self._profile = {"status": "user_confirmed",
                         "source": "user_confirmed_answers_not_independently_verified",
                         "answers": normalized,
                         "unknownFields": [f for f in FIELDS if f not in normalized]}
        self._persist()
        return self.get_profile()
    # --- End profile feature ---

    def _edit_draft(self, draft_id, **updates) -> dict:
        old = self.approvals.get(draft_id)
        if old is None:
            raise SlateError("draft_not_found", "No draft with that id.")
        bad = self._violations(old["resumeId"], {**old["content"], **updates},
                               allowed_mentions=self._target_mentions(old.get("jobId"), old["content"]))
        if bad:  # fail closed: no new draft is created
            raise SlateError("unsupported_claim", "Edit rejected, claims the resume does not support: " + "; ".join(bad))
        try:
            new_id = self.approvals.edit(draft_id, updates)
        except KeyError:
            raise SlateError("draft_not_found", "No draft with that id.")
        return {"draftId": new_id, "status": "draft"}

    def _decide(self, draft_id, decision) -> dict:
        if decision == "approve":
            self._check_draft(draft_id)  # re-validate at approval time
        try:
            status = self.approvals.decide(draft_id, decision)
        except KeyError:
            raise SlateError("draft_not_found", "No draft with that id.")
        except ValueError:
            raise SlateError("invalid_decision", "decision must be 'approve' or 'reject'.")
        except PermissionError:
            raise SlateError("draft_rejected", "A rejected draft cannot be reused. Create a new draft.")
        return {"draftId": draft_id, "status": status}

    def export_draft(self, draft_id) -> dict:
        try:
            content = self.approvals.export(draft_id)
            self._check_draft(draft_id)  # re-validate at export time
            return content
        except KeyError:
            raise SlateError("draft_not_found", "No draft with that id.")
        except PermissionError:
            raise SlateError("draft_not_approved", "Only an approved draft can be used outside the app.")


    def roadmap(self, resume_id, target_role) -> dict:
        ms = build_roadmap(self._resume(resume_id), target_role or "")
        if not ms:
            raise SlateError("role_unknown", "No sample listings for that role yet.")
        return {"milestones": ms}


    def upload_resume(self, *a, **k):
        r = self._upload_resume(*a, **k)
        self._persist()
        return r

    def tailor(self, *a, **k):
        r = self._tailor(*a, **k)
        self._persist()
        return r

    def edit_draft(self, *a, **k):
        r = self._edit_draft(*a, **k)
        self._persist()
        return r

    def decide(self, *a, **k):
        r = self._decide(*a, **k)
        self._persist()
        return r

    # --- Interview feature ---
    def _interview_resume_context(self, resume_id):
        if not resume_id:
            return {}
        parsed = self._resume(resume_id)
        # Send only bounded structured facts, never the original resume text.
        education = [
            {"degree": str(item.get("degree", ""))[:120],
             "institute": str(item.get("institute", ""))[:160],
             "year": item.get("year")}
            for item in parsed.get("education", []) if isinstance(item, dict)
        ][:12]
        experience = [
            {"title": str(item.get("title", ""))[:120],
             "org": str(item.get("org", ""))[:160],
             "months": item.get("months")}
            for item in parsed.get("experience", []) if isinstance(item, dict)
        ][:20]
        return {
            "name": str(parsed.get("name", ""))[:120],
            "skills": [str(skill)[:80] for skill in parsed.get("skills", [])[:80]],
            "education": education,
            "experience": experience,
        }

    def _start_interview(self, target_role, mode="text", resume_id=None) -> dict:
        if mode not in ("text", "voice"):
            raise SlateError("mode_unsupported", "Interview mode must be 'text' or 'voice'.")
        if not isinstance(target_role, str) or not target_role.strip():
            raise SlateError("role_unknown", "Enter a target role before starting the interview.")
        context = self._interview_resume_context(resume_id)
        return self.interviews.start(target_role.strip()[:120],
                                     self.interviews.past_feedback(target_role),
                                     resume_context=context, mode=mode)

    def _answer_interview(self, session_id, text, delivery_metrics=None) -> dict:
        try:
            return self.interviews.answer(session_id, text, delivery_metrics)
        except KeyError:
            raise SlateError("session_not_found", "No interview session with that id.")
        except ValueError as e:
            if str(e) == "answer_empty":
                raise SlateError("answer_empty", "Enter or dictate an answer before submitting.")
            if str(e) in ("interview_complete", "interview_ended"):
                raise SlateError("interview_ended", "This interview has ended.")
            raise

    def _end_interview(self, session_id) -> dict:
        try:
            return self.interviews.end(session_id)
        except KeyError:
            raise SlateError("session_not_found", "No interview session with that id.")

    def _interview_feedback(self, session_id) -> dict:
        try:
            return self.interviews.feedback(session_id)
        except KeyError:
            raise SlateError("session_not_found", "No interview session with that id.")

    def start_interview(self, *a, **k):
        r = self._start_interview(*a, **k)
        self._persist()
        return r

    def answer_interview(self, *a, **k):
        r = self._answer_interview(*a, **k)
        self._persist()
        return r

    def interview_feedback(self, *a, **k):
        r = self._interview_feedback(*a, **k)
        self._persist()
        return r

    def end_interview(self, *a, **k):
        r = self._end_interview(*a, **k)
        self._persist()
        return r
    # --- End interview feature ---
