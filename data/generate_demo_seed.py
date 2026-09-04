"""
AEGIS-SWARM Razorpay Edition :: Demo Seed Data Generator
===========================================================
Generates data/demo_customers.csv and data/demo_transactions.csv --
REAL dataset records backing the three frontend demo cases
(frontend/app/demoCases.ts), so those cases run through the exact same
MCP evidence path as any other transaction (get_customer_history,
get_device_history, get_velocity, get_transaction_history,
get_chargeback_history all resolve real rows, not frontend-fabricated
JSON).

WHY SEPARATE FILES, NOT APPENDED TO transactions.csv/customers.csv:
app/services/data_split.py loads its train/val/test split directly from
data/transactions.csv. Appending demo rows there would either (a)
require excluding them by ID pattern inside load_splits() -- fragile,
easy to break silently -- or (b) contaminate the held-out split with
hand-constructed, non-random rows, which is explicitly against "held-out
means held-out." Keeping demo records in their own files means:
  - data_split.py is completely unaffected (still reads only
    transactions.csv/customers.csv) -- the held-out test set is
    provably untouched by this change.
  - app/mcp/evidence_tools.py loads BOTH the main dataset and the demo
    dataset (see the updated _load_data()), so lookups for
    CUST_DEMO_A/B/C and TXN_DEMO_A/B/C resolve via the exact same code
    path used for every other transaction -- genuine MCP evidence
    retrieval, not a frontend-side fake.

THREE SCENARIOS, EACH WITH ENOUGH HISTORY TO BE EVIDENTIABLE:
- Case A (clear fraud): brand-new customer, zero prior transactions --
  the Investigator finds nothing to contradict the fraud hypothesis.
- Case B (ambiguous): established customer (640-day account, 34 prior
  successful transactions) with SEVERAL historical transactions seeded
  at a similar amount to the flagged transaction, so
  get_transaction_history() finds a customer_avg_amount consistent with
  the current transaction -- genuine contradicting evidence, not
  asserted by the frontend.
- Case C (legitimate): similarly established customer with consistent
  historical spending at a normal amount.
"""

from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).parent

CUSTOMER_COLUMNS = ["customer_id", "account_age_days", "prior_successful_txns", "prior_chargebacks", "known_device_count"]
TXN_COLUMNS = [
    "transaction_id", "customer_id", "amount_inr", "payment_method", "hour_of_day",
    "velocity_1h", "velocity_24h", "new_device", "geo_mismatch", "billing_shipping_mismatch",
    "failed_attempts_prior", "account_age_days", "prior_successful_txns", "prior_chargebacks",
    "known_device_count", "is_fraud",
]


