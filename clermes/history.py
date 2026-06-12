# SPDX-License-Identifier: AGPL-3.0-or-later
"""Append-only event log (events.jsonl).

Each line in ``events.jsonl`` is one JSON object. This module provides three
operations: append a new entry, tail the last N entries, and grep with a
predicate.

File location: ``clermes_home() / "events.jsonl"``.

``grep`` scans forward from the start of the file and returns matching lines
oldest-first (the natural file order). If ``limit`` is set, only the first
``limit`` matching entries are returned. This keeps the caller's mental model
simple: oldest at index 0, just like ``tail``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import clermes_home


def history_path() -> Path:
    """Return the canonical path to events.jsonl."""
    return clermes_home() / "events.jsonl"


def append(event_dict: Dict[str, Any]) -> None:
    """Append one event to events.jsonl.

    Adds a ``ts`` field (``time.time()``) if not already present. Creates the
    file and any missing parent directories on first call.
    """
    if "ts" not in event_dict:
        event_dict = dict(event_dict)
        event_dict["ts"] = time.time()
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event_dict) + "\n")


def _iter_lines() -> List[Dict[str, Any]]:
    """Read all valid JSON lines from events.jsonl. Skips malformed lines."""
    path = history_path()
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    entries.append(obj)
            except json.JSONDecodeError:
                pass
    return entries


def tail(n: int = 50) -> List[Dict[str, Any]]:
    """Return the last ``n`` entries from events.jsonl, oldest first.

    Safe on an empty or missing file.
    """
    entries = _iter_lines()
    return entries[-n:] if n < len(entries) else entries


def grep(
    predicate: Callable[[Dict[str, Any]], bool],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return entries where ``predicate(entry)`` is truthy, oldest first.

    Scans from the beginning of the file. If ``limit`` is set, stops after
    collecting that many matching entries.
    """
    entries = _iter_lines()
    results: List[Dict[str, Any]] = []
    for entry in entries:
        if predicate(entry):
            results.append(entry)
            if limit is not None and len(results) >= limit:
                break
    return results
