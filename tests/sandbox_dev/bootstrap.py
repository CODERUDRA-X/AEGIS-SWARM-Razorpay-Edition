"""
AEGIS-SWARM Razorpay Edition :: Sandbox Test Bootstrap
=========================================================
SANDBOX-ONLY. Not part of the production codebase, not imported by
anything under app/.

This script injects lightweight, dependency-free stand-ins into
sys.modules for packages unavailable in this sandbox (pydantic,
specifically) BEFORE importing any real app.* module. This means every
file under app/ is imported completely unmodified -- `from pydantic
import BaseModel, Field` resolves to our shim purely because of the
sys.modules injection, not because any app/ file was changed to
special-case the sandbox.

This is what lets us verify:
- schema construction and field defaults
- Detector's deterministic score_to_level() mapping
- Investigator's evidence classification logic
- Policy Gate's rule routing
- baseline model training/prediction/evaluation
- full pipeline orchestration wiring

WITHOUT pydantic, fastapi, google-genai, or mcp actually installed.

WHAT IS EXPLICITLY NOT VERIFIED BY THIS SCRIPT:
- Real Gemini API calls (agents/detector.py's LLM path, agents/critic.py)
  -- these require google-genai and a live API key. Any pipeline run
  through this bootstrap uses use_llm_detector=False, use_llm_critic=False
  (template/rule-based fallbacks) specifically to avoid needing google-genai.
- Real MCP subprocess/stdio protocol (app/mcp/client.py's USE_REAL_MCP
  path) -- this requires the `mcp` package. The in-process fallback
  path in client.py IS exercised (real evidence lookup values, just
  without the stdio transport), which is a legitimate, disclosed
  substitute for evidence-retrieval logic testing -- see
  app/mcp/client.py's module docstring.
- FastAPI endpoints (app/main.py) -- requires fastapi, not stubbed here
  since the REST layer is thin wiring around risk_engine.run_pipeline(),
  which IS fully tested below.
"""

import sys
from pathlib import Path

SANDBOX_DIR = Path(__file__).parent
sys.path.insert(0, str(SANDBOX_DIR.parent.parent))  # repo root, so `app.*` imports resolve

from tests.sandbox_dev._pydantic_shim import ShimBaseModel, Field as _shim_field
import types as _types

_pydantic_stub = _types.ModuleType("pydantic")
_pydantic_stub.BaseModel = ShimBaseModel
_pydantic_stub.Field = _shim_field
sys.modules["pydantic"] = _pydantic_stub


def _unavailable(*args, **kwargs):
    raise RuntimeError(
        "google.genai is stubbed out in the sandbox test bootstrap and has no "
        "real implementation. Any code path reaching this point would be "
        "making a real Gemini API call, which requires use_llm=True and a "
        "real `google-genai` install -- neither is available in this sandbox. "
        "Sandbox tests must pass use_llm_detector=False, use_llm_critic=False."
    )

_google_stub = _types.ModuleType("google")
_genai_stub = _types.ModuleType("google.genai")
_genai_types_stub = _types.ModuleType("google.genai.types")


class _StubClient:
    def __init__(self, *args, **kwargs):
        self.models = _StubModels()


class _StubModels:
    def generate_content(self, *args, **kwargs):
        _unavailable()


class _StubGenerateContentConfig:
    def __init__(self, *args, **kwargs):
        pass


_genai_stub.Client = _StubClient
_genai_types_stub.GenerateContentConfig = _StubGenerateContentConfig
_google_stub.genai = _genai_stub

sys.modules["google"] = _google_stub
sys.modules["google.genai"] = _genai_stub
sys.modules["google.genai.types"] = _genai_types_stub

print("[SANDBOX BOOTSTRAP] Injected dependency-free pydantic shim into sys.modules.")
print("[SANDBOX BOOTSTRAP] Injected a NON-FUNCTIONAL google.genai stub (raises if actually called).")
print("[SANDBOX BOOTSTRAP] This is NOT real pydantic or real google-genai -- see _pydantic_shim.py docstring.")
print("[SANDBOX BOOTSTRAP] Production environments with real deps installed do not need this.")
print("[SANDBOX BOOTSTRAP] Any test using this bootstrap MUST pass use_llm_detector=False, use_llm_critic=False.")
