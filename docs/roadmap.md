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
| Media search | Files are tracked by manifests and hashes (Suno downloads, stems, samples, renders); nothing searches their content | Multimodal search over the workspace (see Long-term plans) |

Recommended next milestone: make revising and comparing music ergonomic. Add
score/audio preview and A/B comparison, then extend the patch API for arrangement
(sections, new tracks) while retaining protected-content checks. Broaden the evaluation
suite alongside those edits. DAW/VST adapters can follow once that workflow is reliable.

## Long-term plans

### Search all media by meaning

Let the agent and the user find any sound, image or video in the workspace by
describing it ("dusty Rhodes loop in A minor", "the vocal chop from the JUJU B
session") or by example ("kicks that sound like this one"), instead of by filename.

- **Model.** [Gemini Embedding 2](https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2)
  (stable as `gemini-embedding-2` since April 2026, after a March preview) maps text, images,
  video (up to 120 s, MP4/MOV), audio (embedded natively, without transcribing it) and
  PDFs into one embedding space, so a text query can find audio and audio can find
  audio. Output can be 128 to 3072 dimensions (768, 1536 or 3072 recommended), which trades quality
  against index size. EmbeddingGemma 2, an open and lightweight multimodal model, is a
  candidate for an offline or no-upload mode and needs evaluating against it.
- **Index.** Embed every file the manifests already track (Suno songs, stems, loops,
  hits, renders), once per SHA-256, when it is created or imported. Cover art first needs
  its own step: manifests record Suno's `image_url` but don't save or hash the image, so
  download it next to the song and add it to the manifest before indexing. Split long
  audio into windows that fit the model's input limit, and keep the vectors in a local
  per-workspace store next to the manifest metadata.
- **Query.** Rank by similarity, then filter by the facts Skitz already measures: BPM,
  key and Camelot compatibility (`samples analyze`), stem type, source clip and
  duration. Expose it as `skitz search` and an MCP `media_search` tool, so a request like
  "find a loop that fits this 90 BPM A minor beat" becomes one call.
- **Constraints.** It needs a Gemini API key, added as its own provider credential.
  Uploading audio to Google should be opt-in per workspace, with a local model as the
  alternative. Embedding costs should be shown before large backfills. Only files the
  user saved are indexed, never Suno's protected player streams.

Upstream copyright notices, licenses and attribution remain. User-facing branding
can be Skitz without disguising where its execution engine originated.
