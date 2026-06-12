<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
---
name: clermes:dispatch
description: "Operate the Clermes worker fleet from the orchestrator: pick a worker, dispatch a brief, watch the file channels, surface disputes."
platforms: [linux]
---

# Clermes Dispatch

This skill is loaded by the clermes Hermes plugin. The plugin exposes
the dispatcher as typed tools (`clermes_list`, `clermes_send`,
`clermes_snapshot`, `clermes_dispatch_parallel`, `clermes_drain_events`,
`clermes_history`, etc.) rather than shelling to bash from a code block.
Prefer the tools to direct bash; the tools carry TASK_ID injection,
structured results, and event-cursor accounting the bash form does not.

## Pick the worker

Use `clermes_pick_worker` with the task description. It scores against
`routing.rules` from `~/.clermes/config.yaml`. Branch on the result:

- `worker` set, `ambiguous=false` -> dispatch
- `ambiguous=true` -> surface the candidates to the operator, do not guess
- `used_default=true` -> the task did not match any rule; the configured
  default worker is being used. Sanity-check the routing.

## Dispatch a single task

`clermes_send(worker, prompt, slug?)`. If the prompt lacks a
`TASK_ID:` footer, the tool appends one of the form
`YYYY-MM-DD-HHMM-<slug>` (derived from `slug`, falling back to the
worker name). The returned `task_id` is the canonical handle to watch
for in the file channels.

The dispatcher auto-heals the worker pane if Claude is not the front
process. Conversation context is preserved across heal via
`claude -r <session-id>`.

## Dispatch in parallel

`clermes_dispatch_parallel(jobs)` accepts a list of `{worker, prompt, slug?}`
entries. The tool serializes the sends to the bash dispatcher in a
single call so the agent gets one structured response. Use for audits
or any per-worker decomposition.

## Watch for results

`clermes_drain_events(peek?, types?)` walks the file channels and
returns events newer than the plugin's cursor. The cursor advances on
drain unless `peek=true`. Event types: `done`, `dispute`, `announce`,
`idle`.

The cron watchdog (`clermes-watchdog`) also drains and delivers via
stdout to the operator. The plugin's cursor is separate; both can run
without interfering.

## Query the event log

`clermes_history(n?, filter_type?, filter_worker?)` reads the
append-only `events.jsonl` log. Use it to answer historical questions:
"what happened in the last hour," "when did worker X last finish a
task," or "show me all disputes this session." It does not touch the
file-channel cursors; it is read-only over the log.

Parameters: `n` (default 20, max 500), `filter_type` (exact match
against the `event` field), `filter_worker` (exact match against the
`worker` field).

## Worker discipline reminders (same as the framework skill)

- Outbound to humans is operator-only. Workers stage drafts; the
  operator delivers.
- Disputes route to the principal verbatim. Do not arbitrate.
- One worker per repo at a time. Cross-repo conflicts surface.
- Local edits / commits / reads / scrapes / builds: no announce.
  Push / deploy / external POST: announce + grace + halt-check.

## File channels (live at `~/.clermes/`)

| Path | Purpose |
|---|---|
| `done/<task-id>.json` | Completion + result + artifacts + commit ids |
| `disputes/<task-id>.md` | Question routed to the operator |
| `announcing/<task-id>.txt` | Pre-action callout for irreversible ops |
| `halt/<task-id>` | Touch to abort an announced action during grace window |
| `locks/claude-<name>.lock` | Worker mid-task on its repo |
| `assigned/<worker>` | Active task_id for bell-detection attribution |
| `idle-queue/*.json` | Bell-fired notifications drained by watchdog |
| `events.jsonl` | Append-only structured event log |

Full protocol contract: `~/.clermes/PROTOCOL.md`.
