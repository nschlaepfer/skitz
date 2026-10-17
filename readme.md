# Skitz

A terminal music agent built on Prime Agent. Sign in with your **ChatGPT
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
API-key providers and overrides are blocked. Prime's inherited help and TUI
currently retain some upstream branding and provider menu entries; non-Codex
provider calls are rejected in the runtime.

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

Log in at suno.com, open DevTools, select any `clerk.suno.com` request and copy its
`cookie` request header. Then:

```sh
pbpaste | uv run skitz suno login -
uv run skitz suno whoami
uv run skitz suno generate -d "warm lofi beat about rainy mornings" --out songs/rain
uv run skitz suno generate --title "Night Drive" -t "synthwave, female vocals" \
  --lyrics-file lyrics.txt -m v5 --out songs/night-drive
uv run skitz suno lyrics "a sea shanty about debugging"
```

The cookie is saved to `~/.skitz/suno/cookie` with mode 600 (or set `SUNO_COOKIE`).
Each download folder gets a `manifest.json` with the request, clip metadata and file
hashes. The agent uses `skitz_music.suno`, and MCP clients get `suno_credits`,
`suno_generate`, `suno_status`, `suno_wait` and `suno_lyrics`. When Suno asks for a
captcha, Skitz stops with exit code 4. Create one song by hand on suno.com, then
retry. Skitz never tries to solve or get around a captcha.

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
