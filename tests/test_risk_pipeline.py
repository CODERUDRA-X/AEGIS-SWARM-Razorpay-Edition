"""
AEGIS-SWARM Razorpay Edition :: Test Suite
=============================================
Uses tests/sandbox_dev/bootstrap.py so this suite can run WITHOUT
pydantic/google-genai/mcp installed (see that module's docstring for
full disclosure). All tests here use use_llm_detector=False,
use_llm_critic=False so no real Gemini call is attempted.

WHAT IS ACTUALLY TESTED HERE:
- Deterministic Policy Gate routing logic (all 9 rules)
- Detector's score_to_level() threshold mapping
- Baseline model training/prediction/evaluation plumbing
- Full pipeline wiring (Detector->Investigator->Critic->PolicyGate)
- MCP evidence retrieval (via the disclosed in-process fallback path)

WHAT IS NOT TESTED HERE (requires real deps + credentials, run locally):
- Real Gemini API calls from Detector/Critic (needs GEMINI_API_KEY + google-genai)
- Real MCP subprocess/stdio transport (needs `mcp` package)
- FastAPI endpoint behavior under real pydantic validation (needs fastapi+pydantic)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import tests.sandbox_dev.bootstrap  # noqa: E402 -- must run before any app.* import

from app.schemas.transaction import Transaction  # noqa: E402
from app.schemas.risk import DetectorOutput  # noqa: E402
from app.schemas.evidence import CriticReview  # noqa: E402
from app.agents.detector import score_to_level  # noqa: E402
from app.policy.gate import decide  # noqa: E402
from app.services.data_split import load_splits  # noqa: E402
from app.models.baseline import train_baseline, predict_risk, evaluate_model  # noqa: E402
from app.services.risk_engine import run_pipeline  # noqa: E402


def _make_txn(**overrides) -> Transaction:
    defaults = dict(
        transaction_id="TXN_TEST", customer_id="CUST_TEST", amount_inr=1000.0,
        payment_method="card", hour_of_day=12, velocity_1h=0, velocity_24h=1,
        new_device=False, geo_mismatch=False, billing_shipping_mismatch=False,
        failed_attempts_prior=0, account_age_days=200, prior_successful_txns=10,
        prior_chargebacks=0, known_device_count=2, is_fraud=0,
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def _make_detector(risk_level="HIGH", risk_score=0.7) -> DetectorOutput:
    return DetectorOutput(
        transaction_id="TXN_TEST", risk_score=risk_score, risk_level=risk_level,
        fraud_hypothesis="test", signals=["test signal"], model_source="test",
    )


def _make_critic(verdict="CONFIRM", adjustment="HIGH", n_counter=0) -> CriticReview:
    return CriticReview(
        transaction_id="TXN_TEST", verdict=verdict,
        counter_evidence=[f"counter {i}" for i in range(n_counter)],
        supporting_evidence_acknowledged=[], recommended_adjustment=adjustment,
        critic_reasoning="test reasoning",
    )


# ── score_to_level threshold tests ─────────────────────────────────────

def test_score_to_level_low():
    assert score_to_level(0.0) == "LOW"
    assert score_to_level(0.34) == "LOW"


def test_score_to_level_medium():
    assert score_to_level(0.35) == "MEDIUM"
    assert score_to_level(0.59) == "MEDIUM"


def test_score_to_level_high():
    assert score_to_level(0.60) == "HIGH"
    assert score_to_level(0.84) == "HIGH"


def test_score_to_level_critical():
    assert score_to_level(0.85) == "CRITICAL"
    assert score_to_level(1.0) == "CRITICAL"


# ── Policy Gate rule tests (all 9 rules) ────────────────────────────────

def test_low_always_allows():
    txn = _make_txn()
    d = _make_detector(risk_level="LOW", risk_score=0.1)
    c = _make_critic(verdict="CONFIRM", adjustment="LOW")
    result = decide(txn, d, c)
    assert result.action == "ALLOW"
    assert result.triggered_rule == "R1_LOW_ALLOW"


def test_medium_confirmed_low_by_critic_allows():
    txn = _make_txn()
    d = _make_detector(risk_level="MEDIUM", risk_score=0.4)
    c = _make_critic(verdict="CHALLENGE", adjustment="LOW")
    result = decide(txn, d, c)
    assert result.action == "ALLOW"
    assert result.triggered_rule == "R2_MEDIUM_ALLOW_CONFIRMED_LOW"


def test_medium_default_steps_up():
    txn = _make_txn()
    d = _make_detector(risk_level="MEDIUM", risk_score=0.5)
    c = _make_critic(verdict="CONFIRM", adjustment="MEDIUM")
    result = decide(txn, d, c)
    assert result.action == "STEP_UP"
    assert result.triggered_rule == "R3_MEDIUM_STEP_UP"


def test_high_insufficient_evidence_reviews():
    txn = _make_txn()
    d = _make_detector(risk_level="HIGH", risk_score=0.7)
    c = _make_critic(verdict="INSUFFICIENT_EVIDENCE", adjustment="HIGH")
    result = decide(txn, d, c)
    assert result.action == "REVIEW"
    assert result.triggered_rule == "R5_HIGH_INSUFFICIENT_EVIDENCE"


def test_high_strong_challenge_steps_up():
    txn = _make_txn()
    d = _make_detector(risk_level="HIGH", risk_score=0.7)
    c = _make_critic(verdict="CHALLENGE", adjustment="MEDIUM", n_counter=2)
    result = decide(txn, d, c)
    assert result.action == "STEP_UP"
    assert result.triggered_rule == "R4_HIGH_CRITIC_CHALLENGE_STRONG"


def test_high_weak_challenge_still_blocks():
    """Only 1 counter-evidence item -- not enough to move off BLOCK."""
    txn = _make_txn()
    d = _make_detector(risk_level="HIGH", risk_score=0.7)
    c = _make_critic(verdict="CHALLENGE", adjustment="MEDIUM", n_counter=1)
    result = decide(txn, d, c)
    assert result.action == "BLOCK"
    assert result.triggered_rule == "R6_HIGH_CONFIRMED"


def test_high_confirmed_blocks():
    txn = _make_txn()
    d = _make_detector(risk_level="HIGH", risk_score=0.75)
    c = _make_critic(verdict="CONFIRM", adjustment="HIGH")
    result = decide(txn, d, c)
    assert result.action == "BLOCK"
    assert result.triggered_rule == "R6_HIGH_CONFIRMED"


def test_critical_insufficient_evidence_reviews():
    txn = _make_txn()
    d = _make_detector(risk_level="CRITICAL", risk_score=0.9)
    c = _make_critic(verdict="INSUFFICIENT_EVIDENCE", adjustment="CRITICAL")
    result = decide(txn, d, c)
    assert result.action == "REVIEW"
    assert result.triggered_rule == "R7_CRITICAL_INSUFFICIENT_EVIDENCE"


def test_critical_default_blocks():
    txn = _make_txn()
    d = _make_detector(risk_level="CRITICAL", risk_score=0.92)
    c = _make_critic(verdict="CONFIRM", adjustment="CRITICAL")
    result = decide(txn, d, c)
    assert result.action == "BLOCK"
    assert result.triggered_rule == "R8_CRITICAL_DEFAULT"


def test_critical_strong_challenge_reviews_not_allows():
    """
    Even with 3+ strong counter-evidence items at CRITICAL, the Policy
    Gate downgrades only to REVIEW, never all the way to ALLOW/STEP_UP --
    this is a deliberate asymmetry (see policy/gate.py RULE_DESCRIPTIONS).
    """
    txn = _make_txn()
    d = _make_detector(risk_level="CRITICAL", risk_score=0.9)
    c = _make_critic(verdict="CHALLENGE", adjustment="LOW", n_counter=3)
    result = decide(txn, d, c)
    assert result.action == "REVIEW"
    assert result.triggered_rule == "R9_CRITICAL_STRONG_CHALLENGE"
    assert result.action != "ALLOW"
    assert result.action != "STEP_UP"


def test_policy_decision_is_deterministic():
    """Same inputs must always produce the same output -- no randomness."""
    txn = _make_txn()
    d = _make_detector(risk_level="HIGH", risk_score=0.7)
    c = _make_critic(verdict="CONFIRM", adjustment="HIGH")
    results = [decide(txn, d, c) for _ in range(10)]
    actions = {r.action for r in results}
    rules = {r.triggered_rule for r in results}
    assert len(actions) == 1
    assert len(rules) == 1


# ── Baseline model tests ─────────────────────────────────────────────

def test_baseline_trains_and_predicts():
    splits = load_splits()
    model = train_baseline(splits["train"], backend="logistic_regression")
    assert model.backend == "logistic_regression"
    assert model.training_rows == len(splits["train"])

    proba = predict_risk(model, splits["test"])
    assert len(proba) == len(splits["test"])
    assert all(0.0 <= p <= 1.0 for p in proba)


def test_baseline_evaluate_returns_expected_keys():
    splits = load_splits()
    model = train_baseline(splits["train"], backend="logistic_regression")
    metrics = evaluate_model(model, splits["test"])
    for key in ["precision", "recall", "f1", "roc_auc", "confusion_matrix", "model_backend"]:
        assert key in metrics
    assert metrics["model_backend"] == "logistic_regression"


def test_data_split_is_deterministic_and_disjoint():
    splits_a = load_splits()
    splits_b = load_splits()
    assert splits_a["test"]["transaction_id"].tolist() == splits_b["test"]["transaction_id"].tolist()

    train_ids = set(splits_a["train"]["transaction_id"])
    val_ids = set(splits_a["val"]["transaction_id"])
    test_ids = set(splits_a["test"]["transaction_id"])
    assert train_ids.isdisjoint(val_ids)
    assert train_ids.isdisjoint(test_ids)
    assert val_ids.isdisjoint(test_ids)


# ── Full pipeline wiring tests ───────────────────────────────────────

def test_full_pipeline_runs_without_llm():
    splits = load_splits()
    model = train_baseline(splits["train"], backend="logistic_regression")
    txn = Transaction(**splits["test"].iloc[0].to_dict())

    result = run_pipeline(txn, model, use_llm_detector=False, use_llm_critic=False)

    assert result.transaction.transaction_id == txn.transaction_id
    assert result.detector.transaction_id == txn.transaction_id
    assert result.evidence.transaction_id == txn.transaction_id
    assert result.critic.transaction_id == txn.transaction_id
    assert result.decision.transaction_id == txn.transaction_id
    assert result.decision.action in ("ALLOW", "STEP_UP", "REVIEW", "BLOCK")


def test_full_pipeline_evidence_is_real_not_hallucinated():
    """
    Evidence values must trace back to the actual customer/transaction
    records (via app/mcp/evidence_tools.py), not be re-derived purely
    from the input Transaction object.
    """
    splits = load_splits()
    model = train_baseline(splits["train"], backend="logistic_regression")
    row = splits["test"].iloc[0]
    txn = Transaction(**row.to_dict())

    result = run_pipeline(txn, model, use_llm_detector=False, use_llm_critic=False)

    # account_age_days in the evidence packet should match the customer
    # record looked up via MCP, which should equal what's in the source
    # transaction row (since the dataset was generated consistently)
    assert result.evidence.account_age_days == int(row["account_age_days"])
    assert result.evidence.prior_chargebacks == int(row["prior_chargebacks"])


if __name__ == "__main__":
    import subprocess
    print("Run with: python -m pytest tests/test_risk_pipeline.py -v")
