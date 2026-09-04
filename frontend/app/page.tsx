"use client";

import { useState, useEffect } from "react";
import { PipelineResponse, EvaluationReport, PolicyAction, RiskLevel } from "./types";
import { DEMO_CASES, DemoCase } from "./demoCases";

// Backend URL -- NOT hardcoded to any HuggingFace/Vercel URL the way
// AEGIS v1's frontend was. Set NEXT_PUBLIC_API_URL as an env var at
// build/deploy time (Vercel project settings, or a local .env.local).
// Falls back to localhost:8000 for local dev against `uvicorn app.main:app`.
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const ACTION_COLORS: Record<PolicyAction, string> = {
  ALLOW: "#3fb950",
  STEP_UP: "#d29922",
  REVIEW: "#58a6ff",
  BLOCK: "#f85149",
};

const RISK_COLORS: Record<RiskLevel, string> = {
  LOW: "#3fb950",
  MEDIUM: "#d29922",
  HIGH: "#f0883e",
  CRITICAL: "#f85149",
};

type ViewMode = "console" | "evaluation";

export default function Home() {
  const [view, setView] = useState<ViewMode>("console");
  const [selectedCase, setSelectedCase] = useState<DemoCase>(DEMO_CASES[0]);
  const [result, setResult] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evalReport, setEvalReport] = useState<EvaluationReport | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);

  async function runCase(demoCase: DemoCase) {
    setSelectedCase(demoCase);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(demoCase.transaction),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed with status ${res.status}`);
      }
      const data: PipelineResponse = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error contacting the backend.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (view !== "evaluation" || evalReport) return;
    fetch(`${API_URL}/api/evaluation`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || "Evaluation report not available yet.");
        }
        return res.json();
      })
      .then((data: EvaluationReport) => setEvalReport(data))
      .catch((e) => setEvalError(e instanceof Error ? e.message : "Failed to load evaluation report."));
  }, [view, evalReport]);

  return (
    <div className="min-h-screen flex flex-col">
      <Header view={view} setView={setView} />
      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-8">
        {view === "console" ? (
          <ConsoleView
            selectedCase={selectedCase}
            onRunCase={runCase}
            loading={loading}
            error={error}
            result={result}
          />
        ) : (
          <EvaluationView report={evalReport} error={evalError} />
        )}
      </main>
      <Footer />
    </div>
  );
}

function Header({ view, setView }: { view: ViewMode; setView: (v: ViewMode) => void }) {
  return (
    <header className="border-b border-[var(--border)] bg-[var(--panel)]">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight">AEGIS-SWARM <span className="text-[var(--text-dim)] font-normal">| Risk Operations Console</span></h1>
          <p className="text-xs text-[var(--text-dim)] mt-0.5">Evidence-gated AI risk engine — Razorpay Edition</p>
        </div>
        <nav className="flex gap-2 text-sm">
          <button
            onClick={() => setView("console")}
            className={`px-3 py-1.5 rounded border ${view === "console" ? "border-blue-500 text-blue-400 bg-blue-500/10" : "border-[var(--border)] text-[var(--text-dim)]"}`}
          >
            Console
          </button>
          <button
            onClick={() => setView("evaluation")}
            className={`px-3 py-1.5 rounded border ${view === "evaluation" ? "border-blue-500 text-blue-400 bg-blue-500/10" : "border-[var(--border)] text-[var(--text-dim)]"}`}
          >
            Evaluation
          </button>
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[var(--border)] py-4 text-center text-xs text-[var(--text-dim)]">
      AEGIS-SWARM — Razorpay Edition. Synthetic dataset, disclosed cost-model assumptions. Not a production fraud system.
    </footer>
  );
}

function ConsoleView({
  selectedCase,
  onRunCase,
  loading,
  error,
  result,
}: {
  selectedCase: DemoCase;
  onRunCase: (c: DemoCase) => void;
  loading: boolean;
  error: string | null;
  result: PipelineResponse | null;
}) {
  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-semibold text-[var(--text-dim)] uppercase tracking-wide mb-3">
          Demo Transactions
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {DEMO_CASES.map((c) => (
            <button
              key={c.id}
              onClick={() => onRunCase(c)}
              className={`text-left p-4 rounded-lg border transition ${
                selectedCase.id === c.id ? "border-blue-500 bg-blue-500/5" : "border-[var(--border)] bg-[var(--panel)] hover:border-[var(--text-dim)]"
              }`}
            >
              <div className="text-sm font-semibold">{c.label}</div>
              <div className="text-xs text-[var(--text-dim)] mt-1">Expected: {c.expectedOutcome}</div>
              <div className="text-xs text-[var(--text-dim)] mt-2 leading-relaxed">{c.description}</div>
              <div className="text-xs mt-2 font-mono text-[var(--text-dim)]">
                ₹{c.transaction.amount_inr.toLocaleString("en-IN")} · {c.transaction.payment_method}
              </div>
            </button>
          ))}
        </div>
      </section>

      {loading && (
        <div className="text-sm text-[var(--text-dim)] py-8 text-center">
          Running Detector → Investigator → Critic → Policy Gate...
        </div>
      )}

      {error && (
        <div className="p-4 rounded-lg border border-red-800 bg-red-950/30 text-sm text-red-300">
          <div className="font-semibold mb-1">Backend request failed</div>
          <div>{error}</div>
          <div className="text-xs text-[var(--text-dim)] mt-2">
            Make sure the backend is running at {API_URL} and GEMINI_API_KEY is configured server-side.
          </div>
        </div>
      )}

      {result && !loading && <PipelineTrail result={result} />}
    </div>
  );
}

function PipelineTrail({ result }: { result: PipelineResponse }) {
  const { transaction, detector, evidence, critic, decision } = result;

  return (
    <div className="space-y-4">
      {/* Transaction summary bar */}
      <div className="flex items-center justify-between p-4 rounded-lg border border-[var(--border)] bg-[var(--panel)]">
        <div>
          <div className="text-xs text-[var(--text-dim)]">Transaction</div>
          <div className="font-semibold">{transaction.transaction_id}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-dim)]">Amount</div>
          <div className="font-semibold">₹{transaction.amount_inr.toLocaleString("en-IN")}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-dim)]">Risk Score</div>
          <div className="font-semibold">{decision.final_risk_score.toFixed(3)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-dim)]">Decision</div>
          <div className="font-bold text-lg" style={{ color: ACTION_COLORS[decision.action] }}>
            {decision.action.replace("_", "-")}
          </div>
        </div>
      </div>

      {/* Stage 1: Detector */}
      <StageCard title="1 · DETECTOR" subtitle={`ML baseline (${detector.model_source}) + explanation`}>
        <div className="flex items-center gap-3 mb-3">
          <span
            className="px-2 py-0.5 rounded text-xs font-bold"
            style={{ backgroundColor: RISK_COLORS[detector.risk_level] + "22", color: RISK_COLORS[detector.risk_level] }}
          >
            {detector.risk_level}
          </span>
          <span className="text-sm text-[var(--text-dim)]">score {detector.risk_score.toFixed(3)}</span>
        </div>
        <p className="text-sm mb-2">{detector.fraud_hypothesis}</p>
        <ul className="text-xs text-[var(--text-dim)] space-y-1">
          {detector.signals.map((s, i) => (
            <li key={i}>• {s}</li>
          ))}
        </ul>
      </StageCard>

      {/* Stage 2: Investigator / Evidence */}
      <StageCard title="2 · INVESTIGATOR" subtitle="Real evidence retrieved via MCP (customer/device/velocity/chargeback history)">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-xs">
          <EvidenceStat label="Account Age" value={`${evidence.account_age_days}d`} />
          <EvidenceStat label="Prior Successes" value={String(evidence.prior_successful_txns)} />
          <EvidenceStat label="Chargebacks" value={String(evidence.prior_chargebacks)} />
          <EvidenceStat label="Known Devices" value={String(evidence.known_device_count)} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="text-xs font-semibold text-[#f85149] mb-1">Supporting fraud hypothesis</div>
            <ul className="text-xs text-[var(--text-dim)] space-y-1">
              {evidence.supporting_fraud_signals.map((s, i) => (
                <li key={i}>+ {s}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-xs font-semibold text-[#3fb950] mb-1">Contradicting fraud hypothesis</div>
            <ul className="text-xs text-[var(--text-dim)] space-y-1">
              {evidence.contradicting_fraud_signals.map((s, i) => (
                <li key={i}>− {s}</li>
              ))}
            </ul>
          </div>
        </div>
      </StageCard>

      {/* Stage 3: Adversarial Critic */}
      <StageCard title="3 · ADVERSARIAL CRITIC" subtitle="Actively attempts to disprove the Detector's hypothesis">
        <div className="flex items-center gap-3 mb-3">
          <span
            className={`px-2 py-0.5 rounded text-xs font-bold ${
              critic.verdict === "CHALLENGE" ? "bg-yellow-500/20 text-yellow-400" :
              critic.verdict === "CONFIRM" ? "bg-red-500/20 text-red-400" :
              "bg-blue-500/20 text-blue-400"
            }`}
          >
            {critic.verdict}
          </span>
          <span className="text-sm text-[var(--text-dim)]">recommended: {critic.recommended_adjustment}</span>
        </div>
        <p className="text-sm">{critic.critic_reasoning}</p>
      </StageCard>

      {/* Stage 4: Policy Gate */}
      <StageCard title="4 · POLICY GATE" subtitle="Deterministic rule engine — no LLM in this decision">
        <div className="flex items-center gap-3 mb-2">
          <span
            className="px-3 py-1 rounded font-bold text-sm"
            style={{ backgroundColor: ACTION_COLORS[decision.action] + "22", color: ACTION_COLORS[decision.action] }}
          >
            {decision.action.replace("_", "-")}
          </span>
          <span className="text-xs font-mono text-[var(--text-dim)]">{decision.triggered_rule}</span>
        </div>
        <p className="text-sm text-[var(--text-dim)]">{decision.reasoning}</p>
      </StageCard>
    </div>
  );
}

function StageCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="p-4 rounded-lg border border-[var(--border)] bg-[var(--panel)]">
      <div className="mb-3">
        <div className="text-xs font-bold text-blue-400 tracking-wide">{title}</div>
        <div className="text-xs text-[var(--text-dim)]">{subtitle}</div>
      </div>
      {children}
    </div>
  );
}

function EvidenceStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 rounded border border-[var(--border)]">
      <div className="text-[var(--text-dim)]">{label}</div>
      <div className="font-semibold text-sm">{value}</div>
    </div>
  );
}

function EvaluationView({ report, error }: { report: EvaluationReport | null; error: string | null }) {
  if (error) {
    return (
      <div className="p-4 rounded-lg border border-red-800 bg-red-950/30 text-sm text-red-300">
        <div className="font-semibold mb-1">Evaluation report unavailable</div>
        <div>{error}</div>
        <div className="text-xs text-[var(--text-dim)] mt-2">
          Run <code>python -m app.services.evaluation</code> on the backend to generate it.
        </div>
      </div>
    );
  }

  if (!report) {
    return <div className="text-sm text-[var(--text-dim)] py-8 text-center">Loading evaluation report...</div>;
  }

  const { dataset_manifest, baseline_only, aegis_swarm_pipeline, recall_gap_analysis, model_backend } = report;

  return (
    <div className="space-y-6">
      <div className="p-4 rounded-lg border border-yellow-800 bg-yellow-950/20 text-xs text-yellow-200">
        <strong>Dataset disclosure:</strong> {dataset_manifest.n_transactions} synthetic transactions,
        measured fraud rate {(dataset_manifest.measured_fraud_rate * 100).toFixed(1)}% (elevated vs. real-world
        0.5–3% base rates, deliberately, so the held-out test set has enough fraud examples for stable metrics —
        see data/generate_dataset.py). {(dataset_manifest.label_noise_rate * 100).toFixed(0)}% label noise applied
        so results are not trivially perfect. Baseline model: <strong>{model_backend}</strong>.
      </div>

      <section>
        <h2 className="text-sm font-semibold text-[var(--text-dim)] uppercase tracking-wide mb-3">
          Baseline vs. AEGIS-SWARM — Held-Out Test Set (n={baseline_only.n_test})
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ComparisonCard
            title="Baseline Model Alone"
            subtitle={`${baseline_only.model_backend}, threshold ${baseline_only.threshold}`}
            precision={baseline_only.precision}
            recall={baseline_only.recall}
            f1={baseline_only.f1}
            rocAuc={baseline_only.roc_auc}
            cm={baseline_only.confusion_matrix}
            cost={baseline_only.cost_simulation.total_estimated_cost_inr}
          />
          <ComparisonCard
            title="AEGIS-SWARM Pipeline"
            subtitle={aegis_swarm_pipeline.system_label}
            precision={aegis_swarm_pipeline.binary_metrics_block_vs_rest.precision}
            recall={aegis_swarm_pipeline.binary_metrics_block_vs_rest.recall}
            f1={aegis_swarm_pipeline.binary_metrics_block_vs_rest.f1}
            rocAuc={null}
            cm={aegis_swarm_pipeline.binary_metrics_block_vs_rest.confusion_matrix}
            cost={aegis_swarm_pipeline.total_estimated_cost_inr}
            highlight
          />
        </div>
        <p className="text-xs text-[var(--text-dim)] mt-2">
          AEGIS-SWARM metrics here treat BLOCK as &quot;predicted fraud&quot; and ALLOW/STEP_UP/REVIEW as
          &quot;predicted not-fraud&quot; for binary comparison — see action distribution below for the full
          4-action breakdown, since STEP_UP/REVIEW are partial mitigations, not full misses.
        </p>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-[var(--text-dim)] uppercase tracking-wide mb-3">
          Action Distribution &amp; Cost by Action (AEGIS-SWARM)
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(Object.keys(aegis_swarm_pipeline.action_distribution) as PolicyAction[]).map((action) => (
            <div key={action} className="p-3 rounded-lg border border-[var(--border)] bg-[var(--panel)]">
              <div className="text-xs font-bold" style={{ color: ACTION_COLORS[action] }}>{action.replace("_", "-")}</div>
              <div className="text-2xl font-bold mt-1">{aegis_swarm_pipeline.action_distribution[action]}</div>
              <div className="text-xs text-[var(--text-dim)] mt-1">
                ₹{aegis_swarm_pipeline.cost_by_action_inr[action].toLocaleString("en-IN")} modeled cost
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-[var(--text-dim)] uppercase tracking-wide mb-3">
          Recall Gap Analysis — Root Cause
        </h2>
        <div className="p-4 rounded-lg border border-[var(--border)] bg-[var(--panel)] space-y-3 text-sm">
          <p>
            {recall_gap_analysis.total_missed_fraud_cases} fraud transactions in the test set were not BLOCKed.
          </p>
          <div className="p-3 rounded border border-[var(--border)]">
            <div className="font-semibold text-xs mb-1">
              {recall_gap_analysis.baseline_would_also_miss.count} — Baseline ML detection gap
            </div>
            <p className="text-xs text-[var(--text-dim)]">{recall_gap_analysis.baseline_would_also_miss.explanation}</p>
          </div>
          <div className="p-3 rounded border border-[var(--border)]">
            <div className="font-semibold text-xs mb-1">
              {recall_gap_analysis.critic_deescalated_a_baseline_catch.count} — Critic-driven de-escalation
              ({recall_gap_analysis.critic_deescalated_a_baseline_catch.to_step_up_partial_mitigation} to STEP-UP,{" "}
              {recall_gap_analysis.critic_deescalated_a_baseline_catch.to_allow_full_miss} to ALLOW)
            </div>
            <p className="text-xs text-[var(--text-dim)]">{recall_gap_analysis.critic_deescalated_a_baseline_catch.explanation}</p>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-[var(--text-dim)] uppercase tracking-wide mb-3">
          Cost Model Assumptions (stated, not measured)
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <EvidenceStat label="Fraud miss cost" value={`₹${aegis_swarm_pipeline.cost_model_assumptions.fraud_miss_cost_inr.toLocaleString("en-IN")}`} />
          <EvidenceStat label="False positive cost" value={`₹${aegis_swarm_pipeline.cost_model_assumptions.false_positive_cost_inr.toLocaleString("en-IN")}`} />
          <EvidenceStat label="Step-up friction cost" value={`₹${aegis_swarm_pipeline.cost_model_assumptions.step_up_friction_cost_inr.toLocaleString("en-IN")}`} />
          <EvidenceStat label="Review operational cost" value={`₹${aegis_swarm_pipeline.cost_model_assumptions.review_operational_cost_inr.toLocaleString("en-IN")}`} />
        </div>
      </section>
    </div>
  );
}

function ComparisonCard({
  title, subtitle, precision, recall, f1, rocAuc, cm, cost, highlight,
}: {
  title: string; subtitle: string; precision: number; recall: number; f1: number;
  rocAuc: number | null; cm: { tn: number; fp: number; fn: number; tp: number }; cost: number; highlight?: boolean;
}) {
  return (
    <div className={`p-4 rounded-lg border ${highlight ? "border-blue-500 bg-blue-500/5" : "border-[var(--border)] bg-[var(--panel)]"}`}>
      <div className="font-semibold text-sm">{title}</div>
      <div className="text-xs text-[var(--text-dim)] mb-3">{subtitle}</div>
      <div className="grid grid-cols-3 gap-2 text-center mb-3">
        <MetricBox label="Precision" value={precision} />
        <MetricBox label="Recall" value={recall} />
        <MetricBox label="F1" value={f1} />
      </div>
      {rocAuc !== null && (
        <div className="text-xs text-[var(--text-dim)] mb-2">ROC-AUC: {rocAuc.toFixed(3)}</div>
      )}
      <div className="text-xs text-[var(--text-dim)] mb-2">
        TP={cm.tp} · TN={cm.tn} · FP={cm.fp} · FN={cm.fn}
      </div>
      <div className="text-sm font-semibold">₹{cost.toLocaleString("en-IN")} modeled total cost</div>
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-2 rounded border border-[var(--border)]">
      <div className="text-[10px] text-[var(--text-dim)]">{label}</div>
      <div className="font-bold">{(value * 100).toFixed(1)}%</div>
    </div>
  );
}
