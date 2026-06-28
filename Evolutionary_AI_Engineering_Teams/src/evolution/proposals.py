from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MutationProposal:
    proposal_id: str
    parent_org_id: str
    candidate_org_id: str
    mutation_type: str
    target_failure_signature: str          # signature_key() of the driving failure
    changed_surfaces: List[str]
    expected_effect: str
    regression_risk: str
    rollback_plan: str
    validation_result: Optional[str] = None  # set after gate decision

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "parent_org_id": self.parent_org_id,
            "candidate_org_id": self.candidate_org_id,
            "mutation_type": self.mutation_type,
            "target_failure_signature": self.target_failure_signature,
            "changed_surfaces": self.changed_surfaces,
            "expected_effect": self.expected_effect,
            "regression_risk": self.regression_risk,
            "rollback_plan": self.rollback_plan,
            "validation_result": self.validation_result,
        }


def make_proposal_id() -> str:
    return f"proposal_{uuid.uuid4().hex[:8]}"
