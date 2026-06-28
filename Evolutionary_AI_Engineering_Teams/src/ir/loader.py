from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from .schema import OrganizationHarness


def load_harness(path: Union[str, Path]) -> OrganizationHarness:
    """Load and validate an Organization Harness IR from a YAML file.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError: if the YAML is malformed or fails schema validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Harness file not found: {path}")

    with path.open() as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping at the top level, got {type(raw).__name__}")

    try:
        return OrganizationHarness.model_validate(raw)
    except ValidationError as exc:
        # Surface clean, human-readable errors
        lines = [f"Organization Harness validation failed ({path}):"]
        for err in exc.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            lines.append(f"  [{loc}] {err['msg']}")
        raise ValueError("\n".join(lines)) from exc


def load_harness_from_dict(data: dict) -> OrganizationHarness:
    """Validate an already-parsed dict as an Organization Harness IR."""
    try:
        return OrganizationHarness.model_validate(data)
    except ValidationError as exc:
        lines = ["Organization Harness validation failed:"]
        for err in exc.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            lines.append(f"  [{loc}] {err['msg']}")
        raise ValueError("\n".join(lines)) from exc
