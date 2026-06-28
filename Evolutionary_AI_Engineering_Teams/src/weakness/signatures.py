from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Known mechanism constants — match docs/12_weakness_mining.md
class Mechanism:
    MISSING_REQUIRED_ARTIFACT = "missing_required_artifact"
    REPEATED_FAILED_TOOL_CALL = "repeated_failed_tool_call"
    UNVERIFIED_COMPLETION = "unverified_completion"
    EXCESSIVE_EXPLORATION = "excessive_exploration"
    WEAK_REQUIREMENTS_GROUNDING = "weak_requirements_grounding"
    POOR_HANDOFF = "poor_handoff"
    WRONG_TOOL_PERMISSION = "wrong_tool_permission"
    LATE_TESTING = "late_testing"
    OVERSIZED_PATCH = "oversized_patch"
    REDUNDANT_AGENT = "redundant_agent"


@dataclass
class FailureSignature:
    verifier_cause: str
    agent_behavior: str
    mechanism: str
    agent_id: Optional[str] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "verifier_cause": self.verifier_cause,
            "agent_behavior": self.agent_behavior,
            "mechanism": self.mechanism,
            "agent_id": self.agent_id,
            "detail": self.detail,
        }

    def signature_key(self) -> str:
        """Stable key for exact-match clustering."""
        return f"{self.verifier_cause}|{self.agent_behavior}|{self.mechanism}"
