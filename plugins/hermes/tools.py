# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent-facing tools for the clermes plugin.

Each tool exposes a JSON-schema definition and a handler. The handler
returns a JSON-serializable dict; the framework serializes it to text
before handing it to the LLM.

Design notes:
  * Tools never embed dispatcher logic. They shell out to bin/clermes
    through the dispatcher module. The bash layer stays authoritative.
  * Routing keyword logic lives in clermes.routing and is exposed via
    clermes_pick_worker so the agent can ask "which worker?" without
    dispatching.
  * Parallel dispatch is a separate tool from single-worker send to
    keep the schemas tight.
  * clermes_history reads the append-only events.jsonl log directly
    without touching the file-channel cursors.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from clermes import events, routing
from clermes import history as hist
from . import dispatcher

# Match the bash dispatcher's _extract_task_id pattern exactly. The two
# must stay in lockstep: drift means the assigned/<worker> file (written
# by bash) and the task_id surfaced to the agent (extracted in Python)
# can diverge for prompts where TASK_ID appears mid-token.
_TASK_ID_RE = re.compile(r"TASK_ID:\s*[A-Za-z0-9_.-]+")


def _ensure_task_id(prompt: str, slug: str) -> str:
    """Append a TASK_ID footer if the prompt does not already carry one."""
    if _TASK_ID_RE.search(prompt or ""):
        return prompt
    if not slug:
        slug = "task"
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    return f"{prompt.rstrip()}\n\nTASK_ID: {ts}-{slug}\n"


def _slugify(text: str, max_len: int = 30) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len] or "task"


# ---------------------------------------------------------------------------
# clermes_list
# ---------------------------------------------------------------------------

