"""
AEGIS-SWARM Razorpay Edition :: Evidence Lookup Logic
========================================================
The actual implementation of every evidence tool -- deliberately has NO
dependency on the `mcp` package, so it can be imported and tested in
any environment (including this sandbox, which cannot install `mcp`).

app/mcp/server.py registers these exact functions as MCP tools (real
protocol path). app/mcp/client.py's fallback path calls these exact
functions directly, in-process, when the `mcp` SDK isn't installed.
Either way, the evidence VALUES returned for a given customer_id/
transaction_id are identical -- there is one implementation, not two
copies that could drift.

This is a real replacement for AEGIS v1's mcp_server.py, which called
the live Open-Meteo weather API. These tools instead query the local
synthetic dataset (data/transactions.csv, data/customers.csv) -- a
genuine data lookup, not a hallucinated value, even though the backing
store here is a CSV rather than a production database.
"""

from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).parent.parent.parent / "data"

_transactions_df: pd.DataFrame | None = None
_customers_df: pd.DataFrame | None = None


def _load_data() -> None:
    """
    Loads the main dataset AND, if present, the demo seed dataset
    (data/demo_customers.csv, data/demo_transactions.csv -- see
    data/generate_demo_seed.py), merging them into one lookup table.

    This is what lets the frontend's three demo cases (CUST_DEMO_A/B/C)
    resolve through the exact same evidence-retrieval code path as any
    other transaction -- there is no separate "demo mode" branch here,
    the demo records are just additional rows.

    IMPORTANT: app/services/data_split.py, which produces the held-out
    train/val/test split, reads data/transactions.csv directly and does
    NOT go through this function -- so merging demo records here has
    zero effect on the held-out evaluation split.
    """
    global _transactions_df, _customers_df

    if _transactions_df is None:
        main_txns = pd.read_csv(DATA_DIR / "transactions.csv")
        demo_txns_path = DATA_DIR / "demo_transactions.csv"
        if demo_txns_path.exists():
            demo_txns = pd.read_csv(demo_txns_path)
            _transactions_df = pd.concat([main_txns, demo_txns], ignore_index=True)
        else:
            _transactions_df = main_txns

    if _customers_df is None:
        main_cust = pd.read_csv(DATA_DIR / "customers.csv")
        demo_cust_path = DATA_DIR / "demo_customers.csv"
        if demo_cust_path.exists():
            demo_cust = pd.read_csv(demo_cust_path)
            _customers_df = pd.concat([main_cust, demo_cust], ignore_index=True)
        else:
            _customers_df = main_cust


def get_customer_history(customer_id: str) -> dict:
    """
    Look up a customer's account-level history: how long the account has
    existed, how many prior successful transactions and chargebacks are
    on record. This is the primary evidence source for judging whether a
    flagged transaction is consistent with the customer's normal behavior.
    """
    _load_data()
    row = _customers_df[_customers_df["customer_id"] == customer_id]
    if row.empty:
        return {"error": f"No customer record found for {customer_id}", "mcp_status": "not_found"}
    r = row.iloc[0]
    return {
        "customer_id": customer_id,
        "account_age_days": int(r["account_age_days"]),
        "prior_successful_txns": int(r["prior_successful_txns"]),
        "prior_chargebacks": int(r["prior_chargebacks"]),
        "known_device_count": int(r["known_device_count"]),
        "mcp_status": "success",
    }


def get_device_history(customer_id: str) -> dict:
    """
    Look up how many distinct devices this customer has historically used.
    A transaction from a brand-new device is far less suspicious for a
    customer who regularly uses 3-4 devices than for one who has only
    ever used a single device.
    """
    _load_data()
    row = _customers_df[_customers_df["customer_id"] == customer_id]
    if row.empty:
        return {"error": f"No customer record found for {customer_id}", "mcp_status": "not_found"}
    known_devices = int(row.iloc[0]["known_device_count"])
    return {
        "customer_id": customer_id,
        "known_device_count": known_devices,
        "multi_device_customer": known_devices >= 3,
        "mcp_status": "success",
    }


def get_velocity(transaction_id: str) -> dict:
    """
    Look up the velocity signals (attempts in the last 1h/24h) recorded
    for a specific transaction at the time it occurred.
    """
    _load_data()
    row = _transactions_df[_transactions_df["transaction_id"] == transaction_id]
    if row.empty:
        return {"error": f"No transaction found for {transaction_id}", "mcp_status": "not_found"}
    r = row.iloc[0]
    return {
        "transaction_id": transaction_id,
        "velocity_1h": int(r["velocity_1h"]),
        "velocity_24h": int(r["velocity_24h"]),
        "failed_attempts_prior": int(r["failed_attempts_prior"]),
        "mcp_status": "success",
    }


def get_transaction_history(customer_id: str, exclude_transaction_id: str | None = None) -> dict:
    """
    Look up aggregate statistics on a customer's OTHER transactions in the
    dataset (average amount, count seen) -- used to judge whether the
    current transaction's amount is consistent with the customer's normal
    spending pattern, or a significant outlier.
    """
    _load_data()
    cust_txns = _transactions_df[_transactions_df["customer_id"] == customer_id]
    if exclude_transaction_id:
        cust_txns = cust_txns[cust_txns["transaction_id"] != exclude_transaction_id]

    if cust_txns.empty:
        return {
            "customer_id": customer_id,
            "customer_avg_amount": None,
            "customer_txn_count_seen": 0,
            "mcp_status": "no_other_transactions",
        }

    return {
        "customer_id": customer_id,
        "customer_avg_amount": round(float(cust_txns["amount_inr"].mean()), 2),
        "customer_txn_count_seen": int(len(cust_txns)),
        "mcp_status": "success",
    }


def get_chargeback_history(customer_id: str) -> dict:
    """
    Look up whether this customer has any prior chargebacks on record.
    Chargeback history is one of the strongest priors in real fraud
    systems -- a customer with zero chargebacks across dozens of prior
    transactions is meaningfully different from one with even a single
    prior chargeback.
    """
    _load_data()
    row = _customers_df[_customers_df["customer_id"] == customer_id]
    if row.empty:
        return {"error": f"No customer record found for {customer_id}", "mcp_status": "not_found"}
    chargebacks = int(row.iloc[0]["prior_chargebacks"])
    return {
        "customer_id": customer_id,
        "prior_chargebacks": chargebacks,
        "has_chargeback_history": chargebacks > 0,
        "mcp_status": "success",
    }
