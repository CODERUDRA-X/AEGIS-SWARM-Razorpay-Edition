"""
AEGIS-SWARM Razorpay Edition :: Baseline Fraud Classifier
============================================================
PROVIDER-AGNOSTIC BY DESIGN.
This module exposes three functions that the rest of the system calls:

    train_baseline(df)   -> trained model object + metadata dict
    predict_risk(model, X) -> np.ndarray of fraud probabilities
    evaluate_model(model, X_test, y_test) -> metrics dict

The MODEL_BACKEND variable below is the single switch between backends.
Swapping "xgboost" in for the dev fallback requires editing ONLY the
_fit_xgboost() function body (already stubbed with the real xgboost API
below) -- no other file in this codebase needs to change, because every
caller only ever touches train_baseline/predict_risk/evaluate_model.

============================================================
IMPORTANT / DO NOT MISREPRESENT THIS:
============================================================
This sandbox environment has NO network access, so `pip install xgboost`
cannot complete here (confirmed: PyPI unreachable). Until XGBoost is
installed and run in a real environment, MODEL_BACKEND defaults to
"dev_hist_gb" -- scikit-learn's HistGradientBoostingClassifier, which is
ALSO a histogram-based gradient-boosted-tree model (same algorithm
family as XGBoost/LightGBM) but is NOT XGBoost and must never be
reported as XGBoost results.

Every metrics dict returned by evaluate_model() includes a
"model_backend" field for exactly this reason -- so the README, the
frontend, and any results table can programmatically state which model
actually produced the numbers, instead of a human having to remember
to caveat it correctly every time.

TO RUN THE REAL XGBOOST BASELINE LOCALLY:
    pip install xgboost
    export AEGIS_MODEL_BACKEND=xgboost
    python -m app.services.evaluation --backend xgboost
"""

import os
import json
import pickle
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

MODEL_BACKEND = os.environ.get("AEGIS_MODEL_BACKEND", "dev_hist_gb")

NUMERIC_FEATURES = [
    "amount_inr", "hour_of_day", "velocity_1h", "velocity_24h",
    "failed_attempts_prior", "account_age_days", "prior_successful_txns",
    "prior_chargebacks", "known_device_count",
]
BOOLEAN_FEATURES = ["new_device", "geo_mismatch", "billing_shipping_mismatch"]
CATEGORICAL_FEATURES = ["payment_method"]
ALL_FEATURES = NUMERIC_FEATURES + BOOLEAN_FEATURES + CATEGORICAL_FEATURES
TARGET = "is_fraud"


@dataclass
class TrainedModel:
    """
    Thin wrapper so predict_risk()/evaluate_model() have one consistent
    interface regardless of which backend actually trained the model.
    """
    pipeline: Pipeline
    backend: str
    feature_names: list[str]
    training_rows: int
    training_fraud_rate: float


