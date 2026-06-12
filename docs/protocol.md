<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Clermes Protocol

Coordination contract between the orchestrator and the Claude Code worker fleet.

## Roles

- The **orchestrator** is the top-level agent (a Hermes instance with
  `plugins/hermes/` loaded). It owns routing, memory, scheduling, and all
  outbound contact with humans. One per install.
- **Workers** are domain-specialized, persistent Claude Code agents. Each
  is pinned to one workdir, runs in a long-lived tmux session, and holds
  warm project context across restarts.
- The **principal** is the human operator. Disputes route to them. They
  can override any decision.

## Workers are fully capable

Every worker has the full Claude Code toolkit: Read, Write, Edit, Bash,
WebFetch, WebSearch, gh, git, MCP. The protocol below is coordination, not
containment. The only outbound channel to humans is through the orchestrator.

## File channels (live under `~/.clermes/`)

| Path | Purpose | Written by |
|------|---------|-----------|
| `registry/fleet.json` | Source of truth for which workers exist | Operator setup |
| `workers/<name>/session-id` | Claude session UUID for resume after restart | Dispatcher on spawn |
| `done/<task-id>.json` | Task completion signal + result | Worker |
| `disputes/<task-id>.md` | Question needing the principal's decision | Worker |
| `announcing/<task-id>.txt` | Pre-action callout for irreversible external ops | Worker |
| `halt/<task-id>` | Touch to abort an announced action | Orchestrator or operator |
| `locks/<worker>.lock` | Worker is mid-task on its repo | Worker |
| `logs/<worker>.log` | Append-only audit trail | Worker + dispatcher |

### Task ID convention

Task IDs are short slugs: `YYYY-MM-DD-HHMM-<short-description>`.

Example: `2026-05-21-1437-studio-wordmark-margin`

Every task message sent via the dispatcher should include a `TASK_ID:` footer.
The dispatcher and tools auto-inject one if missing. Without a TASK_ID, the
bell-detection system logs the task as `unknown-<epoch>` and cannot auto-match
a done file to clean up the assigned marker.

## Done schema (`done/<task-id>.json`)

```json
{
  "task_id": "2026-05-21-1437-studio-wordmark-margin",
  "worker": "claude-studio",
  "status": "done",
  "started_at": "2026-05-21T14:37:02Z",
  "finished_at": "2026-05-21T14:41:18Z",
  "result": "Widened SVG viewBox to 90 28 300 84. Italic C and d no longer clipped.",
  "artifacts": ["path/to/file.svg"],
  "commits": ["8acb4da"],
  "session_id": "75e2167f-...",
  "next_action": null
}
```

`status` must be one of: `done | blocked | disputed | error`.

Workers write this file atomically (write to a temp file, then `mv`). The
orchestrator treats the file's presence as the completion signal; it polls
for the file, not for pane content.

## Dispute schema (`disputes/<task-id>.md`)

```markdown
---
task_id: 2026-05-21-1502-task-slug
worker: claude-account
opened_at: 2026-05-21T15:02:11Z
priority: normal
---

## Question

One clear question the principal needs to answer.

## Context

- Relevant fact A
- Relevant fact B

## Options

1. Option one. (Recommended if applicable.)
2. Option two.
3. Option three.
```

Workers write a dispute when they hit a decision point that belongs to the
principal. After writing the dispute, the worker stops and waits. It does
not take the task lock until the dispute is resolved. The orchestrator
surfaces the dispute verbatim; it does not arbitrate.

When the principal answers, the orchestrator sends the reply via the
dispatcher to the same worker. `clermes send` auto-heals the pane (the
worker may have exited to bash while waiting) before delivering the reply.

## Announce-then-act schema (`announcing/<task-id>.txt`)

Single-line format:

```
2026-05-21T15:14:22Z claude-ledger git push origin main grace=10s
```

Workers write this file before any irreversible external action: pushing to
a remote, deploying, posting a webhook, calling an external API that writes.

Local file edits, local commits, scraping, reads, builds: no announcement needed.

The sequence:
1. Worker writes `announcing/<task-id>.txt`.
2. Worker sleeps the grace window (from config; default 10s).
3. Worker checks `halt/<task-id>`.
4. If no halt file: proceed. If halt file exists: abort.

The orchestrator can drop a halt file during the grace window to abort the
action. The principal can also drop it directly.

## Lock semantics

A worker holds `locks/<worker>.lock` while mid-task. The lock file contains:

```json
{"task_id": "...", "started_at": "2026-05-21T14:37:02Z", "pid": 12345}
```

The orchestrator queues additional work for a locked worker rather than
dispatching over it. Cross-worker work that would touch a locked worker's
repo surfaces to the principal as a conflict.

**Locks survive crashes.** If a worker exits mid-task, the lock file stays.
The dispatcher does not auto-clear stale locks: removing a lock that belongs
to a genuinely active worker would corrupt the coordination state. To clear a
stale lock after a confirmed crash, remove the file manually:
`rm ~/.clermes/locks/<worker>.lock`. Then `clermes heal` to respawn.

## Worker startup preamble

Every worker session starts with an injected startup message. The template
lives at `templates/preamble.md` and is rendered with four variables:

- `WORKER`: the worker's registry name.
- `WORKDIR`: the absolute path of the worker's assigned directory.
- `INSTANCE_NAME`: the orchestrator's instance handle (from `config.yaml`).
- `PRINCIPAL`: the human principal's name or handle (from `config.yaml`).

Workers read the protocol from `~/.clermes/PROTOCOL.md` and their
project's `CLAUDE.md` before standing by for the first task.

## Task brief structure

Every task message dispatched via `clermes send` should include:

1. A clear description of the work.
2. A `TASK_ID:` footer with the canonical task ID.
3. Protocol reminder lines (lock acquisition, done/dispute write, announce
   rule). The dispatcher auto-injects a TASK_ID when missing; the protocol
   reminder is the orchestrator's responsibility.

Minimum footer:

```
TASK_ID: 2026-05-21-1437-studio-wordmark-margin
On start: acquire ~/.clermes/locks/claude-<worker>.lock with {task_id, started_at, pid}.
On completion: write ~/.clermes/done/<task-id>.json with status, result, artifacts.
If decision needed: write ~/.clermes/disputes/<task-id>.md and stop.
Before irreversible external action: write announcing/<task-id>.txt, sleep grace, check halt.
```

## Event log

The watchdog appends each drained event to `~/.clermes/events.jsonl`.
The `clermes_history` tool reads this log for historical queries. The
file is append-only; do not modify or truncate it.
