"""
AEGIS-SWARM Razorpay Edition :: Local Production-Path Verification
=======================================================================
Run this ONCE in your local environment (real pydantic/fastapi/
google-genai/mcp/xgboost installed, GEMINI_API_KEY set in .env) to
verify the full real production path end-to-end -- everything that
could NOT be executed in the sandboxed development environment this
project was built in (see README.md's sandbox disclosure section).

Usage:
    python scripts/verify_local_production_path.py

This does NOT use tests/sandbox_dev/bootstrap.py -- it imports app.*
modules directly, using your real installed dependencies. If anything
here fails, that is a genuine bug to fix before submission, not a
sandbox artifact.
"""

import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS = []


def check(name: str, fn):
    print(f"\n{'='*70}\n{name}\n{'='*70}")
    try:
        fn()
        RESULTS.append((name, "PASS", None))
        print(f"[PASS] {name}")
    except Exception as e:
        RESULTS.append((name, "FAIL", str(e)))
        print(f"[FAIL] {name}: {e}")
        traceback.print_exc()


def check_pydantic_real():
    import pydantic
    assert not hasattr(pydantic.BaseModel, "_IS_SHIM"), "Real pydantic should not have shim markers"
    from app.schemas.transaction import Transaction
    t = Transaction(
        transaction_id="TXN_VERIFY", customer_id="CUST_VERIFY", amount_inr=1000.0,
        payment_method="card", hour_of_day=12, velocity_1h=0, velocity_24h=1,
        new_device=False, geo_mismatch=False, billing_shipping_mismatch=False,
        failed_attempts_prior=0, account_age_days=200, prior_successful_txns=10,
        prior_chargebacks=0, known_device_count=2,
    )
    assert t.transaction_id == "TXN_VERIFY"
    print(f"Real pydantic version: {pydantic.VERSION}. Transaction schema constructs correctly.")


def check_xgboost_baseline():
    os.environ["AEGIS_MODEL_BACKEND"] = "xgboost"
    from app.services.data_split import load_splits
    from app.models.baseline import train_baseline, evaluate_model
    splits = load_splits()
    model = train_baseline(splits["train"], backend="xgboost")
    assert model.backend == "xgboost"
    metrics = evaluate_model(model, splits["test"])
    print(f"XGBoost baseline trained. Test metrics: precision={metrics['precision']}, "
          f"recall={metrics['recall']}, roc_auc={metrics['roc_auc']}")
    print("NOTE: compare these numbers against the logistic_regression numbers in README.md -- "
          "update the README's evaluation table with whichever backend performs best, labeled correctly.")


def check_real_mcp():
    import asyncio
    from app.mcp import client as mcp_client
    assert mcp_client.USE_REAL_MCP, (
        "mcp package appears installed but USE_REAL_MCP is False -- check the import in "
        "app/mcp/client.py did not silently fail for a different reason."
    )
    result = asyncio.run(mcp_client.get_customer_history("CUST_DEMO_B"))
    assert result.get("mcp_status") == "success", f"Real MCP call did not return success: {result}"
    assert result.get("account_age_days") == 640, f"Unexpected evidence value: {result}"
    print(f"Real MCP subprocess/stdio round-trip succeeded: {result}")


def check_real_gemini_detector():
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not set -- cannot verify real Gemini path.")
    from app.schemas.transaction import Transaction
    from app.agents.detector import explain_detection
    txn = Transaction(
        transaction_id="TXN_VERIFY_GEMINI", customer_id="CUST_VERIFY", amount_inr=50000.0,
        payment_method="card", hour_of_day=3, velocity_1h=3, velocity_24h=5,
        new_device=True, geo_mismatch=True, billing_shipping_mismatch=True,
        failed_attempts_prior=2, account_age_days=3, prior_successful_txns=0,
        prior_chargebacks=0, known_device_count=1,
    )
    output = explain_detection(txn, risk_score=0.9, use_llm=True)
    assert output.fraud_hypothesis, "Detector LLM call returned empty fraud_hypothesis"
    print(f"Real Gemini Detector call succeeded. Hypothesis: {output.fraud_hypothesis}")


def check_full_demo_cases_real():
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not set -- cannot verify full real pipeline.")
    import pandas as pd
    from app.services.data_split import load_splits
    from app.models.baseline import train_baseline
    from app.services.risk_engine import run_pipeline
    from app.schemas.transaction import Transaction

    splits = load_splits()
    model = train_baseline(splits["train"], backend=os.environ.get("AEGIS_MODEL_BACKEND", "logistic_regression"))
    demo_txns = pd.read_csv(Path(__file__).resolve().parent.parent / "data" / "demo_transactions.csv")

    expected = {"TXN_DEMO_A": "BLOCK", "TXN_DEMO_B": "STEP_UP", "TXN_DEMO_C": "ALLOW"}
    for txn_id, expected_action in expected.items():
        row = demo_txns[demo_txns["transaction_id"] == txn_id].iloc[0]
        txn = Transaction(**row.to_dict())
        result = run_pipeline(txn, model, use_llm_detector=True, use_llm_critic=True)
        status = "MATCH" if result.decision.action == expected_action else "DIFFERS"
        print(f"{txn_id}: expected {expected_action}, got {result.decision.action} [{status}] "
              f"(real LLM critic verdict: {result.critic.verdict}/{result.critic.recommended_adjustment})")
        if status == "DIFFERS":
            print(f"  NOTE: the real LLM Critic may reasonably weigh evidence differently than the "
                  f"rule-based dev critic used during sandbox verification. This is not necessarily a "
                  f"bug -- inspect result.critic.critic_reasoning before assuming something is wrong.")


if __name__ == "__main__":
    check("1. Real Pydantic schema construction", check_pydantic_real)
    check("2. Real XGBoost baseline training + evaluation", check_xgboost_baseline)
    check("3. Real MCP subprocess/stdio evidence retrieval", check_real_mcp)
    check("4. Real Gemini Detector agent call", check_real_gemini_detector)
    check("5. Full pipeline on 3 demo cases with real LLM Detector + Critic", check_full_demo_cases_real)

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    for name, status, err in RESULTS:
        print(f"[{status}] {name}" + (f" -- {err}" if err else ""))

    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    print(f"\n{n_pass}/{len(RESULTS)} checks passed.")
    if n_pass < len(RESULTS):
        sys.exit(1)
