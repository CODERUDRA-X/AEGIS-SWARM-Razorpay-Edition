# AEGIS-SWARM — Razorpay Edition

**Evidence-gated AI risk engine for merchant loss defense.**
Track: AI Risk Manager · Loss class: Payment fraud / chargeback risk.

> AI is not allowed to block a payment until another system has tried to disprove the fraud hypothesis.

---

## Problem

Merchants lose money through payment fraud two ways: fraud that slips through, and
legitimate customers who get wrongly blocked. Most fraud systems optimize for the
first failure mode and ignore the cost of the second. AEGIS-SWARM treats both as
real, measurable costs and makes the trade-off explicit and auditable.

## What AEGIS-SWARM does

For every transaction:

```
Transaction
   ↓
ML Baseline (trained classifier) → risk_score
   ↓
Detector (explains the score, does not decide risk_level)
   ↓
Investigator (retrieves REAL evidence via MCP: customer/device/
              velocity/transaction/chargeback history)
   ↓
Adversarial Critic (actively tries to DISPROVE the fraud hypothesis,
                     using the retrieved evidence — can escalate OR
                     de-escalate)
   ↓
Deterministic Policy Gate (fixed rules, zero LLM calls, always
                            reproducible)
   ↓
Final Decision: ALLOW / STEP_UP / REVIEW / BLOCK
   ↓
Full audit trail (every intermediate output preserved)
```

The Policy Gate — not the LLM — makes the final call. The LLM proposes and
reasons; evidence grounds it; the Critic challenges it; policy controls it.

---

## Relationship to AEGIS-SWARM v1 (crowd-safety)

This is a **domain transformation**, not a from-scratch rewrite and not a
relabeling. AEGIS-SWARM v1 was a 4-agent crowd-safety system (Scout/Risk/Critic/
Commander analyzing drone/CCTV images for crowd-crush risk). That system's
*domain logic* (image analysis, people-counting, weather telemetry, Telegram/Email
dispatch) does not apply to payments and was fully replaced. What was reused is
the underlying *engineering pattern* — proven to work in v1 — applied to a new
problem:

| Reused (pattern) | Replaced (domain logic) |
|---|---|
| FastAPI backend structure, CORS + rate-limit middleware | Image upload pipeline → structured transaction JSON |
| Gemini + Pydantic structured-output pattern | Crowd/image schemas → transaction/risk/evidence/decision schemas |
| MCP client/server subprocess+stdio plumbing | Weather telemetry tool → 5 real transaction-evidence tools |
| Scout→Risk→Critic→Commander *separation of concerns* | LLM-decided threat tiers → ML-scored risk + deterministic Policy Gate |
| Independent-challenge Critic design principle | One-directional escalation bias → symmetric escalate/de-escalate |
| safe JSON parsing, security middleware | — |
| Next.js/Tailwind frontend foundation | Crowd dashboard data bindings → Risk Operations Console |

Explicitly **deleted**, not carried forward: Telegram/Email/Caspian integration,
voice, image/drone upload, weather telemetry, the free-text LLM Commander.

---

## Architecture

