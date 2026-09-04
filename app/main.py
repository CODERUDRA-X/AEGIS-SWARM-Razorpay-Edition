"""
AEGIS-SWARM Razorpay Edition :: FastAPI Backend
==================================================
REUSED FROM AEGIS v1's server.py:
- FastAPI app structure, CORS middleware pattern, slowapi rate limiting
- The general shape of "validate input -> run pipeline -> return JSON"
- safe_json_parse() error-handling philosophy (fail loud with a clear
  error, never silently return malformed data)

REPLACED:
- The single image-upload endpoint is replaced with transaction-analysis
  endpoints operating on structured JSON/CSV, not image files.
- No file-type/size validation for uploaded photos -- instead we
  validate transaction schema conformance via Pydantic.
- Removed: Gemini file upload/cleanup logic (no images in this system).

ENDPOINTS:
  POST /api/analyze          - run the full pipeline on ONE transaction
  POST /api/analyze/batch    - run the full pipeline on a list of transactions
  GET  /api/evaluation       - return the last-computed held-out evaluation report
  GET  /api/health           - basic health check
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv
import json

from app.schemas.transaction import Transaction
from app.models.baseline import train_baseline, load_model, save_model, TrainedModel
from app.services.data_split import load_splits
from app.services.risk_engine import run_pipeline, PipelineResult

load_dotenv()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="AEGIS-SWARM Razorpay Edition — Risk Operations API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Same allowed-origin pattern as v1 -- local dev + deployed frontend.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    os.environ.get("FRONTEND_URL", ""),
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in ALLOWED_ORIGINS if o],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MODEL_PATH = Path(__file__).parent.parent / "models" / "baseline_model.pkl"
EVAL_REPORT_PATH = Path(__file__).parent.parent / "evaluation_results" / "evaluation_report.json"

_model_cache: TrainedModel | None = None


def get_model() -> TrainedModel:
    """
    Lazily loads the trained baseline model, training it fresh on first
    call if no saved model file exists. Cached in-process afterward --
    same "load once, reuse" pattern as v1's MCP data loading.
    """
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    if MODEL_PATH.exists():
        _model_cache = load_model(MODEL_PATH)
    else:
        splits = load_splits()
        _model_cache = train_baseline(splits["train"])
        save_model(_model_cache, MODEL_PATH)

    return _model_cache


def _serialize_result(result: PipelineResult) -> dict:
    return {
        "transaction": result.transaction.model_dump(),
        "detector": result.detector.model_dump(),
        "evidence": result.evidence.model_dump(),
        "critic": result.critic.model_dump(),
        "decision": result.decision.model_dump(),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "AEGIS-SWARM Razorpay Edition"}


@app.post("/api/analyze")
@limiter.limit("20/minute")
def analyze_transaction(request: Request, transaction: Transaction):
    """
    Run the full AEGIS-SWARM pipeline on one transaction.
    Uses the real LLM Detector + Critic (Gemini) -- requires
    GEMINI_API_KEY to be set.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")

    model = get_model()
    try:
        result = run_pipeline(transaction, model, use_llm_detector=True, use_llm_critic=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Pipeline execution failed: {e}")

    return _serialize_result(result)


@app.post("/api/analyze/batch")
@limiter.limit("5/minute")
def analyze_batch(request: Request, transactions: list[Transaction]):
    """
    Run the pipeline over a list of transactions. Uses the rule-based dev
    critic (NOT the LLM) by default for batch runs to avoid burning
    Gemini quota on large batches from the dashboard's "RUN EVAL" button
    -- this endpoint is for the frontend's batch-upload/eval-preview flow,
    not for reporting final submission metrics (use
    app/services/evaluation.py directly with use_llm_critic=True for that).
    """
    if len(transactions) > 500:
        raise HTTPException(status_code=400, detail="Batch size limited to 500 transactions per request.")

    model = get_model()
    results = []
    for txn in transactions:
        try:
            result = run_pipeline(txn, model, use_llm_detector=False, use_llm_critic=False)
            results.append(_serialize_result(result))
        except Exception as e:
            results.append({"transaction_id": txn.transaction_id, "error": str(e)})

    return {"results": results, "note": "Batch analysis uses the rule-based dev critic, not the LLM critic."}


@app.get("/api/evaluation")
def get_evaluation_report():
    """
    Returns the most recently computed held-out evaluation report
    (generated by running `python -m app.services.evaluation`).
    """
    if not EVAL_REPORT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No evaluation report found. Run `python -m app.services.evaluation` first.",
        )
    with open(EVAL_REPORT_PATH) as f:
        return json.load(f)
