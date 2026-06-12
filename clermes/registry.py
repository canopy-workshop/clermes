# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet registry: read/write fleet.json with jsonschema validation.

fleet.json lives at ``clermes_home() / "registry" / "fleet.json"``. All
writes are atomic: the data is written to a ``.tmp`` file first, then
renamed into place with ``os.replace``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import jsonschema

from .config import clermes_home

FLEET_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["workers"],
    "properties": {
        "_comment": {"type": "string"},
        "workers": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["workdir", "owns", "tmux_session"],
                "properties": {
                    "workdir": {"type": "string"},
                    "owns": {"type": "string"},
                    "tmux_session": {"type": "string"},
                    "session_id": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def registry_path() -> Path:
    """Return the canonical path to fleet.json."""
    return clermes_home() / "registry" / "fleet.json"


def read_registry() -> Dict[str, Any]:
    """Read and validate fleet.json.

    Returns ``{"workers": {}}`` if the file does not exist.
    Raises ``jsonschema.ValidationError`` if the file fails schema validation.
    """
    path = registry_path()
    if not path.exists():
        return {"workers": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, FLEET_SCHEMA)
    return data


def write_registry(data: Dict[str, Any]) -> None:
    """Validate and atomically write fleet.json.

    Raises ``jsonschema.ValidationError`` if ``data`` does not match the schema.
    """
    jsonschema.validate(data, FLEET_SCHEMA)
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def worker_names() -> List[str]:
    """Return a sorted list of registered worker names."""
    data = read_registry()
    return sorted((data.get("workers") or {}).keys())


def update_worker(name: str, **fields) -> None:
    """Read, mutate one worker's fields, validate, and atomically write.

    Creates the worker entry if it does not already exist, but the result
    must still satisfy the schema (i.e., ``workdir``, ``owns``, and
    ``tmux_session`` must be present after the update).
    """
    data = read_registry()
    workers = data.setdefault("workers", {})
    worker = workers.setdefault(name, {})
    worker.update(fields)
    write_registry(data)
