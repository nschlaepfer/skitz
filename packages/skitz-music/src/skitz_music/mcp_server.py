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
            "manifest there; otherwise returns clip ids. A captcha_required or auth_expired "
            "error needs the user to act; never try to work around it."
        ),
        "suno_status": "Show the status and audio URLs of Suno clips by id.",
        "suno_wait": "Wait for Suno clips to finish; with output_dir, save mp3s and a manifest.",
        "suno_lyrics": "Have Suno write song lyrics from a prompt (no credits).",
    }
    for name, description in suno_descriptions.items():
        server.tool(name=name, description=description)(getattr(suno, name))
    return server
