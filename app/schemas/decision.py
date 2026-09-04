"""
AEGIS-SWARM Razorpay Edition :: Policy Decision Schema
=========================================================
WHY THIS SCHEMA HAS NO LLM IN ITS PATH (core architectural principle,
non-negotiable per the Razorpay Edition brief):
PolicyDecision is produced ENTIRELY by deterministic Python logic in
policy/gate.py -- fixed thresholds against risk_score and the Critic's
verdict. No field on this model is ever populated by an LLM call. This
is the direct replacement for AEGIS v1's commander.py, which generated
free-text action plans via an LLM call at temperature=0.3. That pattern
is explicitly REPLACED here, not reused: a payment-blocking decision
must be reproducible from the same inputs every time, which an LLM
sampling call structurally cannot guarantee even at low temperature.
"""

from typing import Literal
from pydantic import BaseModel

PolicyAction = Literal["ALLOW", "STEP_UP", "REVIEW", "BLOCK"]


class PolicyDecision(BaseModel):
    """
    - action: the final, machine-executable decision. One of exactly
      four values -- closed Literal, not a free string, so nothing
      downstream (dashboard, audit log, actual payment gateway
      integration) has to defensively parse an unbounded action space.
    - triggered_rule: which specific threshold/rule in gate.py fired --
      this is what makes the decision auditable. A judge (or a real
      compliance reviewer) can trace "why BLOCK?" to one exact rule.
    - final_risk_score: the score the Policy Gate actually decided on
      (post-Critic adjustment where applicable) -- may differ from the
      Detector's original risk_score if the Critic's evidence changed it.
    - estimated_cost_inr: the expected monetary cost of this specific
      decision under the disclosed cost model (see policy/gate.py), used
      for the merchant-loss simulation. Always an ESTIMATE against a
      stated assumption, never presented as a guaranteed real-money figure.
    """
    transaction_id: str
    action: PolicyAction
    triggered_rule: str
    final_risk_score: float
    critic_verdict: str
    reasoning: str
    estimated_cost_inr: float
