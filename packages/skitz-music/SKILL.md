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

Scores use schema 2 (`uv run skitz schema` prints it; `skitz schema patch` prints
the edit format):

```python
score = Score(
    title="Sketch",
    key="C major",
    meter_map=({"measure": 1, "meter": "4/4"}, {"measure": 5, "meter": "3/4"}),
    tempo_map=({"measure": 1, "bpm": 96}, {"measure": 5, "bpm": 120}),
    tracks=(
        Track(id="melody", name="Melody", program=73, events=(
            Event(id="m001", offset="0", duration="3/2", pitches=("E5",)),
            Event(id="m002", offset="3/2", duration="1/2", pitches=("D5",)),
            ...,
        )),
        Track(id="piano", name="Piano", events=(
            Event(id="p001", offset="0", duration="4", pitches=("C4", "E4", "G4")),
            ...,
        )),
    ),
)
```

Offsets and durations are exact strings in quarter-note units. Pitch spelling uses
music21 (`B-3`, `F#4`). `pitches` holds none (an explicit rest), one (a note) or
several (a chord, stored low to high, no doubled keys). A tie joins a whole event to
the next one with the same pitches. Each track is one rhythmic line: events never
overlap, so independent rhythms need separate tracks. Meter and tempo (quarter
notes per minute) change only at measure starts; each map starts at measure 1 and
lists real changes only. Every track must fill whole measures of the meter map and
all tracks end together. `meter="3/4"`, `tempo=90` and `pitch="G4"` are accepted
shorthand. Imports keep chords, meter/tempo changes at barlines and staccato, tenuto
or accent; they reject voices inside one part, pickups, changes inside a measure and
anything else they cannot hold exactly.

`Project("piece").create(score, protected_tracks=["melody"])` creates an immutable
baseline. `project.read()` returns HEAD. Always inspect before editing:
`inspect_score(score)` lists each event's measures and a measure grid with start,
meter and tempo per measure.

```python
before = project.read()  # p002: a half-note chord at the start of bar 2
report = project.apply_score_patch(
    expected_revision=before.revision,
    edits=[
        {"op": "split", "event_id": "p002", "durations": ["1", "1"], "new_ids": ["p002b"]},
        {"event_id": "p002b", "set": {"pitches": ["D4", "F4", "B4"]}},
    ],
    allowed_measures=[2],
    reason="Add a passing chord in bar 2",
)
```

Edits apply in order, and measure numbers mean the score as it is at that step:

- `set` (the default op): `pitches` (or `pitch`), `tie`, `articulation` or `duration`.
  The offset never moves.
- `insert`: `track_id` and a full `event` with a new ID at an exact offset.
- `delete`: `event_id`. Other edits must fill its time.
- `split`: `event_id`, part `durations` that add up to the event, `new_ids` for the
  parts after the first (which keeps its ID and articulation); `tie: true` holds the
  sound instead of restriking.
- `merge`: back-to-back `event_ids` of one track become the earliest event.
- `replace`: `track_id`, contiguous `measures` and `events` (ID, duration, pitches,
  tie, articulation; no offsets) that fill those measures exactly. The track's events
  starting there are removed; reuse a removed ID to keep its identity.
- `transpose`: `track_id`, a spelled `interval` (`M2`, `-P5`, `m3`, `P8`) and optional
  `measures` (whole track when omitted).
- `set_tempo` / `set_meter`: `measure` and `bpm` / `meter`, or null to remove that
  change.

Nothing shifts implicitly: a patch that leaves a gap, an overlap, a broken tie or
an incomplete measure is rejected whole, with the findings. Every measure whose
events, barlines, meter or tempo change must be in `allowed_measures` (a tempo
change affects measures until the next change; a meter change that alters bar
length moves every later barline). New IDs must be unused, untouched events keep
their IDs, and protected tracks cannot change. The report lists changed, added and
removed event IDs and `changed_measures`. Use the project rollback API to restore a
saved revision. Do not edit `.skitz` files directly or remove policy. Schema-1
projects migrate automatically on first read; old revision IDs keep working.

`validate_score` checks structure independently of models. `analyze_voice_leading`
checks declared chorale conventions, not universal musical quality. Findings
include event IDs and offsets so repairs can be localized. `render_score(score,
output_dir, soundfont=sf2_path, audio=True, engrave=True)` emits MIDI, MusicXML,
LilyPond, PDF, WAV and a hash/version manifest. Inspect the manifest for failures.
With no `soundfont`, it uses `SKITZ_SOUNDFONT` or the font from `skitz soundfont
install`; without any, it skips audio and sets `audio_skipped`. `skitz_music.playback.play(project_or_file)`
plays the newest audio render of HEAD; pass `background=True` so the turn
continues, and the user's Skitz screen shows live spectrum bars while it plays.
`skitz_music.playback.stop()` stops it.

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
suno.download(done, Path("songs/rainy-mornings"), request=payload)  # audio + manifest.json
```

As of October 2026, Suno serves no audio to API clients; its Download button builds the
file in the browser, with the clip id in the file's metadata. `download` imports the
user's downloads from `~/Downloads` or `~/.skitz/suno/inbox` by that id. For songs not
downloaded yet it raises `SunoError` kind `download_restricted` (exit code 7) with
`song_urls`. Ask the user to click Download on those pages, or call
`suno.download(done, folder, request=payload, wait_for_browser=True)` to open them and wait
for the files. Never try to read the web player's protected stream. Stems still come from
Get Stems > Download on suno.com or from `skitz_music.separate`.
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