```
aegis-risk/
├── app/
│   ├── main.py                 FastAPI app, endpoints
│   ├── schemas/                 Pydantic contracts (transaction, risk, evidence, decision)
│   ├── agents/
│   │   ├── detector.py          ML score + LLM explanation (score_to_level is deterministic)
│   │   ├── investigator.py      Real MCP evidence retrieval + classification
│   │   └── critic.py            Adversarial LLM challenge (symmetric escalate/de-escalate)
│   ├── policy/gate.py            DETERMINISTIC decision engine — zero LLM calls
│   ├── models/baseline.py        Provider-agnostic ML baseline (train/predict/evaluate)
│   ├── services/
│   │   ├── data_split.py         Stratified 70/15/15 train/val/test split
│   │   ├── risk_engine.py        Orchestrates the full pipeline
│   │   └── evaluation.py         Held-out evaluation harness + cost simulation
│   └── mcp/
│       ├── evidence_tools.py     Shared lookup logic (no MCP SDK dependency)
│       ├── server.py             Real MCP server registration (FastMCP)
│       └── client.py             Real MCP client + sandbox fallback (see disclosure below)
├── data/
│   ├── generate_dataset.py       Synthetic dataset generator (documented generating process)
│   ├── transactions.csv, customers.csv, dataset_manifest.json
├── models/                        Saved baseline model artifact (.pkl)
├── evaluation_results/            Generated evaluation report + per-transaction audit CSV
├── tests/
│   ├── test_risk_pipeline.py      Real test suite (20 tests, see below)
│   └── sandbox_dev/               Sandbox-only compatibility shim (see disclosure below)
├── frontend/                      Next.js Risk Operations Console
├── Dockerfile, requirements.txt, .env.example
```

---

## Dataset — synthetic, disclosed generating process

`data/generate_dataset.py` generates 900 synthetic transactions across 225
customers using a **rule-based generating process**: features are drawn from
different distributions for "legitimate" vs. "fraud" transaction patterns
(velocity, device newness, geo/address mismatch, amount, timing), then **6%
symmetric label noise** is applied afterward so the resulting labels are not
perfectly separable by construction — a model that got 100% here would be a red
flag, not a win.

**Disclosed deviations from real-world data**, stated up front rather than hidden:
- Measured fraud rate after noise: **15.1%** (900 rows: 764 legit / 136 fraud) —
  substantially higher than real-world chargeback rates (typically 0.5–3%).
  This is deliberate: with only ~900 rows, a true 1–2% fraud rate would leave the
  test set with single-digit fraud examples, making precision/recall unstable.
  This is a disclosed dataset-size trade-off, not a claim about real base rates.
- All data is synthetic. No real Razorpay or any other real transaction data was
  used anywhere in this project.
- The dataset manifest (`data/dataset_manifest.json`) is regenerated every run and
  is the single source of truth for these numbers — nothing downstream hardcodes
  a fraud rate.

---

## Baseline model — provider-agnostic, explicitly labeled

`app/models/baseline.py` exposes three functions used everywhere in the codebase:
`train_baseline()`, `predict_risk()`, `evaluate_model()`. The backend is a single
switch (`AEGIS_MODEL_BACKEND` env var / `backend=` argument):

| Backend | Status |
|---|---|
| `logistic_regression` | Runs in any environment (sklearn only). **Best AUC observed in development (0.744)** — see note below. |
| `dev_hist_gb` (sklearn HistGradientBoostingClassifier) | Runs in any environment. Same algorithm family as XGBoost (histogram-based gradient boosting), but **NOT XGBoost** — never reported as XGBoost results. |
| `xgboost` | Written against the real XGBoost sklearn API. **Not run in the development sandbox** (no network access to `pip install xgboost` there — confirmed, not assumed). Run locally: `pip install xgboost && AEGIS_MODEL_BACKEND=xgboost python -m app.services.evaluation xgboost` |

**Honest finding from development**: on this dataset size (630 training rows, 95
fraud examples), plain logistic regression (ROC-AUC 0.744) outperformed the
gradient-boosted dev baseline (ROC-AUC 0.684). This is a real, unforced result —
with this little data, a simpler linear model generalizes better than a more
complex tree ensemble prone to overfitting. Every metrics object returned by
`evaluate_model()` includes a `model_backend` field specifically so this can never
be misreported.

**Action needed before final submission**: run the real XGBoost backend locally
(`pip install xgboost`) and update the evaluation report with those numbers. The
harness is ready — `python -m app.services.evaluation xgboost` — this has not yet
been executed because this environment cannot install XGBoost.

---

## Agents

