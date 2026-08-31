from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .anonymizer import pseudonymize_text
from .application import ExecutionConfig, preview_job, run_job
from .contracts import to_primitive
from .drafts import DraftStore
from .job_io import SUPPORTED_WORKFLOWS, parse_job_payload
from .ledger import validate_run_id
from .policy import PolicyConfig, PolicyGate
from .provider_analysis import analyze_with_provider
from .providers import provider_capabilities, provider_config_from_mapping
from .report_verifier import verify_run_report

MAX_ANONYMIZE_CHARS = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    base_dir: Path
    execution: ExecutionConfig

    def __post_init__(self) -> None:
        if not self.execution.allowed_roots:
            raise ValueError("MCP server requires at least one allowed root")


class NemoFoldMCPService:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.base_dir = config.base_dir.resolve()
        self.path_gate = PolicyGate(PolicyConfig(allowed_roots=config.execution.allowed_roots))
        self.drafts = DraftStore(self.base_dir, config.execution.allowed_roots)

    @staticmethod
    def _run_id(value: str | None) -> str:
        run_id = value or (
            f"mcp_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        )
        validate_run_id(run_id)
        return run_id

    def capabilities(self) -> dict[str, Any]:
        return {
            "schema": "nemofold.mcp-capabilities.v1",
            "workflows": sorted(SUPPORTED_WORKFLOWS),
            "providers": provider_capabilities(),
            "tools": [
                "nemofold_capabilities",
                "nemofold_anonymize",
                "nemofold_preview",
                "nemofold_run",
                "nemofold_analyze_with_provider",
                "nemofold_save_draft",
                "nemofold_list_drafts",
                "nemofold_verify_report",
            ],
            "allowed_root_count": len(self.config.execution.allowed_roots),
            "external_models_allowed": self.config.execution.external_models_allowed,
            "file_actions_allowed": self.config.execution.apply_actions_allowed,
            "competition_provider": "dedicated Nebius token-factory-run path",
        }

    def anonymize(self, text: str, sensitive_terms: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(text, str) or len(text) > MAX_ANONYMIZE_CHARS:
            raise ValueError("text must be a string within the bounded size limit")
        terms = [] if sensitive_terms is None else sensitive_terms
        if not isinstance(terms, list) or any(not isinstance(item, str) for item in terms):
            raise ValueError("sensitive_terms must be a list of strings")
        result = pseudonymize_text(text, sensitive_terms=terms)
        return {
            "schema": "nemofold.mcp-anonymize.v1",
            "text": result.text,
            "replacement_counts": result.replacement_counts,
            "raw_mapping_stored": False,
            "transfer_performed": False,
        }

    def preview(self, job: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        run_id = self._run_id(run_id)
        parsed = parse_job_payload(job, base_dir=self.base_dir)
        result = preview_job(parsed, self.config.execution, run_id=run_id)
        return {
            "report": to_primitive(result.report),
            "report_path": str(result.report_path) if result.report_path else None,
        }

    def run(self, job: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        run_id = self._run_id(run_id)
        parsed = parse_job_payload(job, base_dir=self.base_dir)
        result = run_job(parsed, self.config.execution, run_id=run_id)
        return {
            "report": to_primitive(result.report),
            "report_path": str(result.report_path) if result.report_path else None,
        }

    def analyze_with_provider(
        self,
        job: dict[str, Any],
        provider: dict[str, Any],
        run_id: str | None = None,
        approve_external_transfer: bool = False,
    ) -> dict[str, Any]:
        run_id = self._run_id(run_id)
        if not isinstance(approve_external_transfer, bool):
            raise ValueError("approve_external_transfer must be a boolean")
        parsed = parse_job_payload(job, base_dir=self.base_dir)
        provider_config = provider_config_from_mapping(provider)
        result = analyze_with_provider(
            parsed,
            self.config.execution,
            provider_config,
            run_id=run_id,
            approve_external_transfer=approve_external_transfer,
        )
        return {
            "report": to_primitive(result.report),
            "report_path": str(result.report_path) if result.report_path else None,
        }

    def save_draft(
        self,
        job: dict[str, Any],
        provider: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Save settings for browser review; never persist action or transfer approval."""
        return {"draft": self.drafts.save(job, provider=provider, name=name, source="mcp")}

    def list_drafts(self) -> dict[str, Any]:
        return {"drafts": self.drafts.list()}

    def verify_report(self, report_path: str) -> dict[str, Any]:
        if not isinstance(report_path, str) or not self.path_gate.path_allowed(report_path):
            raise PermissionError("report_path is outside the MCP allow roots")
        result = verify_run_report(
            report_path,
            allowed_roots=self.config.execution.allowed_roots,
        )
        return {
            "valid": result.valid,
            "run_id": result.run_id,
            "errors": list(result.errors),
            "checked_artifacts": result.checked_artifacts,
        }


def build_mcp_server(config: MCPServerConfig):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - packaging error path
        raise ImportError("install NemoFold with the 'mcp' extra") from exc

    service = NemoFoldMCPService(config)
    mcp = FastMCP(
        "NemoFold",
        instructions=(
            "Private evidence-first document workflows. Paths are limited to operator-provided "
            "roots. External model transfer requires both server permission and per-call approval."
        ),
        json_response=True,
    )

    @mcp.tool(name="nemofold_capabilities")
    def capabilities() -> dict[str, Any]:
        """List workflows, providers, gates, and proof boundaries."""
        return service.capabilities()

    @mcp.tool(name="nemofold_anonymize")
    def anonymize(text: str, sensitive_terms: list[str] | None = None) -> dict[str, Any]:
        """Pseudonymize bounded text locally without retaining a reverse mapping."""
        return service.anonymize(text, sensitive_terms)

    @mcp.tool(name="nemofold_preview")
    def preview(job: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        """Validate and preview a NemoFold job under the configured root and privacy gates."""
        return service.preview(job, run_id)

    @mcp.tool(name="nemofold_run")
    def run(job: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        """Execute a NemoFold job; file actions remain server-gated and reversible."""
        return service.run(job, run_id)

    @mcp.tool(name="nemofold_analyze_with_provider")
    def analyze_with_selected_provider(
        job: dict[str, Any],
        provider: dict[str, Any],
        run_id: str | None = None,
        approve_external_transfer: bool = False,
    ) -> dict[str, Any]:
        """Anonymize, analyze with a selected provider, and validate every returned quote."""
        return service.analyze_with_provider(
            job,
            provider,
            run_id,
            approve_external_transfer,
        )

    @mcp.tool(name="nemofold_save_draft")
    def save_draft(
        job: dict[str, Any],
        provider: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Configure a complete job for later review and execution in the local browser."""
        return service.save_draft(job, provider, name)

    @mcp.tool(name="nemofold_list_drafts")
    def list_drafts() -> dict[str, Any]:
        """List model- or CLI-prepared jobs waiting in the local browser inbox."""
        return service.list_drafts()

    @mcp.tool(name="nemofold_verify_report")
    def verify_report(report_path: str) -> dict[str, Any]:
        """Verify a RunReport and every recorded artifact inside the configured roots."""
        return service.verify_report(report_path)

    return mcp


def run_stdio_server(config: MCPServerConfig) -> None:
    build_mcp_server(config).run(transport="stdio")


def main() -> int:
    parser = argparse.ArgumentParser(description="NemoFold MCP stdio server")
    parser.add_argument("--allow-root", action="append", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--allow-external-models", action="store_true")
    parser.add_argument("--max-external-cost-usd", type=float, default=0.0)
    parser.add_argument("--approve-actions", action="store_true")
    args = parser.parse_args()
    run_stdio_server(
        MCPServerConfig(
            base_dir=Path(args.base_dir),
            execution=ExecutionConfig(
                allowed_roots=tuple(args.allow_root),
                external_models_allowed=args.allow_external_models,
                max_external_cost_usd=args.max_external_cost_usd,
                apply_actions_allowed=args.approve_actions,
            ),
        )
    )
    return 0
