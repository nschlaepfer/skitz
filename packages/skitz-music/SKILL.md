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

## Suno songs

Suno makes finished, produced audio from a text description, or from lyrics plus
style tags. That is different from the editable scores above. Use it when the user
asks for a full song or a Suno track. Each generation makes 2 clips and spends the
user's Suno credits, so confirm before generating more than once.

```python
from pathlib import Path
from skitz_music.suno import SunoClient, SunoError, build_payload

suno = SunoClient()  # reads SUNO_COOKIE or ~/.skitz/suno/cookie
suno.billing()       # {"credits": ..., "plan": ...}
payload = build_payload(description="warm lofi beat about rainy mornings", model="v4.5")
# Custom mode: build_payload(lyrics="[Verse]\n...", tags="indie folk, male vocals", title="...")
clips = suno.generate(payload)
done = suno.wait([c["id"] for c in clips], timeout=300)
suno.download(done, Path("songs/rainy-mornings"), request=payload)  # mp3s + manifest.json
```

`suno.lyrics(prompt)` drafts lyrics without spending credits. Model aliases are
`v3.5`, `v4`, `v4.5`, `v4.5+` and `v5`. Errors are `SunoError` with a `kind`. Stop and
tell the user on `auth_missing` or `auth_expired` (save a fresh cookie with
`skitz suno login -`), `captcha_required` (create one song by hand on suno.com) or
`out_of_credits`. Never try to solve or get around a captcha. On `timeout`, call
`wait` again with the same ids. Suno audio is a separate artifact, not a revision of
a Skitz score.
