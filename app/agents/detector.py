"""
AEGIS-SWARM Razorpay Edition :: Detector Agent
=================================================
ROLE: Combines the trained baseline model's risk_score (a real ML
prediction, not an LLM guess) with an LLM-generated explanation of
WHY the transaction looks risky, citing specific signal values.

WHAT'S REUSED FROM AEGIS v1:
The Gemini client + Pydantic response_schema pattern from v1's
agents/risk.py is carried over directly -- genai.Client(), temperature
tuned low for consistency, response_mime_type="application/json" +
response_schema enforcing the DetectorOutput contract at the API level.

WHAT'S DIFFERENT (core architectural change from the Razorpay brief):
In AEGIS v1, the Risk Agent's threat_level WAS the model's own judgment
-- an LLM classifying LOW/MEDIUM/HIGH/CRITICAL purely from Scout's
visual description. Here, the LLM does NOT decide risk_level. The
baseline ML model (app/models/baseline.py) produces risk_score, and
risk_level is derived from that score via FIXED, DISCLOSED thresholds
(see policy/gate.py RISK_LEVEL_THRESHOLDS) -- not invented by the LLM
per-transaction. The Detector's LLM call exists ONLY to translate the
model's score + raw signals into a readable fraud_hypothesis and a
signals list. This is the direct implementation of the brief's
"ML predicts, agents investigate and reason" separation.
"""

import os
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.schemas.transaction import Transaction
from app.schemas.risk import DetectorOutput, RiskLevel
from app.agents._llm_timeout import call_with_timeout


class _DetectorExplanation(BaseModel):
    """LLM-only output contract -- explanation text, NOT the risk decision itself."""
    fraud_hypothesis: str
    signals: list[str]


# Fixed, disclosed thresholds mapping continuous risk_score to a discrete
# risk_level. Defined here (not inside the LLM prompt) so the mapping is
# deterministic and auditable -- the exact same thresholds the Policy
# Gate calibrates against (see policy/gate.py for the shared source).
RISK_LEVEL_THRESHOLDS = {
    "LOW": 0.0,
    "MEDIUM": 0.35,
    "HIGH": 0.60,
    "CRITICAL": 0.85,
}


def score_to_level(risk_score: float) -> RiskLevel:
    """Deterministic score -> level mapping. No LLM involved."""
    if risk_score >= RISK_LEVEL_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if risk_score >= RISK_LEVEL_THRESHOLDS["HIGH"]:
        return "HIGH"
    if risk_score >= RISK_LEVEL_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _build_raw_signals(txn: Transaction, risk_score: float) -> list[str]:
    """
    Deterministic, code-computed candidate signals -- computed BEFORE the
    LLM call so the model has real numbers to cite rather than having to
    invent plausible-sounding ones. The LLM's job is to select/phrase the
    relevant subset, not fabricate values.
    """
    signals = []
    if txn.velocity_1h >= 2:
        signals.append(f"{txn.velocity_1h} attempts in the last hour")
    if txn.new_device:
        signals.append("transaction from an unrecognized device")
    if txn.geo_mismatch:
        signals.append("IP geography does not match billing location")
    if txn.billing_shipping_mismatch:
        signals.append("billing and shipping addresses do not match")
    if txn.failed_attempts_prior >= 1:
        signals.append(f"{txn.failed_attempts_prior} failed attempt(s) immediately prior")
    if txn.account_age_days < 30:
        signals.append(f"account is only {txn.account_age_days} days old")
    if txn.prior_chargebacks > 0:
        signals.append(f"{txn.prior_chargebacks} prior chargeback(s) on this account")
    if txn.amount_inr > 20000:
        signals.append(f"high transaction value (₹{txn.amount_inr:,.2f})")
    if not signals:
        signals.append("no strong individual risk signals; score reflects overall pattern")
    return signals


def explain_detection(txn: Transaction, risk_score: float, use_llm: bool = True) -> DetectorOutput:
    """
    Args:
        txn: the transaction being assessed.
        risk_score: ALREADY COMPUTED by the baseline ML model
                    (app.models.baseline.predict_risk) -- this function
                    does not compute risk itself.
        use_llm: if False, skips the Gemini call and returns a
                 template-based explanation using only the deterministic
                 signals. Useful for the evaluation harness, which runs
                 the pipeline over the full test set and should not
                 require hundreds of LLM calls just to get risk_level
                 routing (which is threshold-based, not LLM-based, anyway).

    Returns:
        DetectorOutput -- risk_level is ALWAYS derived deterministically
        from risk_score via score_to_level(), regardless of use_llm.
    """
    risk_level = score_to_level(risk_score)
    raw_signals = _build_raw_signals(txn, risk_score)

    if not use_llm:
        hypothesis = (
            f"Model-assigned risk score {risk_score:.2f} ({risk_level}) based on: "
            f"{'; '.join(raw_signals)}."
        )
        return DetectorOutput(
            transaction_id=txn.transaction_id,
            risk_score=risk_score,
            risk_level=risk_level,
            fraud_hypothesis=hypothesis,
            signals=raw_signals,
            model_source=os.environ.get("AEGIS_MODEL_BACKEND", "dev_hist_gb"),
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    prompt = f"""You are the Detector Agent in a payment fraud risk system.
A machine learning model has ALREADY computed a fraud risk score for this
transaction -- you are NOT deciding the risk level. Your job is only to
write a clear, evidence-citing explanation.

Transaction: {txn.transaction_id}
ML risk score: {risk_score:.3f} (already computed, do not re-score)
Risk level: {risk_level} (already determined by fixed thresholds, do not re-classify)

Raw candidate signals identified by rule-based feature analysis:
{chr(10).join('- ' + s for s in raw_signals)}

Transaction details:
- amount: ₹{txn.amount_inr:,.2f}
- payment method: {txn.payment_method}
- hour of day: {txn.hour_of_day}
- velocity (1h/24h): {txn.velocity_1h}/{txn.velocity_24h}
- new device: {txn.new_device}
- geo mismatch: {txn.geo_mismatch}
- billing/shipping mismatch: {txn.billing_shipping_mismatch}
- account age (days): {txn.account_age_days}
- prior successful transactions: {txn.prior_successful_txns}
- prior chargebacks: {txn.prior_chargebacks}

Your task:
1. Write a one-to-two sentence fraud_hypothesis explaining WHY this
   transaction received this risk level, citing specific numbers above.
2. Select the 2-4 MOST relevant signals from the candidate list (or write
   your own if you can point to a specific number in the transaction
   details) -- do not just repeat the full candidate list verbatim.

Do not invent signals not supported by the data above. Do not change the
risk score or risk level -- those are already final."""

    response = call_with_timeout(
        client.models.generate_content,
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_DetectorExplanation,
            temperature=0.1,  # factual explanation task -- low temp for consistency, reused from v1
        ),
    )

    import json
    parsed = json.loads(response.text)

    return DetectorOutput(
        transaction_id=txn.transaction_id,
        risk_score=risk_score,
        risk_level=risk_level,
        fraud_hypothesis=parsed.get("fraud_hypothesis", raw_signals[0] if raw_signals else "N/A"),
        signals=parsed.get("signals", raw_signals),
        model_source=os.environ.get("AEGIS_MODEL_BACKEND", "dev_hist_gb"),
    )
