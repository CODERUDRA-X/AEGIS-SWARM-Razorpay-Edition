"""
AEGIS-SWARM Razorpay Edition :: Train/Validation/Test Split
==============================================================
One split, computed once, reused everywhere (baseline training, agent
evaluation, full-pipeline evaluation) so every reported number is on
the SAME held-out test set. This is the "held-out means held-out" rule
from the strategy doc -- test rows are never touched during training,
threshold calibration, or prompt iteration.

70/15/15 split, stratified by is_fraud so the already-small fraud class
doesn't end up unevenly distributed across splits by chance.
"""

from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split

DATA_DIR = Path(__file__).parent.parent.parent / "data"
RANDOM_STATE = 42


def load_splits() -> dict[str, pd.DataFrame]:
    """
    Returns {"train": df, "val": df, "test": df} -- 70/15/15, stratified
    on is_fraud. Deterministic (fixed random_state) so re-running always
    yields the identical split -- required for "test set never seen"
    guarantees to actually hold across separate script runs.
    """
    df = pd.read_csv(DATA_DIR / "transactions.csv")

    train_df, temp_df = train_test_split(
        df, test_size=0.30, stratify=df["is_fraud"], random_state=RANDOM_STATE
    )
    val_df, test_df = train_test_split(
        temp_df, test_size=0.50, stratify=temp_df["is_fraud"], random_state=RANDOM_STATE
    )

    return {
        "train": train_df.reset_index(drop=True),
        "val": val_df.reset_index(drop=True),
        "test": test_df.reset_index(drop=True),
    }


if __name__ == "__main__":
    splits = load_splits()
    for name, split_df in splits.items():
        fraud_rate = split_df["is_fraud"].mean()
        print(f"{name:5s}: {len(split_df):4d} rows | fraud_rate={fraud_rate:.4f} "
              f"({int(split_df['is_fraud'].sum())} fraud)")
