# Skitz

A terminal music agent. Run it on your **ChatGPT subscription** or on **Claude**
with an Anthropic API key, compose an editable score, render it, and make revisions
that preserve protected tracks.

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

## Models

| Provider | Sign in | Default model | Override |
|---|---|---|---|
| ChatGPT (`codex`) | `skitz login`: your ChatGPT subscription, OAuth | `gpt-6.1-sol` | `SKITZ_CODEX_MODEL` |
| Claude (`claude`) | `skitz auth login claude`: an Anthropic API key, billed per use | `claude-opus-5-5` | `SKITZ_CLAUDE_MODEL` |

```sh
uv run skitz agent                          # whichever is connected; ChatGPT first
uv run skitz agent --provider claude        # Claude Opus 5.5
uv run skitz agent --model claude-sonnet-5-5
uv run skitz agent --provider codex --model gpt-6-astra
```

`SKITZ_PROVIDER=claude` makes Claude the default. Skitz adds `gpt-6.1-sol` and
`claude-opus-5-5` to the runtime's catalog through `~/.skitz/agent/models.json`, and
keeps any entries you add there. Claude Pro/Max subscription sign-in isn't
supported: Anthropic doesn't allow third-party apps to offer claude.ai login without
its approval, so the runtime refuses Claude subscription tokens. Other API-key
providers, `--api-key` and `--models` stay blocked. `skitz auth` shows whether each
provider actually works, refreshing an expired ChatGPT sign-in where it can.

The terminal mark, window title,
help and subscription menu use the Skitz identity. First launch signs in with
ChatGPT rather than opening an upstream onboarding flow. Internal runtime package
names and protocol versions are preserved; the terminal's version label currently
shows the pinned engine version. Some inherited coding-oriented prompts and
advanced diagnostic text remain for a later music-interface pass.

## Music Tools

```sh
uv run skitz schema            # score format; `skitz schema patch` for edits
uv run skitz create my-piece score.json --protect soprano
uv run skitz inspect my-piece
uv run skitz validate my-piece
uv run skitz analyze my-piece
uv run skitz patch my-piece patch.json
uv run skitz migrate my-piece  # schema-1 projects also migrate on first read
uv run skitz render my-piece --soundfont /path/to/GeneralUser-GS.sf2
uv run skitz verify my-piece --require-audio
uv run skitz export my-piece accepted-piece.zip
```

`uv run skitz demo demo-piece` creates a clearly labeled authored test fixture.
`uv run skitz import imported-piece source.abc` imports supported ABC or
uncompressed MusicXML. Unsupported constructs fail explicitly. Original Skitz
scripts and documentation live in `legacy/`; original examples remain in `Examples/`.

Scores (schema 2) use exact quarter-note fractions, spelled pitches, stable event
IDs, explicit rests, ties and basic articulations. An event can be a chord, each
track is one rhythmic line, and meter and tempo maps change at measure starts. The
canonical JSON revision is the source of truth. Patches change pitches, chords, ties
and articulations, split, merge, insert, delete and resize events, rewrite a
track's whole measures, transpose, and set tempo or meter, all against an expected
revision and within named measures, with protected tracks immutable. Arbitrary DAW
sessions, independent voices inside one track, mid-measure tempo or meter changes,
key changes and lossless LilyPond import are not supported.

## Suno Songs

Skitz can also make finished songs on your own Suno account, for requests that
want produced audio rather than an editable score. Suno has no public API, so this
uses your suno.com web session and its private endpoints. These can change without
notice, and automating them may conflict with Suno's terms. Every generation spends
your Suno credits.

Connect your account once. The command opens a Skitz Chrome window (its own profile
under `~/.skitz/suno/browser`, separate from your everyday browser). Sign in to
Suno there, press Enter in the terminal, and Skitz reads that session, checks it
with Suno and saves it. It never reads your normal Chrome. Without Chrome, it falls
back to copying the `__client` cookie from DevTools:

```sh
uv run skitz auth login suno     # or: uv run skitz login suno
uv run skitz auth                # status of Suno, ChatGPT and Claude
uv run skitz suno whoami
uv run skitz suno generate -d "warm lofi beat about rainy mornings" --out songs/rain
uv run skitz suno generate --title "Night Drive" -t "synthwave, female vocals" \
  --lyrics-file lyrics.txt -m v5 --out songs/night-drive
uv run skitz suno lyrics "a sea shanty about debugging"
```

