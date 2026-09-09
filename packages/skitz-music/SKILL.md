---
name: skitz-music
description: Compose, inspect, validate, render, and revise editable symbolic music. Use for music composition, SATB chorales, arrangement, notation, MIDI, and protected musical edits.
---

# Skitz Music

This is an executable Python skill. Import its modules inside the persistent kernel:

```python
from skitz_music import Score, Event, Track, Project
from skitz_music.analysis import (
    inspect_score,
    validate_score,
    analyze_voice_leading,
    compare_revisions,
)
from skitz_music.render import render_score
```

Create `Score(tracks=(Track(id="melody", name="Melody", events=(
Event(id="m001", offset="0", duration="3", pitch="G4"),)),))`.
Offsets and durations are exact strings in quarter-note units. Pitch spelling uses
music21 (`B-3`, `F#4`); `pitch=None` is an explicit rest. V1 supports fixed meter
and tempo, monophonic tracks, ties and basic articulations. Reject unsupported
imports rather than silently discarding chords, meter changes or tempo changes.

`Project("piece").create(score, protected_tracks=["soprano"])` creates an immutable
baseline. `project.read()` returns HEAD. Always inspect before editing:

```python
before = project.read()
report = project.apply_score_patch(
    expected_revision=before.revision,
    edits=[{"event_id": "b002", "set": {"pitch": "D3"}}],
    allowed_measures=[2],
    reason="Repair bass motion in bar 2",
)
```

Existing event pitches, ties and articulations can be changed. Timing, IDs and
track identities are immutable in this patch API. Use the project rollback API
to restore a saved revision. Do not edit `.skitz` files directly or remove policy.

`validate_score` checks structure independently of models. `analyze_voice_leading`
checks declared chorale conventions, not universal musical quality. Findings
include event IDs and offsets so repairs can be localized. `render_score(score,
output_dir, soundfont=sf2_path, audio=True, engrave=True)` emits MIDI, MusicXML,
LilyPond, PDF, WAV and a hash/version manifest. Inspect the manifest for failures.
Without a SoundFont, request notation/MIDI explicitly with `audio=False`.

Never describe score analysis as listening. Preserve first attempts and every
repair during evaluations. Auggie's Bach Benchmark is inspiration and a separate
direct-LilyPond task; the Skitz structured-score workflow is not a faithful one-shot
reproduction. Consult `docs/evaluation.md` in the Skitz checkout for conditions.
