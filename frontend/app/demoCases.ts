// AEGIS-SWARM Razorpay Edition :: Demo Case Fixtures
// ======================================================
// Three reproducible transactions covering the required demo spread:
// clear fraud -> BLOCK, ambiguous/suspicious -> STEP_UP, legitimate ->
// ALLOW. Each transaction_id/customer_id below corresponds to a REAL
// seeded record in data/demo_transactions.csv / data/demo_customers.csv
// (see data/generate_demo_seed.py) -- the backend's Investigator agent
// retrieves evidence for these via the exact same MCP evidence path
// used for every other transaction (get_customer_history,
// get_device_history, get_velocity, get_transaction_history,
// get_chargeback_history all resolve real rows). Nothing here is
// evidence the frontend asserts on its own; the fields below are only
// the INPUT transaction -- everything the Investigator/Critic see
// beyond this is fetched live from the backend.
//
// All three outcomes were empirically verified end-to-end (Detector ->
// Investigator -> Critic -> Policy Gate) against the trained baseline
// model before being finalized here:
//   Case A -> BLOCK   (risk_score 0.998, CRITICAL, rule R8_CRITICAL_DEFAULT)
//   Case B -> STEP_UP (risk_score 0.766, HIGH, rule R4_HIGH_CRITIC_CHALLENGE_STRONG)
//   Case C -> ALLOW   (risk_score 0.293, LOW, rule R1_LOW_ALLOW)
//
// IMPORTANT HONESTY NOTE: verification above used the rule-based dev
// critic (no live Gemini call), since that's what was available for
// automated testing. The real LLM Critic (agents/critic.py) may weigh
// evidence differently in its final wording, though the underlying
// evidence retrieved is identical either way -- re-verify these three
// cases with GEMINI_API_KEY configured before a live demo.

import { Transaction } from "./types";

export interface DemoCase {
  id: string;
  label: string;
  expectedOutcome: string;
  description: string;
  transaction: Transaction;
}

export const DEMO_CASES: DemoCase[] = [
  {
    id: "clear-fraud",
    label: "Case A — Clear Fraud",
    expectedOutcome: "BLOCK",
    description:
      "New device, 2-day-old account, IP/billing mismatch, velocity spike, high amount, no purchase history for the Investigator to find that would contradict the hypothesis.",
    transaction: {
      transaction_id: "TXN_DEMO_A",
      customer_id: "CUST_DEMO_A",
      amount_inr: 78900,
      payment_method: "card",
      hour_of_day: 3,
      velocity_1h: 4,
      velocity_24h: 7,
      new_device: true,
      geo_mismatch: true,
      billing_shipping_mismatch: true,
      failed_attempts_prior: 3,
      account_age_days: 2,
      prior_successful_txns: 0,
      prior_chargebacks: 0,
      known_device_count: 1,
    },
  },
  {
    id: "ambiguous",
    label: "Case B — Ambiguous / Suspicious",
    expectedOutcome: "STEP_UP",
    description:
      "Elevated risk signals (new device, late-night timing, velocity, a failed attempt, and an amount well above this customer's seeded transaction history) on an established 640-day account. The Investigator finds real contradicting evidence (account tenure, zero chargebacks) — but not enough to fully clear it, so the Critic challenges toward STEP_UP rather than an outright BLOCK.",
    transaction: {
      transaction_id: "TXN_DEMO_B",
      customer_id: "CUST_DEMO_B",
      amount_inr: 32400,
      payment_method: "card",
      hour_of_day: 2,
      velocity_1h: 2,
      velocity_24h: 4,
      new_device: true,
      geo_mismatch: false,
      billing_shipping_mismatch: false,
      failed_attempts_prior: 1,
      account_age_days: 640,
      prior_successful_txns: 34,
      prior_chargebacks: 0,
      known_device_count: 2,
    },
  },
  {
    id: "legitimate",
    label: "Case C — Legitimate",
    expectedOutcome: "ALLOW",
    description:
      "Normal transaction amount and timing, established account, no mismatch signals. The Investigator finds the amount is consistent with this customer's seeded transaction history — real contradicting evidence, not asserted.",
    transaction: {
      transaction_id: "TXN_DEMO_C",
      customer_id: "CUST_DEMO_C",
      amount_inr: 2200,
      payment_method: "upi",
      hour_of_day: 11,
      velocity_1h: 0,
      velocity_24h: 1,
      new_device: false,
      geo_mismatch: false,
      billing_shipping_mismatch: false,
      failed_attempts_prior: 0,
      account_age_days: 410,
      prior_successful_txns: 22,
      prior_chargebacks: 0,
      known_device_count: 2,
    },
  },
];
