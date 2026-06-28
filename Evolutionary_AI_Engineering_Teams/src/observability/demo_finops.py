"""Scripted FinOps evolution demo.

Emits the SAME PipelineEvents a real run does, so it renders in the existing
Monitor view (log stream + agent cards + score) — but instantly and reliably,
for a recorded demo. Story:

  Generation 1: bq_agent + vm_agent + gke_agent  -> score 70 (Cloud SQL gap)
  -> user feedback "where's sql data" lands in eval_cases
  Generation 2: adds sql_agent                   -> score 85

Between generations it (optionally) waits until an eval case mentioning "sql"
exists, tying the scripted run to the real feedback the presenter types in the
Eval Dataset tab. Falls through after a timeout so it never hangs on camera.
"""
from __future__ import annotations

import time
from typing import Any, List, Optional

from src.observability.events import PipelineEvent

HARNESS_ID = "wf-finops-cost-optimizer"
OBJECTIVE = "Identify idle / over-provisioned GCP resources and estimate monthly savings"

# Per-agent step delay (keeps the log stream readable but quick on camera).
_STEP = 0.45

_GEN1_AGENTS = [
    {"id": "bq_agent", "name": "BigQuery Billing Analyst",
     "role": "Analyze the billing export to find the biggest cost drivers",
     "tools": ["bq_tool", "web_search"]},
    {"id": "vm_agent", "name": "Compute Engine Optimizer",
     "role": "Find idle / over-provisioned VM instances to rightsize",
     "tools": ["monitoring_tool", "compute_tool"]},
    {"id": "gke_agent", "name": "GKE Utilization Auditor",
     "role": "Find underutilized GKE clusters and node pools",
     "tools": ["monitoring_tool", "gke_tool"]},
]
_SQL_AGENT = {
    "id": "sql_agent", "name": "Cloud SQL Cost Analyst",
    "role": "Find idle / over-provisioned Cloud SQL instances",
    "tools": ["sql_tool", "monitoring_tool"],
}


def _agent_brief(a: dict) -> dict:
    return {"id": a["id"], "name": a["name"], "role": a["role"]}


def _snapshot_agents(agents: List[dict]) -> List[dict]:
    return [{
        "id": a["id"], "name": a["name"], "role": a["role"],
        "prompt": f"You are the {a['name']}. {a['role']}.",
        "tools": a["tools"], "model": "gemini-3.5-flash",
        "budget": {"max_tool_calls": 6}, "phase": "analyze",
    } for a in agents]


def play_finops_demo(bus, tracker=None, store=None, wait_for_sql: bool = True) -> None:
    """Emit the scripted two-generation FinOps run through `bus`."""

    def emit(etype: str, generation: int = 0, **data):
        bus.publish(PipelineEvent(type=etype, generation=generation, data=data))

    def run_agents(agents: List[dict], generation: int):
        total_calls = 0
        for a in agents:
            emit("agent_start", generation, agent_id=a["id"],
                 agent_name=a["name"], role=a["role"])
            time.sleep(_STEP)
            for tool in a["tools"]:
                emit("agent_tool_call", generation, agent_id=a["id"],
                     agent_name=a["name"], tool=tool)
                total_calls += 1
                time.sleep(_STEP)
            emit("agent_finish", generation, agent_id=a["id"],
                 agent_name=a["name"], success=True,
                 artifacts=[f"{a['id']}_findings"])
            time.sleep(_STEP * 0.5)
        emit("run_complete", generation, total_tool_calls=total_calls, elapsed=round(total_calls * 0.4, 1))

    if tracker is not None:
        try:
            tracker.reset(task=OBJECTIVE, max_generations=2)
        except Exception:
            pass

    # ── Evolution start ────────────────────────────────────────
    emit("evolution_start", 0, harness_id=HARNESS_ID, objective=OBJECTIVE,
         max_generations=2, agents=[_agent_brief(a) for a in _GEN1_AGENTS])
    time.sleep(_STEP)

    # ── Generation 1: 3 agents, score 70, Cloud SQL gap ────────
    emit("generation_start", 1, harness_id=HARNESS_ID,
         agents=[_agent_brief(a) for a in _GEN1_AGENTS])
    time.sleep(_STEP)
    run_agents(_GEN1_AGENTS, 1)
    emit("evaluation_complete", 1, score=70.0, passed=False, threshold=85.0,
         metrics={"cost_findings": 40.0, "savings_accuracy": 30.0, "coverage": 0.0})
    time.sleep(_STEP)
    emit("weakness_mined", 1, count=1, signatures=[{
        "mechanism": "missing_capability",
        "agent_behavior": "No agent inspects Cloud SQL spend — SQL costs unaccounted for",
    }])
    time.sleep(_STEP)
    emit("generation_finish", 1, score=70.0, accepted_candidate=HARNESS_ID)
    emit("harness_snapshot", 1, harness_id=HARNESS_ID,
         agents=_snapshot_agents(_GEN1_AGENTS),
         phases=[{"name": "analyze", "agents": [a["id"] for a in _GEN1_AGENTS]}],
         edges=[])
    time.sleep(_STEP)

    # ── Wait for the real "sql" feedback (ties to the eval tab) ─
    if wait_for_sql and store is not None:
        for _ in range(45):  # ~90s max, then proceed anyway
            try:
                cases = store.list_eval_cases()
                if any("sql" in ((c.get("input") or "") + " " + (c.get("feedback") or "")).lower()
                       for c in cases):
                    break
            except Exception:
                pass
            time.sleep(2)

    # ── Generation 2: add sql_agent (from feedback), score 85 ──
    gen2_agents = _GEN1_AGENTS + [_SQL_AGENT]
    emit("mutation_proposed", 2, index=1, total=1, mutation_type="add_agent",
         effect="Add sql_agent to cover Cloud SQL costs (driven by user feedback: \"where's sql data\")")
    time.sleep(_STEP)
    emit("gate_decision", 2, mutation_type="add_agent", accepted=True,
         reason="judged score improves 70 -> 85; Cloud SQL coverage gap closed")
    time.sleep(_STEP)
    emit("generation_start", 2, harness_id=HARNESS_ID,
         agents=[_agent_brief(a) for a in gen2_agents])
    time.sleep(_STEP)
    run_agents(gen2_agents, 2)
    emit("evaluation_complete", 2, score=85.0, passed=True, threshold=85.0,
         metrics={"cost_findings": 40.0, "savings_accuracy": 30.0, "coverage": 15.0})
    time.sleep(_STEP)
    emit("weakness_mined", 2, count=0, signatures=[])
    emit("generation_finish", 2, score=85.0, accepted_candidate=HARNESS_ID)
    emit("harness_snapshot", 2, harness_id=HARNESS_ID,
         agents=_snapshot_agents(gen2_agents),
         phases=[{"name": "analyze", "agents": [a["id"] for a in gen2_agents]}],
         edges=[])
    time.sleep(_STEP)
    emit("evolution_complete", 2, generations=2, initial_score=70.0, final_score=85.0)
