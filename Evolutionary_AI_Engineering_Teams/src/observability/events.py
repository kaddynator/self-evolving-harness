from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Event type constants — used as `event.type` strings
# ---------------------------------------------------------------------------

class E:
    EVOLUTION_START     = "evolution_start"
    EVOLUTION_COMPLETE  = "evolution_complete"
    GENERATION_START    = "generation_start"
    GENERATION_FINISH   = "generation_finish"
    PHASE_START         = "phase_start"
    PHASE_FINISH        = "phase_finish"
    AGENT_START         = "agent_start"
    AGENT_TOOL_CALL     = "agent_tool_call"
    AGENT_FINISH        = "agent_finish"
    RUN_COMPLETE        = "run_complete"
    EVALUATION_COMPLETE = "evaluation_complete"
    WEAKNESS_MINED      = "weakness_mined"
    MUTATION_PROPOSED   = "mutation_proposed"
    GATE_DECISION       = "gate_decision"


@dataclass
class PipelineEvent:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    generation: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "generation": self.generation,
            "timestamp": self.timestamp,
            "data": self.data,
        }
