# Upstream Provenance

- Repository: https://github.com/PrimeIntellect-ai/prime-agent
- Commit: `f771dfcedd684d1afff84ca2c6fa95c7a21efbc2`
- Source version: `0.9.4`
- Imported: 2026-09-08
- Method: `git archive <commit> | tar -x -C vendor/prime-agent`
- Full source snapshot, no nested `.git`. Skitz's existing history is retained.
- Original Skitz base: `a7e6572` on `main`; integration branch: `skitz-cli`.

Local upstream patches:

1. `packages/ai/src/stream.ts`: when `SKITZ_SUBSCRIPTION_ONLY=1`, reject model
   dispatch outside `openai-codex` / `openai-codex-responses`. Includes a focused test.
2. `packages/coding-agent/src/cli-main.ts`: when `SKITZ_DISABLE_UPDATES=1`, refuse
   update commands before startup, including the child used by interactive `/update`.
3. Corresponding package change fragments and the subscription regression test.

All other product code lives outside the imported runtime. Preserve inherited
workspace package names, OAuth contracts and copyright notices. `npm ci` uses the
upstream lockfile; Python music dependencies use the root `uv.lock`.

To refresh: import a separately reviewed commit, reapply the listed patches,
record the new SHA, rerun upstream checks, subscription tests, local tests,
MCP integration and live music acceptance. Never run a global find/replace rename
or allow Prime's self-updater to replace Skitz's pinned runtime.

Reference rendering SoundFont used during development (not vendored):
GeneralUser GS, S. Christian Collins, repository
https://github.com/mrbumpy409/GeneralUser-GS at
`684543d5e5efaef08d02be50dcda8d552478fa60`.
`GeneralUser-GS.sf2` SHA-256:
`9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe`.
Its license is published in that repository's `documentation/LICENSE.txt`.
