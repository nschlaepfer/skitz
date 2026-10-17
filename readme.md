# Skitz

A terminal music agent. Sign in with your **ChatGPT
subscription**, compose an editable score, render it, and make revisions that
preserve protected tracks. No OpenAI API key is needed or used by the launcher.

## Start

Requires Python 3.11+, Node.js 22.8+, npm and uv. The complete pinned Prime source
is included in `vendor/prime-agent`; no separate Prime installation is required.

```sh
npm run setup
uv run skitz doctor
uv run skitz login
uv run skitz agent
```

`login` opens ChatGPT sign-in in your browser. Subscription eligibility, model
availability and limits are controlled by OpenAI. Skitz stores its own OAuth
session under `~/.skitz/agent`, separately from Codex and Prime. It never imports
their credentials. Set `SKITZ_HOME` to use another Skitz state directory.

Example request:

> Compose four bars for soprano, alto, tenor and bass in G minor and 3/4.
> Protect the soprano. Validate, repair parallel fifths or octaves in the other
> voices, and render a score and audio. Preserve all revisions.

The initial model is Prime's pinned Codex default, `gpt-5.5`. Select another
subscription model with `uv run skitz agent --model <model-id>` or `SKITZ_MODEL`.
API-key providers and overrides are blocked. The terminal mark, window title,
help and subscription menu use the Skitz identity. First launch signs in with
ChatGPT rather than opening an upstream onboarding flow. Internal runtime package
names and protocol versions are preserved; the terminal's version label currently
shows the pinned engine version. Some inherited coding-oriented prompts and
advanced diagnostic text remain for a later music-interface pass.

## Music Tools

```sh
uv run skitz schema
uv run skitz create my-piece score.json --protect soprano
uv run skitz inspect my-piece
uv run skitz validate my-piece
uv run skitz analyze my-piece
uv run skitz patch my-piece patch.json
uv run skitz render my-piece --soundfont /path/to/GeneralUser-GS.sf2
uv run skitz verify my-piece --require-audio
uv run skitz export my-piece accepted-piece.zip
```

`uv run skitz demo demo-piece` creates a clearly labeled authored test fixture.
`uv run skitz import imported-piece source.abc` imports supported ABC or
uncompressed MusicXML. Unsupported constructs fail explicitly. Original Skitz
scripts and documentation live in `legacy/`; original examples remain in `Examples/`.

Scores use exact quarter-note fractions, spelled pitches, stable event IDs,
monophonic tracks, fixed meter/tempo, explicit rests, ties and basic articulations.
The canonical JSON revision is the source of truth. Edits currently support
pitch, tie and articulation changes within named measures. Arbitrary DAW sessions,
polyphonic track import, changing tempo/meter maps and lossless LilyPond import
are not supported in this first version.

## Suno Songs

Skitz can also make finished songs on your own Suno account, for requests that
want produced audio rather than an editable score. Suno has no public API, so this
uses your suno.com web session and its private endpoints. These can change without
notice, and automating them may conflict with Suno's terms. Every generation spends
your Suno credits.

Connect your account once. The command opens the right pages and walks you through
copying one cookie, then checks it with Suno before saving:

```sh
uv run skitz auth login suno     # or: uv run skitz login suno
uv run skitz auth                # status of Suno and ChatGPT
uv run skitz suno whoami
uv run skitz suno generate -d "warm lofi beat about rainy mornings" --out songs/rain
uv run skitz suno generate --title "Night Drive" -t "synthwave, female vocals" \
  --lyrics-file lyrics.txt -m v5 --out songs/night-drive
uv run skitz suno lyrics "a sea shanty about debugging"
```

**What works today (verified live, October 2026).** Credits, generation requests,
status, lyrics, models (`skitz suno models --live`), stem listings and Suno's beat
grid all work. **Audio downloads do not.** Suno now returns `audio_url:
/api/forbidden` for songs and stems, and the alternative `media_urls` are encrypted
for its web player. Skitz reports this as exit code 7 and does not try to get around
it. Download songs or stems on suno.com (Get Stems > Download), then use
`skitz samples` on the files. `skitz suno stems <clip>` lists a clip's 12 stems in 2
variants. `skitz suno downbeats <clip>` returns Suno's BPM and bar-1 offset, which
you can pass to `samples loops --bpm --offset`. Making stems needs a captcha in the
web app, so start them there. The default model is v6 (`chirp-hawk`), and the
sign-in host is `auth.suno.com`. A short-lived access token can stand in for the
cookie through `SUNO_JWT`.

The cookie is saved to `~/.skitz/suno/cookie` with mode 600 (or set `SUNO_COOKIE`).
Each download folder gets a `manifest.json` with the request, clip metadata and file
hashes. The agent uses `skitz_music.suno`, and MCP clients get `suno_credits`,
`suno_generate`, `suno_status`, `suno_wait` and `suno_lyrics`. When Suno asks for a
captcha, Skitz stops with exit code 4. Create one song by hand on suno.com, then
retry. Skitz never tries to solve or get around a captcha.

