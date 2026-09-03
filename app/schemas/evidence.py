"""
AEGIS-SWARM Razorpay Edition :: Evidence & Critic Schemas
============================================================
Two output contracts:
  1. EvidencePacket -- what the Investigator agent produces after
     calling the MCP evidence tools (customer/device/velocity/
     chargeback history). This is the "real evidence retrieval" layer
     the Razorpay strategy doc calls for -- MCP tools return actual
     lookups against data/customers.csv + data/transactions.csv, not
     LLM-hallucinated context.
  2. CriticReview -- what the Adversarial Critic produces after trying
     to disprove the Detector's fraud_hypothesis using the evidence
     packet. Reuses the escalation-asymmetry design principle from
     AEGIS v1's critic.py, but inverted: v1's Critic could only
     ESCALATE (crowd-safety bias: under-reporting costs lives). This
     Critic's job is explicitly the opposite -- it actively looks for
     reasons to DE-ESCALATE a false positive, because in payments,
     over-blocking has a real, measurable cost too (see policy/gate.py
     cost model). Both directions are legitimate escalation/de-escalation,
     evidence-driven, not vibes-driven.
"""

from typing import Literal
from pydantic import BaseModel, Field


class EvidencePacket(BaseModel):
    """
    Structured evidence pulled via MCP tools for one transaction.
    Every field here corresponds to one MCP tool call in app/mcp/server.py
    -- nothing here is inferred by an LLM; it is a direct lookup result.
    """
    transaction_id: str
    customer_id: str

    # From get_customer_history()
    account_age_days: int
    prior_successful_txns: int
    prior_chargebacks: int

    # From get_device_history()
    known_device_count: int
    is_new_device: bool

    # From get_velocity()
    velocity_1h: int
    velocity_24h: int

    # From get_transaction_history() -- aggregate stats on this customer's
    # OTHER transactions in the dataset, used to judge if this transaction
    # is consistent with their normal behavior
    customer_avg_amount: float | None
    customer_txn_count_seen: int

    # From get_chargeback_history()
    has_chargeback_history: bool

    supporting_fraud_signals: list[str]     # evidence that points TOWARD fraud
    contradicting_fraud_signals: list[str]  # evidence that points AWAY from fraud


class CriticReview(BaseModel):
    """
    Output contract for the Adversarial Critic.
    - verdict: CHALLENGE means the Critic found evidence undermining the
      Detector's fraud_hypothesis; CONFIRM means it could not.
    - counter_evidence: the specific EvidencePacket fields the Critic is
      citing -- must be traceable back to actual evidence, not invented.
    - recommended_adjustment: the Critic's suggested risk_level after
      considering counter-evidence. Like risk_level, this is a closed
      Literal so the Critic cannot invent a 5th tier -- same structural
      fix as AEGIS v1's confirmed bug fix for invented threat tiers.
    """
    transaction_id: str
    verdict: Literal["CHALLENGE", "CONFIRM", "INSUFFICIENT_EVIDENCE"]
    counter_evidence: list[str]
    supporting_evidence_acknowledged: list[str]
    recommended_adjustment: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    critic_reasoning: str = Field(..., min_length=1)
