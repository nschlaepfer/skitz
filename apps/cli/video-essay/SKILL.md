---
name: video-essay
description: Produce or revise a video essay, trailer, or harness demo through a connected Scarlet project, with an editorial brief, reviewable cuts, optional Skitz score, and verified exports.
---

# Video Essay

Use Prime for the session, Scarlet for the timeline and review, and Skitz Music
for editable scores and mix renders. Take timing and edit state from Scarlet.

## Establish the brief

- Capture the thesis, audience, target duration, available media, required
  evidence or attribution, and any sequences the user wants protected.
- Read `project_get` and `timeline_get` (full) through the `scarlet` MCP server.
  Verify the project against the request. Record the base timeline version.
- If resuming an essay, inventory the existing cuts and source media before
  planning changes. If the only available asset is the archived six-second
  harness demo, identify it as a fixture in the brief and any review notes.

## Produce one reviewable sequence

1. Choose a bounded opening or section. Map each narrative beat to narration
   or dialogue, a picture or source, and a timeline range. Mark missing assets
   in the plan. Preserve the current order and timing of protected material.
2. Discover Scarlet's tool schemas. Propose edits against the recorded
   `fromVersion` using `intent: "suggestion"`. Include an editorial reason.
   Use explicit clip placements to avoid shifting approved sequences.
3. If music is requested, create or revise the cue through Skitz Music. Stage
   its audio with `skitz scarlet stage-audio`, import it with `asset_add`, and
   place it on its own track inside the selected picture range. Preserve source
   dialogue and record the score revision if there is one.
4. Reopen the proposal using its `toVersion`. Compare the before and after
   versions. Check the actual change ranges, duration, and clip timing outside
   the authorized section, including protected material. If the base changed
   while working, re-inspect the head before proposing another edit.

## Review and export

- Request a bounded preview of the proposed version, wait for render completion,
  and inspect its reported duration and streams. Report what was mechanically
  verified and what still needs a person to watch or listen to.
- For review, record the Scarlet project ID, base and proposed version IDs,
  change ID, edited ranges, render ID and any unresolved editorial decisions.
  Include the Skitz score revision and cue source if used.
- Export the specific approved version when the user asks for delivery.
  `export_otio` produces an editable timeline. Use Scarlet's render operation
  for a finished video. Include the export paths and version in the handoff.
