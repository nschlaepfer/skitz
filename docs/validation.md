# Verification Receipt - 2026-09-08

Environment: macOS ARM64; Python 3.11.13; Node 22.17.1; music21 9.9.2;
LilyPond 2.26.0; FluidSynth 2.6.0. Prime commit and SoundFont hashes are in
`upstream.md`. This is local verification, not a cross-platform release claim.

## Source and Runtime

- At the initial refactor, all 1,258 tracked upstream files were present. Only `packages/ai/src/stream.ts`
  and `packages/coding-agent/src/cli-main.ts` differ from the imported commit;
  additional regression/change-fragment files were documented. Subsequent product
  branding changes are listed separately in `upstream.md`.
- Original Skitz files and examples were checked against Git HEAD byte-for-byte.
- Root Python tests cover schema, edits, concurrency, import, rendering, MCP,
  benchmark conditions and export/verification.
- Upstream lint, type, installer and browser-smoke checks pass. The focused
  subscription-provider test passes; the direct upstream update command is refused
  when the Skitz flag is set.
- Actual ChatGPT OAuth sign-in completed. No API-key fallback was used.

## Live Music Run

A real `openai-codex` / `gpt-5.5` run used Prime's persistent Python tool and
the installed music skill to create an original four-bar SATB phrase in G minor
and 3/4, protect the soprano, diagnose six parallel-interval findings, and apply
two bounded repair patches.

- Initial revision: `50c1c429c41c2f29f1f2087bb0442716ee8f02b1c20e001088433d483b49d9b8`
- Intermediate revision: `e3b51824315a2b1a3fcf9100317e4d14cb35ca7638ff0edcc29c2b2ea35232d9`
- Final revision: `f0aeea4792188aef9a982259c12f012a4374abad7cb3c370a9f5e36221c7c183`
- Only `b002`, `b003`, `b005` differ between initial and final scores.
- Soprano, alto and tenor tracks are exactly unchanged.
- Final structural validation passes; the limited chorale checker reports no findings.
- MIDI, MusicXML, LilyPond, PDF and WAV were produced and independently hash-checked.
- The rendered PDF was visually inspected; WAV has nonempty audio frames.

The first autonomous invocation returned nonzero after its turn budget despite
having produced the complete artifacts. Do not count that process as a successful
autonomous-gate run. Independent `skitz verify` passed, and a subsequent ordinary
Prime agent invocation called the verifier and exited successfully. For formal
autonomous acceptance, provide an explicit independently owned completion gate.

## Other Conditions

The deterministic editing acceptance separately injected and detected a parallel
octave, restored exactly the edited bass event, preserved the soprano, and rendered
baseline, injected and repaired revisions. This is fixture-based harness testing.

A direct subscription response to the **paraphrased** Bach task compiled on its
first attempt. The run used 66 input tokens and 2,396 output tokens. It had no
tools while generating the response. It is not an exact-prompt reproduction,
musical-quality score or budget-matched comparison against the full Skitz run.
Provider-internal dollar estimates, where present in upstream traces, are catalog
metadata and do not establish billing; these calls used subscription authentication.

Raw development evidence is retained under ignored `work/acceptance`,
`work/live-composition` and `work/bach-subscription-smoke`. The accepted composition
export includes canonical revisions and derived artifacts but no OAuth credentials.
