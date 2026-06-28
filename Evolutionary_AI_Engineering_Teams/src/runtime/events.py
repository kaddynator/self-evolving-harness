from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    agent_started = "agent_started"
    agent_finished = "agent_finished"
    tool_called = "tool_called"
    tool_error = "tool_error"
    artifact_created = "artifact_created"
    tests_run = "tests_run"
    evaluation_completed = "evaluation_completed"
    weakness_mined = "weakness_mined"
    mutation_proposed = "mutation_proposed"
    mutation_validated = "mutation_validated"
    mutation_applied = "mutation_applied"
    phase_started = "phase_started"
    phase_finished = "phase_finished"
    run_started = "run_started"
    run_finished = "run_finished"


@dataclass
class TraceEvent:
    event_type: EventType
    agent_id: Optional[str] = None
    phase: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    # wall-clock seconds from run start; set by executor
    elapsed_seconds: float = 0.0
