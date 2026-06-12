<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# clermes Hermes plugin

Dispatch tasks to a fleet of long-lived Claude Code workers running in
tmux. Each worker is pinned to one workdir and holds warm project
context across sessions. Coordination is file-based under
`~/.clermes/`.

The plugin is a typed Hermes wrapper around the bash dispatcher at
`bin/clermes`. It exposes the same surface as the bash dispatcher
without the shell-out friction.

## Install

The clermes repo's `install.sh --with-hermes-plugin` copies the plugin
into `~/.hermes/plugins/clermes/`. Hermes picks it up on next start.
Enable it under `plugins.enabled` in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - clermes
```

## Tools

| Tool | Purpose |
|---|---|
| `clermes_list` | Fleet status (text). |
| `clermes_snapshot` | JSON inventory: pane state, recent output, locks. Preferred read primitive. |
| `clermes_send` | Dispatch a task. Auto-appends a `TASK_ID:` footer when missing. |
| `clermes_capture` | Tail a worker's pane for live progress checks. |
| `clermes_spawn` | Spawn a worker. No-op if already running. |
| `clermes_heal` | Respawn dead workers; resume Claude in bash-fronted panes. |
| `clermes_pick_worker` | Score the fleet against a task description. Flags ambiguous matches. |
| `clermes_dispatch_parallel` | Dispatch independent tasks across multiple workers in one call. |
| `clermes_drain_events` | Return new events from done/disputes/announcing/idle-queue since last drain. |
| `clermes_history` | Query the append-only events.jsonl log. Filter by event type or worker. |

## Slash command

`/clermes <subcommand>` for quick fleet inspection from the REPL:

| Subcommand | Action |
|---|---|
| `list` | Print fleet status. |
| `snapshot` | Print full JSON snapshot. |
| `recent` | Print the last 20 log entries from events.jsonl. |
| `who` | Print each worker's health-check result. |

## Requirements

`tmux`, `jq`, and `claude` on PATH. Linux only (the dispatcher uses
tmux hooks and bell-detection paths tested on Linux).

## What this plugin does NOT do

- It does not duplicate dispatcher logic in Python. The bash layer in
  `bin/clermes` stays authoritative.
- It does not write to Honcho directly. Workers use the Claude Code
  Honcho plugin; the operator uses the Hermes Honcho plugin.

## License

AGPL-3.0-or-later. Loading this plugin into a Hermes process does not
relicense Hermes itself; Hermes stays MIT and this plugin stays AGPL
at runtime. See the top-level LICENSE for terms and the project
README for the network-use clause.