def build_demo_records():
    customers = []
    transactions = []

    # ── Case A: Clear Fraud ────────────────────────────────────────────
    # Brand-new account, zero history -- nothing for the Investigator to
    # find that would contradict the fraud hypothesis.
    customers.append({
        "customer_id": "CUST_DEMO_A", "account_age_days": 2,
        "prior_successful_txns": 0, "prior_chargebacks": 0, "known_device_count": 1,
    })
    transactions.append({
        "transaction_id": "TXN_DEMO_A", "customer_id": "CUST_DEMO_A", "amount_inr": 78900.0,
        "payment_method": "card", "hour_of_day": 3, "velocity_1h": 4, "velocity_24h": 7,
        "new_device": True, "geo_mismatch": True, "billing_shipping_mismatch": True,
        "failed_attempts_prior": 3, "account_age_days": 2, "prior_successful_txns": 0,
        "prior_chargebacks": 0, "known_device_count": 1, "is_fraud": 1,
    })

    # ── Case B: Ambiguous / Suspicious ──────────────────────────────────
    # Established account (640 days, 34 prior successes) with GENUINELY
    # MIXED evidence: some real historical transactions exist (so
    # get_transaction_history() finds a real customer_avg_amount), but
    # the current transaction's amount is enough of an outlier from that
    # average, and the account uses few enough known devices, that the
    # evidence doesn't overwhelmingly clear the transaction either --
    # this is what makes the case genuinely ambiguous rather than a
    # disguised ALLOW. Elevated velocity/timing/failed-attempt signals
    # push the baseline model's risk_score into HIGH territory; the
    # account history then provides real (but not total) contradicting
    # evidence, landing on STEP_UP via Policy Gate rule R4 -- verified
    # empirically against the trained baseline, not asserted.
    customers.append({
        "customer_id": "CUST_DEMO_B", "account_age_days": 640,
        "prior_successful_txns": 34, "prior_chargebacks": 0, "known_device_count": 2,
    })
    demo_b_history_amounts = [9800, 11200, 8600, 12100, 10400]
    for i, amt in enumerate(demo_b_history_amounts):
        transactions.append({
            "transaction_id": f"TXN_DEMO_B_HIST{i+1}", "customer_id": "CUST_DEMO_B", "amount_inr": float(amt),
            "payment_method": "card", "hour_of_day": 15, "velocity_1h": 0, "velocity_24h": 1,
            "new_device": False, "geo_mismatch": False, "billing_shipping_mismatch": False,
            "failed_attempts_prior": 0, "account_age_days": 640, "prior_successful_txns": 34,
            "prior_chargebacks": 0, "known_device_count": 2, "is_fraud": 0,
        })
    transactions.append({
        "transaction_id": "TXN_DEMO_B", "customer_id": "CUST_DEMO_B", "amount_inr": 32400.0,
        "payment_method": "card", "hour_of_day": 2, "velocity_1h": 2, "velocity_24h": 4,
        "new_device": True, "geo_mismatch": False, "billing_shipping_mismatch": False,
        "failed_attempts_prior": 1, "account_age_days": 640, "prior_successful_txns": 34,
        "prior_chargebacks": 0, "known_device_count": 2, "is_fraud": 0,
    })

    # ── Case C: Legitimate ───────────────────────────────────────────────
    # Established account with real consistent low-value spending history.
    customers.append({
        "customer_id": "CUST_DEMO_C", "account_age_days": 410,
        "prior_successful_txns": 22, "prior_chargebacks": 0, "known_device_count": 2,
    })
    demo_c_history_amounts = [2100, 2350, 1980, 2450, 2260]
    for i, amt in enumerate(demo_c_history_amounts):
        transactions.append({
            "transaction_id": f"TXN_DEMO_C_HIST{i+1}", "customer_id": "CUST_DEMO_C", "amount_inr": float(amt),
            "payment_method": "upi", "hour_of_day": 11, "velocity_1h": 0, "velocity_24h": 1,
            "new_device": False, "geo_mismatch": False, "billing_shipping_mismatch": False,
            "failed_attempts_prior": 0, "account_age_days": 410, "prior_successful_txns": 22,
            "prior_chargebacks": 0, "known_device_count": 2, "is_fraud": 0,
        })
    transactions.append({
        "transaction_id": "TXN_DEMO_C", "customer_id": "CUST_DEMO_C", "amount_inr": 2200.0,
        "payment_method": "upi", "hour_of_day": 11, "velocity_1h": 0, "velocity_24h": 1,
        "new_device": False, "geo_mismatch": False, "billing_shipping_mismatch": False,
        "failed_attempts_prior": 0, "account_age_days": 410, "prior_successful_txns": 22,
        "prior_chargebacks": 0, "known_device_count": 2, "is_fraud": 0,
    })

    return pd.DataFrame(customers, columns=CUSTOMER_COLUMNS), pd.DataFrame(transactions, columns=TXN_COLUMNS)


def main():
    customers_df, transactions_df = build_demo_records()
    customers_df.to_csv(DATA_DIR / "demo_customers.csv", index=False)
    transactions_df.to_csv(DATA_DIR / "demo_transactions.csv", index=False)
    print(f"Saved {len(customers_df)} demo customers -> {DATA_DIR / 'demo_customers.csv'}")
    print(f"Saved {len(transactions_df)} demo transactions -> {DATA_DIR / 'demo_transactions.csv'}")
    print("These are SEPARATE from data/transactions.csv and data/customers.csv -- "
          "the held-out train/val/test split (app/services/data_split.py) is unaffected.")


if __name__ == "__main__":
    main()
