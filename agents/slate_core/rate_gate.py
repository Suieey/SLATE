"""In-process rate and concurrency bounds for expensive endpoints.

Per-request size caps cannot bound repeated or concurrent use: outbound
GitHub fetches, LLM calls and heavy uploads share provider quotas and one
small server, so a public deployment also needs per-user and global
ceilings. In-memory on purpose (the app runs a single worker); abuse gets
an honest 429 with a retry hint, never a silent drop and never an unbounded
queue. Limits are env-tunable so local development and tests stay easy.
"""
import os
import threading
import time

from .service import SlateError


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


class RateGate:
    """Sliding-window counters per (bucket, key) plus one global semaphore.

    Memory is bounded: keys idle past their window are pruned and the map is
    hard-capped, so a flood of distinct users cannot grow it without limit.
    """

    # (per-user count, window seconds, global count) per bucket
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits = {}
        self._max_tracked = _int_env("SLATE_RATE_MAX_TRACKED", 10000)
        self._sem = threading.BoundedSemaphore(_int_env("SLATE_EXPENSIVE_CONCURRENCY", 4))
        self.buckets = {
            # Outbound-fetch / heavy-upload work (GitHub, LeetCode, PDFs).
            "fetch": (_int_env("SLATE_RATE_FETCH_USER", 30), 600,
                      _int_env("SLATE_RATE_FETCH_GLOBAL", 150)),
            # LLM-backed work (AI draft, explanation, interview) - provider
            # free-tier quota is the real budget, so the global ceiling is an
            # hour window.
            "ai": (_int_env("SLATE_RATE_AI_USER", 30), 3600,
                   _int_env("SLATE_RATE_AI_GLOBAL", 240)),
        }

    def _record(self, key, limit: int, window: int, now: float) -> None:
        stamps = [t for t in self._hits.get(key, []) if now - t < window]
        if len(stamps) >= limit:
            retry = max(1, int(window - (now - stamps[0])))
            raise SlateError(
                "rate_limited",
                "Too many requests right now. Try again in about %d seconds." % retry)
        stamps.append(now)
        self._hits[key] = stamps

    def check(self, bucket: str, user_key: str) -> None:
        conf = self.buckets.get(bucket)
        if not conf:
            return
        per_user, window, per_global = conf
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self._max_tracked:
                self._hits = {k: v for k, v in self._hits.items()
                              if v and now - v[-1] < window}
            # Hard cap, fail closed: when pruning idle keys is not enough (a
            # flood of fresh distinct keys), a NEW key is refused instead of
            # letting the map grow without bound. Keys already tracked keep
            # their normal budget; the window slides, so the refusal lifts.
            if len(self._hits) > self._max_tracked and (bucket, "u:" + user_key) not in self._hits:
                raise SlateError(
                    "rate_limited",
                    "The server is busy with other requests right now. Try again in a few seconds.")
            self._record((bucket, "global"), per_global, window, now)
            self._record((bucket, "u:" + user_key), per_user, window, now)

    def acquire(self) -> None:
        if not self._sem.acquire(blocking=False):
            raise SlateError(
                "rate_limited",
                "The server is busy with other requests right now. Try again in a few seconds.")

    def release(self) -> None:
        self._sem.release()