CLERMES_LIST_SCHEMA: Dict[str, Any] = {
    "name": "clermes_list",
    "description": (
        "Show fleet status: which workers exist, whether each is alive, "
        "what state the tmux pane is in (claude|bash|dead|other), and which "
        "workers hold a lock. Use this when planning dispatch or answering "
        "'what is the fleet doing right now.'"
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def handle_list(_args: Dict[str, Any], **_kwargs) -> str:
    return json.dumps({"output": dispatcher.list_workers()}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_snapshot
# ---------------------------------------------------------------------------

CLERMES_SNAPSHOT_SCHEMA: Dict[str, Any] = {
    "name": "clermes_snapshot",
    "description": (
        "Return a JSON inventory of every worker: pane state, the last "
        "lines of recent output, and any held lock. Preferred read primitive "
        "when the agent needs to make a routing or status decision based on "
        "what workers are doing."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def handle_snapshot(_args: Dict[str, Any], **_kwargs) -> str:
    return json.dumps(dispatcher.snapshot(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_send
# ---------------------------------------------------------------------------

CLERMES_SEND_SCHEMA: Dict[str, Any] = {
    "name": "clermes_send",
    "description": (
        "Dispatch a task to a single worker. The prompt should be the full "
        "brief; if it lacks a TASK_ID footer, one is appended automatically "
        "based on a slug derived from the task. The dispatcher auto-heals "
        "the worker pane if Claude is not the front process."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worker": {
                "type": "string",
                "description": "Worker name from the registry, e.g. 'studio'.",
            },
            "prompt": {
                "type": "string",
                "description": "Full task brief. Worker will execute as a Claude Code agent.",
            },
            "slug": {
                "type": "string",
                "description": (
                    "Optional short slug for the auto-generated TASK_ID. "
                    "Ignored if the prompt already includes a TASK_ID."
                ),
            },
        },
        "required": ["worker", "prompt"],
    },
}


def handle_send(args: Dict[str, Any], **_kwargs) -> str:
    worker = (args.get("worker") or "").strip()
    prompt = args.get("prompt") or ""
    slug = _slugify(args.get("slug") or worker)
    if not worker:
        return json.dumps({"ok": False, "error": "worker is required"})
    if not prompt.strip():
        return json.dumps({"ok": False, "error": "prompt is required"})
    full = _ensure_task_id(prompt, slug)
    task_id_match = _TASK_ID_RE.search(full)
    task_id = task_id_match.group(0).split(":", 1)[1].strip() if task_id_match else None
    result = dispatcher.send(worker, full)
    return json.dumps(
        {
            "ok": result.ok,
            "worker": worker,
            "task_id": task_id,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# clermes_capture
# ---------------------------------------------------------------------------

CLERMES_CAPTURE_SCHEMA: Dict[str, Any] = {
    "name": "clermes_capture",
    "description": (
        "Capture the last N lines of a worker's tmux pane. Use for live "
        "progress checks while a task is in flight. Note: pane capture "
        "shows suggested follow-up prompts as a lighter-coloured line "
        "in the input box. Suggested text has NOT been sent."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worker": {"type": "string", "description": "Worker name."},
            "lines": {
                "type": "integer",
                "description": "Number of pane lines (default 80).",
            },
        },
        "required": ["worker"],
    },
}


def handle_capture(args: Dict[str, Any], **_kwargs) -> str:
    worker = (args.get("worker") or "").strip()
    lines = int(args.get("lines") or 80)
    if not worker:
        return json.dumps({"ok": False, "error": "worker is required"})
    output = dispatcher.capture(worker, lines)
    return json.dumps({"worker": worker, "lines": lines, "pane": output}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_spawn
# ---------------------------------------------------------------------------

CLERMES_SPAWN_SCHEMA: Dict[str, Any] = {
    "name": "clermes_spawn",
    "description": (
        "Spawn a worker by name. No-op if the worker is already running with "
        "Claude as the front process. Heals stale panes (bash-fronted) by "
        "resuming Claude against the saved session id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worker": {"type": "string", "description": "Worker name from the registry."}
        },
        "required": ["worker"],
    },
}


def handle_spawn(args: Dict[str, Any], **_kwargs) -> str:
    worker = (args.get("worker") or "").strip()
    if not worker:
        return json.dumps({"ok": False, "error": "worker is required"})
    result = dispatcher.spawn(worker)
    return json.dumps(
        {"ok": result.ok, "worker": worker, "stdout": result.stdout, "stderr": result.stderr},
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# clermes_heal
# ---------------------------------------------------------------------------

CLERMES_HEAL_SCHEMA: Dict[str, Any] = {
    "name": "clermes_heal",
    "description": (
        "Heal the fleet: respawn dead workers, resume Claude in bash-fronted "
        "panes. Session ids are preserved so conversation context survives."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def handle_heal(_args: Dict[str, Any], **_kwargs) -> str:
    return json.dumps({"output": dispatcher.heal()}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_pick_worker
# ---------------------------------------------------------------------------

CLERMES_PICK_WORKER_SCHEMA: Dict[str, Any] = {
    "name": "clermes_pick_worker",
    "description": (
        "Score workers against a task description using the keyword rules "
        "from ~/.clermes/config.yaml routing.rules. Returns the best match or "
        "signals ambiguous=true when two or more workers tie. Surface ambiguous "
        "routes to the operator rather than guessing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Free-text task description to route.",
            }
        },
        "required": ["task"],
    },
}


def handle_pick_worker(args: Dict[str, Any], **_kwargs) -> str:
    task = args.get("task") or ""
    result = routing.pick(task)
    return json.dumps(result.as_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_dispatch_parallel
# ---------------------------------------------------------------------------

CLERMES_DISPATCH_PARALLEL_SCHEMA: Dict[str, Any] = {
    "name": "clermes_dispatch_parallel",
    "description": (
        "Dispatch independent tasks to multiple workers in one call. Each "
        "entry specifies worker + prompt (+ optional slug). TASK_ID footers "
        "are auto-injected when missing. Returns per-worker results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "description": "List of dispatch jobs.",
                "items": {
                    "type": "object",
                    "properties": {
                        "worker": {"type": "string"},
                        "prompt": {"type": "string"},
                        "slug": {"type": "string"},
                    },
                    "required": ["worker", "prompt"],
                },
            }
        },
        "required": ["jobs"],
    },
}


def handle_dispatch_parallel(args: Dict[str, Any], **_kwargs) -> str:
    jobs = args.get("jobs") or []
    results: List[Dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        single = handle_send(job)
        try:
            results.append(json.loads(single))
        except json.JSONDecodeError:
            results.append({"ok": False, "raw": single})
    return json.dumps({"jobs": results}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# clermes_drain_events
# ---------------------------------------------------------------------------

CLERMES_DRAIN_EVENTS_SCHEMA: Dict[str, Any] = {
    "name": "clermes_drain_events",
    "description": (
        "Drain new events from the file channels (done, disputes, announcing, "
        "idle-queue) since the last drain. Returns ordered events; the plugin "
        "cursor advances unless peek=true. Use peek to inspect without "
        "consuming events the cron watchdog has not yet delivered."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "peek": {
                "type": "boolean",
                "description": "If true, do not advance the cursor.",
            },
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": list(events.EVENT_TYPES)},
                "description": "Restrict to event types. Omit for all.",
            },
        },
        "required": [],
    },
}


def handle_drain_events(args: Dict[str, Any], **_kwargs) -> str:
    peek = bool(args.get("peek", False))
    types = args.get("types") or None
    new_events = events.drain(advance_cursor=not peek, types=types)
    return json.dumps(
        {
            "count": len(new_events),
            "events": [ev.as_dict() for ev in new_events],
            "cursor_advanced": (not peek) and bool(new_events),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# clermes_history
# ---------------------------------------------------------------------------

_HISTORY_SCAN_WINDOW = 500

CLERMES_HISTORY_SCHEMA: Dict[str, Any] = {
    "name": "clermes_history",
    "description": (
        "Query the watchdog's append-only event log at events.jsonl. Returns "
        "up to n events matching the optional filters, drawn from the most "
        f"recent {_HISTORY_SCAN_WINDOW} log entries. Use this to answer 'what "
        "happened in the last hour' or 'when did worker X last finish a task.'"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": (
                    "Maximum events to return after filtering (default 20, max 500). "
                    f"Filters apply within the most recent {_HISTORY_SCAN_WINDOW} log entries."
                ),
            },
            "filter_type": {
                "type": "string",
                "description": "Exact match against the 'event' field. Omit for all types.",
            },
            "filter_worker": {
                "type": "string",
                "description": "Exact match against the 'worker' field. Omit for all workers.",
            },
        },
        "required": [],
    },
}


def handle_history(args: Dict[str, Any], **_kwargs) -> str:
    n = int(args.get("n") or 20)
    n_max = min(n, 500)
    filter_type = args.get("filter_type") or None
    filter_worker = args.get("filter_worker") or None

    # Scan the recent window, then filter within it, then take the last n_max.
    # This gives the agent "last n events matching the filter from recent
    # history" rather than "filter within an already-truncated window".
    window = hist.tail(_HISTORY_SCAN_WINDOW)
    if filter_type:
        window = [e for e in window if e.get("event") == filter_type]
    if filter_worker:
        window = [e for e in window if e.get("worker") == filter_worker]
    entries = window[-n_max:]

    return json.dumps({"count": len(entries), "events": entries}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool table for registration
# ---------------------------------------------------------------------------

TOOLS = (
    ("clermes_list",              CLERMES_LIST_SCHEMA,              handle_list,              "📋"),
    ("clermes_snapshot",          CLERMES_SNAPSHOT_SCHEMA,          handle_snapshot,          "🛰️"),
    ("clermes_send",              CLERMES_SEND_SCHEMA,              handle_send,              "📨"),
    ("clermes_capture",           CLERMES_CAPTURE_SCHEMA,           handle_capture,           "🔍"),
    ("clermes_spawn",             CLERMES_SPAWN_SCHEMA,             handle_spawn,             "🌱"),
    ("clermes_heal",              CLERMES_HEAL_SCHEMA,              handle_heal,              "🩹"),
    ("clermes_pick_worker",       CLERMES_PICK_WORKER_SCHEMA,       handle_pick_worker,       "🎯"),
    ("clermes_dispatch_parallel", CLERMES_DISPATCH_PARALLEL_SCHEMA, handle_dispatch_parallel, "🔀"),
    ("clermes_drain_events",      CLERMES_DRAIN_EVENTS_SCHEMA,      handle_drain_events,      "📬"),
    ("clermes_history",           CLERMES_HISTORY_SCHEMA,           handle_history,           "📜"),
)


def check_clermes_available() -> bool:
    """Plugin precondition: bin/clermes resolvable."""
    try:
        dispatcher.dispatcher_bin()
        return True
    except FileNotFoundError:
        return False