### Samples

Suno clips can also be cut into samples and layered into new audio (needs ffmpeg):

```sh
uv run skitz suno generate -i -t "dusty boom bap drum break" --bpm 90 --out songs/drums
uv run skitz samples info songs/drums/<clip>.mp3
uv run skitz samples stems songs/drums/<clip>.mp3 --drumkit --out stems/drums
uv run skitz samples loops songs/drums/<clip>.mp3 --bars 2 --out samples/drums
uv run skitz samples hits songs/drums/<clip>.mp3 --max 16 --out samples/drum-hits
uv run skitz samples layer out/beat.wav --bpm 90 --bars 8 \
  --place samples/drums/<loop01>.wav:0:x4/2 \
  --place samples/drum-hits/<hit01>.wav:3q:x8/4:-4dB \
  --base my-piece/renders/<run>/score.wav
```

`--bpm` on `generate` adds the tempo to the Suno prompt and records it, so `loops`
cuts on the bar grid without being told again. Stems carry that tempo too.

`stems` separates a full mix locally on the Apple GPU through
[python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator),
run in its own uv tool environment so PyTorch stays out of the Skitz venv. The
default is BS-RoFormer SW, which outputs vocals, drums, bass, guitar, piano and
other. It is the top single model for drums and bass on the
[MVSEP leaderboard](https://mvsep.com/quality_checker/multisong_leaderboard).
`--drumkit` adds MDX23C DrumSep: kick, snare, toms, hi-hat, ride and crash. On an
M3 Max, 30 s of audio takes about 8 s per model. Other presets are `4stem` (HTDemucs,
MIT-licensed) and `vocals` (Mel-Band RoFormer). The first run downloads about 700 MB
of weights to `~/.skitz/models/separation`. The default checkpoint has no stated
license, so treat its stems as personal-use. A placement is
`SAMPLE:AT[b|q|s][:xREPEAT/EVERY][:GAINdB]`, in 0-based bars (default), beats (`q`)
or seconds (`s`). `--plan` takes the same placements as JSON. Outputs are 16-bit
44.1 kHz WAVs, each with a manifest of source hashes, cut points and settings. MCP
clients get `samples_info`, `samples_loops`, `samples_hits`, `samples_slice` and
`samples_layer` and `samples_stems`.

## Rendering

On macOS:

```sh
brew install lilypond fluid-synth
```

Provide a SoundFont you are licensed to use. See
[GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) for a compatible
option, its license and attribution. Skitz does not redistribute the SoundFont.
Set `SKITZ_SOUNDFONT` or pass `--soundfont`. For only notation/MIDI, use `--no-audio`.
For only source/MIDI/MusicXML, also use `--no-engrave`.

Each render records the revision, tool versions, SoundFont hash, synthesis settings
and artifact hashes. PDF/WAV rendering currently requires the tested macOS
restricted-worker backend. Other platforms fail closed for these operations;
source/MIDI/MusicXML operations remain available where dependencies work.
Rendering failures return nonzero status and retained diagnostics.

## Use From Codex

Skitz exposes local MCP tools for creating projects, score inspection, validation,
voice-leading analysis, bounded edits, revision comparison, rendering, rollback
and export. Configure your MCP client to launch:

```sh
/absolute/path/to/skitz/.venv/bin/skitz mcp --workspace /absolute/path/to/music
```

For Codex, add this server to your own configuration:

```toml
[mcp_servers.skitz]
command = "/absolute/path/to/skitz/.venv/bin/skitz"
args = ["mcp", "--workspace", "/absolute/path/to/music"]
```

The MCP operations do not call a model or require authentication. Codex can use
them through its own signed-in session. The repository also includes a discoverable
Codex skill in `.agents/skills/skitz/` and a Python-backed Prime skill in
`packages/skitz-music/`. No global Codex settings are changed by installation.

## Checks and Benchmarks

```sh
npm run check
uv run python evals/verify-editing.py work/editing-run --soundfont /path/to/font.sf2
uv run skitz bench --condition single-response \
  --prompt-file evals/bach-reproduction/paraphrased-prompt.txt --output work/bach-one-shot
```

Use a fresh output directory for each evaluation. Auggie's
[Bach Benchmark](https://aug5th.substack.com/p/the-bach-benchmark) inspired the
chorale tasks, notation feedback and voice-leading checks. The included prompt is
an attributed paraphrase. Supply the original published prompt locally for an
exact reproduction. Single-response, compiler-repair and structured Skitz runs
are distinct conditions, not interchangeable results. See [evaluation](docs/evaluation.md).

Prime's unrestricted agent kernel is not a security sandbox. Use trusted projects
or an external restricted environment for the full agent. The notation/audio
workers have separate restrictions; see [architecture](docs/architecture.md).

MIT license for Skitz. Prime and inherited pi notices are retained in full; see
[third-party notices](THIRD_PARTY_NOTICES.md) and [upstream provenance](docs/upstream.md).
