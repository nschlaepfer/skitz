"""Local MCP tools for Codex and other MCP clients. No model or API key required."""

from mcp.server.fastmcp import FastMCP

from .service import MusicService


def create_server(workspace: str) -> FastMCP:
    service = MusicService(workspace)
    server = FastMCP(
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
        "samples_layer": (
            "Mix samples onto a timeline into a new WAV, optionally over a base such as a "
            "score render. Placements: {sample, at, unit: bar|beat|second, gain_db, repeat, "
            "every}. Bars and beats are 0-based and need bpm."
        ),
    }
    for name, description in sample_descriptions.items():
        server.tool(name=name, description=description)(getattr(sampler, name))
    return server
