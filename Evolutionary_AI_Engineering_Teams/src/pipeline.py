from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from src.ir.loader import load_harness
from src.ir.schema import OrganizationHarness
from src.runtime.executor import RuntimeExecutor, RunResult
from src.runtime.mock_agents import run_mock_agent
from src.evaluation.scorer import score_run, EvaluationResult
from src.evaluation.gate import apply_validation_gate, GateDecision
from src.weakness.miner import mine_weaknesses
from src.weakness.signatures import FailureSignature
from src.evolution.engine import propose_mutations
from src.evolution.proposals import MutationProposal
from src.memory.store import MongoMemoryStore
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.observability.bus import EventBus


@dataclass
class CycleResult:
    harness: OrganizationHarness
    run: RunResult
    evaluation: EvaluationResult
    signatures: List[FailureSignature]
    proposals: List[Tuple[MutationProposal, OrganizationHarness]] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    accepted_candidate: Optional[OrganizationHarness] = None


class EvolutionPipeline:
    """Ties together the full harness evolution loop.

    Usage:
        pipeline = EvolutionPipeline(store)
        result = pipeline.run_cycle(harness)          # run + evaluate + mine + propose
        next_harness = result.accepted_candidate      # best mutation, if any accepted

    Pass agent_runner=make_gemini_runner(client) to use real Gemini agents
    instead of the built-in mock.
    """

    def __init__(
        self,
        store: MongoMemoryStore,
        parent_evaluation: Optional[EvaluationResult] = None,
        agent_runner=None,
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self._store = store
        self._parent_evaluation = parent_evaluation
        self._bus = event_bus
        self._executor = RuntimeExecutor(
            agent_runner=agent_runner or run_mock_agent,
            event_bus=event_bus,
        )

    def _emit(self, event_type: str, generation: int = 0, **data) -> None:
        if self._bus is None:
            return
        from src.observability.events import PipelineEvent
        self._bus.publish(PipelineEvent(type=event_type, generation=generation, data=data))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_cycle(self, harness: OrganizationHarness, generation: int = 1) -> CycleResult:
        """Execute one full evolution cycle for the given harness."""
        # 1. Persist harness
        self._store.save_organization(harness)

        # 2. Run
        run = self._executor.run(harness, generation=generation)
        self._store.save_run(run)

        # 3. Evaluate
        ev = score_run(run, harness.evaluation)
        self._store.save_evaluation(ev)
        self._emit(
            "evaluation_complete",
            generation=generation,
            score=ev.total_score,
            passed=ev.passed_threshold,
            threshold=ev.success_threshold,
            metrics=ev.metric_scores,
        )

        # 4. Weakness mining
        sigs = mine_weaknesses(run, ev, harness)
        self._store.save_lesson(
            harness.organization.id,
            run.run_id,
            [s.to_dict() for s in sigs],
            accepted=ev.passed_threshold,
        )
        self._emit(
            "weakness_mined",
            generation=generation,
            count=len(sigs),
            signatures=[{"mechanism": s.mechanism, "agent_behavior": s.agent_behavior} for s in sigs],
        )

        # 5. Propose mutations
        proposals = propose_mutations(harness, sigs)

        # 6. Gate each candidate
        gate_decisions: List[GateDecision] = []
        accepted_candidate: Optional[OrganizationHarness] = None

        for i, (proposal, candidate) in enumerate(proposals, start=1):
            self._emit(
                "mutation_proposed",
                generation=generation,
                index=i,
                total=len(proposals),
                mutation_type=proposal.mutation_type,
                effect=proposal.expected_effect,
            )

            # Run the candidate to get a real evaluation
            cand_run = self._executor.run(candidate, generation=generation)
            cand_ev = score_run(cand_run, candidate.evaluation)

            decision = apply_validation_gate(
                cand_ev,
                parent=ev,
                gate=harness.evaluation.validation_gate,
            )
            proposal.validation_result = "accepted" if decision.accepted else "rejected"

            self._emit(
                "gate_decision",
                generation=generation,
                mutation_type=proposal.mutation_type,
                accepted=decision.accepted,
                reason=decision.reason,
            )

            self._store.save_mutation(
                run_id=cand_run.run_id,
                harness_id=candidate.organization.id,
                harness_version=candidate.organization.version,
                decision=decision,
                parent_run_id=run.run_id,
            )
            gate_decisions.append(decision)

            if decision.accepted and accepted_candidate is None:
                # Persist the winning candidate and its run
                self._store.save_organization(candidate)
                self._store.save_run(cand_run)
                self._store.save_evaluation(cand_ev)
                accepted_candidate = candidate

        return CycleResult(
            harness=harness,
            run=run,
            evaluation=ev,
            signatures=sigs,
            proposals=proposals,
            gate_decisions=gate_decisions,
            accepted_candidate=accepted_candidate,
        )

    def run_evolution(
        self,
        harness: OrganizationHarness,
        max_generations: int = 3,
        stop_event: Optional[Any] = None,
    ) -> List[CycleResult]:
        """Run up to `max_generations` evolution cycles, chaining accepted candidates."""
        self._emit(
            "evolution_start",
            generation=0,
            harness_id=harness.organization.id,
            objective=harness.organization.objective,
            max_generations=max_generations,
            agents=[{"id": a.id, "name": a.name, "role": a.role} for a in harness.agents],
        )

        results: List[CycleResult] = []
        current = harness
        initial_score: Optional[float] = None

        for gen in range(1, max_generations + 1):
            if stop_event is not None and stop_event.is_set():
                break
            self._emit(
                "generation_start",
                generation=gen,
                harness_id=current.organization.id,
                agents=[{"id": a.id, "name": a.name, "role": a.role} for a in current.agents],
            )

            result = self.run_cycle(current, generation=gen)
            results.append(result)

            if initial_score is None:
                initial_score = result.evaluation.total_score

            self._emit(
                "generation_finish",
                generation=gen,
                score=result.evaluation.total_score,
                accepted_candidate=(
                    result.accepted_candidate.organization.id
                    if result.accepted_candidate else None
                ),
            )

            # Emit full harness snapshot so UI can display topology and agent details.
            snap_harness = result.accepted_candidate if result.accepted_candidate else current
            self._emit(
                "harness_snapshot",
                generation=gen,
                harness_id=snap_harness.organization.id,
                agents=[{
                    "id": a.id,
                    "name": a.name,
                    "role": a.role,
                    "prompt": a.prompt,
                    "tools": a.tools,
                    "model": a.model,
                    "budget": {"max_tool_calls": a.budget.max_tool_calls},
                    "phase": next(
                        (p.name for p in snap_harness.execution.phases if a.id in p.agents),
                        "",
                    ),
                } for a in snap_harness.agents],
                phases=[
                    {"name": p.name, "agents": list(p.agents)}
                    for p in snap_harness.execution.phases
                ],
                edges=[{
                    "from": e.from_agent,
                    "to": e.to,
                    "type": e.type.value if hasattr(e.type, "value") else str(e.type),
                } for e in snap_harness.communication.edges],
            )

            # Advance to the accepted candidate if one was found; otherwise
            # continue with the same harness so the user sees all N generations.
            if result.accepted_candidate is not None:
                current = result.accepted_candidate

        final_score = results[-1].evaluation.total_score if results else 0.0
        self._emit(
            "evolution_complete",
            generation=len(results),
            generations=len(results),
            initial_score=initial_score or 0.0,
            final_score=final_score,
        )

        return results
