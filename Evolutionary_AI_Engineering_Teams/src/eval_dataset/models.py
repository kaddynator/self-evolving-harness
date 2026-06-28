from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Case lifecycle
NEEDS_LABEL = "needs_label"
LABELED = "labeled"

# Where the case came from
SRC_PRODUCTION = "production_negative"
SRC_USER = "user_provided"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return "ec-" + uuid.uuid4().hex[:12]


@dataclass
class EvalCase:
    """One eval case in the dataset.

    A case captured from production starts with status=needs_label and a blank
    expected_output. A human (admin or the end user) fills expected_output, which
    flips it to labeled and makes it usable as a reference for grading/evolution.
    """

    agent_id: str
    input: str
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None
    status: str = NEEDS_LABEL
    source: str = SRC_PRODUCTION
    feedback: str = ""          # the negative-sentiment signal / customer comment
    sentiment: str = ""         # e.g. "negative"
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now)
    labeled_at: Optional[str] = None
    labeled_by: Optional[str] = None

    def to_doc(self) -> Dict[str, Any]:
        d = asdict(self)
        d["_id"] = d.pop("id")
        return d

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "EvalCase":
        doc = dict(doc)
        if "_id" in doc and "id" not in doc:
            doc["id"] = doc.pop("_id")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in doc.items() if k in known})

    def label(self, expected_output: str, labeled_by: str = "admin") -> None:
        self.expected_output = expected_output
        self.status = LABELED
        self.labeled_at = _now()
        self.labeled_by = labeled_by
