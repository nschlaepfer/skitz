"""Local MCP tools for Codex and other MCP clients. No model or API key required."""

from mcp.server.mcpserver import MCPServer

from .service import MusicService


def create_server(workspace: str) -> MCPServer:
    service = MusicService(workspace)
    server = MCPServer(
        "Skitz",
        instructions="Editable music operations. Inspect revisions before edits; preserve protected tracks.",
    )
    descriptions = {
        "create_project": "Create an editable score project with immutable protected tracks.",
        "inspect_score": "Inspect events, track identities, meter and the current revision.",
        "validate_score": "Check exact rhythm, track lengths and tie integrity.",
        "analyze_voice_leading": "Find chorale-specific parallel fifths/octaves, crossings and range warnings.",
        "apply_score_patch": "Apply pitch, tie or articulation edits to explicitly allowed measures at an expected revision.",
        "compare_revisions": "Compare exact event changes and unchanged tracks between saved revisions.",
        "render_score": "Render notation, MIDI and optional audio with provenance and diagnostics.",
        "rollback": "Restore a saved revision while preserving protected tracks.",
        "export_project": "Export the accepted score, revision history and matching renders as a ZIP archive.",
    }
    for name, description in descriptions.items():
        server.tool(name=name, description=description)(getattr(service, name))

    from .suno import SunoService

    suno = SunoService(workspace)
    suno_descriptions = {
        "suno_credits": "Check the user's Suno session and remaining credits.",
        "suno_generate": (
            "Generate a song on the user's Suno account (2 clips; spends credits). Give "
            "description, or lyrics/tags/title. With output_dir, waits and saves mp3s and a "
            "manifest there; otherwise returns clip ids. Set bpm (and usually instrumental) "
            "when the clips will be cut into samples. A captcha_required or auth_expired "
            "error needs the user to act; never try to work around it."
        ),
        "suno_status": "Show the status and audio URLs of Suno clips by id.",
        "suno_wait": "Wait for Suno clips to finish; with output_dir, save mp3s and a manifest.",
        "suno_lyrics": "Have Suno write song lyrics from a prompt (no credits).",
        "suno_stems": (
            "List the 12 stems (2 variants each) the user made for a clip on suno.com (Edit > "
            "Get Stems). Suno does not let API clients download stem audio (it is encrypted "
            "for the web player); ask the user to use Download there, then use samples_* tools. Creating stems needs a captcha in the "
            "web app, so ask the user to start them there. For local splitting use samples_stems."
        ),
        "suno_downbeats": (
            "Suno's beat grid for a clip, with bpm and first_downbeat: pass those to "
            "samples_loops (bpm, offset) to cut on Suno's own bar lines."
        ),
    }
    for name, description in suno_descriptions.items():
        server.tool(name=name, description=description)(getattr(suno, name))

    from .samples import SamplesService

    sampler = SamplesService(workspace)
    sample_descriptions = {
        "samples_info": "Length, peak, Suno-recorded BPM and an estimated BPM for an audio file.",
        "samples_analyze": (
            "Estimate tempo (bpm, confidence, half/double, first_beat), key/mode (with "
            "Camelot code and runner-up keys) and a triad chord per bar. Every value is an "
            "estimate from the signal, not listening: say so, and prefer recorded BPMs."
        ),
        "samples_fit": (
            "Time-stretch audio to a target bpm and/or pitch-shift it to a target key (or by "
            "semitones) without changing the other. Source bpm defaults to the recorded one, "
            "else an estimate; source key to an estimate. The manifest records which, plus "
            "tempo_ratio and pitch_ratio. Fitted files carry their new bpm for samples_loops."
        ),
        "samples_fx": (
            "Run an effect chain over one file (a stem, a loop or a finished mix). chain is "
            "an object like samples_layer fx, or a string like 'hp=80,comp=-20/3,limit'."
        ),
        "samples_loops": (
            "Cut audio (e.g. a Suno mp3) into back-to-back loops of `bars` at `bpm`, or "
            "`every` seconds. BPM defaults to the one recorded by suno_generate(bpm=...)."
        ),
        "samples_hits": "Detect transients and cut them into one-shot WAVs (drum hits, stabs).",
        "samples_slice": "Cut one region, in seconds, into a WAV.",
        "samples_stems": (
            "Split audio into stems on the local GPU (about 8 s per 30 s of audio per model). "
            "model: stems (vocals/drums/bass/guitar/piano/other, default), 4stem, vocals, or "
            "drumkit. drumkit=true also splits drums into kick/snare/toms/hh/ride/crash. "
            "Stems keep the source's recorded BPM for samples_loops."
        ),
        "samples_layer": (
            "Mix samples onto a timeline into a new WAV, optionally over a base such as a "
            "score render. Placements: {sample, at, unit: bar|beat|second, gain_db, pan "
            "(-1..1), repeat, every, track, fx}. Bars and beats are 0-based and need bpm. fx "
            "and master take {highpass: hz|{hz, slope}, lowpass, low_shelf: {hz, db}, "
            "high_shelf, peak, compress: {threshold_db, ratio, attack_ms, release_ms, "
            "makeup_db}, delay: {beats|seconds, feedback, mix}, reverb: wet|{wet, room}, "
            "gain_db, pan, limit: true|{ceiling_db}}. End master with limit."
        ),
        "samples_export": (
            "Write a samples_layer plan for Ableton Live or Logic Pro: the mix, 32-bit float "
            "stems per track (start at 0 s, after fx, before master), the source samples, "
            "and placements.mid with tempo and one MIDI track per stem."
        ),
    }
    for name, description in sample_descriptions.items():
        server.tool(name=name, description=description)(getattr(sampler, name))
    return server