### Detector (`app/agents/detector.py`)
Combines the baseline model's `risk_score` (real ML output) with an LLM-written
explanation. **The LLM does not decide `risk_level`** — that's a deterministic
threshold mapping (`score_to_level()`): LOW <0.35, MEDIUM <0.60, HIGH <0.85,
CRITICAL ≥0.85. The LLM only explains, citing pre-computed candidate signals.

### Investigator (`app/agents/investigator.py`)
Calls 5 real MCP evidence tools and classifies retrieved facts as
supporting/contradicting the fraud hypothesis — **mostly deterministic
classification**, not an LLM call, because the value here is genuine evidence
retrieval, not LLM creativity (per the project brief).

### Adversarial Critic (`app/agents/critic.py`)
The core differentiator. Actively tries to disprove the Detector's hypothesis
using the Investigator's evidence. **Symmetric**: can push risk down (evidence
contradicts fraud) or up (evidence under-weighted by the Detector) — deliberately
different from AEGIS v1's Critic, which could only escalate (correct for
crowd-safety, wrong for payments, where over-blocking has a real cost too).

### Policy Gate (`app/policy/gate.py`)
**Zero LLM calls.** Nine fixed, documented rules (`R1`–`R9`, see
`RULE_DESCRIPTIONS` in the source) route risk_level + Critic verdict to one of
ALLOW/STEP_UP/REVIEW/BLOCK. Same inputs always produce the same output — verified
by `test_policy_decision_is_deterministic`. This is the direct replacement for
v1's free-text LLM Commander, deliberately not reused as a pattern, because a
payment-blocking decision must be reproducible, which sampling-based LLM calls
cannot structurally guarantee.

**Cost model** (`FRAUD_MISS_COST_INR=10,000`, `FALSE_POSITIVE_COST_INR=500`,
`STEP_UP_FRICTION_COST_INR=50`, `REVIEW_OPERATIONAL_COST_INR=120`): **stated
assumptions for cost simulation, not measured real-world Razorpay figures** — we
have no access to real merchant loss data. Change these two constants in
`policy/gate.py` and every downstream cost figure updates consistently.

---

## MCP — real evidence retrieval

`app/mcp/evidence_tools.py` contains 5 tools (`get_customer_history`,
`get_device_history`, `get_velocity`, `get_transaction_history`,
`get_chargeback_history`) that perform genuine lookups against
`data/customers.csv`/`transactions.csv` — not hallucinated or static responses.
`app/mcp/server.py` registers these as real MCP tools via FastMCP + stdio
transport (the same subprocess/stdio pattern proven in AEGIS v1).

**Sandbox disclosure**: the development sandbox used to build this project has no
network access and could not `pip install mcp`. `app/mcp/client.py` therefore has
two paths: the real MCP subprocess/stdio path (`USE_REAL_MCP=True`, written
against the real SDK API, **not executed in this sandbox**), and an in-process
fallback that calls the exact same `evidence_tools.py` functions directly,
skipping only the transport layer — evidence *values* are identical either way. A
one-time warning prints whichever path is active, so this was never silently
misrepresented. **Verify the real MCP path locally**: `pip install mcp httpx`,
then re-run — the startup log will confirm the switch.

---

## Gemini — real production path, sandbox-disclosed

Both `agents/detector.py` and `agents/critic.py` are written against the real
`google-genai` SDK (`genai.Client`, `response_schema=`, structured Pydantic
output) — the same pattern proven in AEGIS v1. **Not executed in this sandbox**
(no network to install `google-genai`, no API key configured here). Set
`GEMINI_API_KEY` in `.env` (see `.env.example`) to run for real.

Every pipeline function accepts `use_llm_detector` / `use_llm_critic` flags.
`main.py`'s `/api/analyze` endpoint always uses `True` (the real system) and
returns a clear error if `GEMINI_API_KEY` is unset — it does not silently fall
back to a template. `/api/analyze/batch` and the evaluation harness default to
`False` (rule-based fallbacks) for cost/speed reasons during development and
large-batch runs — **results generated this way are always labeled "(dev critic,
non-LLM)" and must never be presented as final AEGIS-SWARM performance.**

