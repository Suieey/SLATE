"""Bound request bodies before FastAPI's JSON/multipart parsers run.

This bounds app-side buffering, not server/proxy network limits or PDF decoding.
No request body, filename, token or parser exception is logged here.
"""
import asyncio
from fastapi.responses import JSONResponse

MAX_JSON_BODY_BYTES = 2_000_000
MAX_PDF_BODY_BYTES = 5_000_000 + 65_536  # file plus bounded multipart overhead
BODY_READ_SECONDS = 20


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        limit = MAX_PDF_BODY_BYTES if scope.get("path") == "/v1/resume/pdf" else MAX_JSON_BODY_BYTES

        async def error(status, code, message):
            await JSONResponse({"error": {"code": code, "message": message}}, status_code=status)(scope, receive, send)

        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
                if declared < 0: raise ValueError()
            except ValueError:
                return await error(400, "bad_request", "Invalid request length.")
            if declared > limit:
                return await error(413, "request_too_large", "Request body is too large. PDF files must be at most 5 MB.")

        async def collect():
            parts, total = [], 0
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return None
                chunk = event.get("body", b"")
                total += len(chunk)
                if total > limit:
                    raise OverflowError()
                parts.append(chunk)
                if not event.get("more_body", False):
                    return b"".join(parts)
        try:
            body = await asyncio.wait_for(collect(), BODY_READ_SECONDS)
        except OverflowError:
            return await error(413, "request_too_large", "Request body is too large. PDF files must be at most 5 MB.")
        except asyncio.TimeoutError:
            return await error(408, "upload_timeout", "Request body took too long to upload. Retry with a smaller file or a stable connection.")
        if body is None:
            return
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        return await self.app(scope, replay, send)
