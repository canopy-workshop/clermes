<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Clermes

File-based orchestration for a fleet of long-lived Claude Code workers.

## Project shelved (October 2026)

I am pausing active development of Clermes in favor of upstream enhancements
in [Hermes Agent](https://github.com/NousResearch/hermes-agent) and projects
like [OpenRig](https://github.com/mvschwarz/openrig). This repository remains
available as a reference; the documentation below describes the existing
implementation, and the planned v1.0.0 release is shelved.

I built Clermes to keep persistent coding workers coordinated across
projects: dispatching tasks, preserving context, and surfacing completions
and decisions without spending my day checking terminals. I am proud of
the work that went into it.

Seeing these capabilities find a home upstream, and seeing other projects
independently develop similar approaches, is flattering. I have a lot of
respect for the maintainers carrying this work forward and keeping pace
with the tools underneath it.

Stepping back is also a load off my shoulders. I built Clermes to give
myself more time to run my business. Using those upstream improvements
lets me put more of that time into client work and less into maintaining
my own orchestration layer.

## Overview

Clermes runs a fleet of Claude Code workers in tmux, each pinned to one
repository and one session. A Hermes-class orchestrator picks a worker,
writes a task brief, and waits for file-channel signals: a done JSON, a
dispute Markdown, or a pre-action announcement. Workers have the full Claude
Code toolkit and coordinate entirely through files under `~/.clermes/`.

The design is explicit about what it trades: polling and bell detection instead
of a push-notification daemon; bash for the tmux surface (where 17 pitfalls
required encoding hardened patterns); Python for the data layer (routing
logic, event cursors, typed tool schemas); file channels for coordination state
(no DB, no daemon, inspectable with standard tools).

Clermes includes a self-hosted Honcho memory backend so the orchestrator and
workers share a single user model across sessions.

## 60-second install

```bash
# Clone and install the Python package.
git clone https://github.com/canopy-workshop/clermes.git
cd clermes
make install             # pip install -e . in a venv

# Install the bash dispatcher.
make install-bin         # symlinks bin/clermes to ~/.local/bin/

# Start the Honcho memory backend (requires Docker + Ollama).
sudo mkdir -p /srv/pgdata/honcho && sudo chown 999:999 /srv/pgdata/honcho
ollama pull qwen3.5:latest && ollama pull nomic-embed-text
make honcho-up

# Set up config from examples.
mkdir -p ~/.clermes/registry
cp examples/config.yaml.example ~/.clermes/config.yaml
cp examples/fleet.json.example ~/.clermes/registry/fleet.json
$EDITOR ~/.clermes/config.yaml      # set instance.name and instance.principal
$EDITOR ~/.clermes/registry/fleet.json  # define your workers

# Install Claude Code bell hooks (fires when Claude needs input).
clermes install-claude-hooks --user

# Spawn your first worker.
clermes spawn scratch
```

## First dispatch

From the CLI:

```bash
# Send a task to the scratch worker.
clermes send scratch \
  "List all Python files modified in the last 7 days and write the count to a
done file.

TASK_ID: 2026-05-26-1200-count-py-files
On start: acquire ~/.clermes/locks/claude-scratch.lock.
On completion: write ~/.clermes/done/2026-05-26-1200-count-py-files.json.
If decision needed: write dispute file and stop."

# Wait for completion.
while [ ! -f ~/.clermes/done/2026-05-26-1200-count-py-files.json ]; do sleep 5; done
jq . ~/.clermes/done/2026-05-26-1200-count-py-files.json
```

From the Hermes plugin's `clermes_send` tool (inside the orchestrator session):

```python
result = clermes_send(
    worker="scratch",
    prompt="List all Python files modified in the last 7 days and write the count.",
    slug="count-py-files"
)
# result.task_id is the canonical handle to watch.
# TASK_ID footer is appended automatically.
```

Then drain events:

```python
events = clermes_drain_events(types=["done", "dispute"])
```

## Where to go next

- `docs/architecture.md`: system overview, layer breakdown, file channel table.
- `docs/protocol.md`: file-channel contract, done/dispute/announce schemas,
  lock semantics, task brief structure.
- `docs/bell-detection.md`: how the orchestrator learns a worker needs input.
- `docs/plugin.md`: Hermes plugin tool reference (10 tools + `/clermes` command).
- `docs/honcho.md`: Honcho memory backend setup, cold-start, pitfalls.
- `docs/recipes/`: worked examples: parallel dispatch, dispute flow,
  announce-then-act, troubleshooting.
- `skills/clermes-dispatch/SKILL.md`: operator skill loaded by the plugin.
- `skills/clermes-dispatch/references/dispatcher-pitfalls.md`: full pitfall
  list with reproduction transcripts.

## Status

Shelved as of October 2026. Active development is paused, and the planned
v1.0.0 release is shelved. The public repository is retained for reference.

## License

AGPL-3.0-or-later. See `LICENSE`.

Combined-work attributions (Honcho, plastic-labs/honcho): see `NOTICE`.
