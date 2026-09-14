"""
AEGIS-SWARM Razorpay Edition :: Isolated Gemini Connectivity Diagnostic
==========================================================================
Run this ALONE, outside the full pipeline, to isolate exactly where a
Gemini call is stalling. It does NOT import anything from app/ except
the .env loader -- if THIS script also hangs for the full timeout, the
problem is proven to be network/environment, not application code
(risk_engine, MCP session cleanup, etc. are not even imported here).

Usage:
    python scripts/diagnose_gemini_connectivity.py

Reads GEMINI_API_KEY from .env automatically (same loading mechanism
as the rest of the app, via app/__init__.py).
"""

import os
import sys
import time
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: F401 -- triggers app/__init__.py's load_dotenv()


def step(name):
    print(f"\n{'='*70}\n{name}\n{'='*70}")


def check_dns():
    step("1. DNS resolution for generativelanguage.googleapis.com")
    start = time.monotonic()
    try:
        ip = socket.gethostbyname("generativelanguage.googleapis.com")
        elapsed = time.monotonic() - start
        print(f"[OK] Resolved to {ip} in {elapsed:.2f}s")
        return True
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"[FAIL] DNS resolution failed after {elapsed:.2f}s: {e}")
        print("  -> This points to a DNS/network config issue, not the SDK or your API key.")
        return False


def check_raw_tcp_connect():
    step("2. Raw TCP connect to generativelanguage.googleapis.com:443")
    start = time.monotonic()
    try:
        sock = socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=10)
        elapsed = time.monotonic() - start
        sock.close()
        print(f"[OK] TCP connect succeeded in {elapsed:.2f}s")
        return True
    except socket.timeout:
        elapsed = time.monotonic() - start
        print(f"[FAIL] TCP connect TIMED OUT after {elapsed:.2f}s")
        print("  -> Something between you and Google is dropping/blocking the connection")
        print("     silently -- classic symptom of a firewall, antivirus HTTPS inspection,")
        print("     or corporate/VPN network policy. This is NOT an API key or SDK problem.")
        return False
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"[FAIL] TCP connect failed after {elapsed:.2f}s: {type(e).__name__}: {e}")
        return False


def check_proxy_env_vars():
    step("3. Proxy environment variables")
    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "NO_PROXY"]
    found = {k: v for k in proxy_vars if (v := os.environ.get(k))}
    if found:
        print(f"[FOUND] Proxy variables are set: {found}")
        print("  -> If this proxy is misconfigured, unreachable, or requires auth the SDK")
        print("     doesn't handle, this alone can cause exactly this hang pattern.")
    else:
        print("[NONE] No proxy environment variables set.")


def check_raw_https_request():
    step("4. Raw HTTPS request via urllib (no google-genai SDK involved)")
    import urllib.request
    start = time.monotonic()
    try:
        req = urllib.request.Request("https://generativelanguage.googleapis.com/", method="GET")
        urllib.request.urlopen(req, timeout=10)
        elapsed = time.monotonic() - start
        print(f"[OK] HTTPS request completed in {elapsed:.2f}s (any HTTP status is fine here -- "
              f"we're only checking the connection itself completes)")
    except Exception as e:
        elapsed = time.monotonic() - start
        # A 404 or 403 HTTPError here is actually a GOOD sign -- it means the
        # connection worked and Google responded. Only a timeout is bad.
        if "urlopen error" in str(e).lower() or "timed out" in str(e).lower():
            print(f"[FAIL] HTTPS request timed out after {elapsed:.2f}s: {e}")
            print("  -> Confirms a network-path problem outside Python entirely.")
        else:
            print(f"[OK] Got an HTTP-level response (not a hang): {type(e).__name__}: {e}")
            print(f"     (elapsed {elapsed:.2f}s -- this is fine, means the connection worked)")


def check_genai_sdk_call(timeout_seconds=15):
    step(f"5. Real google-genai SDK call, with an explicit SHORT ({timeout_seconds}s) SDK-level timeout")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[SKIP] GEMINI_API_KEY not set.")
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        print(f"[FAIL] Could not import google-genai: {e}")
        return

    print(f"google-genai installed. Attempting a minimal generate_content call "
          f"with http_options timeout={timeout_seconds*1000}ms (SDK-enforced, not just our own wrapper)...")

    start = time.monotonic()
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_seconds * 1000),  # milliseconds
        )
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents="Reply with exactly one word: OK",
        )
        elapsed = time.monotonic() - start
        print(f"[OK] Gemini responded in {elapsed:.2f}s: {response.text!r}")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"[FAIL] after {elapsed:.2f}s: {type(e).__name__}: {e}")
        if elapsed >= timeout_seconds - 1:
            print("  -> The SDK's own timeout fired (not a hang) -- this means the underlying")
            print("     connection attempt itself is what's slow/blocked, consistent with steps 1-4.")
        else:
            print("  -> Failed FAST, before the timeout -- this is a different class of problem")
            print("     (auth/key/quota/region), not a hang. Read the exact error message above.")


if __name__ == "__main__":
    print("AEGIS-SWARM :: Gemini Connectivity Diagnostic")
    print(f"GEMINI_API_KEY present: {bool(os.environ.get('GEMINI_API_KEY'))}")

    dns_ok = check_dns()
    if dns_ok:
        check_raw_tcp_connect()
    check_proxy_env_vars()
    check_raw_https_request()
    check_genai_sdk_call()

    print(f"\n{'='*70}\nDONE -- read the [OK]/[FAIL] lines above top to bottom.\n{'='*70}")
    print("If steps 1-4 all FAIL or hang: this is a network/firewall/proxy/antivirus")
    print("problem on this machine, not an AEGIS-SWARM code problem or an API key problem.")
    print("Try: (a) a different network (mobile hotspot), (b) temporarily disabling")
    print("antivirus/VPN, (c) Google Colab as a clean-network sanity check.")
