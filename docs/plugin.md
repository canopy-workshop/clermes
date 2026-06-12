<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Hermes Plugin Reference

## Overview

The `plugins/hermes/` plugin wraps the bash dispatcher (`bin/clermes`) as
10 typed tools and one slash command. The orchestrator calls these tools
rather than shelling out directly, which gives it structured responses,
automatic TASK_ID injection, and event-cursor accounting.

The bash layer stays authoritative. The plugin calls `bin/clermes` through a
subprocess bridge (`dispatcher.py`). It does not re-implement dispatch logic
in Python.

Load order: Hermes loads the plugin at startup. The plugin registers the tools
and the `/clermes` slash command. The tool schemas and descriptions are the
source of truth for what the orchestrator can ask the dispatcher to do.

## Tool reference

### `clermes_list`

Show fleet status: which workers exist, whether each tmux session is alive, the
state of the front process in each pane (`claude`, `bash`, `dead`, or
`other:<proc>`), and which workers hold a lock. Use when planning a dispatch or
answering "what is the fleet doing right now."

No parameters.

### `clermes_snapshot`

Return a JSON inventory of every worker: pane state, the last lines of recent
output, and any held lock. This is the preferred read primitive when the
orchestrator needs to make a routing or status decision based on what workers
are currently doing. More detail than `clermes_list`; use this when live state
matters.

No parameters.

### `clermes_send`

Dispatch a task to a single worker. The prompt should be the full task brief.
If the prompt lacks a `TASK_ID:` footer, the tool appends one automatically in
the form `YYYY-MM-DD-HHMM-<slug>`, where `slug` comes from the optional `slug`
parameter, falling back to the worker name. The returned `task_id` is the
canonical handle to watch in the file channels.

The dispatcher auto-heals the worker pane: if Claude is not the front process,
it resumes with `claude -r <session-id>` before delivering the prompt.
Conversation context survives the heal.

Parameters: `worker` (required), `prompt` (required), `slug` (optional).

### `clermes_capture`

Capture the last N lines of a worker's tmux pane for a live progress check
while a task is in flight. Useful when the principal asks "what is it doing"
or when the orchestrator wants to spot-check a worker that should have
completed by now.

Note: Claude Code's TUI displays a lighter-colored suggested follow-up prompt
in the input box when idle. `tmux capture-pane` picks this up and it can look
like an instruction that was sent. That text has NOT been sent. The worker is
idle at the prompt, waiting.

Parameters: `worker` (required), `lines` (optional, default 80).

### `clermes_spawn`

Spawn a worker by name. No-op if the worker is already running with Claude as
the front process. If Claude exited (pane state is `bash` or `other`), the tool
resumes the existing tmux session with `claude -r <session-id>`, preserving
conversation history. If there is no tmux session at all (`dead`), it creates
one.

Parameters: `worker` (required).

### `clermes_heal`

Heal the entire fleet: respawn dead workers, resume Claude in bash-fronted panes.
Session IDs are preserved, so conversation context survives across the heal.
Running `clermes_heal` is equivalent to calling `clermes_spawn` for every worker
in the registry.

No parameters.

### `clermes_pick_worker`

Score the fleet against a task description using the keyword rules from
`~/.clermes/config.yaml` `routing.rules`. Returns the best-matched worker.
When two or more workers tie, the tool sets `ambiguous=true` and lists the
candidates. Surface ambiguous matches to the operator rather than guessing.
Two workers editing the same file is a race condition; the lock system exists
to prevent it, but it is better to route correctly than to rely on the lock
as a last resort.

Parameters: `task` (required, free-text description).

### `clermes_dispatch_parallel`

Dispatch independent tasks to multiple workers in one call. Accepts a list of
`{worker, prompt, slug?}` entries. TASK_ID footers are auto-injected when
missing. The tool serializes the sends to the bash dispatcher and returns
per-worker results in one structured response. Use for per-worker audit passes
or any decomposition where the tasks are independent.

Parameters: `jobs` (required, array of `{worker, prompt, slug?}` objects).

### `clermes_drain_events`

Drain new events from the file channels (done, disputes, announcing, idle-queue)
since the last drain. Returns ordered events. The plugin cursor advances on each
drain unless `peek=true`. The cron watchdog also drains via a separate mechanism;
the plugin cursor and the watchdog cursor are independent.

Use `peek=true` to inspect pending events without consuming them from the
plugin's perspective. Use `types` to filter to a specific event category
(`done`, `dispute`, `announce`, `idle`).

Parameters: `peek` (optional, default false), `types` (optional, array).

### `clermes_history`

Query the append-only `events.jsonl` log. Scans the most recent 500 log entries,
applies filters, and returns up to `n` matching events (default 20, max 500).
Use for historical questions: "what happened in the last hour," "when did worker
X last complete a task," "show me all disputes this session."

The history tool does not touch file-channel cursors; it is read-only over the
event log.

Parameters: `n` (optional), `filter_type` (optional, exact match on the
`event` field), `filter_worker` (optional, exact match on the `worker` field).

## Slash command: `/clermes`

Quick fleet inspection from the Hermes REPL. Available subcommands:

| Subcommand | Action |
|-----------|--------|
| `list` | Print fleet status (same as `clermes_list`). |
| `snapshot` | Print the full JSON snapshot (same as `clermes_snapshot`). |
| `recent` | Print the last 20 entries from `events.jsonl`. |
| `who` | Print each worker's health-check result. |

## Installation and registration

```bash
# Install the Hermes plugin:
./install.sh --with-hermes-plugin
# Copies plugins/hermes/ to ~/.hermes/plugins/clermes/

# Enable in ~/.hermes/config.yaml:
plugins:
  enabled:
    - clermes
```

Restart Hermes after enabling. The plugin registers its tools and slash
command at load time. Any subsequent `make install` in the clermes repo
updates the plugin in place; restart Hermes to pick up changes.

The plugin's SKILL.md is at `plugins/hermes/SKILL.md` and is loaded as
an in-session reference when the orchestrator starts. The operator skill
for dispatch workflows is at `skills/clermes-dispatch/SKILL.md`.

## Requirements

`tmux`, `jq`, and `claude` on PATH. Linux only. The dispatcher uses tmux
session hooks and bell-detection paths tested on Linux; it has not been
tested on macOS.
