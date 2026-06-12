# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured event stream for the Clermes file channels.

The dispatcher writes events as files under ``~/.clermes/{done,disputes,
announcing,idle-queue}/``. This module walks those directories and returns a
unified, ordered list of events for the agent to react to.

The cursor lives at ``clermes_home() / "state" / ".plugin-cursor"`` so the
Hermes plugin can drain events without consuming what cron is delivering. The
cron watchdog has its own state file (``.watchdog-state``); this cursor is
separate.

File extension rules
--------------------
- ``done/``        -- ``.json`` files
- ``disputes/``    -- ``.md`` files
- ``announcing/``  -- ``.txt`` files
- ``idle-queue/``  -- ``.json`` files
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import clermes_home

EVENT_TYPES = ("done", "dispute", "announce", "idle")


@dataclass
class Event:
    type: str
    task_id: Optional[str]
    worker: Optional[str]
    path: str
    mtime: float
    body: Any
    raw: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "task_id": self.task_id,
            "worker": self.worker,
            "path": self.path,
            "mtime": self.mtime,
            "body": self.body,
        }


def cursor_path() -> Path:
    """Return the path to the plugin cursor file."""
    return clermes_home() / "state" / ".plugin-cursor"


def read_cursor() -> float:
    """Return the last-seen event timestamp, or 0.0 if no cursor exists."""
    path = cursor_path()
    if not path.exists():
        return 0.0
    try:
        return float(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0.0


def write_cursor(ts: float) -> None:
    """Write the cursor timestamp to disk, creating parent directories as needed."""
    path = cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{ts:.6f}\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _walk(dir_name: str) -> Iterable[Path]:
    root = clermes_home() / dir_name
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_file():
            yield child


def _done_event(path: Path, mtime: float) -> Optional[Event]:
    body = _read_json(path)
    task_id = None
    worker = None
    if isinstance(body, dict):
        task_id = body.get("task_id")
        worker = body.get("worker")
    if not task_id:
        task_id = path.stem
    return Event(
        type="done",
        task_id=task_id,
        worker=worker,
        path=str(path),
        mtime=mtime,
        body=body,
    )


def _dispute_event(path: Path, mtime: float) -> Optional[Event]:
    text = _read_text(path)
    return Event(
        type="dispute",
        task_id=path.stem,
        worker=None,
        path=str(path),
        mtime=mtime,
        body=text,
        raw=text,
    )


def _announce_event(path: Path, mtime: float) -> Optional[Event]:
    text = _read_text(path) or ""
    worker = None
    parts = text.split()
    if len(parts) >= 2:
        worker = parts[1]
    return Event(
        type="announce",
        task_id=path.stem,
        worker=worker,
        path=str(path),
        mtime=mtime,
        body=text.strip(),
        raw=text,
    )


def _idle_event(path: Path, mtime: float) -> Optional[Event]:
    body = _read_json(path)
    task_id = None
    worker = None
    if isinstance(body, dict):
        task_id = body.get("task_id")
        worker = body.get("worker")
    return Event(
        type="idle",
        task_id=task_id,
        worker=worker,
        path=str(path),
        mtime=mtime,
        body=body,
    )


def scan(since: float = 0.0, types: Optional[Iterable[str]] = None) -> List[Event]:
    """Return all events with mtime > since, ordered oldest first.

    Files that disappear between the directory walk and the stat call are
    silently skipped -- this is normal in a production environment where the
    watchdog and dispatcher are continuously draining and writing files.
    """
    wanted = set(types) if types else set(EVENT_TYPES)
    events: List[Event] = []
    if "done" in wanted:
        for p in _walk("done"):
            if not p.name.endswith(".json"):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > since:
                ev = _done_event(p, mtime)
                if ev:
                    events.append(ev)
    if "dispute" in wanted:
        for p in _walk("disputes"):
            if not p.name.endswith(".md"):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > since:
                ev = _dispute_event(p, mtime)
                if ev:
                    events.append(ev)
    if "announce" in wanted:
        for p in _walk("announcing"):
            if not p.name.endswith(".txt"):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > since:
                ev = _announce_event(p, mtime)
                if ev:
                    events.append(ev)
    if "idle" in wanted:
        for p in _walk("idle-queue"):
            if not p.name.endswith(".json"):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > since:
                ev = _idle_event(p, mtime)
                if ev:
                    events.append(ev)
    events.sort(key=lambda e: e.mtime)
    return events


def drain(advance_cursor: bool = True, types: Optional[Iterable[str]] = None) -> List[Event]:
    """Return new events since last drain.

    Advances the cursor by default so subsequent calls don't re-deliver the
    same events. Pass ``advance_cursor=False`` to peek without consuming.
    """
    since = read_cursor()
    events = scan(since=since, types=types)
    if events and advance_cursor:
        write_cursor(events[-1].mtime)
    return events
