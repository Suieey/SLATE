"""Backend-enforced approval gate. State lives here, never in a client."""

class ApprovalStore:
    def __init__(self):
        self._drafts = {}   # draftId -> dict(content, status)
        self._n = 0

    def create_draft(self, resume_id, job_id, content) -> str:
        self._n += 1
        did = f"draft_{self._n:03d}"
        self._drafts[did] = {"resumeId": resume_id, "jobId": job_id, "content": dict(content), "status": "draft"}
        return did

    def get(self, draft_id):
        return self._drafts.get(draft_id)

    def decide(self, draft_id, decision):
        d = self._drafts.get(draft_id)
        if d is None:
            raise KeyError("draft_not_found")
        if decision not in ("approve", "reject"):
            raise ValueError("invalid_decision")
        if d["status"] == "rejected":
            raise PermissionError("draft_rejected")
        d["status"] = "approved" if decision == "approve" else "rejected"
        return d["status"]

    def edit(self, draft_id, content_updates) -> str:
        """Editing never keeps an approval: it creates a new draft that needs its own approval."""
        d = self._drafts.get(draft_id)
        if d is None:
            raise KeyError("draft_not_found")
        content = {**d["content"], **content_updates}
        new_id = self.create_draft(d["resumeId"], d["jobId"], content)
        # A successful edit invalidates the parent's old approval too. Keep its
        # content/source binding intact; a new explicit decision can approve
        # that exact historical version again. Rejected parents stay rejected.
        if d["status"] == "approved":
            d["status"] = "draft"
        return new_id

    def export(self, draft_id) -> dict:
        d = self._drafts.get(draft_id)
        if d is None:
            raise KeyError("draft_not_found")
        if d["status"] != "approved":
            raise PermissionError("draft_not_approved")
        return d["content"]
