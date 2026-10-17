---
name: skitz
description: Use Skitz to create, inspect, validate, render and make protected edits to symbolic music projects from Codex. Use for music notation, SATB, MIDI and controlled musical revisions in this repository.
---

# Skitz for Codex

Use the local Skitz MCP tools when connected. Otherwise run `uv run skitz` from
this repository. `uv run skitz schema` exposes the exact canonical score format.
Read `packages/skitz-music/SKILL.md` for Python calls, representations and edit
constraints. These operations run locally without model calls or API keys.

For autonomous music tasks delegated to the Prime harness, use `uv run skitz agent`
after the user signs in with `uv run skitz login`. It uses the user's ChatGPT
subscription. Do not request an API key or copy credentials from other apps.

Inspect HEAD, declare the allowed measures, patch against that revision, validate,
render and compare. Preserve protected tracks and save evidence for every revision.
Do not overwrite validators or manually mutate project state. Treat chorale
conventions as style-specific diagnostics and audio generation as rendering,
not listening. The authored demo and deterministic evaluation are test fixtures,
not model-generated music or a Bach Benchmark score.

Check connections with `uv run skitz auth --json` (Suno and ChatGPT). If Suno is not
connected, ask the user to run `uv run skitz auth login suno`. It is guided, and you
never handle the cookie. For finished, produced songs, use the `suno_*` MCP tools or `uv run skitz suno`
(`--help` lists exit codes). They use the user's own Suno session cookie and spend
Suno credits; each generation makes 2 clips. If you get `captcha_required`,
`auth_expired` or `out_of_credits`, stop and tell the user. Never work around a captcha. Suno currently blocks audio downloads for API clients
(exit 7, `download_restricted`). Ask the user to download from suno.com instead, and
never try to decrypt or work around it. `suno_stems` lists stems, and `suno_downbeats`
gives the BPM and bar offset for cutting loops.

To use Suno as a sample source, generate with a `bpm` (usually instrumental). Then
cut the result with the `samples_*` MCP tools or `uv run skitz samples` (stems, loops,
hits, slice, layer, info). `stems` splits a full mix on the local GPU into
vocals/drums/bass/guitar/piano/other, and `--drumkit` splits drums into kit pieces. `layer` builds new WAVs from samples, optionally over a Skitz
score render. Read `packages/skitz-music/SKILL.md` for the workflow.
