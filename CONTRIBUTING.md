# Contributing to Skitz

## Setup

Requires Python 3.11+, Node.js 22.8+, npm, uv and ffmpeg (`brew install ffmpeg`).

```sh
npm run setup      # pinned Prime runtime + Python packages
npm run check      # ruff, pytest, TypeScript and the Prime runtime checks
```

`npm run check` is exactly what CI runs. It must pass before a pull request can merge.

## Workflow

`main` is protected: changes land through pull requests with passing CI, and
force pushes and branch deletion are blocked.

1. Branch from `main` with a short name, such as `feat/suno-stems` or `fix/render-timeout`.
2. Keep each pull request focused. Fill in the template, including how you tested.
3. Wait for the `check` job to pass, resolve review conversations, then merge.
   Branches are deleted automatically after merging.

## Conventions

- Python follows `ruff` at a line length of 100. Run `uv run ruff format` on files you touch.
- Every CLI command prints one JSON object. Errors go in JSON too, with an exit
  code an agent can act on.
- Tests live in `tests/`. Network calls are mocked with `httpx.MockTransport`.
  Anything that needs a real account or a large model download is opt-in through
  an environment variable.
- `vendor/prime-agent` is pinned. Update it only through a reviewed source import
  (see `docs/upstream.md`).

## Secrets

Never commit or paste credentials: no Suno cookies, access tokens, OAuth files or
API keys. They live under `~/.skitz` or in environment variables, outside the
repository.
