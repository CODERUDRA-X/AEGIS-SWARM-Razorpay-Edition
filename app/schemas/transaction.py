"""
AEGIS-SWARM Razorpay Edition :: Transaction Schema
=====================================================
This is the input contract for the entire pipeline. Every downstream
component (baseline model, Detector, Investigator, Critic, Policy Gate)
receives data conforming to this shape -- either a single Transaction
or a row from the transactions.csv dataset.

WHY A SEPARATE SCHEMA FILE (reused pattern from AEGIS-SWARM v1):
Same design principle as the original ScoutReport/RiskAssessment
schemas -- Pydantic enforces the contract at the type level so a typo'd
field name fails loudly at construction time, not silently three layers
downstream in a KeyError.
"""

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    """
    A single payment transaction plus the account-level context needed
    to assess it. Mirrors the columns in data/transactions.csv exactly,
    so a CSV row can be loaded directly into this model.
    """
    transaction_id: str
    customer_id: str
    amount_inr: float = Field(..., gt=0)
    payment_method: str  # "card" | "upi" | "netbanking" | "wallet"
    hour_of_day: int = Field(..., ge=0, le=23)

    # Velocity signals
    velocity_1h: int = Field(..., ge=0)
    velocity_24h: int = Field(..., ge=0)

    # Device / geography signals
    new_device: bool
    geo_mismatch: bool
    billing_shipping_mismatch: bool
    failed_attempts_prior: int = Field(..., ge=0)

    # Account-history signals (looked up by customer_id -- this is exactly
    # what the Investigator agent independently re-fetches as "evidence"
    # rather than trusting whatever was bundled into the request)
    account_age_days: int = Field(..., ge=0)
    prior_successful_txns: int = Field(..., ge=0)
    prior_chargebacks: int = Field(..., ge=0)
    known_device_count: int = Field(..., ge=0)

    # Ground truth -- only present in the dataset for training/eval,
    # NEVER passed to the live pipeline at inference time.
    is_fraud: int | None = None
