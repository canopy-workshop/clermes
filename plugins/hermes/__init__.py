# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clermes plugin: dispatch tasks to long-lived Claude Code workers.

Hermes-side wrapper around the bash dispatcher at bin/clermes. Exposes
the dispatcher as typed Hermes tools so the orchestrator can delegate
heavy-lift work to dedicated Claude Code instances pinned to one workdir
each.

The bash dispatcher stays the operationally-tested layer; this plugin
is a thin, structured surface on top.
"""

from __future__ import annotations

import json
import logging
import platform
from pathlib import Path

from .tools import TOOLS, check_clermes_available

logger = logging.getLogger(__name__)


def _on_session_start(**_kwargs) -> None:
    """Log fleet status at session start for the agent's first-turn read."""
    try:
        from . import dispatcher
        names = dispatcher.worker_names()
        logger.info("clermes plugin: %d workers in registry", len(names))
    except Exception as exc:
        logger.debug("clermes on_session_start probe failed: %s", exc)


def _cmd_handler(arg: str) -> str:
    """Handle /clermes subcommands: list, snapshot, recent, who."""
    from . import dispatcher
    from clermes import history as hist

    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"

    if sub == "list":
        return dispatcher.list_workers()

    if sub == "snapshot":
        return json.dumps(dispatcher.snapshot(), indent=2)

    if sub == "recent":
        entries = hist.tail(20)
        lines = []
        for ev in entries:
            ts_raw = ev.get("ts", "")
            try:
                import datetime
                ts = datetime.datetime.utcfromtimestamp(float(ts_raw)).isoformat() + "Z"
            except (TypeError, ValueError):
                ts = str(ts_raw)
            event = ev.get("event", ev.get("type", ""))
            worker = ev.get("worker", "")
            task_id = ev.get("task_id", "")
            parts_out = [ts]
            if event:
                parts_out.append(f"[{event}]")
            if worker:
                parts_out.append(f"worker={worker}")
            if task_id:
                parts_out.append(f"task_id={task_id}")
            lines.append(" ".join(parts_out))
        return "\n".join(lines) if lines else "(no recent events)"

    if sub == "who":
        names = dispatcher.worker_names()
        if not names:
            return "(no workers in registry)"
        rows = []
        for name in names:
            result = dispatcher.run(["health", name])
            status = result.stdout.strip() or result.stderr.strip() or f"rc={result.returncode}"
            rows.append(f"{name}: {status}")
        return "\n".join(rows)

    return f"Unknown subcommand: {sub!r}. Valid: list, snapshot, recent, who"


def register(ctx) -> None:
    """Plugin entrypoint. Wires tools, the SKILL.md, lifecycle hooks, and the slash command."""
    if platform.system().lower() != "linux":
        logger.info(
            "clermes plugin: linux-only, skipping (platform=%s)", platform.system()
        )
        return

    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(
            name=name,
            toolset="clermes",
            schema=schema,
            handler=handler,
            check_fn=check_clermes_available,
            emoji=emoji,
        )

    ctx.register_hook("on_session_start", _on_session_start)

    skill_path = Path(__file__).resolve().parent / "SKILL.md"
    if skill_path.exists():
        try:
            ctx.register_skill(
                name="dispatch",
                path=skill_path,
                description="Operate the Clermes worker fleet from the orchestrator.",
            )
        except Exception as exc:
            logger.debug("clermes skill registration failed: %s", exc)

    try:
        ctx.register_command(
            name="clermes",
            handler=_cmd_handler,
            description="Inspect the Clermes fleet.",
        )
    except (AttributeError, TypeError, Exception) as exc:
        logger.warning("clermes plugin: /clermes command not registered: %s", exc)
