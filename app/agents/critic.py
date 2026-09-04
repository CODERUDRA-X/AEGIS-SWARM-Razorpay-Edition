"""
AEGIS-SWARM Razorpay Edition :: Adversarial Critic Agent
===========================================================
ROLE: Actively tries to DISPROVE the Detector's fraud_hypothesis using
the Investigator's evidence packet. This is the direct evolution of
AEGIS v1's critic.py -- same "don't be a rubber stamp" design principle,
but the escalation bias is now SYMMETRIC rather than one-directional.

WHY THIS IS AN INVERSION OF v1's CRITIC, NOT A COPY:
AEGIS v1's Critic could only escalate (crowd-safety framing: under-
reporting risk costs lives, so the asymmetry was deliberate and correct
FOR THAT DOMAIN). The Razorpay strategy brief is explicit that this
asymmetry does NOT transfer to payments: blocking a legitimate customer
has a real, measurable cost (customer friction, lost revenue, merchant
trust) that is comparable in kind to a missed-fraud cost, not
negligible by comparison. So this Critic is deliberately built to
challenge in BOTH directions -- it can push a HIGH down to MEDIUM when
evidence contradicts the hypothesis, or push a MEDIUM up to HIGH when
evidence the Detector under-weighted supports it. Both directions use
the identical evaluation procedure; neither is privileged by the prompt.

WHY adjusted_threat_level STAYS A CLOSED LITERAL (reused fix from v1):
Same structural reasoning as AEGIS v1's confirmed bug fix -- see
CriticReview.recommended_adjustment's Literal type in
app/schemas/evidence.py. The model cannot invent a 5th tier no matter
how the prompt is worded, because the schema itself is the enforcement
mechanism, not prompt wording.

WHY THE CRITIC CANNOT MAKE THE FINAL DECISION:
Per the brief's core architectural principle, this agent's output feeds
the Policy Gate (policy/gate.py) -- it never directly produces an
ALLOW/STEP_UP/REVIEW/BLOCK action. The Critic proposes a
recommended_adjustment; the Policy Gate is what actually decides,
deterministically.
"""

import os
import json
from google import genai
from google.genai import types

from app.schemas.transaction import Transaction
from app.schemas.risk import DetectorOutput
from app.schemas.evidence import EvidencePacket, CriticReview


def challenge(txn: Transaction, detector_output: DetectorOutput, evidence: EvidencePacket) -> CriticReview:
    """
    Independently evaluate whether the Detector's fraud_hypothesis holds
    up against the Investigator's retrieved evidence. May recommend
    escalating OR de-escalating the risk level -- see module docstring.

    Raises:
        ValueError: if GEMINI_API_KEY is not set.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    prompt = f"""You are the Adversarial Critic Agent in a payment fraud risk system.
Your role is to act as an independent auditor whose job is specifically
to try to DISPROVE the fraud hypothesis below -- not to rubber-stamp it.

Detector's assessment:
- risk_score: {detector_output.risk_score:.3f}
- risk_level: {detector_output.risk_level}
- fraud_hypothesis: {detector_output.fraud_hypothesis}
- signals cited: {json.dumps(detector_output.signals)}

Evidence retrieved independently by the Investigator (real lookups, not assumptions):
- account_age_days: {evidence.account_age_days}
- prior_successful_txns: {evidence.prior_successful_txns}
- prior_chargebacks: {evidence.prior_chargebacks}
- known_device_count: {evidence.known_device_count}
- is_new_device: {evidence.is_new_device}
- velocity_1h / velocity_24h: {evidence.velocity_1h} / {evidence.velocity_24h}
- customer_avg_amount: {evidence.customer_avg_amount}
- customer_txn_count_seen: {evidence.customer_txn_count_seen}
- has_chargeback_history: {evidence.has_chargeback_history}

Supporting evidence (points TOWARD fraud):
{chr(10).join('+ ' + s for s in evidence.supporting_fraud_signals) if evidence.supporting_fraud_signals else '(none found)'}

Contradicting evidence (points AWAY from fraud):
{chr(10).join('- ' + s for s in evidence.contradicting_fraud_signals) if evidence.contradicting_fraud_signals else '(none found)'}

Your task:
1. Weigh supporting vs. contradicting evidence honestly. Do not default
   to agreeing with the Detector, and do not default to disagreeing --
   follow the evidence.
2. IMPORTANT: your job is symmetric. If the evidence meaningfully
   contradicts the fraud hypothesis (e.g. long account history, no prior
   chargebacks, device switching is normal for this customer, amount
   consistent with history), you should recommend a LOWER risk level
   and set verdict to CHALLENGE. If the evidence is thin or actually
   supports elevating beyond what the Detector assigned, you should
   recommend a HIGHER risk level and still set verdict to CHALLENGE
   (challenging is not the same as always lowering risk). If the
   evidence genuinely supports the Detector's original assessment as-is,
   set verdict to CONFIRM. If the evidence is too sparse to responsibly
   judge either way (e.g. brand-new customer, no transaction history
   available), set verdict to INSUFFICIENT_EVIDENCE.
3. List counter_evidence: the SPECIFIC evidence fields that undermine
   the fraud hypothesis (empty list if verdict is CONFIRM).
4. List supporting_evidence_acknowledged: the specific evidence fields
   you agree genuinely support risk, even if you're also challenging
   other parts of the hypothesis.
5. Give critic_reasoning: 1-3 sentences citing the SPECIFIC evidence
   driving your verdict -- a real risk analyst should be able to trace
   your conclusion back to a specific number above.

There is no tier above CRITICAL and none below LOW -- if evidence
suggests more or less severity than these bounds, use the nearest valid
tier and put the nuance in your reasoning text."""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CriticReview,
            # Same temperature as v1's Critic -- low enough for reliable,
            # reproducible evidence weighing, high enough to reason about
            # genuine trade-offs between conflicting signals.
            temperature=0.2,
        ),
    )

    parsed = json.loads(response.text)
    parsed["transaction_id"] = txn.transaction_id  # ensure ID is always correct, not LLM-generated
    return CriticReview(**parsed)
