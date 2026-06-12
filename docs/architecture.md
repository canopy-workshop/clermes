<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Clermes Architecture

## The shape

Clermes runs a fleet of long-lived Claude Code workers, each pinned to
one repository and one tmux session, coordinated by an orchestrator
(a Hermes-class top-level agent). The orchestrator picks a worker, writes
a task brief, and waits for file-channel signals to come back. Workers
handle everything in their workdir: reads, writes, commits, builds. Only
the orchestrator has a channel to humans.

```
Operator / Human
      │
      ▼
Hermes orchestrator  (instance handle from config.yaml)
   clermes_send / clermes_dispatch_parallel
      │
      ▼
bin/clermes  (bash dispatcher)
   tmux send-keys / paste-buffer
      │
      ▼
tmux sessions  (one per worker)
   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
   │claude-ledger│ │claude-studio│ │claude-scratch│  ...
   │  workdir A  │ │  workdir B  │ │  workdir C  │
   └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
          │                │                │
          └────────────────┴────────────────┘
                           │
                   ~/.clermes/ file channels
                   done/  disputes/  announcing/
                   locks/ assigned/  idle-queue/
                           │
                           ▼
               Hermes plugin + cron watchdog
               drain events → orchestrator
```

Shared memory (optional): a self-hosted Honcho instance gives the
orchestrator and workers a single coherent user model. See `docs/honcho.md`.

## Layers

### Layer 1: `bin/clermes` (bash dispatcher)

Owns the tmux surface and the Claude binary. Responsibilities:

- Spawn and resume tmux sessions using `claude -r <session-id>`.
- Detect pane state from `tmux list-panes -F '#{pane_current_command}'`,
  not from visual pane content.
- Deliver prompts via `tmux load-buffer` + `paste-buffer` (never `send-keys`
  line-by-line for multi-line text).
- Install and apply tmux `monitor-bell` + `alert-bell` hooks for
  bell-based attention detection.
- Install Claude Code `bell-on-input-needed.sh` hook via
  `install-claude-hooks`.
- Write `assigned/<worker>` atomically before delivery.
- Check for post-compact sentinel after send and resend if swallowed.
- Resolve the claude binary via `readlink -f $(which claude)` to avoid
  the symlink launcher exit-before-TUI pitfall.

The bash layer stays authoritative. The Python plugin calls it; it does
not reimplement it.

### Layer 2: `clermes/` Python package (data spine)

Pure Python. No subprocess calls. Responsibilities:

- `clermes.config`: load and validate `~/.clermes/config.yaml` and
  `~/.clermes/registry/fleet.json`.
- `clermes.registry`: typed registry entries (worker name, workdir,
  tmux session, session UUID).
- `clermes.routing`: keyword-rule scoring against `config.yaml`
  `routing.rules`; returns best match + ambiguous flag.
- `clermes.events`: drain file channels (done, disputes, announcing,
  idle-queue) with a cursor; parse and type each event.
- `clermes.history`: read the append-only `events.jsonl` log with
  optional filters.

### Layer 3: `scripts/` (cron + tmux hook callbacks)

Shell scripts invoked by the system, not by the operator directly.

- `bell-on-input-needed.sh`: Claude Code hook (registered in
  `settings.json`). Fires on Notification and Stop events; writes
  `printf '\a'` to `/dev/tty` to ring the terminal bell.
- `clermes-on-bell.sh`: tmux `alert-bell` callback. Checks assigned
  marker, captures pane, dedupes by SHA-1, writes `idle-queue/*.json`.
- `clermes-watchdog`: cron job (every minute). Drains `idle-queue/`,
  cleans up stale `assigned/` markers when done/dispute files appear,
  emits one block per notification to stdout for delivery to the
  orchestrator.

### Layer 4: `plugins/hermes/` (orchestrator tools)

Python Hermes plugin. Exposes the dispatcher surface as 10 typed tools
and one `/clermes` slash command. The tools handle TASK_ID injection,
structured responses, and event-cursor accounting. All heavy work still
goes through `bin/clermes` via subprocess.

## File channels

All coordination lives under `~/.clermes/`. No daemon. No database for
coordination state. Each directory serves one purpose:

| Path | Written by | Purpose |
|------|-----------|---------|
| `registry/fleet.json` | Operator setup | Source of truth: worker names, workdirs, tmux sessions |
| `workers/<name>/session-id` | Dispatcher on spawn | Stable Claude session UUID for resume |
| `done/<task-id>.json` | Worker | Task completion signal + result + artifacts |
| `disputes/<task-id>.md` | Worker | Decision question routed to the principal |
| `announcing/<task-id>.txt` | Worker | Pre-action callout before irreversible external ops |
| `halt/<task-id>` | Orchestrator or operator | Touch to abort an announced action during grace window |
| `locks/<worker>.lock` | Worker | Worker is mid-task; contains `{task_id, started_at, pid}` |
| `assigned/<worker>` | Dispatcher | Current task_id, written atomically on each send |
| `idle-queue/*.json` | `clermes-on-bell.sh` | Bell-fired notifications pending watchdog drain |
| `state/last-notify-<worker>` | `clermes-on-bell.sh` | SHA-1 dedupe key for bell detection |
| `logs/<worker>.log` | Dispatcher | Append-only pane snapshots |
| `events.jsonl` | Watchdog | Append-only structured event log for history queries |

See `docs/protocol.md` for the full contract: schemas, write rules, and
lock semantics.

## What lives where in this repo

```
bin/
  clermes              Bash dispatcher. The single executable operators
                       install to ~/.local/bin/clermes.

clermes/               Python package. Install with: pip install -e .
  config.py            Load + validate config.yaml and fleet.json.
  registry.py          Typed worker registry entries.
  routing.py           Keyword-rule scoring for worker selection.
  events.py            File-channel drain with cursor; event typing.
  history.py           Read events.jsonl with optional filters.

scripts/
  bell-on-input-needed.sh   Claude Code Notification/Stop hook.
  clermes-on-bell.sh        tmux alert-bell callback.
  clermes-watchdog           Cron drain + watchdog.

plugins/hermes/
  tools.py             10 typed tool schemas + handlers.
  dispatcher.py        Subprocess bridge to bin/clermes.
  SKILL.md             In-session reference loaded by the plugin.
  README.md            Plugin installation instructions.

honcho/
  Dockerfile           Pins HONCHO_REF=v3.0.7 from plastic-labs/honcho.
  docker-compose.yml   api / deriver / postgres / redis. Postgres on bind mount.
  *.example            Config templates for both plugins.
  README.md            Full setup and wiring guide.

templates/
  preamble.md          Worker startup message template. Variables:
                       WORKER, WORKDIR, INSTANCE_NAME, PRINCIPAL.

docs/
  architecture.md      This file.
  protocol.md          File-channel contract: schemas, write rules, lock semantics.
  bell-detection.md    Bell pipeline end to end.
  plugin.md            Hermes plugin reference.
  honcho.md            Honcho integration reference.
  recipes/             Worked examples.

tests/
  *.sh                 Bash tests for the dispatcher (49 cases).
  test_*.py            Python tests for the clermes package (48 cases).
```

## Why this shape

**Bash for the tmux + Claude surface.** Getting tmux pane lifecycle right
against Claude Code required working through 17 pitfalls about binary
resolution, send-keys timing, pipefail traps, and pane-state detection.
Encoding those fixes in a single well-tested bash script keeps them in
one place and makes the test surface concrete.

**Python for data and tools.** Routing logic, event cursors, and history
queries are cleaner in typed Python. The tool schemas the Hermes plugin
exposes are Python dicts; keeping the data layer in the same language
avoids a JSON-over-subprocess round-trip for every routing decision.

**File channels, no daemon.** A coordinator daemon would need its own
lifecycle, crash recovery, and IPC surface. File channels give
persistence for free, are inspectable with standard shell tools, and
survive tmux server restarts without special handling. The tradeoff is
that polling and bell detection replace push notifications. For a
developer-workstation fleet that tasks are on the order of minutes, the
tradeoff is acceptable.

**AGPL because Honcho is AGPL.** Honcho (plastic-labs/honcho) is
AGPL-3.0-or-later. The combined work inherits that license. Workers and
operators connecting to a Honcho server over the network trigger the
network-use clause; see the LICENSE and NOTICE files.