**What works today (verified live, October 2026).** Credits, generation requests,
status, lyrics, models (`skitz suno models --live`), stem listings and Suno's beat
grid all work. **Suno no longer serves audio to API clients:** it returns
`audio_url: /api/forbidden` for songs and stems, its player stream is encrypted, and
its Download button builds the file in the browser. Skitz never reads that stream.
Instead it brings in the files you download: every song Suno's Download button saves
carries its clip id in the file's metadata, so `skitz suno download` (and `--out` on
`generate` and `wait`) finds them in `~/Downloads` or `~/.skitz/suno/inbox` by that
id, even when two clips share a title. It copies them into the folder you name, with
a manifest that keeps the BPM you asked for:

```sh
uv run skitz suno download <id> <id> --out songs/rain                     # files already downloaded
uv run skitz suno download <id> --out songs/rain --wait-for-browser       # opens the song page,
                                                                          # waits for your click
uv run skitz suno inbox                                                   # Suno files found, by clip id
```

Songs that haven't been downloaded yet return exit code 7 with their `song_urls`. Files
without Suno's tag (an exported WAV, say) are matched by title and length, but only
when exactly one clip fits. Set `SKITZ_SUNO_WATCH` (folders separated by `:`) to look
elsewhere. Stems still have to be downloaded on suno.com (Get Stems > Download) or
split locally with `skitz samples stems`. `skitz suno stems <clip>` lists a clip's 12 stems in 2
variants. `skitz suno downbeats <clip>` returns Suno's BPM and bar-1 offset, which
you can pass to `samples loops --bpm --offset`. Making stems needs a captcha in the
web app, so start them there. The default model is v6 (`chirp-hawk`), and the
sign-in host is `auth.suno.com`. A short-lived access token can stand in for the
cookie through `SUNO_JWT`.

The cookie is saved to `~/.skitz/suno/cookie` with mode 600 (or set `SUNO_COOKIE`).
Each download folder gets a `manifest.json` with the request, clip metadata and file
hashes, merged by clip id, so several songs can share a folder. Every generate request
is also recorded in `~/.skitz/suno/requests.jsonl`, so a song imported later still
knows its BPM. The agent uses `skitz_music.suno`, and MCP clients get `suno_credits`,
`suno_generate`, `suno_status`, `suno_wait`, `suno_download`, `suno_inbox`,
`suno_library`, `suno_jobs` and `suno_lyrics`.

**Letting the agent work without you.** These keep Skitz from stopping to ask:

```sh
uv run skitz suno library --search "JUJU B"      # find songs by title or style; shows which are downloaded
uv run skitz suno budget set 50                  # credits per day the agent may spend unasked
uv run skitz suno jobs                           # generations still open, with live status
uv run skitz suno jobs --resume --wait-for-browser   # finish them after a restart or timeout
uv run skitz suno generate -d "..." --wait-for-captcha   # hand a captcha to you, then carry on
```

- **Library.** `library` pages through your Suno songs (newest first, 20 per page) and
  matches `--search` against title and style. It leaves out trashed songs and the stems
  made on suno.com (`--stems` adds the stems back). Each song says whether its file is
  already in `~/Downloads` or the inbox (`downloaded`) and where to download it
  (`song_url`).
- **Jobs.** Every generation is kept in `~/.skitz/suno/jobs.json` with its request and
  output folder. If Skitz stops before the audio is saved, `jobs --resume` waits for
  the clips and saves each job into its own folder. With `--wait-for-browser`, it also
  opens the pages of songs that still need your Download click. `jobs --all` includes
  finished jobs, and `jobs --dismiss <id>` stops tracking one.
- **Budget.** Set a daily limit with `SKITZ_SUNO_BUDGET` or `skitz suno budget set N`
  (the environment wins; `budget clear` removes the saved one). Before each generation
  Skitz checks today's spending. It logs credits before and after to
  `~/.skitz/suno/spend.jsonl`, and refuses with exit code 8 (`budget_exceeded`) when the
  next generation would pass the limit. The next cost is the last measured one, or 10
  credits until Skitz has measured one. Within the budget the agent generates without
  asking each time. It never changes the budget itself.
