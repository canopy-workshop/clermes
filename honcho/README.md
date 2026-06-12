<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Honcho stack for clermes

Turnkey local Honcho deployment, wired for local LLMs by default.
Built so the operator agent and the Claude Code worker fleet share one
coherent model of the user.

## Topology

```
        ┌──────────────────┐
        │  Honcho server   │  api / deriver / postgres / redis
        │  127.0.0.1:8001  │  this directory's docker-compose.yml
        └────────┬─────────┘
                 │  same workspace + user peer
    ┌────────────┴────────────┐
    │                         │
  ~/.honcho/config.json   ~/.hermes/honcho.json
  (Claude Code plugin)    (Hermes plugin)
  workers write as        operator writes as
  aiPeer "claude"         aiPeer "<instance-name>"
    │                         │
    └──── user peer: matches ─┘
          workspace: matches
```

The same Honcho server backs both plugins. The two plugins are
independent codebases with independent config files; they only need
to agree on `workspace` and the user peer ID for the vectors to align.

## Quick start

```bash
# 1. From this directory:
cp honcho/.env.example honcho/.env
$EDITOR honcho/.env   # adjust if Ollama lives elsewhere or you want hosted providers

# 2. Make sure the postgres bind-mount target exists with the right owner.
sudo mkdir -p /srv/pgdata/honcho
sudo chown 999:999 /srv/pgdata/honcho

# 3. Make sure Ollama is running and the configured models are pulled.
ollama pull qwen3.5:latest
ollama pull nomic-embed-text

# 4. Bring up the stack from the repo root.
make honcho-up

# 5. Verify the API is reachable.
curl -s http://127.0.0.1:8001/health
```

The Dockerfile clones `plastic-labs/honcho` at the pinned ref during
the build. No manual Honcho checkout is required.

## Pinning Honcho

The `HONCHO_REF` build arg controls which version of Honcho the image
builds from. It accepts any git branch, tag, or commit SHA.

The default is `v3.0.7` (latest stable release as of 2026-05-26).

To override for a single run:

```bash
HONCHO_REF=v3.0.8 docker compose up -d --build
```

To pin persistently, set `HONCHO_REF` in your `.env` file. The
`.env.example` includes the variable with the same default the
compose file uses; keep them in sync when upgrading.

For production deployments, always pin to a specific tag or commit SHA.
`HONCHO_REF=main` will track the upstream head and may break without
warning when Honcho ships breaking changes.

## Configuration

Edit `.env` to swap providers. Defaults wire the deriver and embeddings
to a local Ollama on the host. `host.docker.internal` resolves to the
host via the `extra_hosts` entry in `docker-compose.yml`.

### Why the Qwen `think:false` knob matters

Qwen 3.5 has an extended thinking mode that fires unpredictably. When
it fires on a deriver call, the model emits a reasoning block instead
of strict JSON, the deriver logs `Repair failed: empty JSON`, and zero
observations are extracted from that batch. The `.env.example` ships
`DERIVER_MODEL_CONFIG__OVERRIDES__EXTRA_BODY={"think": false}` to keep
the structured-output path clean. Leave it in unless you have switched
to a model that does not have the toggle.

### Switching to a hosted provider

Drop the `OVERRIDES__BASE_URL` lines and add the relevant API key. The
deriver and embedding model configs follow Honcho's standard model
config format. See Honcho's docs for the full surface.

### Auth disabled by default

`AUTH_USE_AUTH=false` means the API accepts requests without a bearer
token. That is safe for a localhost-only install bound to `127.0.0.1`.
If you expose the port beyond localhost (reverse proxy, VPN, etc.),
set `AUTH_USE_AUTH=true` and configure tokens before doing so.

## Dialectic cadence

The `dialecticCadence` setting in `hermes-honcho.json.example` is set
to `10` by default. This controls how many turns pass between Hermes
triggering a dialectic (socratic) memory query.

Start at `10`. The first sessions after cold-start generate noisy,
low-signal observations; frequent dialectic queries during that period
produce little useful context and add latency. Once the memory has
warmed up over several working sessions, lower the cadence to `3-5` for
more responsive context retrieval.

The `contextCadence: 2` setting (passive context recall) is cheap and
can stay low from the start.

## Wiring the plugins

Both plugins must name the same workspace and the same user peer.

### Claude Code (workers)

```bash
cp honcho/claude-honcho.config.json.example ~/.honcho/config.json
$EDITOR ~/.honcho/config.json
```

Replace `YOUR_USER_PEER` with a stable handle for the human user
(immutable; pick once and live with it). Fill in the `sessions` map
with one entry per workdir for per-project memory.

### Hermes (operator)

```bash
cp honcho/hermes-honcho.json.example ~/.hermes/honcho.json
$EDITOR ~/.hermes/honcho.json
```

Replace `YOUR_USER_PEER` with the same value used in the Claude Code
config. Replace `YOUR_INSTANCE_NAME` with the operator's instance
handle (whatever you put in `~/.clermes/config.yaml` `instance.name`).
The user peer must match across both files; the aiPeer can differ.

Add the Honcho plugin in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: honcho
```

Restart Hermes; respawn the Claude Code workers with `clermes heal` so
they pick up the new `~/.honcho/config.json`.

## Durable state lives on a bind mount

Postgres data is bind-mounted at `/srv/pgdata/honcho/` (see the
`database` service in `docker-compose.yml`). That path is in the host's
daily backup. **Do not** move postgres to a named Docker volume; named
volumes are not in the backup path. If you need to migrate to a
different host directory, do it deliberately and update your backup
config to match.

Redis uses a named Docker volume (`redis-data`). Redis is a cache;
losing it means a cold cache, not data loss.

## Schema initialization

The `database/init.sql` file in this directory installs the `pgvector`
extension into Postgres on first start. Honcho's API container then runs
Alembic migrations on every startup to bring the schema to the current
version. Both steps are required: pgvector must exist before migrations
run, and Alembic handles the rest automatically.

## Peer renames

Peer IDs are immutable. There is no rename API. To re-identify a user,
start fresh in a new workspace:

```bash
BASE=http://127.0.0.1:8001/v3
WS=default

# Delete sessions in the old workspace first.
curl -s $BASE/workspaces/$WS/sessions/list -X POST \
  -H 'Content-Type: application/json' -d '{}' \
  | jq -r '.items[].id' \
  | xargs -I{} curl -s -X DELETE $BASE/workspaces/$WS/sessions/{}

# Then drop the workspace.
curl -s -X DELETE $BASE/workspaces/$WS

# Start fresh. First write to the new workspace creates it.
```

Update both plugin config files to point at the new workspace and
peer, restart Hermes, respawn workers.

## What this directory does not do

- It does not manage Ollama. Pull models yourself; the stack reaches
  Ollama through `host.docker.internal:11434`.
- It does not seed prior memory. If you want to bring flat-file memory
  in as starter context, see Honcho's import tooling.
- It does not pin the `plastic-labs/honcho` license for you. Honcho is
  AGPL-3.0-or-later; this bundle inherits that license. See `LICENSE`
  in the repo root.
