"""
AEGIS-SWARM Razorpay Edition :: Bounded Gemini Call Wrapper
==============================================================
Added after a real hang was diagnosed during a full held-out evaluation
run on Windows (`python -m app.services.evaluation xgboost --llm-critic`
ran 20+ minutes with no progress and no report produced).

Investigation confirmed multiple contributing causes (see
app/mcp/client.py's module docstring for the primary one -- subprocess-
per-MCP-tool-call overhead). This module addresses a SEPARATE, smaller
contributing factor: neither app/agents/detector.py nor
app/agents/critic.py's `client.models.generate_content(...)` call had
any timeout. If a single Gemini call stalls (network hiccup, or the
google-genai SDK's own internal retry/backoff extending well beyond
what looks like "hanging"), there was no bound and no way to detect
which transaction it happened on.

`call_with_timeout()` runs a blocking callable in a short-lived worker
thread and enforces a wall-clock timeout via
`concurrent.futures.Future.result(timeout=...)` -- this works
identically on Windows, Linux, and macOS (unlike `signal.alarm`, which
is POSIX-only and would not have helped on the Windows environment
where this was diagnosed).

This does NOT change what is sent to Gemini, the prompt, the
temperature, the response schema, or how the response is parsed -- it
only bounds how long the codebase will wait for the call to return.
"""

import os
import concurrent.futures

# Generous default: a real Gemini call normally completes in a few
# seconds. 45s comfortably covers normal network variance while still
# guaranteeing the evaluation loop cannot stall forever on one call.
# Configurable per-environment without a code change.
GEMINI_CALL_TIMEOUT_SECONDS = float(os.environ.get("AEGIS_GEMINI_TIMEOUT_SECONDS", "45"))

# One shared, small thread pool for these bounded calls -- avoids
# spinning up a new thread (and its OS-level overhead) for every single
# Gemini call across 135 evaluation rows.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="gemini-call")


class GeminiCallTimeout(TimeoutError):
    """Raised when a Gemini API call exceeds GEMINI_CALL_TIMEOUT_SECONDS."""
    pass


def call_with_timeout(fn, *args, timeout: float | None = None, **kwargs):
    """
    Runs fn(*args, **kwargs) in a worker thread and waits up to
    `timeout` seconds (default GEMINI_CALL_TIMEOUT_SECONDS) for it to
    return. Raises GeminiCallTimeout if the deadline is exceeded --
    the underlying call keeps running in its thread in that case (Python
    cannot forcibly kill a thread), but the caller is unblocked and can
    report/skip/retry rather than waiting indefinitely.
    """
    timeout = timeout if timeout is not None else GEMINI_CALL_TIMEOUT_SECONDS
    future = _executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise GeminiCallTimeout(
            f"Gemini call did not return within {timeout}s (fn={getattr(fn, '__qualname__', fn)})"
        )