---

## Sandbox testing disclosure (read this before trusting "it works")

This project was built in a sandboxed development environment with **no network
access** — `pydantic`, `fastapi`, `google-genai`, `mcp`, and `xgboost` could not
be installed there (confirmed via failed `pip install` attempts, not assumed).
To verify the actual logic (schemas, Policy Gate rules, evidence classification,
baseline training, full pipeline orchestration) without those packages,
`tests/sandbox_dev/` provides a **dependency-free compatibility shim** —
explicitly NOT real Pydantic, injected only into `sys.modules` for sandbox test
runs, never imported by any file under `app/`. Every production file
(`app/schemas/*.py`, `app/agents/*.py`, etc.) uses the real `pydantic`/`fastapi`/
`google-genai` imports unmodified — the shim exists purely so those same,
unmodified files could be exercised in the sandbox.

**What this means concretely**:
- ✅ Verified in the sandbox: dataset generation, all schema construction, the
  full Policy Gate rule matrix (all 9 rules, 20/20 tests passing), baseline model
  training/prediction/evaluation, MCP evidence retrieval (via the disclosed
  fallback path — real lookup values, no protocol layer), full pipeline
  orchestration end-to-end with rule-based Detector/Critic stand-ins.
- ❌ **Not verified in the sandbox, must be run locally**: real Gemini API calls,
  real MCP subprocess/stdio transport, FastAPI request/response cycle under real
  Pydantic validation, the Next.js frontend build (`npm install` also failed here
  — no npm registry access), and the real XGBoost baseline.

---

## Evaluation — held-out, honest

Run: `python -m app.services.evaluation [logistic_regression|dev_hist_gb|xgboost] [--llm-critic]`

Test set (135 held-out transactions, never touched during training) results as of
this build (`logistic_regression` baseline, rule-based dev critic — **not the
final LLM critic numbers**, see disclosure above):

| System | Precision | Recall | F1 | ROC-AUC | FP | FN | Total Modeled Cost |
|---|---|---|---|---|---|---|---|
| Baseline (logistic regression) | 35.7% | 50.0% | 41.7% | 0.744 | 18 | 10 | ₹1,09,000 |
| AEGIS-SWARM (dev critic) | 57.1% | 40.0% | 47.1% | — | 6 | 12 | ₹93,850 |

**Read this honestly, not as a marketing table**: AEGIS-SWARM's binary "BLOCK vs.
rest" precision is higher and total modeled cost is lower — driven mainly by far
fewer false positives (18→6), because STEP_UP/REVIEW absorb cases a binary
baseline would have blocked outright. Recall on this specific metric is lower
(50%→40%), and that trade-off is investigated, not hidden — see below.

### Recall gap — root cause, not assumption

`recall_gap_analysis` in the evaluation report decomposes every missed fraud
case:

- **The baseline itself assigned risk scores below the binary 0.5 threshold to
  10 of the 12 missed fraud cases.** This reflects an **ML feature-signal gap**
  (or, for some rows, a label-noise flip applied during dataset generation).
- **2 of 12 misses**: the baseline *would* have flagged these (score ≥0.5), and
  the Critic's evidence-based challenge moved the decision away from BLOCK.
  **Both of these landed on STEP_UP** (extra verification, not a free pass) —
  zero landed on ALLOW. This is the Critic doing exactly its designed job:
  trading some recall for lower false-positive cost against genuinely
  contradicting evidence (established accounts, consistent spending, no
  chargeback history).

**No code was changed to "fix" this** — the behavior is working as designed, and
patching it would mean discarding the actual finding. Full per-transaction detail
in `evaluation_results/per_transaction_results.csv`.

---

## Demo cases (`frontend/app/demoCases.ts`)

