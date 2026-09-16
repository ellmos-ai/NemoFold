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


async def _exercise_medical_authority_over_stdio(tmp_path: Path) -> dict:
    documents = tmp_path / "medical-documents"
    documents.mkdir()
    (documents / "bericht.txt").write_text(
        "Befund: Schilddrüse vergrößert.\n", encoding="utf-8"
    )
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
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "synopsis_merge",
        "input_roots": ["medical-documents"],
        "output_dir": "medical-output",
        "questions": [],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {
            "application_domain": "medical_reports",
            "medical_purpose": "diagnosis",
            "formats": ["md"],
        },
    }
    async with (
        stdio_client(parameters) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(
            "nemofold_run",
            {"job": job, "run_id": "mcp_medical_diagnosis"},
        )
    if result.structuredContent:
        return dict(result.structuredContent)
    return json.loads(result.content[0].text)


def test_real_stdio_handshake_lists_and_calls_nemofold_tools(tmp_path) -> None:
    tools, payload = asyncio.run(_exercise_stdio_server(tmp_path))

    assert "nemofold_analyze_with_provider" in tools
    assert "nemofold_verify_report" in tools
    assert payload["text"] == "Contact <EMAIL_001>."
    assert payload["transfer_performed"] is False


def test_real_mcp_stdio_preserves_the_medical_authority_block(tmp_path) -> None:
    payload = asyncio.run(_exercise_medical_authority_over_stdio(tmp_path))

    assert payload["report"]["status"] == "blocked"
    assert payload["report"]["errors"] == ["medical_authority_denied:diagnosis"]
    assert payload["report"]["metadata"]["medical_authority"] == "denied"
    assert payload["report"]["metadata"]["needs_user_input"] is True
    assert Path(payload["report_path"]).is_file()
    assert not tuple((tmp_path / "medical-output").glob("*.synopsis.md"))