- **Captcha handoff.** When Suno asks for a captcha, Skitz stops with exit code 4. With
  `--wait-for-captcha` (MCP `wait_for_captcha`), it opens suno.com/create in your
  browser instead. You create one song there by hand and solve the captcha. Skitz checks
  Suno's `/api/c/check` every 5 seconds, and once Suno stops asking, it retries the
  generation once. Skitz never solves, scripts or gets around a captcha.
- **Reconnect.** If the saved session expires, Skitz re-reads the Skitz Chrome profile
  (`~/.skitz/suno/browser`) headlessly once, saves the new cookie and retries. It never
  reads your everyday browser's profile. Only if that fails does it report
  `auth_expired`. Set `SKITZ_SUNO_RECONNECT=0` to turn this off.
- **Retries.** Requests are retried up to 3 times with jittered backoff on HTTP
  429/502/503/504 and network errors, honoring `Retry-After` up to 60 seconds. A
  generation is retried only when Suno surely didn't take it (429, 503, or a connection
  that never opened). After a 502/504, check `library` before generating again.

| Exit | `error_kind` | Who acts |
|---|---|---|
| 0 | | done |
| 1 | `usage` | fix the arguments |
| 2 | `api_error`, `network_error`, `generation_failed`, `not_ready` | retry later |
| 3 | `auth_missing`, `auth_expired` | you: `skitz auth login suno` |
| 4 | `captcha_required` | you: solve it on suno.com, or rerun with `--wait-for-captcha` |
| 5 | `out_of_credits` | you |
| 6 | `timeout` | `wait` again with the same ids, or `jobs --resume` |
| 7 | `download_restricted` | you: click Download on each `song_urls` page |
| 8 | `budget_exceeded` | you: raise the budget, or wait until tomorrow |

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
44.1 kHz WAVs, each with a manifest of source hashes, cut points and settings.

`transcribe` turns a pitched stem back into an editable score project, so a Suno
song's bass line or vocal melody can be inspected, patched and rendered like any
other Skitz score:

```sh
uv run skitz samples transcribe stems/song/bass.wav --out projects/song-bass
uv run skitz suno downbeats <clip-id> > beats.json
uv run skitz samples transcribe stems/song/vocals.wav --downbeats beats.json \
  --out projects/song-vocals
uv run skitz samples transcribe stems/song/piano.wav --tracks 3 --grid 8 \
  --bpm 92 --offset 0.41 --out projects/song-piano
```

It runs Spotify's [basic-pitch](https://github.com/spotify/basic-pitch) 0.4.0
(Apache-2.0) in its own uv tool environment, using its CoreML model on Apple
Silicon: about 10 s for 3 minutes of audio, after a first-run install of about
350 MB. Tempo comes from `--bpm`, `--downbeats`, the BPM recorded for the clip or
its stems, or an estimate; `--offset` sets the first downbeat. Notes snap to
`--grid` (16 = sixteenths; 12 and 24 are triplets) and each track is one monophonic
line with explicit rests and ties over bar lines. Overlaps keep the lowest note for
bass, the loudest for vocals and the highest otherwise (`--line`), and `--tracks N`
splits chords into N tracks. The project's `transcribe-manifest.json` records the
source hash, model version, grid, and every note merged or dropped; the raw notes
are kept as MIDI. Transcription is an estimate, best on clean single-instrument
stems; drums are refused (use `hits`).

#### Fit, mix and export

Make samples fit the song, add effects, and take the result into Ableton Live or
Logic Pro:

```sh
uv run skitz samples analyze songs/keys/<clip>.mp3    # estimated BPM, key/mode, chords
uv run skitz samples fit songs/keys/<clip>.mp3 --bpm 90 --key "A minor" --out samples/keys
uv run skitz samples fx stems/song/vocals.wav fx/vocals.wav --chain hp=120,comp=-20/3,reverb=0.15
uv run skitz samples layer out/beat.wav --bpm 90 --bars 8 \
  --place samples/drums/<loop01>.wav:0:x4/2 --place samples/keys/<clip>-90bpm-Am.wav:0 \
  --fx 1:hp=40,comp=-18/4 --fx 2:lp=6000,delay=0.75q/0.3/0.2,pan=-0.2 --master comp=-14/2,limit
uv run skitz samples export out/beat-daw --bpm 90 --bars 8 --plan plan.json --master limit
```

