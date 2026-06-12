<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Honcho Integration

## What Honcho is

Honcho (from Plastic Labs, `plastic-labs/honcho`) is a self-hosted
AI-native memory service built around peer-based user modeling and dialectic
recall. It stores observations about the user derived from conversational
context and makes them available across sessions and across agents.

Clermes uses Honcho to give the orchestrator and the Claude worker fleet a
single shared model of the user, so each agent builds on what the others
have learned rather than starting from scratch each session.

Honcho is AGPL-3.0-or-later. The clermes Honcho bundle inherits that license.
See the repo `LICENSE` and `NOTICE` files.

## How clermes uses Honcho

Two plugins, one server:

```
        Honcho server (127.0.0.1:8001)
        api / deriver / postgres / redis
              │
    ┌─────────┴──────────┐
    │                    │
~/.honcho/config.json  ~/.hermes/honcho.json
(Claude Code plugin)   (Hermes plugin)
workers write as       operator writes as
aiPeer "claude"        aiPeer "<instance-name>"
    │                    │
    └── user peer: same ─┘
        workspace: same
```

The two plugins are independent codebases. They only need to agree on the
`workspace` and `user peer` for the vectors to align. The `aiPeer` can differ
per agent; each builds its own self-model while reading the shared user
representation.

## Bringing the stack up

```bash
# From the repo root:
cp honcho/.env.example honcho/.env
$EDITOR honcho/.env         # adjust if Ollama lives elsewhere

# Ensure the postgres bind-mount target exists.
sudo mkdir -p /srv/pgdata/honcho
sudo chown 999:999 /srv/pgdata/honcho

# Pull the models Honcho needs.
ollama pull qwen3.5:latest
ollama pull nomic-embed-text

# Start the stack.
make honcho-up

# Verify.
curl -s http://127.0.0.1:8001/health
```

Full wiring instructions are in `honcho/README.md`. That file covers config
templates, plugin setup for both sides, and the peer rename procedure.

## Dialectic cadence

The `dialecticCadence` setting in `~/.hermes/honcho.json` controls how many
turns pass between the orchestrator triggering a dialectic (Socratic) memory
query.

The default is `10`. The reason to start high: during cold start, Honcho
has no observations about the user and the dialectic fires against an empty
model, producing noisy or generic context injections. Frequent dialectic calls
during that period add latency without adding useful signal.

Once the memory has warmed up over several working sessions (`honcho_profile`
returns real facts), lower `dialecticCadence` to `3-5` for more responsive
context retrieval.

`contextCadence: 2` (passive context recall) is cheap and can stay low from
the start.

## The `think: false` Qwen knob

If you are running Qwen 3.5 as the deriver model via Ollama, the `.env` must
include:

```env
DERIVER_MODEL_CONFIG__OVERRIDES__EXTRA_BODY={"think": false}
```

Why this is required: Qwen 3.5 has an extended thinking mode that activates
unpredictably. When it fires on a deriver call, the model emits a reasoning
block instead of strict JSON output. The deriver logs `Repair failed: empty
JSON` and extracts zero observations from that batch.

Setting `think: false` via `EXTRA_BODY` disables extended thinking for deriver
calls, which need structured JSON output, not open-ended reasoning. The toggle
does not affect Qwen in other contexts.

After changing `.env`, restart the deriver container:

```bash
docker compose restart deriver   # from the honcho/ directory
```

## Workspace rotation procedure

Peer IDs in Honcho are immutable. There is no rename API. If you need to
re-identify a user or fix a bad workspace name, the procedure is:

1. List and delete all sessions in the old workspace:
   ```bash
   BASE=http://127.0.0.1:8001/v3; WS=<old-workspace>
   curl -s $BASE/workspaces/$WS/sessions/list -X POST \
     -H 'Content-Type: application/json' -d '{}' \
     | jq -r '.items[].id' \
     | xargs -I{} curl -s -X DELETE $BASE/workspaces/$WS/sessions/{}
   ```
2. Delete the workspace: `curl -s -X DELETE $BASE/workspaces/$WS`
   (fails with 409 while sessions exist; complete step 1 first).
3. Update both config files (`~/.honcho/config.json` and
   `~/.hermes/honcho.json`) to the new workspace and peer names.
4. Restart Hermes; run `clermes heal` to respawn workers so they pick up
   the new `~/.honcho/config.json`.

## Cold-start observations are noisy (pitfall 15)

Fresh Honcho has no observations about the user. During cold start:

- `honcho_profile` returns "No profile facts available yet." This is normal,
  not an error.
- The deriver processes turn batches but extracts zero or generic observations
  because there is no anchoring context. This clears up after a few real sessions.
- The dialectic may fire incoherent queries (generic category names like
  "medications," "open-source community," "ML research") because it is
  pattern-matching against example categories with no priors. This is the
  primary reason to keep `dialecticCadence` high during cold start.
- The dialectic may inject malformed `<memory-context>` blocks. Ignore them;
  they are a side-effect of the deriver returning empty output.

## The silent tally pattern (pitfall 17)

Honcho occasionally injects context blocks that are clearly wrong for the
conversation. The most common case: generic crisis-support or wellness
boilerplate landing in a technical session because the deriver
pattern-matched frustrated debugging language as distress signals.

The recommended handling for the orchestrator:

- Do NOT announce each misfire as it happens. That is noise.
- Keep a silent running count of context blocks that are plainly wrong (not
  just stale or tangential, but factually incorrect for the user's state).
- When the count reaches 10 in a session, surface to the operator and file a
  bug report.

**Remediating a bad Honcho conclusion:** deleting the source document from
Postgres is not enough. Honcho caches derived conclusions in Redis and
continues serving them. Full remediation requires: (1) delete the source
Postgres document, (2) flush Redis (or nuke the Redis cache), and (3) accept
that the conclusion may continue firing for the current session if the
meta-conversation about it becomes itself a source of re-derivation. The
conclusion resolves cleanly in future sessions once the offending context
is no longer recent.

## Flat-file memory stays active

`memory.provider: honcho` in `~/.hermes/config.yaml` adds Honcho alongside
the built-in flat `MEMORY.md` / `USER.md` store. The flat file is never
replaced. Keep hand-curating it as the zero-dependency fallback: if Honcho's
Postgres or API container fails, the flat file is the only memory that
survives with no moving parts.

Honcho is a self-hosted service that can crash-loop on startup (observed:
the api container failing to resolve the `database` host during container
bring-up). The flat file covers the gap.

## Durable state

Postgres data is bind-mounted at `/srv/pgdata/honcho/`. This path is in the
host's daily backup. Do not move Postgres to a named Docker volume; named
volumes are not in the backup path.

Redis uses a named Docker volume (`redis-data`). Redis is a cache; losing it
means a cold cache rebuild, not data loss.