Three transactions backed by **real seeded dataset records**
(`data/demo_customers.csv`, `data/demo_transactions.csv` — generated by
`data/generate_demo_seed.py`), so the Investigator retrieves genuine MCP
evidence for these cases exactly as it would for any other transaction — no
evidence is fabricated in the frontend. These seed files are kept **separate**
from `data/transactions.csv`/`customers.csv` specifically so the held-out
train/val/test split is provably unaffected (`app/services/data_split.py` reads
only the main CSVs; verified by direct ID-overlap check — zero overlap).

All three outcomes were run end-to-end (Detector → Investigator → Critic → Policy
Gate) against the trained baseline model and verified empirically, not asserted:

| Case | Scenario | Risk score | Risk level | Critic verdict/adjustment | Rule | **Decision** |
|---|---|---|---|---|---|---|
| A — Clear Fraud | New device, 2-day account, IP/billing mismatch, velocity spike | 0.998 | CRITICAL | CHALLENGE / CRITICAL | R8_CRITICAL_DEFAULT | **BLOCK** |
| B — Ambiguous | Elevated signals (new device, night, velocity, failed attempt) on a 640-day account with real but partial contradicting history | 0.766 | HIGH | CHALLENGE / MEDIUM | R4_HIGH_CRITIC_CHALLENGE_STRONG | **STEP_UP** |
| C — Legitimate | Normal amount/timing, established account, amount consistent with real seeded history | 0.293 | LOW | CHALLENGE / LOW | R1_LOW_ALLOW | **ALLOW** |

**Honesty note**: this verification run used the rule-based dev critic (no live
Gemini call available during automated testing). The evidence retrieved is
identical either way (real MCP lookups against the seeded records); the real LLM
Critic's exact wording/reasoning may differ — re-verify these three cases with
`GEMINI_API_KEY` configured before a live demo.

Two real bugs were found and fixed while building this verification, not
papered over:
1. `investigator.py`'s evidence classifier previously padded empty
   supporting/contradicting lists with placeholder text (`"no additional
   evidence found..."`), which the rule-based critic's signal-counting logic
   then miscounted as a real signal. Fixed: empty lists stay empty; display-time
   fallback text was moved to the Critic's prompt formatting instead.
2. The rule-based dev critic's `INSUFFICIENT_EVIDENCE` heuristic fired whenever
   `customer_txn_count_seen == 0`, regardless of how much other evidence existed
   — this incorrectly downgraded Case A (7 supporting signals, CRITICAL risk)
   to REVIEW instead of BLOCK. Fixed: `INSUFFICIENT_EVIDENCE` now requires both
   thin AND balanced evidence (`total_signals <= 2 and |support − contra| <= 1`).

---

## Setup

```bash
# Backend
cp .env.example .env   # fill in GEMINI_API_KEY
pip install -r requirements.txt
python data/generate_dataset.py         # regenerate dataset if needed
python -m app.services.evaluation       # generate evaluation_results/
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Testing

```bash
# Real test suite (20 tests) -- works without pydantic/fastapi installed,
# via the sandbox_dev shim (see disclosure above)
python -m pytest tests/test_risk_pipeline.py -v
# or, without pytest installed:
python tests/test_risk_pipeline.py
```

---

## Limitations (stated, not hidden)

- All data is synthetic; no real transaction data of any kind was used.
- Fraud rate (15.1%) is elevated vs. real-world base rates, disclosed above.
- Cost-model constants are stated assumptions, not measured figures.
- XGBoost backend is written but not yet run (sandbox network constraint) —
  action item before final numbers are locked.
- Real Gemini/MCP paths are written against correct APIs but not executed in
  the development sandbox — must be verified locally before submission.
- Frontend has not been `npm run build`-verified (no local npm registry access
  in the sandbox) — verify locally before deploy.
- Binary precision/recall on BLOCK-vs-rest is a simplification of a 4-action
  system; the full action distribution and cost breakdown should always be read
  alongside it, not instead of it.
