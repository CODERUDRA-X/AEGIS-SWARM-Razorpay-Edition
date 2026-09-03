"""
AEGIS-SWARM Razorpay Edition :: Investigator Agent
=====================================================
ROLE: Calls the MCP evidence tools (app/mcp/client.py) to independently
retrieve customer/device/velocity/transaction/chargeback history, then
classifies each piece of evidence as supporting or contradicting the
Detector's fraud hypothesis.

WHY THIS AGENT IS MOSTLY DETERMINISTIC, NOT AN LLM CALL:
The strategy doc is explicit: "the important thing is that the agent
obtains evidence, rather than simply hallucinating context." The value
of this agent is the REAL MCP round-trip, not LLM creativity. Sorting
retrieved facts into supporting/contradicting buckets is a rule-based
classification problem (e.g. "0 prior chargebacks" is unambiguously
contradicting evidence for a fraud hypothesis) -- adding an LLM call
here would introduce non-determinism into what should be a factual
evidence-gathering step, without adding real value. This mirrors the
same design principle as AEGIS v1's Scout agent: keep observation
(here: evidence retrieval + classification) separate from and prior to
judgment (here: the Critic's actual challenge).
"""

import asyncio

from app.schemas.transaction import Transaction
from app.schemas.risk import DetectorOutput
from app.schemas.evidence import EvidencePacket
from app.mcp.client import gather_all_evidence


def _classify_evidence(txn: Transaction, raw_evidence: dict) -> tuple[list[str], list[str]]:
    """
    Deterministic classification of retrieved evidence into signals that
    SUPPORT the fraud hypothesis vs. signals that CONTRADICT it. Every
    rule here is traceable to a specific evidence field -- auditable by
    construction, not an LLM's implicit judgment call.
    """
    supporting: list[str] = []
    contradicting: list[str] = []

    cust_hist = raw_evidence.get("customer_history", {})
    device_hist = raw_evidence.get("device_history", {})
    velocity = raw_evidence.get("velocity", {})
    txn_hist = raw_evidence.get("transaction_history", {})
    chargeback_hist = raw_evidence.get("chargeback_history", {})

    # Chargeback history -- one of the strongest priors
    if chargeback_hist.get("has_chargeback_history"):
        supporting.append(
            f"customer has {chargeback_hist.get('prior_chargebacks')} prior chargeback(s) on record"
        )
    elif chargeback_hist.get("mcp_status") == "success":
        contradicting.append("customer has zero prior chargebacks on record")

    # Account tenure + transaction history
    account_age = cust_hist.get("account_age_days")
    prior_successes = cust_hist.get("prior_successful_txns")
    if account_age is not None and prior_successes is not None:
        if account_age >= 180 and prior_successes >= 5:
            contradicting.append(
                f"established account ({account_age} days old, {prior_successes} prior successful transactions)"
            )
        elif account_age < 14:
            supporting.append(f"very new account ({account_age} days old)")

    # Device history -- context for the new_device flag
    if txn.new_device:
        if device_hist.get("multi_device_customer"):
            contradicting.append(
                f"new device, but customer has {device_hist.get('known_device_count')} known devices historically "
                f"-- device switching is normal for this customer"
            )
        else:
            supporting.append(
                "new device AND customer has historically used very few devices -- unusual for this account"
            )

    # Velocity, cross-checked against retrieved (not just submitted) values
    v1h = velocity.get("velocity_1h", txn.velocity_1h)
    v24h = velocity.get("velocity_24h", txn.velocity_24h)
    if v1h >= 3:
        supporting.append(f"{v1h} transaction attempts in the last hour (retrieved via MCP)")
    if velocity.get("failed_attempts_prior", 0) >= 2:
        supporting.append(f"{velocity.get('failed_attempts_prior')} failed attempts immediately prior")

    # Amount consistency with historical spending pattern
    avg_amount = txn_hist.get("customer_avg_amount")
    if avg_amount is not None and avg_amount > 0:
        ratio = txn.amount_inr / avg_amount
        if ratio >= 4:
            supporting.append(
                f"amount (₹{txn.amount_inr:,.2f}) is {ratio:.1f}x this customer's historical average "
                f"(₹{avg_amount:,.2f})"
            )
        elif 0.3 <= ratio <= 2.5:
            contradicting.append(
                f"amount (₹{txn.amount_inr:,.2f}) is consistent with this customer's historical "
                f"average (₹{avg_amount:,.2f})"
            )
    elif txn_hist.get("customer_txn_count_seen", 0) == 0:
        supporting.append("no prior transaction history available for this customer to compare against")

    # Geo/address mismatch -- carried straight through, these are already
    # facts about the transaction itself, not something to re-derive
    if txn.geo_mismatch:
        supporting.append("IP geography does not match billing location")
    if txn.billing_shipping_mismatch:
        supporting.append("billing and shipping addresses do not match")

    # NOTE: we deliberately do NOT pad empty lists with placeholder text
    # like "no supporting evidence found" here. EvidencePacket's schema
    # allows empty lists, and padding them would corrupt any downstream
    # code that counts len(supporting_fraud_signals) as a real signal
    # count (e.g. the rule-based dev critic's escalate/de-escalate logic
    # in risk_engine.py) -- a placeholder string is not evidence and
    # must not be counted as if it were. Callers that need a fallback
    # display string for an empty list handle that at display time.

    return supporting, contradicting


def investigate(txn: Transaction, detector_output: DetectorOutput) -> EvidencePacket:
    """
    Retrieves real evidence via MCP (app.mcp.client.gather_all_evidence)
    and classifies it relative to the Detector's fraud hypothesis.

    This function is synchronous at the call site (wraps the async MCP
    client call) so it composes cleanly with the rest of the pipeline in
    services/risk_engine.py, which orchestrates the full sync pipeline.
    """
    raw_evidence = asyncio.run(gather_all_evidence(txn.transaction_id, txn.customer_id))

    supporting, contradicting = _classify_evidence(txn, raw_evidence)

    cust_hist = raw_evidence.get("customer_history", {})
    device_hist = raw_evidence.get("device_history", {})
    velocity = raw_evidence.get("velocity", {})
    txn_hist = raw_evidence.get("transaction_history", {})
    chargeback_hist = raw_evidence.get("chargeback_history", {})

    return EvidencePacket(
        transaction_id=txn.transaction_id,
        customer_id=txn.customer_id,
        account_age_days=cust_hist.get("account_age_days", txn.account_age_days),
        prior_successful_txns=cust_hist.get("prior_successful_txns", txn.prior_successful_txns),
        prior_chargebacks=cust_hist.get("prior_chargebacks", txn.prior_chargebacks),
        known_device_count=device_hist.get("known_device_count", txn.known_device_count),
        is_new_device=txn.new_device,
        velocity_1h=velocity.get("velocity_1h", txn.velocity_1h),
        velocity_24h=velocity.get("velocity_24h", txn.velocity_24h),
        customer_avg_amount=txn_hist.get("customer_avg_amount"),
        customer_txn_count_seen=txn_hist.get("customer_txn_count_seen", 0),
        has_chargeback_history=chargeback_hist.get("has_chargeback_history", txn.prior_chargebacks > 0),
        supporting_fraud_signals=supporting,
        contradicting_fraud_signals=contradicting,
    )
