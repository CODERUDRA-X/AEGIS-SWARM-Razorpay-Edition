"""
AEGIS-SWARM Razorpay Edition :: MCP Client Wrapper
=====================================================
REUSED PATTERN from AEGIS v1's server.py::get_telemetry_via_mcp() --
the subprocess-spawn + stdio_client + ClientSession + session.initialize()
+ session.call_tool() sequence is carried over essentially unchanged,
because it is genuine, working MCP client plumbing, not domain-specific
code. Only the tool names and arguments being called are new.

WHY WRAP EACH TOOL CALL IN ITS OWN FUNCTION:
The Investigator agent (app/agents/investigator.py) needs to call five
different evidence tools per transaction. Rather than have the agent
manage raw MCP session objects, this module exposes one Python async
function per MCP tool with a typed, simple signature -- the agent code
reads like normal function calls, while the actual protocol handshake
still happens for real underneath.

============================================================
IMPORTANT / SANDBOX DISCLOSURE -- READ BEFORE TRUSTING "MCP WORKS":
============================================================
This build sandbox has NO network access, so `pip install mcp` cannot
complete here (same root cause as the XGBoost situation in
app/models/baseline.py). That means the REAL MCP code path below
(USE_REAL_MCP=True, using the actual `mcp` SDK) has NOT been executed
in this environment -- it has been written against the correct, real
mcp SDK API (identical import shape to AEGIS v1's proven working
server.py/mcp_server.py), but it is untested here.

To make the Investigator agent buildable and testable in THIS sandbox
right now, this module also provides a fallback in-process evidence
path (_call_tool_fallback) that calls the exact same tool functions
from app/mcp/server.py directly, in-process, with no subprocess/stdio
involved. This produces IDENTICAL evidence output (same functions,
same data lookups) -- it only skips the protocol transport layer.

The switch is automatic: if `import mcp` fails, USE_REAL_MCP becomes
False and the fallback is used, with a one-time printed warning so
this is never silently misrepresented as "real MCP ran."

TO VERIFY REAL MCP LOCALLY:
    pip install mcp httpx
    python -c "import asyncio; from app.mcp.client import gather_all_evidence; \\
               print(asyncio.run(gather_all_evidence('TXN_000070', 'CUST_00139')))"
    # Check the printed startup message confirms "real MCP subprocess/stdio path".

============================================================
PERSISTENT-SESSION FIX (added after a real hang was diagnosed on
Windows during full held-out evaluation):
============================================================
The functions below (get_customer_history, get_device_history, etc.)
each independently call _call_mcp_tool(), which -- if not given an
existing session -- spawns a BRAND NEW subprocess (full process
creation + JSON-RPC initialize() handshake) via _call_mcp_tool_real()
for that ONE call, then tears the subprocess down. gather_all_evidence()
calls five of these per transaction. Over a 135-row evaluation run,
that is 675 individual subprocess spawns.

This was fine for single-transaction use (a live /api/analyze request,
or the one-off verify_local_production_path.py check) where the
per-call overhead is invisible. It is NOT fine for the evaluation
harness, which calls gather_all_evidence() 135 times in a loop --
process creation is expensive, especially on Windows (no fork();
CreateProcess is commonly 1-3+ seconds under antivirus real-time
scanning), and 675 sequential spawns can plausibly account for 20+
minutes of low-CPU, I/O-bound wall-clock time that looks like a hang
but is actually just extreme sequential process-creation overhead.

The fix: `mcp_session()` below is an async context manager that opens
ONE subprocess + one JSON-RPC session and keeps it alive for reuse
across many tool calls. Every function in this module now accepts an
OPTIONAL `session` parameter:
  - session=None (default): unchanged behavior -- opens and tears down
    its own subprocess for this one call. Used by every existing
    caller (main.py's /api/analyze, verify_local_production_path.py,
    the test suite) with ZERO changes needed to those call sites.
  - session=<an object from mcp_session()>: reuses that session's
    already-open subprocess instead of spawning a new one. Used by
    app/services/evaluation.py's evaluation loop, which opens exactly
    ONE session for the entire 135-transaction run.

This is purely a transport-efficiency change. It does not alter what
evidence is returned, what the tools do, or any evaluation semantics.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

MCP_SERVER_PATH = str(Path(__file__).resolve().parent / "server.py")

# Bounded timeout for a single MCP tool call. Previously there was NO
# timeout anywhere on session.call_tool() -- if a call genuinely hung
# (vs. merely being slow due to subprocess-spawn overhead, see the
# PERSISTENT-SESSION FIX note above), there was no way to detect or
# recover from it. 30s is generous for a local subprocess round-trip
# (which should normally take milliseconds); configurable via env var
# so this can be tuned per-environment without a code change.
MCP_CALL_TIMEOUT_SECONDS = float(os.environ.get("AEGIS_MCP_TIMEOUT_SECONDS", "30"))

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    USE_REAL_MCP = True
    print("[MCP CLIENT] `mcp` SDK found -- using real MCP subprocess/stdio path.")
except ImportError:
    USE_REAL_MCP = False
    print(
        "[MCP CLIENT] WARNING: `mcp` SDK not installed in this environment "
        "(no network access in this sandbox). Falling back to in-process "
        "tool calls that hit the SAME functions in app/mcp/evidence_tools.py "
        "(also used by app/mcp/server.py's real MCP registration), "
        "just without the stdio/subprocess transport layer. Evidence "
        "VALUES are identical either way; only the protocol path differs. "
        "Install `mcp` locally to exercise the real subprocess/stdio path."
    )


@asynccontextmanager
async def mcp_session():
    """
    Opens ONE MCP subprocess + one JSON-RPC ClientSession and yields it
    for reuse across many tool calls -- this is the persistent-session
    fix described in the module docstring. The subprocess is spawned and
    initialize()'d exactly once, then torn down exactly once when the
    `async with` block exits (or on exception).

    If `mcp` isn't installed (sandbox/dev fallback), yields None -- every
    function in this module treats session=None as "use the no-session
    path" regardless of whether that means "spawn a fresh subprocess"
    (USE_REAL_MCP=True) or "call the in-process fallback" (USE_REAL_MCP=False),
    so callers do not need to branch on USE_REAL_MCP themselves.

    Usage:
        async with mcp_session() as session:
            for txn in many_transactions:
                evidence = await gather_all_evidence(txn.id, txn.cust_id, session=session)
    """
    if not USE_REAL_MCP:
        yield None
        return

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env=None,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _call_mcp_tool_real(tool_name: str, arguments: dict, session=None) -> dict:
    """
    REAL MCP PATH. If `session` is provided, reuses it (no new
    subprocess). Otherwise spawns a fresh subprocess for this one call
    -- the original behavior, preserved exactly for callers that don't
    pass a session (single-transaction use: main.py, verify script,
    tests).

    Every call is now bounded by MCP_CALL_TIMEOUT_SECONDS via
    asyncio.wait_for -- previously unbounded, which meant a genuinely
    stuck call (as opposed to merely slow due to subprocess overhead)
    would hang the whole process with no way to detect it.
    """
    try:
        if session is not None:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=MCP_CALL_TIMEOUT_SECONDS,
            )
        else:
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[MCP_SERVER_PATH],
                env=None,
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as new_session:
                    await asyncio.wait_for(new_session.initialize(), timeout=MCP_CALL_TIMEOUT_SECONDS)
                    result = await asyncio.wait_for(
                        new_session.call_tool(tool_name, arguments=arguments),
                        timeout=MCP_CALL_TIMEOUT_SECONDS,
                    )

        if result.content and len(result.content) > 0:
            raw_data = result.content[0].text
            return json.loads(raw_data)

        return {"error": "Empty response from MCP tool", "mcp_status": "empty_response"}

    except asyncio.TimeoutError:
        print(f"[MCP CLIENT] TIMEOUT after {MCP_CALL_TIMEOUT_SECONDS}s calling {tool_name}({arguments})")
        return {"error": f"MCP call timed out after {MCP_CALL_TIMEOUT_SECONDS}s", "mcp_status": "timeout"}
    except Exception as e:
        print(f"[MCP CLIENT] Protocol communication failed calling {tool_name}: {e}")
        return {"error": str(e), "mcp_status": "protocol_failure"}


def _call_mcp_tool_fallback(tool_name: str, arguments: dict) -> dict:
    """
    FALLBACK PATH (sandbox-only, used when `mcp` SDK is unavailable).
    Calls the exact same tool function from app/mcp/evidence_tools.py
    directly, in-process -- the same functions app/mcp/server.py
    registers as real MCP tools. Returns identical evidence values to
    the real MCP path -- the FastMCP @mcp.tool() decorator does not
    change what the underlying Python function returns, so this is not
    a different implementation, just a different transport (none, vs.
    subprocess/stdio/JSON-RPC).
    """
    from app.mcp import evidence_tools

    tool_fn = getattr(evidence_tools, tool_name, None)
    if tool_fn is None:
        return {"error": f"Unknown tool '{tool_name}'", "mcp_status": "not_found"}
    return tool_fn(**arguments)


async def _call_mcp_tool(tool_name: str, arguments: dict, session=None) -> dict:
    """Dispatches to the real MCP path (optionally reusing `session`) or the in-process fallback."""
    if USE_REAL_MCP:
        return await _call_mcp_tool_real(tool_name, arguments, session=session)
    return _call_mcp_tool_fallback(tool_name, arguments)


async def get_customer_history(customer_id: str, session=None) -> dict:
    return await _call_mcp_tool("get_customer_history", {"customer_id": customer_id}, session=session)


async def get_device_history(customer_id: str, session=None) -> dict:
    return await _call_mcp_tool("get_device_history", {"customer_id": customer_id}, session=session)


async def get_velocity(transaction_id: str, session=None) -> dict:
    return await _call_mcp_tool("get_velocity", {"transaction_id": transaction_id}, session=session)


async def get_transaction_history(customer_id: str, exclude_transaction_id: str | None = None, session=None) -> dict:
    args = {"customer_id": customer_id}
    if exclude_transaction_id:
        args["exclude_transaction_id"] = exclude_transaction_id
    return await _call_mcp_tool("get_transaction_history", args, session=session)


async def get_chargeback_history(customer_id: str, session=None) -> dict:
    return await _call_mcp_tool("get_chargeback_history", {"customer_id": customer_id}, session=session)


async def gather_all_evidence(transaction_id: str, customer_id: str, session=None) -> dict:
    """
    Convenience function: calls all five evidence tools for one
    transaction and returns the combined raw results. This is what
    the Investigator agent calls -- one function, five real MCP
    round-trips underneath (not five hallucinated fields).

    Pass `session` (from `async with mcp_session() as session:`) to
    reuse one already-open subprocess across many calls to this
    function -- e.g. across all 135 transactions in a held-out
    evaluation run -- instead of spawning 5 new subprocesses every
    single call. Defaults to None (original per-call-subprocess
    behavior), so every existing caller is unaffected.
    """
    customer_hist = await get_customer_history(customer_id, session=session)
    device_hist = await get_device_history(customer_id, session=session)
    velocity = await get_velocity(transaction_id, session=session)
    txn_hist = await get_transaction_history(customer_id, exclude_transaction_id=transaction_id, session=session)
    chargeback_hist = await get_chargeback_history(customer_id, session=session)

    return {
        "customer_history": customer_hist,
        "device_history": device_hist,
        "velocity": velocity,
        "transaction_history": txn_hist,
        "chargeback_history": chargeback_hist,
    }
