from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _exercise_stdio_server(tmp_path: Path) -> tuple[set[str], dict]:
    env = dict(os.environ)
    source_root = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = str(source_root)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "nemofold",
            "mcp",
            "--base-dir",
            str(tmp_path),
            "--allow-root",
            str(tmp_path),
        ],
        env=env,
    )
    async with (
        stdio_client(parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool(
            "nemofold_anonymize",
            {
                "text": "Contact analyst@example.org.",
                "sensitive_terms": [],
            },
        )
    if result.structuredContent:
        payload = dict(result.structuredContent)
    else:
        payload = json.loads(result.content[0].text)
    return {tool.name for tool in tools.tools}, payload


def test_real_stdio_handshake_lists_and_calls_nemofold_tools(tmp_path) -> None:
    tools, payload = asyncio.run(_exercise_stdio_server(tmp_path))

    assert "nemofold_analyze_with_provider" in tools
    assert "nemofold_verify_report" in tools
    assert payload["text"] == "Contact <EMAIL_001>."
    assert payload["transfer_performed"] is False
