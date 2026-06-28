from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.ir.schema import Agent, OrganizationHarness, Phase
from src.runtime.events import EventType, TraceEvent
from src.runtime.mock_agents import run_mock_agent
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.observability.bus import EventBus


AgentRunner = Callable[[Agent], Dict[str, Any]]


@dataclass
class RunResult:
    run_id: str
    harness_id: str
    harness_version: int
    success: bool
    events: List[TraceEvent] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    shared_memory: Dict[str, Any] = field(default_factory=dict)
    agent_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_tool_calls: int = 0
    elapsed_seconds: float = 0.0
    stop_reason: str = "completed"


class RuntimeExecutor:
    """Executes an Organization Harness IR phase by phase.

    agent_runner: injectable so tests or Gemini integration can swap in a
    real agent implementation without changing this class.
    """

    def __init__(
        self,
        agent_runner: AgentRunner = run_mock_agent,
        event_bus: Optional["EventBus"] = None,
    ):
        self._agent_runner = agent_runner
        self._bus = event_bus

    def _emit(self, event_type: str, generation: int = 0, **data) -> None:
        if self._bus is None:
            return
        from src.observability.events import PipelineEvent
        self._bus.publish(PipelineEvent(type=event_type, generation=generation, data=data))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, harness: OrganizationHarness, generation: int = 0) -> RunResult:
        run_id = str(uuid.uuid4())
        start = time.monotonic()

        # Let stateful runners (e.g. the Gemini tool runner) reset per-run state
        # such as shared memory and the tool sandbox. Plain-function runners
        # (the mock) have no new_run attribute, so this is a no-op for them.
        getattr(self._agent_runner, "new_run", lambda: None)()

        result = RunResult(
            run_id=run_id,
            harness_id=harness.organization.id,
            harness_version=harness.organization.version,
            success=False,
        )

        result.events.append(TraceEvent(EventType.run_started, data={"run_id": run_id}))

        for phase in harness.execution.phases:
            stop = self._run_phase(phase, harness, result, start, generation=generation)
            if stop:
                result.stop_reason = stop
                break
        else:
            result.success = True
            result.stop_reason = "completed"

        result.elapsed_seconds = time.monotonic() - start

        # Store the full trace as a named artifact so weakness mining and
        # evaluators can find it under harness.task.artifacts_expected.
        trace_artifact = [
            {
                "event_type": e.event_type.value,
                "agent_id": e.agent_id,
                "phase": e.phase,
                "elapsed_seconds": e.elapsed_seconds,
            }
            for e in result.events
        ]
        result.artifacts["execution_trace"] = trace_artifact
        if harness.communication.shared_memory.enabled:
            result.shared_memory["execution_trace"] = trace_artifact

        result.events.append(
            TraceEvent(
                EventType.run_finished,
                elapsed_seconds=result.elapsed_seconds,
                data={
                    "run_id": run_id,
                    "success": result.success,
                    "stop_reason": result.stop_reason,
                    "total_tool_calls": result.total_tool_calls,
                },
            )
        )
        self._emit(
            "run_complete",
            generation=generation,
            success=result.success,
            total_tool_calls=result.total_tool_calls,
            elapsed=result.elapsed_seconds,
        )
        return result

    # ------------------------------------------------------------------
    # Phase execution
    # ------------------------------------------------------------------

    def _run_phase(
        self,
        phase: Phase,
        harness: OrganizationHarness,
        result: RunResult,
        run_start: float,
        generation: int = 0,
    ) -> Optional[str]:
        """Run one phase. Returns a stop_reason string if execution should halt, else None."""
        elapsed = time.monotonic() - run_start
        result.events.append(
            TraceEvent(
                EventType.phase_started,
                phase=phase.name,
                elapsed_seconds=elapsed,
                data={"agents": phase.agents},
            )
        )
        self._emit("phase_start", generation=generation, phase=phase.name, agents=phase.agents)

        # Check runtime budget
        policies = harness.runtime_policies
        max_rt = harness.evaluation.validation_gate.max_runtime_seconds
        if elapsed > max_rt:
            return "max_runtime_reached"

        agents = [harness.agent_by_id(aid) for aid in phase.agents]

        if phase.parallel and len(agents) > 1:
            stop = self._run_parallel(agents, phase.name, harness, result, run_start, generation=generation)
        else:
            stop = self._run_sequential(agents, phase.name, harness, result, run_start, policies, generation=generation)

        elapsed = time.monotonic() - run_start
        result.events.append(
            TraceEvent(
                EventType.phase_finished,
                phase=phase.name,
                elapsed_seconds=elapsed,
            )
        )
        self._emit("phase_finish", generation=generation, phase=phase.name)
        return stop

    def _run_sequential(
        self,
        agents: List[Agent],
        phase_name: str,
        harness: OrganizationHarness,
        result: RunResult,
        run_start: float,
        policies,
        generation: int = 0,
    ) -> Optional[str]:
        for agent in agents:
            stop = self._run_agent(agent, phase_name, harness, result, run_start, generation=generation)
            if stop:
                return stop
            # Check tool call policy
            if result.total_tool_calls >= policies.max_tool_calls_before_reflection:
                result.events.append(
                    TraceEvent(
                        EventType.tool_called,
                        agent_id=agent.id,
                        phase=phase_name,
                        data={"note": "reflection_threshold_hit"},
                    )
                )
        return None

    def _run_parallel(
        self,
        agents: List[Agent],
        phase_name: str,
        harness: OrganizationHarness,
        result: RunResult,
        run_start: float,
        generation: int = 0,
    ) -> Optional[str]:
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futures = {
                pool.submit(self._run_agent, agent, phase_name, harness, result, run_start, generation): agent
                for agent in agents
            }
            for fut in as_completed(futures):
                stop = fut.result()
                if stop:
                    return stop
        return None

    # ------------------------------------------------------------------
    # Single-agent execution
    # ------------------------------------------------------------------

    def _run_agent(
        self,
        agent: Agent,
        phase_name: str,
        harness: OrganizationHarness,
        result: RunResult,
        run_start: float,
        generation: int = 0,
    ) -> Optional[str]:
        elapsed = time.monotonic() - run_start
        result.events.append(
            TraceEvent(
                EventType.agent_started,
                agent_id=agent.id,
                phase=phase_name,
                elapsed_seconds=elapsed,
            )
        )
        self._emit(
            "agent_start",
            generation=generation,
            agent_id=agent.id,
            agent_name=agent.name,
            role=agent.role,
            phase=phase_name,
        )

        agent_start_time = time.monotonic()

        # Callback invoked after each tool — emits SSE events in real-time
        # so the browser sees one tool at a time rather than a burst.
        _inline_emitted: List[str] = []

        def _on_tool(tool_name: str, success: bool) -> None:
            evt_type = EventType.tool_error if not success else EventType.tool_called
            result.events.append(
                TraceEvent(
                    evt_type,
                    agent_id=agent.id,
                    phase=phase_name,
                    elapsed_seconds=time.monotonic() - run_start,
                    data={"tool": tool_name},
                )
            )
            self._emit(
                "agent_tool_call",
                generation=generation,
                agent_id=agent.id,
                tool=tool_name,
                success=success,
            )
            _inline_emitted.append(tool_name)

        try:
            agent_result = self._agent_runner(agent, on_tool_call=_on_tool)
        except TypeError:
            # Gemini runner or other runners that don't accept on_tool_call
            agent_result = self._agent_runner(agent)

        result.agent_results[agent.id] = agent_result

        # Only emit tool call events if they weren't already emitted inline.
        if not _inline_emitted:
            for tc in agent_result.get("tool_calls", []):
                evt_type = EventType.tool_error if "error" in tc.get("result", {}) else EventType.tool_called
                result.events.append(
                    TraceEvent(
                        evt_type,
                        agent_id=agent.id,
                        phase=phase_name,
                        elapsed_seconds=time.monotonic() - run_start,
                        data=tc,
                    )
                )
                self._emit(
                    "agent_tool_call",
                    generation=generation,
                    agent_id=agent.id,
                    tool=tc.get("tool_name", tc.get("tool", "unknown")),
                    success="error" not in tc.get("result", {}),
                )
        result.total_tool_calls += agent_result.get("tool_call_count", 0)

        # Merge artifacts into shared memory
        artifacts_produced = []
        for key, val in agent_result.get("artifacts", {}).items():
            result.artifacts[key] = val
            if harness.communication.shared_memory.enabled:
                result.shared_memory[key] = val
            artifacts_produced.append(key)
            result.events.append(
                TraceEvent(
                    EventType.artifact_created,
                    agent_id=agent.id,
                    phase=phase_name,
                    elapsed_seconds=time.monotonic() - run_start,
                    data={"artifact": key},
                )
            )

        # Check required artifacts before finish
        policies = harness.runtime_policies
        if policies.require_artifact_before_finish:
            missing = self._check_missing_artifacts(harness, result)
            if missing and phase_name == harness.execution.phases[-1].name:
                result.events.append(
                    TraceEvent(
                        EventType.agent_finished,
                        agent_id=agent.id,
                        phase=phase_name,
                        elapsed_seconds=time.monotonic() - run_start,
                        data={"warning": "missing_artifacts", "missing": missing},
                    )
                )

        elapsed = time.monotonic() - run_start
        agent_elapsed = time.monotonic() - agent_start_time
        result.events.append(
            TraceEvent(
                EventType.agent_finished,
                agent_id=agent.id,
                phase=phase_name,
                elapsed_seconds=elapsed,
                data={"success": agent_result.get("success", False)},
            )
        )
        self._emit(
            "agent_finish",
            generation=generation,
            agent_id=agent.id,
            success=agent_result.get("success", False),
            artifacts=artifacts_produced,
            elapsed=agent_elapsed,
        )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_missing_artifacts(
        self, harness: OrganizationHarness, result: RunResult
    ) -> List[str]:
        return [
            a for a in harness.task.artifacts_expected
            if a not in result.artifacts
        ]
