# Refactor Status and Next Work

Skitz is a working first version, not a replacement for every part of Prime.
The original two-call ABC script is preserved as legacy, and is no longer the
active orchestration path. New Skitz code owns symbolic scores, protected edits,
validation, rendering, the local interface, MCP tools and evaluation conditions.
Prime still provides the agent loop, Python kernel, terminal framework, sessions,
subagents and subscription provider implementation.

At the initial refactor there were approximately 1,600 lines of custom Python/TypeScript
source, plus about 380 lines of Python tests. The vendored harness contains 1,258
upstream files. A percentage of lines renamed or rewritten would not measure
product completeness; the important distinction is which behavior Skitz owns.

| Area | Current State | Next Useful Work |
| --- | --- | --- |
| Agent execution | Live subscription composition and repair verified | Independently owned autonomous completion gates |
| Score model | Exact rhythms, spelled pitches, chords, meter/tempo maps, stable IDs | Key changes, independent voices per track, dynamics and richer expression |
| Editing | Protected pitch, chord, rhythm (split/merge/insert/delete/replace), transposition and tempo/meter edits with rollback | Arrangement edits (add/move sections, add tracks) and readable musical diffs |
| Playback and notation | PDF, MIDI, MusicXML and WAV with hashes | In-app playback, score preview and synchronized passage selection |
| Revision comparison | Exact event differences and unchanged tracks | A/B auditions and readable musical diffs |
| Evaluation | Structural checks, limited chorale rules, separated response/repair runs | Held-out tasks, multiple styles and blind human comparisons |
| Product identity | Skitz primary terminal branding and ChatGPT sign-in | Music-specific starter prompts, settings and advanced diagnostics |
| Distribution | Source install; macOS restricted rendering | Packaged releases, bundled renderer setup and other-platform workers |

Recommended next milestone: make revising and comparing music ergonomic. Add
score/audio preview and A/B comparison, then extend the patch API for arrangement
(sections, new tracks) while retaining protected-content checks. Broaden the evaluation
suite alongside those edits. DAW/VST adapters can follow once that workflow is reliable.

Upstream copyright notices, licenses and attribution remain. User-facing branding
can be Skitz without disguising where its execution engine originated.
