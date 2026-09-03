// AEGIS-SWARM Razorpay Edition :: Frontend Type Contract
// ==========================================================
// Mirrors app/schemas/*.py EXACTLY -- field names and types match the
// Pydantic models 1:1, so a backend response can be used directly
// without any renaming/mapping layer. This is what item E of the
// checklist means by "actually consume the new backend data model" --
// there is no crowd-safety field anywhere in this file (no
// people_count, environment_type, scene_category, etc.).

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type PolicyAction = "ALLOW" | "STEP_UP" | "REVIEW" | "BLOCK";
export type CriticVerdict = "CHALLENGE" | "CONFIRM" | "INSUFFICIENT_EVIDENCE";

export interface Transaction {
  transaction_id: string;
  customer_id: string;
  amount_inr: number;
  payment_method: string;
  hour_of_day: number;
  velocity_1h: number;
  velocity_24h: number;
  new_device: boolean;
  geo_mismatch: boolean;
  billing_shipping_mismatch: boolean;
  failed_attempts_prior: number;
  account_age_days: number;
  prior_successful_txns: number;
  prior_chargebacks: number;
  known_device_count: number;
  is_fraud?: number | null;
}

export interface DetectorOutput {
  transaction_id: string;
  risk_score: number;
  risk_level: RiskLevel;
  fraud_hypothesis: string;
  signals: string[];
  model_source: string;
}

export interface EvidencePacket {
  transaction_id: string;
  customer_id: string;
  account_age_days: number;
  prior_successful_txns: number;
  prior_chargebacks: number;
  known_device_count: number;
  is_new_device: boolean;
  velocity_1h: number;
  velocity_24h: number;
  customer_avg_amount: number | null;
  customer_txn_count_seen: number;
  has_chargeback_history: boolean;
  supporting_fraud_signals: string[];
  contradicting_fraud_signals: string[];
}

export interface CriticReview {
  transaction_id: string;
  verdict: CriticVerdict;
  counter_evidence: string[];
  supporting_evidence_acknowledged: string[];
  recommended_adjustment: RiskLevel;
  critic_reasoning: string;
}

export interface PolicyDecision {
  transaction_id: string;
  action: PolicyAction;
  triggered_rule: string;
  final_risk_score: number;
  critic_verdict: string;
  reasoning: string;
  estimated_cost_inr: number;
}

export interface PipelineResponse {
  transaction: Transaction;
  detector: DetectorOutput;
  evidence: EvidencePacket;
  critic: CriticReview;
  decision: PolicyDecision;
}

export interface ConfusionMatrix {
  tn: number;
  fp: number;
  fn: number;
  tp: number;
}

export interface EvaluationReport {
  dataset_manifest: {
    n_transactions: number;
    n_customers: number;
    n_fraud: number;
    n_legit: number;
    measured_fraud_rate: number;
    pre_noise_target_rate: number;
    label_noise_rate: number;
  };
  train_val_test_sizes: { train: number; val: number; test: number };
  model_backend: string;
  baseline_only: {
    model_backend: string;
    n_test: number;
    threshold: number;
    precision: number;
    recall: number;
    f1: number;
    roc_auc: number | null;
    pr_auc: number | null;
    confusion_matrix: ConfusionMatrix;
    test_fraud_rate: number;
    cost_simulation: { total_estimated_cost_inr: number; avg_cost_per_transaction_inr: number };
  };
  aegis_swarm_pipeline: {
    system_label: string;
    n_test: number;
    binary_metrics_block_vs_rest: {
      precision: number;
      recall: number;
      f1: number;
      confusion_matrix: ConfusionMatrix;
    };
    action_distribution: Record<PolicyAction, number>;
    cost_by_action_inr: Record<PolicyAction, number>;
    total_estimated_cost_inr: number;
    avg_cost_per_transaction_inr: number;
    rule_trigger_counts: Record<string, number>;
    cost_model_assumptions: {
      fraud_miss_cost_inr: number;
      false_positive_cost_inr: number;
      step_up_friction_cost_inr: number;
      review_operational_cost_inr: number;
      disclosure: string;
    };
  };
  recall_gap_analysis: {
    total_missed_fraud_cases: number;
    baseline_would_also_miss: { count: number; explanation: string; transaction_ids: string[] };
    critic_deescalated_a_baseline_catch: {
      count: number;
      to_step_up_partial_mitigation: number;
      to_allow_full_miss: number;
      explanation: string;
      transaction_ids: string[];
    };
  };
}
