import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from skitz_music.fixtures import chorale_fixture


def test_real_stdio_mcp_score_workflow(tmp_path):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "skitz_music.cli", "mcp", "--workspace", str(tmp_path)],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {
                    "create_project",
                    "inspect_score",
                    "apply_score_patch",
                    "render_score",
                    "export_project",
                } <= names
                result = await client.call_tool(
                    "create_project",
                    {
                        "project": "piece",
                        "score": chorale_fixture().model_dump(mode="json"),
                        "protected_tracks": ["soprano"],
                    },
                )
                assert not result.is_error
                result = await client.call_tool("inspect_score", {"project": "piece"})
                assert not result.is_error
                data = json.loads(result.content[0].text)
                revision = data["revision"]
                protected = await client.call_tool(
                    "apply_score_patch",
                    {
                        "project": "piece",
                        "expected_revision": revision,
                        "edits": [{"event_id": "soprano_001", "set": {"pitch": "C4"}}],
                        "allowed_measures": [1],
                        "reason": "negative control",
                    },
                )
                assert protected.is_error
                edited = await client.call_tool(
                    "apply_score_patch",
                    {
                        "project": "piece",
                        "expected_revision": revision,
                        "edits": [{"event_id": "bass_002", "set": {"pitch": "A2"}}],
                        "allowed_measures": [2],
                        "reason": "inject test error",
                    },
                )
                assert not edited.is_error
                analysis = await client.call_tool("analyze_voice_leading", {"project": "piece"})
                assert not analysis.is_error
                assert "parallel_octave" in analysis.content[0].text

    asyncio.run(check())
