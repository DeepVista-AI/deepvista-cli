"""Small helpers shared across catalog/session modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_state(path: Path) -> dict[str, Any]:
    """Load JSON state from ``path``. Returns ``{}`` when missing or corrupt."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_json_state(path: Path, data: dict[str, Any]) -> None:
    """Persist JSON state to ``path``, creating parent dirs on demand."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
