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
With no `soundfont`, it uses `SKITZ_SOUNDFONT` or the font from `skitz soundfont
install`; without any, it skips audio and sets `audio_skipped`. `skitz_music.playback.play(project_or_file)`
plays the newest audio render of HEAD.

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
payload = build_payload(description="warm lofi beat about rainy mornings", model="v6")
# Custom mode: build_payload(lyrics="[Verse]\n...", tags="indie folk, male vocals", title="...")
clips = suno.generate(payload)
done = suno.wait([c["id"] for c in clips], timeout=300)
suno.download(done, Path("songs/rainy-mornings"), request=payload)  # mp3s + manifest.json
```

As of October 2026, Suno blocks audio downloads for API clients: `download` raises
`SunoError` with kind `download_restricted` (exit code 7). Ask the user to download
the song or stems on suno.com, then work on those files with `skitz_music.samples`.
`suno.stems(clip_id)` lists the 12 stems in 2 variants, and
`tempo_from_downbeats(suno.downbeats(clip_id))` gives `bpm` and `first_downbeat`.
Pass those to `chop_loops(..., bpm=..., offset=...)` to cut on Suno's bar lines.
Making stems needs a captcha in the web app, so never try to automate it.

`suno.lyrics(prompt)` drafts lyrics without spending credits. Model aliases are
`v6` (default), `v6-wild`, `v6-mini`, and the older `v5`, `v4.5+`, `v4.5` and `v4`. Errors are `SunoError` with a `kind`. Stop and
tell the user on `auth_missing` or `auth_expired` (save a fresh cookie with
`skitz auth login suno`), `captcha_required` (create one song by hand on suno.com) or
`out_of_credits`. Never try to solve or get around a captcha. On `timeout`, call
`wait` again with the same ids. Suno audio is a separate artifact, not a revision of
a Skitz score.

## Samples from Suno

Use Suno as a sample source: generate focused instrumental material at a known
tempo, cut it into loops and one-shots, then layer those into new audio. This needs
ffmpeg.

```python
from skitz_music import samples

payload = build_payload(tags="dusty boom bap drum break, no melody", instrumental=True, bpm=90)
clips = suno.wait([c["id"] for c in suno.generate(payload)], timeout=300)
saved = suno.download(clips, Path("songs/drums"), request={**payload, "skitz_bpm": 90})
mp3 = saved["files"][0]["path"]

samples.info(mp3)                                         # length, peak, BPM recorded/estimated
loops = samples.chop_loops(mp3, "samples/drums", bars=2)  # BPM read from the Suno manifest
hits = samples.chop_hits(mp3, "samples/drum-hits", max_hits=16)
samples.slice_sample(mp3, "samples/fx", start=12.0, end=14.5, name="riser")
samples.layer(
    "out/beat.wav",
    [
        {"sample": loops["outputs"][0]["path"], "at": 0, "repeat": 4, "every": 2},
        {"sample": hits["outputs"][0]["path"], "at": 3, "unit": "beat", "gain_db": -4},
    ],
    bpm=90,
    bars=8,
    base="piece/renders/<run>/score.wav",  # optional: mix over a Skitz score render
)
```

To sample from a full mix, split it into stems first. This runs locally on the
Apple GPU, at about 8 s per 30 s of audio per model:

```python
from skitz_music.separate import separate

split = separate(mp3, "stems/song", drumkit=True)  # vocals drums bass guitar piano other
kick = split["drumkit"]["stems"]["kick"]["path"]     # plus snare toms hh ride crash
samples.chop_hits(kick, "samples/kicks", max_hits=8)
samples.chop_loops(split["stems"]["bass"]["path"], "samples/bass", bars=2)  # BPM carried over
```

Presets: `stems` (BS-RoFormer SW, 6 stems, the default), `4stem` (HTDemucs,
MIT-licensed), `vocals` (Mel-Band RoFormer) and `drumkit` (MDX23C DrumSep). A stem
marked `silent` had nothing in it, for example vocals in an instrumental. The default
checkpoint has no stated license, so treat its stems as personal-use. The first run
downloads about 700 MB of weights to `~/.skitz/models/separation`.

To edit a stem as notation, transcribe it into a new project. This runs Spotify's
basic-pitch 0.4.0 locally in its own uv tool environment (CoreML on Apple Silicon,
about 10 s for 3 minutes of audio; the first run installs about 350 MB):

```python
from skitz_music.transcribe import transcribe

result = transcribe(split["stems"]["bass"]["path"], "projects/song-bass")  # BPM carried over
result["warnings"], result["notes"], result["onset_shift"]                # check these first
project = Project("projects/song-bass")  # then inspect, patch and render as usual
```

Tempo comes from `bpm`, then `downbeats` (a saved `skitz suno downbeats` JSON), then
the BPM Skitz recorded for the clip or its stems, then `estimate_bpm` (flagged in
`warnings`). Pass `offset`, the first downbeat in seconds, so bar lines match the
song; notes before it become a pickup. Notes snap to `grid` (16 = sixteenths, the
default; 8, 4, 32, and 12 or 24 for triplets) and notes under half a step are
dropped. Each track is one monophonic line with explicit rests, and notes crossing
a bar line are tied. Overlapping notes are resolved by `line`: `bottom` for bass,
`loudest` for vocals, `top` otherwise, and a note under half as loud as the one it
competes with never wins (overtones). `tracks=3` peels chords into three tracks
instead. `join_repeats=True` merges same-pitch notes that vibrato split apart. The
key is estimated unless you pass `key`, and pitches are spelled in it. Drums are
refused; cut them with `chop_hits`.

The project gets `transcribe-manifest.json` (source hash, model and version, tempo
sources, grid, and the count of notes merged, truncated or dropped and why) and
`transcription/basic-pitch.mid` with the raw notes. If `onset_shift.mean_ms` is
near a quarter of `grid_step_ms`, the tempo or offset is wrong. A transcription is
an estimate: dense chords, pads and full mixes come out poorly, so separate first,
and render the score to compare it with the stem before calling it faithful.

Placements are 0-based in `bar` (default with bpm), `beat` or `second` units. Each
operation writes 16-bit, 44.1 kHz stereo WAVs plus a manifest with source hashes and
cut points. Mixes that would clip are scaled to -1 dBFS and say so. Prompt Suno for
isolated material ("drums only", "solo Rhodes chords", "no vocals") and put the tempo
in `bpm`, so loops land on the bar grid. `estimated_bpm` is a rough estimate that
can be off by double or half. Prefer the recorded BPM, or cut by `every` seconds.
