"""Music operations shared by the Prime kernel, CLI, and MCP clients."""

from .score import Event, Score, Track
from .store import Project

__all__ = ["Event", "Project", "Score", "Track"]
