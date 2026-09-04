"""
AEGIS-SWARM Razorpay Edition :: Package Initialization
==========================================================
Loads the repository-root .env exactly once, the moment anything under
`app.*` is first imported. This is what guarantees GEMINI_API_KEY (and
any other .env-configured value) is available consistently regardless
of entry point -- Python always imports a package's __init__.py before
any of its submodules, so this runs ahead of app.main, app.agents.*,
app.services.*, etc. no matter which one triggered the import.

BUG THIS FIXES:
Previously, `load_dotenv()` was called individually inside app/main.py
and scripts/verify_local_production_path.py -- but NOT anywhere in the
app.services.evaluation import chain. Running
`python -m app.services.evaluation xgboost --llm-critic` therefore never
loaded .env before app/agents/critic.py and app/agents/detector.py read
GEMINI_API_KEY from os.environ, raising `ValueError: GEMINI_API_KEY is
not set.` even with a valid, populated .env file on disk. Confirmed by
tracing every load_dotenv()/GEMINI_API_KEY reference in the codebase --
app/main.py and the verify script each loaded .env for themselves, but
nothing loaded it on behalf of a bare `python -m app.services.evaluation`
invocation.

WHY HERE, NOT "add load_dotenv() to evaluation.py too":
Patching evaluation.py alone would fix this one entry point but leaves
the same class of bug latent for any future entry point (a new script,
a new service module, a test file that imports app.agents.critic
directly) that also forgets to call load_dotenv() itself. Loading it
once at the package boundary removes the failure mode entirely, for
every current and future entry point, with a one-file change.

WHY AN EXPLICIT PATH, NOT load_dotenv()'S DEFAULT DISCOVERY:
python-dotenv's bare `load_dotenv()` walks upward from the caller's
stack frame looking for a .env file, which is usually fine but is a
heuristic that can behave differently depending on how deeply nested
the importing module is, the working directory a process was launched
from, or how a test runner collects files. Resolving the path
explicitly relative to this file's own location (repo root = parent of
this app/ package) is deterministic in every case above.

This does NOT modify, remove, or duplicate the load_dotenv() calls
already present in app/main.py or scripts/verify_local_production_path.py
-- those are harmless now (python-dotenv's default override=False means
re-loading an already-set variable is a no-op), and leaving them in
place minimizes the diff against the existing, working code.
"""

from pathlib import Path
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / ".env"

# override=False (the default): never clobbers a variable already set
# directly in the shell/process environment -- .env only fills in what
# isn't already there.
load_dotenv(dotenv_path=_ENV_PATH)
