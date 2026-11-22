"""HTTP adapter over slate_core, following contracts/api-contracts.md.

Separate from backend/ on purpose (that folder holds the teammate's DB/server setup, PR #4).

Built up feature by feature: the shell (middleware, error handlers, create_app)
plus the resume intake / skill review routes. Later slices mount their own routes.
"""
import os, sys
from contextlib import nullcontext
from typing import Optional
from fastapi import APIRouter, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse  # FileResponse: interview feature page
from pydantic import BaseModel, Field, StrictBool

# Load local environment files without overriding values already set by the shell.
try:
    from dotenv import load_dotenv
    _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(_ROOT, ".env"))
    load_dotenv(os.path.join(_ROOT, "backend", ".env"))
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from slate_core import SlateService, SlateError  # noqa: E402
from slate_core.auth import AuthError  # noqa: E402
from slate_core.resume import ParseError, extract_pdf_text, MAX_PDF_BYTES  # noqa: E402

STATUS = {"resume_not_found": 404, "job_not_found": 404, "draft_not_found": 404,
          "resume_unreadable": 422, "invalid_decision": 422,
          "role_unknown": 404,
          "draft_not_approved": 403, "draft_rejected": 409, "unsupported_claim": 422}  # feature slices append their codes
STATUS.update(unauthenticated=401, invalid_token=401, auth_not_configured=503, state_conflict=409)
STATUS.setdefault("invalid_target", 422)
STATUS.setdefault("invalid_source_preservation", 422)
STATUS.setdefault("target_not_found", 404)
STATUS.setdefault("demo_reset_disabled", 403)
STATUS.setdefault("reset_not_confirmed", 422)
STATUS.setdefault("ai_not_configured", 503)
# --- LeetCode practice sheet feature ---
STATUS.setdefault("profile_not_found", 404)
STATUS.setdefault("company_not_found", 404)
STATUS.setdefault("sheet_not_found", 404)
STATUS.setdefault("invalid_username", 422)
STATUS.setdefault("sheet_unreadable", 422)
STATUS.setdefault("leetcode_unavailable", 502)
STATUS.setdefault("sheet_unavailable", 502)
# --- End LeetCode practice sheet feature ---
# --- GitHub project review feature ---
STATUS.setdefault("invalid_repo", 422)
STATUS.setdefault("invalid_github_username", 422)
STATUS.setdefault("too_many_repos", 422)
STATUS.setdefault("github_user_not_found", 404)
STATUS.setdefault("repo_not_found", 404)
STATUS.setdefault("github_unavailable", 502)
STATUS.setdefault("github_rate_limited", 429)
STATUS.setdefault("rate_limited", 429)
# --- End GitHub project review feature ---
STATUS.setdefault("ai_explanation_unusable", 502)
STATUS.setdefault("ai_consent_required", 403)  # appended, so sibling PRs editing the dict do not collide
# --- Profile feature ---
STATUS.setdefault("profile_not_confirmed", 422)
STATUS.setdefault("invalid_profile", 422)
# --- End profile feature ---
# --- Role-fit guardrail ---
STATUS.setdefault("role_change_needs_acknowledgment", 409)
# --- End role-fit guardrail ---
# --- Interview feature ---
STATUS.setdefault("session_not_found", 404)
STATUS.setdefault("mode_unsupported", 422)
STATUS.setdefault("answer_empty", 422)
STATUS.setdefault("interview_complete", 409)
STATUS.setdefault("interview_ended", 409)
# --- End interview feature ---

class ResumeIn(BaseModel):
    text: str = Field(max_length=200_000)  # plain text for now; PDF upload is an open question in the contract

class SkillReviewIn(BaseModel):
    skills: list[str] = Field(max_length=64)
    confirm: StrictBool

# --- Profile feature ---
class ProfileIn(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict, max_length=16)
    confirm: StrictBool
# --- End profile feature ---

class TargetIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    organization: str = Field(default="", max_length=160)
    rawText: str = Field(min_length=1, max_length=20_000)
    sourceUrl: str = Field(default="", max_length=2000)
    parentTargetId: Optional[str] = None

class TargetTailorIn(BaseModel):
    resumeId: str
    targetId: str
    acknowledgeRoleChange: StrictBool = False  # role-fit guardrail


class ExplainIn(BaseModel):
    consent: StrictBool = False


class TailorIn(BaseModel):
    resumeId: str
    jobId: str
    acknowledgeRoleChange: StrictBool = False  # role-fit guardrail