`analyze` estimates tempo (with half/double alternatives and the first beat), key
and mode (with a Camelot code and runner-up keys) and one major/minor triad per bar.
These are signal estimates, labelled as such; prefer the BPM and key you asked Suno
for. `fit` time-stretches and pitch-shifts independently with
[pedalboard](https://github.com/spotify/pedalboard)'s Rubber Band (or ffmpeg's
`rubberband` filter without it). It records the source BPM and key, where they came
from, and the tempo and pitch ratios. Between major and minor keys it moves to the
target's relative key.

Effect chains are `KEY=VALUE` pairs: `hp`/`lp` (Hz, optional `/slope`), `lowshelf`,
`highshelf` and `peak` (`Hz/dB[/Q]`), `comp` (`threshold/ratio[/attack/release/makeup]`),
`delay` (`time` in seconds or beats with `q`, `/feedback/mix`), `reverb` (`wet[/room]`),
`gain`, `pan` (-1 to 1) and `limit` (a lookahead brickwall at `-1` dBFS, or
`limit=CEILING`). `--fx N:CHAIN` applies to placement N; `--master` runs on the sum.
In a `--plan`, placements take `pan`, `fx` (the same effects as JSON) and `track`.

`export` writes the mastered mix, one 32-bit float stem per track starting at 0 s
(after placement effects, before the master), the source samples, and
`placements.mid` with the tempo and one MIDI track per stem. Drop the stems at bar 1
in the DAW, or load `samples/` into a sampler and play them from the MIDI. Effects
need pedalboard, which `npm run setup` installs (`pip install 'skitz-music[fx]'`
elsewhere). MCP clients get `samples_info`, `samples_analyze`, `samples_fit`,
`samples_fx`, `samples_loops`, `samples_hits`, `samples_slice`, `samples_layer`,
`samples_export`, `samples_stems` and `samples_transcribe`.

## Rendering

On macOS:

```sh
brew install lilypond fluid-synth
```

For audio, install a SoundFont once:

```sh
uv run skitz soundfont install     # GeneralUser GS, ~32 MB, into ~/.skitz/soundfonts
uv run skitz render my-piece        # PDF, MIDI, MusicXML, LilyPond and WAV
uv run skitz play my-piece          # plays the newest audio render of HEAD
```

`soundfont install` fetches [GeneralUser GS](https://schristiancollins.com/generaluser.php)
by S. Christian Collins from the author's
[GitHub repository](https://github.com/mrbumpy409/GeneralUser-GS), pinned to one
commit, and keeps it only if its size and SHA-256 match. Its license, saved next to
it, allows use for private or commercial music. Skitz doesn't bundle the file.
Renders use `--soundfont`, then `SKITZ_SOUNDFONT`, then the installed font. With
none, audio is skipped with a hint (`audio_skipped`) rather than failing the render.
An explicit `--soundfont` that doesn't exist fails. `skitz play <file>` plays any
audio, and `--background` / `--stop` control playback.

## Animations

The agent screen is music-themed. While the agent works, the spinner is a four-bar
equalizer; the SKITZ mark shimmers in a magenta-to-cyan gradient; and whenever audio
plays (`skitz play … --background`, or the agent playing a render), a two-row strip
of live spectrum bars with the title and a clock is pinned right above the editor. It
stays in the fixed area at the bottom, so the chat above never moves and stays
readable. `skitz play <project|file> --visualize` shows taller bars in any terminal. The bars come from the audio itself: a Hann-window FFT in 32
log-spaced bands at 20 fps, computed when playback starts (about 0.5 s for a
3-minute song). The loader and visualizer are a Skitz extension
(`apps/cli/skitz-visuals.ts`); the header shimmer lives in the runtime's splash
(`themes/skitz-shimmer.ts`), because the session daemon doesn't forward extension
headers. Set `SKITZ_ANIMATIONS=off` for the stock screen.

Behind it all, an animated ASCII gradient fills the screen, modeled on React Bits'
[Gradient ASCII](https://reactbits.dev/backgrounds/gradient-ascii) background (horizon
shape) and written from scratch for the terminal. Light falls from the top over a dark
arched horizon in their default blues, drawn with ` =+xX0S8#@` from dim to bright, with
drift, flicker and grain. It only fills empty space and fades out within about 14
columns, and two rows, of any text, so messages sit in a clear pocket. It runs only in
fullscreen mode (never in scrollback) at 8 fps, about 1 ms per frame.
`SKITZ_BACKGROUND=off` turns off just the backdrop. For only notation/MIDI, use
`--no-audio`; for only source/MIDI/MusicXML, also use `--no-engrave`.

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
