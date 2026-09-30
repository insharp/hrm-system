"""
app/core/rate_limit.py
======================
Lightweight in-process rate limiter for sensitive auth endpoints
(login, 2FA, OTP send/verify, password reset) to blunt brute-force attacks.

It uses a fixed-window counter keyed by (scope, client-IP). This has no external
dependencies (no Redis) which keeps local dev and single-process deployments
simple. NOTE: state lives in the worker's memory, so with multiple worker
processes each worker enforces the limit independently. For a hardened
multi-worker/multi-host deployment, swap `_HITS` for a shared store (Redis).

Usage (FastAPI dependency factory):

    from app.core.rate_limit import rate_limit

    @router.post("/login", dependencies=[Depends(rate_limit("login", limit, window))])
    def login(...): ...

or call the guard directly inside a handler:

    enforce_rate_limit(request, "login", limit, window)
"""

import threading
import time
from typing import Callable

from fastapi import HTTPException, Request, status

from app.core.config import RATE_LIMIT_ENABLED, TRUST_PROXY_HEADERS

# (scope, ip) -> (window_start_epoch, count)
_HITS: dict[tuple[str, str], tuple[float, int]] = {}
_LOCK = threading.Lock()

# Opportunistic cleanup so the dict doesn't grow unbounded for one-off IPs.
_LAST_SWEEP = 0.0
_SWEEP_INTERVAL_SECONDS = 300


def _client_ip(request: Request) -> str:
    """Best-effort client IP. Honours X-Forwarded-For only when TRUST_PROXY_HEADERS is on."""
    forwarded = request.headers.get("x-forwarded-for") if TRUST_PROXY_HEADERS else None
    if forwarded:
        # First entry is the original client.
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    """Drop stale windows. Caller must hold _LOCK."""
    global _LAST_SWEEP
    if now - _LAST_SWEEP < _SWEEP_INTERVAL_SECONDS:
        return
    _LAST_SWEEP = now
    stale = [
        key for key, (start, _) in _HITS.items()
        # Keep at most ~1h of history regardless of the endpoint window.
        if now - start > 3600
    ]
    for key in stale:
        _HITS.pop(key, None)


def enforce_rate_limit(request: Request, scope: str, limit: int, window_seconds: int) -> None:
    """
    Raise HTTP 429 if the client IP has exceeded `limit` requests to `scope`
    within `window_seconds`. No-op when RATE_LIMIT_ENABLED is False.
    """
    if not RATE_LIMIT_ENABLED or limit <= 0:
        return

    ip = _client_ip(request)
    key = (scope, ip)
    now = time.time()

    with _LOCK:
        _sweep(now)
        start, count = _HITS.get(key, (now, 0))

        # Window expired → start a fresh one.
        if now - start >= window_seconds:
            start, count = now, 0

        count += 1
        _HITS[key] = (start, count)

        if count > limit:
            retry_after = max(1, int(window_seconds - (now - start)))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


def rate_limit(scope: str, limit: int, window_seconds: int) -> Callable[[Request], None]:
    """FastAPI dependency factory wrapping `enforce_rate_limit`."""

    def _dependency(request: Request) -> None:
        enforce_rate_limit(request, scope, limit, window_seconds)

    return _dependency