class RoadmapIn(BaseModel):
    resumeId: str
    targetRole: str


class EditIn(BaseModel):
    tailoredResume: Optional[str] = None
    coverNote: Optional[str] = None

class ApprovalIn(BaseModel):
    draftId: str
    decision: str

# --- Interview feature ---
class MockIn(BaseModel):
    targetRole: str = Field(min_length=1, max_length=120)
    mode: str = "text"
    resumeId: Optional[str] = None

class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    deliveryMetrics: Optional[dict] = None
# --- End interview feature ---


class ResetIn(BaseModel):
    confirm: str = ""

# --- LeetCode practice sheet feature ---
class PracticeProfileIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)

class PracticeSheetIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=120)
# --- End LeetCode practice sheet feature ---
# --- GitHub project review feature ---
class RepoListIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)

class ProjectReviewIn(BaseModel):
    repos: list = Field(min_length=1, max_length=8)
# --- End GitHub project review feature ---

def _mount(r: APIRouter, get_svc, outbound_gated):
    """The one route table. get_svc(request) -> SlateService decides whose data
    the call touches; the authenticated app derives it from the bearer token."""

    @r.post("/resume")
    def resume(request: Request, b: ResumeIn):
        with get_svc(request) as svc: return svc.upload_resume(b.text)

    @r.post("/resume/pdf")
    def resume_pdf(request: Request, file: UploadFile = File(...)):
        with get_svc(request, "fetch") as svc:  # authenticate BEFORE touching the upload
            # FastAPI runs sync endpoints in its worker pool. Never hold the
            # blocking per-user lock while awaiting on the event loop.
            data = file.file.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise SlateError("resume_unreadable", "PDF is too large (5 MB max).")
            try:
                text = extract_pdf_text(data)
            except ParseError as e:
                raise SlateError("resume_unreadable", str(e))
            result = svc.upload_resume(text)
            result["sourceText"] = text
            result["sourceTextKind"] = "original_uploaded_text_not_user_addendum"
            return result

    @r.get("/resume")
    def list_resumes(request: Request):
        with get_svc(request) as svc: return svc.list_resumes()

    @r.get("/resume/{rid}")
    def get_resume(request: Request, rid: str):
        with get_svc(request) as svc: return svc.get_resume(rid)

    @r.post("/resume/{rid}/skills/review")
    def review_skills(request: Request, rid: str, b: SkillReviewIn):
        with get_svc(request) as svc: return svc.review_resume_skills(rid, b.skills, b.confirm)

    # --- Profile feature ---
    @r.get("/profile")
    def get_profile(request: Request):
        with get_svc(request) as svc: return svc.get_profile()

    @r.get("/profile/suggestions")
    def profile_suggestions(request: Request, resumeId: str):
        with get_svc(request) as svc: return svc.profile_suggestions(resumeId)

    @r.post("/profile")
    def save_profile(request: Request, b: ProfileIn):
        with get_svc(request) as svc: return svc.save_profile(b.answers, b.confirm)
    # --- End profile feature ---

    @r.get("/jobs")
    def jobs(request: Request, query: str = "", location: str = "", resumeId: Optional[str] = None,
             source: Optional[str] = None):
        with get_svc(request) as svc: return svc.jobs(query, location, resumeId, source)

    @r.get("/jobs/feed")
    def jobs_feed(request: Request):
        with get_svc(request) as svc: return svc.jobs_feed_status()

    @r.post("/targets")
    def create_target(request: Request, b: TargetIn):
        with get_svc(request) as svc:
            return svc.create_target(b.title, b.organization, b.rawText, b.sourceUrl, b.parentTargetId)

    @r.get("/targets")
    def list_targets(request: Request):
        with get_svc(request) as svc: return svc.list_targets()

    @r.get("/targets/{target_id}")
    def get_target(request: Request, target_id: str):
        with get_svc(request) as svc: return svc.get_target(target_id)

    @r.post("/tailor/target")
    def tailor_target(request: Request, b: TargetTailorIn):
        with get_svc(request) as svc: return svc.tailor_target(b.resumeId, b.targetId, b.acknowledgeRoleChange)


    @r.post("/tailor")
    def tailor(request: Request, b: TailorIn):
        with get_svc(request) as svc: return svc.tailor(b.resumeId, b.jobId, b.acknowledgeRoleChange)

    @r.post("/tailor/ai")
    def tailor_ai(request: Request, b: TailorIn):
        # Opt-in AI drafting: off unless the server has a key AND the service supports it.
        with get_svc(request, "ai") as svc:  # authenticate first
            fn = getattr(svc, "tailor_ai", None)
            if fn is None or not os.getenv("LLM_API_KEY"):
                raise SlateError("ai_not_configured",
                                 "AI tailoring is off on this server. Set LLM_API_KEY to enable it.")
            return fn(b.resumeId, b.jobId, acknowledge_role_change=b.acknowledgeRoleChange)

    @r.post("/resume/{rid}/explain")
    def explain_resume(request: Request, rid: str, b: ExplainIn):
        # Opt-in model explanation of the parse. Off unless a key (or injected client) exists.
        with get_svc(request, "ai") as svc:  # authenticate first
            # Resume text leaves this server for the model provider only on an explicit
            # per-request yes. Nothing is stored; a missing/false flag never reaches the model.
            if b.consent is not True:
                raise SlateError("ai_consent_required",
                                 "Sending your resume text to the AI provider needs your explicit yes on each request.")
            fn = getattr(svc, "explain_resume", None)
            if fn is None or not (os.getenv("LLM_API_KEY") or getattr(svc, "_llm_client", None)):
                raise SlateError("ai_not_configured",
                                 "AI explanation is off on this server. Set LLM_API_KEY to enable it.")
            prep = svc.explain_prepare(rid)
        # The provider call runs after the per-user lock is released, so a slow model
        # cannot block this user's other requests. It touches no stored state.
        from slate_core.ai_service import explain_finish, explain_generate
        return explain_finish(prep, explain_generate(prep))

    @r.get("/drafts")
    def list_drafts(request: Request):
        with get_svc(request) as svc: return svc.list_drafts()

    @r.get("/drafts/{draft_id}")
    def get_draft(request: Request, draft_id: str):
        with get_svc(request) as svc: return svc.get_draft(draft_id)

    @r.get("/drafts/{draft_id}/download")
    def download(request: Request, draft_id: str):
        with get_svc(request) as svc:
            text = svc.download_draft(draft_id)
            # Generated ids are not accepted as arbitrary header text.
            import re
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", draft_id)[:80]
            return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="slate-' + safe + '.txt"'})

    @r.post("/drafts/{draft_id}/edit")
    def edit(request: Request, draft_id: str, b: EditIn):
        with get_svc(request) as svc: return svc.edit_draft(draft_id, **b.model_dump(exclude_none=True))

    @r.get("/drafts/{draft_id}/export")
    def export(request: Request, draft_id: str):
        with get_svc(request) as svc: return svc.export_draft(draft_id)

    @r.post("/roadmap")
    def roadmap(request: Request, b: RoadmapIn):
        with get_svc(request) as svc: return svc.roadmap(b.resumeId, b.targetRole)

    @r.post("/approvals")
    def approvals(request: Request, b: ApprovalIn):
        with get_svc(request) as svc: return svc.decide(b.draftId, b.decision)



    # --- LeetCode practice sheet feature ---
    @r.get("/practice/companies")
    def practice_companies(request: Request, q: str = ""):
        with get_svc(request):
            pass  # authenticate; the company list itself is static public data
        from slate_core.leetcode_sheet import search_companies
        return {"companies": search_companies(q)}

    @r.post("/practice/scan")
    def practice_scan_resumes(request: Request):
        """Find LeetCode profile links in the caller's own saved resume texts."""
        from slate_core.leetcode_sheet import extract_leetcode_usernames
        with get_svc(request, "fetch") as svc:
            found = []
            for meta in svc.list_resumes()["resumes"]:
                text = svc.get_resume(meta["resumeId"]).get("sourceText", "")
                names = extract_leetcode_usernames(text)
                if names:
                    found.append({"resumeId": meta["resumeId"], "name": meta["name"], "usernames": names})
            return {"matches": found}

    @r.post("/practice/scan-pdf")
    def practice_scan_pdf(request: Request, file: UploadFile = File(...)):
        """Find LeetCode links in an uploaded PDF, including hyperlink annotations
        (a linked name/icon carries the URL without visible text). Nothing stored."""
        from slate_core.leetcode_sheet import extract_pdf_leetcode_usernames
        with get_svc(request, "fetch"):  # authenticate BEFORE touching the upload
            data = file.file.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise SlateError("resume_unreadable", "PDF is too large (5 MB max).")
            return {"usernames": extract_pdf_leetcode_usernames(data)}

    @r.post("/practice/profile")
    def practice_profile(request: Request, b: PracticeProfileIn):
        """Public LeetCode stats for the confirmed username. Only the username
        leaves this server; no resume data is sent."""
        with outbound_gated(request):  # slot held across the real fetch
            from slate_core.leetcode_sheet import fetch_public_profile
            return fetch_public_profile(b.username)

    @r.post("/practice/sheet")
    def practice_sheet(request: Request, b: PracticeSheetIn):
        """Company practice sheet from the built-in MIT-licensed community
        compilation. Live public fetches run after the per-user lock is
        released; they touch no stored state."""
        with outbound_gated(request):  # slot held across the real fetches
            from slate_core.leetcode_sheet import build_practice_sheet
            return build_practice_sheet(b.username, b.company)

    @r.post("/practice/sheet-from-csv")
    def practice_sheet_from_csv(request: Request, file: UploadFile = File(...),
                                username: str = Form(...), company: str = Form("")):
        """Practice sheet from a CSV the user uploads (their own sheet).
        Nothing is stored."""
        from slate_core.leetcode_sheet import MAX_SHEET_CSV_BYTES, build_practice_sheet_from_csv
        with get_svc(request):  # authenticate BEFORE touching the upload
            data = file.file.read(MAX_SHEET_CSV_BYTES + 1)
            if len(data) > MAX_SHEET_CSV_BYTES:
                raise SlateError("sheet_unreadable", "CSV is too large (2 MB max).")
            csv_text = data.decode("utf-8-sig", errors="replace")
        with outbound_gated(request):  # the CSV build fetches the live profile
            return build_practice_sheet_from_csv(username, company, csv_text)
    # --- End LeetCode practice sheet feature ---

    # --- GitHub project review feature ---
    @r.post("/projects/scan")
    def projects_scan_resumes(request: Request):
        """Find GitHub links in the caller's own saved resume texts."""
        from slate_core.project_review import extract_github_links
        repos, users, seen = [], [], set()
        with get_svc(request, "fetch") as svc:
            for meta in svc.list_resumes()["resumes"]:
                text = svc.get_resume(meta["resumeId"]).get("sourceText", "")
                found = extract_github_links(text)
                for entry in found["repos"]:
                    key = (entry["owner"].lower(), entry["repo"].lower())
                    if key not in seen:
                        seen.add(key)
                        repos.append(entry)
                for u in found["usernames"]:
                    if u.lower() not in seen:
                        seen.add(u.lower())
                        users.append(u)
        return {"repos": repos, "usernames": users}

    @r.post("/projects/scan-pdf")
    def projects_scan_pdf(request: Request, file: UploadFile = File(...)):
        """Find GitHub links in an uploaded PDF, including hyperlink annotations
        that hide the URL behind an icon or name. The upload is never stored."""
        from slate_core.project_review import extract_pdf_github_links
        with get_svc(request, "fetch"):  # authenticate BEFORE touching the upload
            data = file.file.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise SlateError("resume_unreadable", "PDF is too large.")
            return extract_pdf_github_links(data)

    @r.post("/projects/repos")
    def projects_repos(request: Request, b: RepoListIn):
        """List a GitHub username's public repos so the user can PICK which ones
        are their resume projects. No auto-selection."""
        with outbound_gated(request):  # slot held across the real fetch
            from slate_core.project_review import list_user_repos
            return list_user_repos(b.username)

    @r.post("/projects/review")
    def projects_review(request: Request, b: ProjectReviewIn):
        """Static, evidence-based review of the chosen public repos. Nothing is
        stored and no repository code is ever executed."""
        with outbound_gated(request):  # was ungated; slot held across the review fetches
            from slate_core.project_review import build_review
            return build_review([str(v) for v in b.repos])
    # --- End GitHub project review feature ---

    # --- Interview feature ---
    @r.get("/config")
    def config():
        """What the login UI needs. Client ids / anon keys are public by design;
        this endpoint exposes no user data and needs no token. Token
        verification is enforced in create_authenticated_app. create_app is
        single-tenant test-fixture mode only."""
        gid = os.getenv("GOOGLE_CLIENT_ID")
        surl, skey = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
        if gid:
            return {"mode": "google", "googleClientId": gid}
        if surl and skey:
            return {"mode": "supabase", "supabaseUrl": surl, "supabaseAnonKey": skey}
        if os.getenv("SLATE_DEV_AUTH") == "1":
            return {"mode": "dev"}
        return {"mode": "unconfigured"}

    @r.post("/interview/mock")
    def mock(request: Request, b: MockIn):
        with get_svc(request, "ai") as svc:
            return svc.start_interview(b.targetRole, b.mode, b.resumeId)

    @r.post("/interview/{sid}/answer")
    def answer(request: Request, sid: str, b: AnswerIn):
        with get_svc(request, "ai") as svc:
            return svc.answer_interview(sid, b.text, b.deliveryMetrics)

    @r.post("/interview/{sid}/end")
    def end_interview(request: Request, sid: str):
        with get_svc(request, "ai") as svc:
            return svc.end_interview(sid)

    @r.get("/interview/{sid}/feedback")
    def feedback(request: Request, sid: str):
        with get_svc(request) as svc:
            return svc.interview_feedback(sid)
    # --- End interview feature ---


    @r.post("/demo/reset")
    def demo_reset(request: Request, b: ResetIn):
        # Off unless the local demo server opts in: SLATE_DEMO_RESET=1 uvicorn ...
        # In the authenticated app this wipes ONLY the caller's own data.
        if os.getenv("SLATE_DEMO_RESET") != "1":
            raise SlateError("demo_reset_disabled",
                             "Demo reset is off. Start the local demo with SLATE_DEMO_RESET=1 to enable it.")
        with get_svc(request) as svc: return svc.reset_demo(b.confirm)


