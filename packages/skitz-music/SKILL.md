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

Placements are 0-based in `bar` (default with bpm), `beat` or `second` units. Each
operation writes 16-bit, 44.1 kHz stereo WAVs plus a manifest with source hashes and
cut points. Mixes that would clip are scaled to -1 dBFS and say so. Prompt Suno for
isolated material ("drums only", "solo Rhodes chords", "no vocals") and put the tempo
in `bpm`, so loops land on the bar grid. `estimated_bpm` is a rough estimate that
can be off by double or half. Prefer the recorded BPM, or cut by `every` seconds.

## Fitting, mixing and exporting samples

Analyze a sample, fit it to the song's tempo and key, mix with effects, and hand the
result to a DAW. Fitting and effects use Spotify's pedalboard, installed with the
Skitz workspace (`pip install 'skitz-music[fx]'` elsewhere). Without it, `fit_sample`
falls back to Rubber Band through ffmpeg; gain, pan and `limit` work without either.

```python
report = samples.analyze(mp3)  # tempo, key and chords; every section has "estimate": True
report["tempo"]   # {"bpm": 92.0, "confidence": 0.8, "alternatives": [46.0, 184.0], "first_beat": 0.04}
report["key"]     # {"key": "A minor", "camelot": "8A", "alternatives": [...], "confidence": ...}
report["chords"]["progression"]  # ["Am", "F", "C", "G"], one major/minor triad per bar

fitted = samples.fit_sample(mp3, "samples/keys", bpm=90, key="C minor")  # or semitones=-2
samples.chop_loops(fitted["outputs"][0]["path"], "samples/keys-loops", bars=2)  # BPM carried
samples.apply_fx("stems/song/vocals.wav", "fx/vocals.wav", "hp=120,comp=-20/3,reverb=0.15")

plan = [
    {"sample": loop, "at": 0, "repeat": 4, "every": 2, "fx": {"highpass": 40, "compress": -18}},
    {"sample": hit, "at": 3, "unit": "beat", "pan": -0.3, "gain_db": -4,
     "fx": {"delay": {"beats": 0.75, "feedback": 0.3, "mix": 0.25}, "reverb": 0.2}},
]
samples.layer("out/beat.wav", plan, bpm=90, bars=8, master={"compress": -14, "limit": True})
samples.export_plan("out/beat-daw", plan, bpm=90, bars=8, master={"limit": True})
```

Every `analyze` result is an estimate from the signal, not listening. Say so when you
report it, and prefer a BPM or key the user or Suno gave. Tempo can lock to double or
half; `first_beat` is the strongest beat phase, not necessarily bar 1. Relative keys
(C major and A minor) are easy to confuse, so check the `alternatives`. Chords are
major/minor triads only, on a grid of one bar (`chord_beats` changes it).

`fit_sample` changes tempo and pitch independently. Without `source_bpm` it uses the
recorded Suno or fit BPM, then an estimate; without `source_key`, an estimate. The
manifest's `estimated` list names any guessed input. Keys shift by -6 to +5
semitones. Between major and minor it lands on the target's relative key (C major fit
to D minor is F major, which shares D minor's notes), recorded as `key_relation`. The
manifest records `tempo_ratio`, `length_ratio`, `semitones`, `pitch_ratio` and the
engine. Loops stay exact: the output is input length / tempo ratio.

Effects take a dict or a chain string and always run in this order: `highpass` and
`lowpass` (Hz, or `{hz, slope}` in 6/12/18/24 dB/octave), `low_shelf`/`high_shelf`
`{hz, db, q}`, `peak` (one or a list of `{hz, db, q}`), `compress` (`{threshold_db,
ratio, attack_ms, release_ms, makeup_db}`), `delay` (`{beats | seconds, feedback,
mix}`), `reverb` (wet, or `{wet, room, damping, width, dry}`), `gain_db`, `pan`
(-1 left to 1 right, balance law) and `limit` (`true` or `{ceiling_db, release_ms,
lookahead_ms}`). `limit` is a lookahead brickwall: nothing passes `ceiling_db`
(default -1 dBFS) and quieter material is untouched. The chain string form is
`hp=120/24,lowshelf=200/-3,peak=1000/-4/2,comp=-18/4,delay=0.75q/0.3/0.25,reverb=0.2,pan=-0.5,limit`.

Placement effects run on that placement's own lane, so tails carry across repeats.
Its `gain_db` and `pan` then act as the fader. Placements that share a `track` name
(default: the sample's file name) form one track. `master` runs on the sum. Manifests
record every resolved stage with its defaults, the pedalboard version and the peak
before safety scaling.

`export_plan` writes `<name>.wav` (the mastered mix) and `stems/NN-<track>.wav`: 32-bit
float, starting at 0 s, after placement effects and before the master, so they sum to
the pre-master mix. It also copies the source samples to `samples/` and writes
`placements.mid`, a type-1 MIDI file with the tempo, the time signature and one track
of notes per stem. Notes default to C3 (60, as Ableton Live and Logic Pro number it),
or set `note` per placement; velocity follows `gain_db`. In the DAW, set the project
tempo and drop the stems at bar 1, or load `samples/` into a sampler and play them
from the MIDI.