def _build_preprocessor(scale_numeric: bool = False) -> ColumnTransformer:
    """
    Shared preprocessing -- one-hot encode payment_method always.
    scale_numeric=True additionally standardizes numeric features, which
    tree-based models (dev_hist_gb, xgboost) don't need but LogisticRegression
    does (unscaled amount_inr in the thousands vs. 0/1 booleans causes the
    lbfgs solver to fail to converge -- confirmed while building this).
    """
    transformers = [("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES)]
    if scale_numeric:
        transformers.append(("num", StandardScaler(), NUMERIC_FEATURES))
        remainder_cols = "drop"  # booleans still need to pass through explicitly below
        transformers.append(("bool_passthrough", "passthrough", BOOLEAN_FEATURES))
    else:
        remainder_cols = "passthrough"

    return ColumnTransformer(transformers=transformers, remainder=remainder_cols)


def _fit_dev_hist_gb(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    TEMPORARY DEVELOPMENT BASELINE -- scikit-learn HistGradientBoostingClassifier.
    Used only because this sandbox cannot install xgboost. Same
    gradient-boosted-histogram-tree family as XGBoost, but a DIFFERENT
    implementation with different defaults -- do not expect identical
    numbers to a real XGBoost run, and never call this "XGBoost" in any
    report or UI.
    """
    clf = HistGradientBoostingClassifier(
        max_iter=200,
        max_depth=4,
        learning_rate=0.08,
        class_weight="balanced",  # dataset is imbalanced (~15% fraud) -- see data/generate_dataset.py
        random_state=42,
    )
    pipe = Pipeline([("prep", _build_preprocessor()), ("clf", clf)])
    pipe.fit(X, y)
    return pipe


def _fit_xgboost(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    REAL XGBOOST BACKEND -- not runnable in this sandbox (no network to
    pip install), but written against the actual xgboost sklearn API so
    it should run as-is once `pip install xgboost` succeeds locally.

    scale_pos_weight handles the class imbalance the same way
    class_weight="balanced" does for the dev backend -- kept consistent
    in spirit so a backend comparison isn't confounded by imbalance
    handling differing between the two.
    """
    import xgboost as xgb  # local import: only required if this backend is selected

    fraud_rate = y.mean()
    scale_pos_weight = (1 - fraud_rate) / fraud_rate if fraud_rate > 0 else 1.0

    clf = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        random_state=42,
    )
    pipe = Pipeline([("prep", _build_preprocessor()), ("clf", clf)])
    pipe.fit(X, y)
    return pipe


def _fit_logistic_regression(X: pd.DataFrame, y: pd.Series) -> Pipeline:
    """
    Simplest possible baseline -- kept available as a third option / sanity
    check. If a gradient-boosted model can't beat plain logistic regression
    by a meaningful margin, that itself is a finding worth reporting, not
    hiding.
    """
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
    pipe = Pipeline([("prep", _build_preprocessor(scale_numeric=True)), ("clf", clf)])
    pipe.fit(X, y)
    return pipe


_BACKEND_FITTERS = {
    "dev_hist_gb": _fit_dev_hist_gb,
    "xgboost": _fit_xgboost,
    "logistic_regression": _fit_logistic_regression,
}


def train_baseline(df: pd.DataFrame, backend: str | None = None) -> TrainedModel:
    """
    Train the baseline fraud classifier on a training split.

    Args:
        df: DataFrame with ALL_FEATURES columns + TARGET column (is_fraud).
        backend: one of "dev_hist_gb" | "xgboost" | "logistic_regression".
                 Defaults to MODEL_BACKEND (env var AEGIS_MODEL_BACKEND,
                 falls back to "dev_hist_gb").

    Returns:
        TrainedModel wrapper. Pass this directly to predict_risk()/evaluate_model().
    """
    backend = backend or MODEL_BACKEND
    if backend not in _BACKEND_FITTERS:
        raise ValueError(f"Unknown backend '{backend}'. Options: {list(_BACKEND_FITTERS)}")

    X = df[ALL_FEATURES].copy()
    y = df[TARGET].astype(int)

    pipeline = _BACKEND_FITTERS[backend](X, y)

    return TrainedModel(
        pipeline=pipeline,
        backend=backend,
        feature_names=ALL_FEATURES,
        training_rows=len(df),
        training_fraud_rate=round(float(y.mean()), 4),
    )


def predict_risk(model: TrainedModel, df: pd.DataFrame) -> np.ndarray:
    """
    Return fraud probability (0.0-1.0) for each row in df.
    df must contain ALL_FEATURES columns (TARGET column not required/used).
    """
    X = df[model.feature_names].copy()
    proba = model.pipeline.predict_proba(X)[:, 1]
    return proba


def evaluate_model(model: TrainedModel, df_test: pd.DataFrame, threshold: float = 0.5) -> dict:
    """
    Compute held-out evaluation metrics. This is the SAME function used
    for the baseline alone and for comparing against the full AEGIS-SWARM
    pipeline (see app/services/evaluation.py) -- one evaluation harness,
    reused, so numbers are directly comparable across systems.

    threshold: decision threshold applied to risk_score to derive a binary
    prediction for precision/recall/F1/confusion-matrix. Note this is
    DIFFERENT from the Policy Gate's multi-tier thresholds (LOW/MEDIUM/
    HIGH/CRITICAL -> ALLOW/STEP_UP/REVIEW/BLOCK) -- this single threshold
    exists only to produce a standard binary classification report for
    the baseline model in isolation, since a raw ML model has no notion
    of STEP_UP/REVIEW.
    """
    from sklearn.metrics import (
        precision_score, recall_score, f1_score, confusion_matrix,
        roc_auc_score, average_precision_score,
    )

    y_true = df_test[TARGET].astype(int).to_numpy()
    y_score = predict_risk(model, df_test)
    y_pred = (y_score >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    metrics = {
        "model_backend": model.backend,
        "n_test": len(df_test),
        "threshold": threshold,
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_score)), 4) if len(set(y_true)) > 1 else None,
        "pr_auc": round(float(average_precision_score(y_true, y_score)), 4) if len(set(y_true)) > 1 else None,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "test_fraud_rate": round(float(y_true.mean()), 4),
    }
    return metrics


def save_model(model: TrainedModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)
    meta_path = path.with_suffix(".meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "backend": model.backend,
            "feature_names": model.feature_names,
            "training_rows": model.training_rows,
            "training_fraud_rate": model.training_fraud_rate,
        }, f, indent=2)


def load_model(path: Path) -> TrainedModel:
    with open(path, "rb") as f:
        return pickle.load(f)
