"""Server-side LLM adapters for Gemini interview coaching and Groq tailoring.

Gemini interview coaching uses GEMINI_API_KEY; Groq tailoring uses LLM_API_KEY.
Neither key is read from or written to the client. Tests can inject MockLLM.
"""
import json
import os
import urllib.request

DEFAULT_MODEL = "gemini-3.8-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


class LLMClient:
    """Provider-replaceable interface: one method, plain text in and out."""

    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class MockLLM(LLMClient):
    """Deterministic stand-in for tests and demos without a key."""

    def __init__(self, reply: str = "mock response"):
        self.reply = reply
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class GeminiLLM(LLMClient):
    """Gemini Developer API over stdlib urllib. Key comes only from GEMINI_API_KEY."""

    def __init__(self, model: str = None, api_key: str = None, timeout: int = 30):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.api_key = (api_key if api_key is not None else
                        os.environ.get("GEMINI_API_KEY", ""))
        self.timeout = timeout

    def _request_body(self, prompt: str) -> bytes:
        return json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set on the server.")
        req = urllib.request.Request(
            API_BASE.format(model=self.model),
            data=self._request_body(prompt),
            headers={"content-type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            # Keep HTTP status and provider diagnostics; never include request headers or secrets.
            detail = ""
            if hasattr(e, "read"):
                try:
                    payload = json.loads(e.read().decode("utf-8", errors="replace"))
                    detail = str(payload.get("error", {}).get("message", ""))[:500]
                except Exception:
                    pass
            status = getattr(e, "code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise LLMError(f"Gemini request failed{suffix}: {detail or str(e)[:300]}") from None
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM response had no text.")

GROQ_API_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"


class GroqLLM(LLMClient):
    """Groq Cloud chat completions (OpenAI-compatible) over stdlib urllib.

    Key comes from the LLM_API_KEY env var, the same server-side swap
    convention as GeminiLLM. Verified against the free tier (Nov 8, 2026).
    """

    def __init__(self, model: str = GROQ_DEFAULT_MODEL, api_key: str = None, timeout: int = 30):
        self.model = model
        self.api_key = api_key if api_key is not None else os.environ.get("LLM_API_KEY", "")
        self.timeout = timeout

    def _request_body(self, prompt: str) -> bytes:
        return json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

    def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not set on the server.")
        req = urllib.request.Request(
            GROQ_API_BASE,
            data=self._request_body(prompt),
            headers={"content-type": "application/json",
                     # Groq's edge 403s urllib's default user agent
                     "user-agent": "slate/0.1 (python-urllib)",
                     "authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise LLMError(f"LLM request failed: {e}")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM response had no text.")


def llm_tailored_draft(parsed: dict, job: dict, client: LLMClient,
                       resume_text: str = "") -> dict:
    """LLM-generated tailored draft with the claim gate kept.

    Returns the build_draft shape plus flaggedClaims, violations and
    requiresApproval (always True: a human approves every LLM draft).

    Gate coverage (rule-based, fail-closed - from claims.validate):
    skills named in the draft, experience durations beyond the resume total,
    percentages and GPA values not in the original text, and degrees the
    resume does not list. What it still CANNOT catch: paraphrased or implied
    claims, employers/projects/job titles invented in free text, tone.
    A pass means "no rule-detectable unsupported claim", never "true".
    """
    from .claims import validate
    from .tailor import check_claims
    text = client.generate(build_tailor_prompt(parsed, job))
    resume, _, note = text.partition("COVER NOTE")
    resume = resume.replace("RESUME", "", 1).strip(" :\n")
    note = note.strip(" :\n")
    low = text.lower()
    claims = [s for s in job["skills"] if s.lower() in low]
    flagged = check_claims(parsed, claims)
    violations = validate(parsed, resume_text, resume, note) if resume_text else []
    return {
        "tailoredResume": resume,
        "coverNote": note,
        "claims": claims,
        "gaps": [s for s in job["skills"] if s not in claims],
        "flaggedClaims": flagged,
        "violations": violations,
        "requiresApproval": True,
    }


def build_tailor_prompt(parsed: dict, job: dict) -> str:
    """Prompt for a tailored resume draft and cover note. Callers must keep the
    existing claim check on whatever comes back - the LLM is not a fact check."""
    return (
        "Rewrite this resume for the job below. Rules: only claim skills, employers, "
        "education and numbers that appear in the original resume; do not invent anything. "
        "Return plain text with a 'RESUME' section and a 'COVER NOTE' section.\n\n"
        f"ORIGINAL RESUME:\n{json.dumps(parsed, indent=2)}\n\n"
        f"JOB:\n{json.dumps(job, indent=2)}"
    )


def build_feedback_prompt(questions: list, answers: list) -> str:
    """Prompt for interview feedback returning summary and weak areas."""
    qa = "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(questions, answers))
    return (
        "You are an interview coach. Given this mock interview transcript, return "
        "plain text with a 'SUMMARY' section (2-3 sentences) and a 'WEAK AREAS' "
        "section (one per line).\n\n"
        f"{qa}"
    )