def _shell(r: APIRouter) -> FastAPI:
    app = FastAPI(title="Slate API (core adapter)")
    from .request_limits import RequestBodyLimit
    app.add_middleware(RequestBodyLimit)
    app.include_router(r)

    @app.middleware("http")
    async def private_api_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/") or request.url.path == "/v1":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SlateError)
    async def _slate(_: Request, e: SlateError):
        return JSONResponse(e.to_dict(), status_code=STATUS.get(e.code, 400))

    @app.exception_handler(AuthError)
    async def _auth(_: Request, e: AuthError):
        return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=STATUS.get(e.code, 401))

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError):
        return JSONResponse({"error": {"code": "bad_request", "message": "Request body or query is invalid."}}, status_code=422)

    # --- Interview feature ---
    web_root = os.path.join(os.path.dirname(__file__), "..", "..", "web")
    web_interview = os.path.join(web_root, "interview.html")
    web_index = os.path.join(web_root, "index.html")
    web_ai = os.path.join(web_root, "ai.html")
    web_motion = os.path.join(web_root, "motion.js")

    @app.get("/resume", include_in_schema=False)
    @app.get("/targets", include_in_schema=False)
    @app.get("/draft", include_in_schema=False)
    @app.get("/comparisons", include_in_schema=False)
    @app.get("/roadmap", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def index_page():
        return FileResponse(web_index)

    @app.get("/ai", include_in_schema=False)
    def ai_page():
        return FileResponse(web_ai)


    @app.get("/interview", include_in_schema=False)
    def interview_page():
        return FileResponse(web_interview) if os.path.exists(web_interview) else JSONResponse({"message": "Interview page not found"})

    # --- LeetCode practice sheet feature ---
    web_practice = os.path.join(web_root, "practice.html")

    @app.get("/practice", include_in_schema=False)
    def practice_page():
        return FileResponse(web_practice) if os.path.exists(web_practice) else JSONResponse({"message": "Practice sheet page not found"}, status_code=404)
    # --- End LeetCode practice sheet feature ---

    # --- Onboarding & profile pages feature ---
    web_onboarding = os.path.join(web_root, "onboarding.html")
    web_profile = os.path.join(web_root, "profile.html")

    @app.get("/onboarding", include_in_schema=False)
    def onboarding_page():
        return FileResponse(web_onboarding) if os.path.exists(web_onboarding) else JSONResponse({"message": "Onboarding page not found"}, status_code=404)

    @app.get("/profile", include_in_schema=False)
    def profile_page():
        return FileResponse(web_profile) if os.path.exists(web_profile) else JSONResponse({"message": "Profile page not found"}, status_code=404)
    # --- End onboarding & profile pages feature ---

    # --- GitHub project review feature ---
    web_projects = os.path.join(web_root, "projects.html")

    @app.get("/projects", include_in_schema=False)
    def projects_page():
        return FileResponse(web_projects) if os.path.exists(web_projects) else JSONResponse({"message": "Project review page not found"}, status_code=404)
    # --- End GitHub project review feature ---

    @app.get("/motion.js", include_in_schema=False)
    def motion_script():
        return FileResponse(web_motion, media_type="text/javascript") if os.path.exists(web_motion) else JSONResponse({"message": "Motion script not found"}, status_code=404)
    # --- End interview feature ---

    return app


def create_app(service: Optional[SlateService] = None) -> FastAPI:
    """Test-fixture mode: single tenant, no auth. The served app never uses this."""
    svc = service or SlateService()
    r = APIRouter(prefix="/v1")
    _mount(r, lambda request, bucket=None: nullcontext(svc),
           lambda request: nullcontext(None))  # test fixture ignores rate buckets
    return _shell(r)


def create_authenticated_app(auth, user_store, llm_client=None) -> FastAPI:
    """The production construction: bearer token -> verified user -> that user's
    service, built fresh per request from the per-user store. A user id is never
    read from the request; demo reset wipes only the caller's own data."""
    from contextlib import contextmanager
    from slate_core.ai_service import AISlateService
    from slate_core.user_store import WriteConflict
    from .user_snapshot import RequestSnapshot, request_locked

    from slate_core.rate_gate import RateGate
    rate_gate = RateGate()

    @contextmanager
    def get_svc(request: Request, bucket: str = None):
        """bucket names an expensive class of work ("fetch" outbound/uploads,
        "ai" LLM-backed): the rate gate applies per-user and global ceilings
        plus a global concurrency bound before any work starts."""
        if auth is None:
            raise SlateError("auth_not_configured",
                             "Sign-in is not configured on this server. Set GOOGLE_CLIENT_ID "
                             "(or SUPABASE_URL + SUPABASE_ANON_KEY), or SLATE_DEV_AUTH=1 for local dev.")
        user = auth.authenticate(request.headers.get("authorization"))
        gated = bucket is not None
        if gated:
            rate_gate.check(bucket, user.id)
            rate_gate.acquire()
        try:
            with request_locked(user.id):  # separate from stores' own locks; avoids nested-lock deadlock
                try:
                    yield AISlateService(RequestSnapshot(user_store, user.id), llm_client=llm_client)
                except WriteConflict:
                    raise SlateError("state_conflict", "Your saved data changed in another request. Nothing from this request was saved. Reopen the latest version and try again.") from None
        finally:
            if gated:
                rate_gate.release()

    @contextmanager
    def outbound_gated(request: Request):
        """Bound the ACTUAL outbound work: authenticate, apply the fetch rate
        ceilings and hold the global concurrency slot for the whole network
        call. No per-user store lock is taken here on purpose: pure outbound
        fetches touch no stored state, and the store lock must never be held
        across the network. (Previously the slot was acquired and released by
        an empty get_svc block while the real fetch ran after release, which
        bounded nothing.)"""
        if auth is None:
            raise SlateError("auth_not_configured",
                             "Sign-in is not configured on this server. Set GOOGLE_CLIENT_ID "
                             "(or SUPABASE_URL + SUPABASE_ANON_KEY), or SLATE_DEV_AUTH=1 for local dev.")
        user = auth.authenticate(request.headers.get("authorization"))
        rate_gate.check("fetch", user.id)
        rate_gate.acquire()
        try:
            yield user
        finally:
            rate_gate.release()

    r = APIRouter(prefix="/v1")

    _mount(r, get_svc, outbound_gated)
    return _shell(r)

def _build_auth():
    """Exactly one provider. A real provider always wins over the dev flag, so a
    misconfigured deployment cannot silently fall into dev sign-in."""
    from slate_core.auth import DevAuth, GoogleAuth, SupabaseAuth
    gid = os.getenv("GOOGLE_CLIENT_ID")
    surl, skey = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if gid:
        return GoogleAuth(gid)
    if surl and skey:
        return SupabaseAuth(surl, skey)
    if os.getenv("SLATE_DEV_AUTH") == "1":
        return DevAuth()
    return None  # app still imports/serves pages; /v1 data calls answer 503

def _build_store():
    from slate_core.user_store import MemUserStore, SqlUserStore
    url = os.getenv("SLATE_STATE_URL")  # postgres (TLS) in production; sqlite locally; unset = ephemeral
    return SqlUserStore(url) if url else MemUserStore()

app = create_authenticated_app(_build_auth(), _build_store())
