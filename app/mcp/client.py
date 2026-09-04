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
"""

import sys
import json
from pathlib import Path

MCP_SERVER_PATH = str(Path(__file__).resolve().parent / "server.py")

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


async def _call_mcp_tool_real(tool_name: str, arguments: dict) -> dict:
    """
    REAL MCP PATH. Spawns the evidence MCP server as a subprocess,
    performs the JSON-RPC initialize() handshake, calls the requested
    tool, and returns its parsed JSON result. Mirrors AEGIS v1's
    get_telemetry_via_mcp() function structure exactly. Untested in
    this sandbox (see module docstring) -- verify locally.
    """
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env=None,
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)

                if result.content and len(result.content) > 0:
                    raw_data = result.content[0].text
                    return json.loads(raw_data)

                return {"error": "Empty response from MCP tool", "mcp_status": "empty_response"}

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


async def _call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Dispatches to the real MCP path or the in-process fallback, per USE_REAL_MCP."""
    if USE_REAL_MCP:
        return await _call_mcp_tool_real(tool_name, arguments)
    return _call_mcp_tool_fallback(tool_name, arguments)


async def get_customer_history(customer_id: str) -> dict:
    return await _call_mcp_tool("get_customer_history", {"customer_id": customer_id})


async def get_device_history(customer_id: str) -> dict:
    return await _call_mcp_tool("get_device_history", {"customer_id": customer_id})


async def get_velocity(transaction_id: str) -> dict:
    return await _call_mcp_tool("get_velocity", {"transaction_id": transaction_id})


async def get_transaction_history(customer_id: str, exclude_transaction_id: str | None = None) -> dict:
    args = {"customer_id": customer_id}
    if exclude_transaction_id:
        args["exclude_transaction_id"] = exclude_transaction_id
    return await _call_mcp_tool("get_transaction_history", args)


async def get_chargeback_history(customer_id: str) -> dict:
    return await _call_mcp_tool("get_chargeback_history", {"customer_id": customer_id})


async def gather_all_evidence(transaction_id: str, customer_id: str) -> dict:
    """
    Convenience function: calls all five evidence tools for one
    transaction and returns the combined raw results. This is what
    the Investigator agent calls -- one function, five real MCP
    round-trips underneath (not five hallucinated fields).
    """
    customer_hist = await get_customer_history(customer_id)
    device_hist = await get_device_history(customer_id)
    velocity = await get_velocity(transaction_id)
    txn_hist = await get_transaction_history(customer_id, exclude_transaction_id=transaction_id)
    chargeback_hist = await get_chargeback_history(customer_id)

    return {
        "customer_history": customer_hist,
        "device_history": device_hist,
        "velocity": velocity,
        "transaction_history": txn_hist,
        "chargeback_history": chargeback_hist,
    }
