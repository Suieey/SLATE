"""Slate core: framework-free logic for the MVP flow.

Pure Python (standard library only). Returns the shapes in contracts/api-contracts.md,
so a FastAPI route, the CLI or the web app can call it directly.
No LLM calls: everything is deterministic so the demo is repeatable.
"""
from .service import SlateService, SlateError

__all__ = ["SlateService", "SlateError"]
