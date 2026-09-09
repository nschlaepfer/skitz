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
