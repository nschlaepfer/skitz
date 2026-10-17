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
        "render_score": (
            "Render notation, MIDI and audio with provenance and diagnostics. Audio uses the "
            "installed SoundFont; without one it is skipped with a hint (audio_skipped)."
        ),
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
        "samples_transcribe": (
            "Transcribe audio, usually a pitched stem from samples_stems, into a new editable "
            "score project (basic-pitch, runs locally). Notes snap to a bar grid: bpm comes "
            "from the argument, downbeats (a saved suno_downbeats JSON), the BPM recorded for "
            "the file or its stems, else an estimate; offset is the first downbeat in seconds "
            "(first_downbeat from suno_downbeats). grid is the shortest note (16 = sixteenths, "
            "12 = eighth triplets). Each track is one monophonic line; tracks > 1 splits "
            "chords, and line (top, bottom, loudest) picks which overlapping note wins; "
            "join_repeats merges same-pitch notes that vibrato split into repeats. "
            "Returns kept, merged and dropped note counts, onset_shift and warnings; then "
            "use inspect_score, apply_score_patch and render_score on the project. Drums "
            "are unpitched: use samples_hits."
        ),
        "samples_layer": (
            "Mix samples onto a timeline into a new WAV, optionally over a base such as a "
            "score render. Placements: {sample, at, unit: bar|beat|second, gain_db, repeat, "
            "every}. Bars and beats are 0-based and need bpm."
        ),
    }
    for name, description in sample_descriptions.items():
        server.tool(name=name, description=description)(getattr(sampler, name))

    from .playback import PlaybackService

    player = PlaybackService(workspace)
    playback_descriptions = {
        "play_audio": (
            "Play audio on the user's speakers: a project folder plays its newest audio render "
            "of the current revision, or give an audio file. Returns at once; stop_audio stops it."
        ),
        "stop_audio": "Stop audio started with play_audio.",
    }
    for name, description in playback_descriptions.items():
        server.tool(name=name, description=description)(getattr(player, name))
    return server
