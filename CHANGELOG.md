# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-05-26

First publishable release.

### Added

- `bin/clermes`: bash dispatcher for the Claude worker fleet. Encodes 17 pitfalls as hard constraints, including pane-state detection via `pane_current_command`, `readlink -f` for the Claude binary, the 1-second post-`new-session` settle delay, the workdir-to-projects-dir non-alphanumeric encoding, multi-line prompt delivery through `load-buffer`/`paste-buffer`, atomic writes to `assigned/<worker>`, idempotent monitor-bell + alert-bell hook application on every spawn and send, and a post-send compact-swallow recovery check.
- `templates/preamble.md`: worker preamble template with `${WORKER}`, `${WORKDIR}`, `${INSTANCE_NAME}`, `${PRINCIPAL}` substitution. Per-worker override at `workers/<name>/preamble.md` wins.
- `clermes/` Python package: `config` (yaml loader + env overrides + `Settings` dataclass), `registry` (jsonschema-validated `fleet.json` read/write with atomic writes), `events` (file-channel walker with cursor at `state/.plugin-cursor`, TOCTOU-safe stat calls), `history` (append-only `events.jsonl` writer + `tail` + `grep`), `routing` (keyword scorer with `ambiguous` flag, env-override-aware via `load_settings`).
- `scripts/bell-on-input-needed.sh`: Claude Code hook that rings the terminal bell on Notification and on Stop when the last assistant message ends with `?`.
- `scripts/clermes-on-bell.sh`: tmux alert-bell handler. Writes idle-queue entries, dedupes by pane-content hash.
- `scripts/clermes-watchdog`: Python cron job. Sweeps stale `assigned/` markers, drains `idle-queue/`, surfaces new files in `done/disputes/announcing/` since the previous run, and appends every observation to `events.jsonl`. Silent stdout when nothing happened.
- `plugins/hermes/`: Hermes plugin exposing 10 typed tools (`clermes_list`, `clermes_snapshot`, `clermes_send`, `clermes_capture`, `clermes_spawn`, `clermes_heal`, `clermes_pick_worker`, `clermes_dispatch_parallel`, `clermes_drain_events`, `clermes_history`) plus a `/clermes` slash command (`list`, `snapshot`, `recent`, `who`). The new `clermes_history` tool queries `events.jsonl` with optional event-type and worker filters scoped to the most recent 500 entries.
- `honcho/`: self-building Honcho stack. `Dockerfile.honcho` clones `plastic-labs/honcho` at `HONCHO_REF=v3.0.7` inside the image build; no separate operator checkout required. Postgres data binds to `/srv/pgdata/honcho/` to land in the host backup path. Defaults to local Ollama (`qwen3.5:latest` deriver, `nomic-embed-text` embeddings) with `think:false` to keep structured-output deriver calls valid.
- `skills/clermes-dispatch/`: operator skill loaded by the plugin, plus the full pitfall reference under `references/dispatcher-pitfalls.md`.
- `docs/`: architecture, protocol, bell-detection, plugin, and honcho references, plus four worked-recipe pages (parallel dispatch, dispute flow, announce-then-act, troubleshooting).
- `examples/config.yaml.example`, `examples/fleet.json.example`: operator config templates.
- Test suite: 49 bash + 48 python = 97 tests. Bash tests cover the dispatcher's TASK_ID extraction (with pipefail-safety), pane-state probing, spawn/heal/send paths, preamble rendering, and the bell handler's seven decision branches. Python tests cover config defaults and env overrides, registry schema validation, event scanning and cursor advancement, history append/tail/grep, routing rules and ambiguity, and the full plugin tool surface.

### License

AGPL-3.0-or-later. See `LICENSE`. Combined-work attributions for Hermes (MIT), Honcho (AGPL-3.0), and Claude Code (commercial) live in `NOTICE`.

## [Unreleased]
