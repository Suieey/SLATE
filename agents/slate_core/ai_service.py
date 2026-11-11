"""Opt-in AI tailoring on top of SlateService. Off by default.

The deterministic tailor path stays the default everywhere. This subclass adds
one method, tailor_ai, which asks an LLM (Groq by default) for a draft and then
keeps every safeguard the deterministic path has, plus more:

- the prompt is grounded: the model only sees numbered source blocks built
  deterministically from the uploaded resume and the job, and every content
  line must cite the blocks it uses
- grounding.check_grounding then mechanically re-checks those citations:
  uncited lines, unknown citations, numbers or capitalized names missing from
  the cited blocks, and lines whose content words mostly leave the cited
  blocks are all violations (see grounding.py for what it cannot catch)
- the draft enters the SAME approval store in "draft" status; approval and
  export re-validate through the normal _decide / export_draft path, which
  this class extends so grounding violations also block approval
- flagged skills and rule violations travel with the response so the review
  UI can show them before a human decides
- requiresApproval is always true; nothing auto-approves

Nothing here runs without LLM_API_KEY set on the server. The API layer also
refuses the route when the key is missing, so the feature is doubly off by
default.
"""
from . import jobs as J
from .claims import validate
from .grounding import build_grounded_prompt, check_grounding, source_blocks
from .llm import GroqLLM
from .service import SlateError, SlateService
from .tailor import check_claims


class AISlateService(SlateService):
    def __init__(self, store=None, llm_client=None):
        super().__init__(store)
        self._llm_client = llm_client  # tests inject MockLLM here
        # Interview coaching uses Gemini only. LLM_API_KEY may belong to Groq
        # (used by AI tailoring) and must never be sent to the Gemini endpoint.
        import os
        if llm_client is not None or os.getenv("GEMINI_API_KEY"):
            from .interview import GeminiInterviewCoach
            self.interviews.coach = GeminiInterviewCoach(llm_client)

    def _blocks(self, resume_id, job):
        return source_blocks(self._texts[resume_id], job)

    def tailor_ai(self, resume_id, job_id, client=None) -> dict:
        parsed = self._resume(resume_id)
        job = J.get_job(job_id)
        if job is None:
            raise SlateError("job_not_found", "No job with that id.")
        client = client or self._llm_client or GroqLLM()
        blocks = self._blocks(resume_id, job)
        text = client.generate(build_grounded_prompt(blocks))
        resume, _, note = text.partition("COVER NOTE")
        resume = resume.replace("RESUME", "", 1).strip(" :\n")
        note = note.strip(" :\n")
        low = text.lower()
        claims = [s for s in job["skills"] if s.lower() in low]
        flagged = check_claims(parsed, claims)
        violations = validate(parsed, self._texts[resume_id], resume, note)
        violations += check_grounding(resume, blocks, allow_job=False)
        violations += check_grounding(note, blocks)
        did = self.approvals.create_draft(
            resume_id, job_id,
            {"tailoredResume": resume, "coverNote": note, "aiGenerated": True})
        self._persist()
        return {"draftId": did, "tailoredResume": resume,
                "coverNote": note, "status": "draft",
                "aiGenerated": True,
                "claimsChecked": claims, "skillGaps": [s for s in job["skills"] if s not in claims],
                "flaggedClaims": flagged, "violations": violations,
                "requiresApproval": True}

    def get_draft(self, draft_id):
        result = super().get_draft(draft_id)
        if result["content"].get("aiGenerated"):
            blocks = self._blocks(result["resumeId"], J.get_job(result["jobId"]))
            result["violations"] += check_grounding(result["content"].get("tailoredResume", ""), blocks, allow_job=False)
            result["violations"] += check_grounding(result["content"].get("coverNote", ""), blocks)
        return result

    def _check_draft(self, draft_id):
        """Approval re-checks the claim rules (super) AND the grounding of the
        stored content, so a draft with unsupported lines cannot be approved.
        Only drafts this class created (marked aiGenerated) get the grounding
        check; deterministic drafts keep the standard claim check only."""
        d = super()._check_draft(draft_id)
        if not d["content"].get("aiGenerated"):
            return d
        job = J.get_job(d.get("jobId"))
        blocks = self._blocks(d["resumeId"], job)
        bad = check_grounding(d["content"].get("tailoredResume", ""), blocks, allow_job=False)
        bad += check_grounding(d["content"].get("coverNote", ""), blocks)
        if bad:
            raise SlateError("unsupported_claim",
                             "Draft has lines not grounded in the resume: " + "; ".join(bad))
        return d
