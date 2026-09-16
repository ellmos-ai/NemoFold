from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pytest

from nemofold.application import ExecutionConfig
from nemofold.cli import build_parser, main
from nemofold.job_io import SUPPORTED_WORKFLOWS
from nemofold.webapp import WebAppConfig, build_server


@contextmanager
def running_server(tmp_path):
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def running_public_demo(source_root):
    server = build_server(
        WebAppConfig(
            base_dir=source_root.parent,
            execution=ExecutionConfig(allowed_roots=(str(source_root),)),
            public_demo=True,
            demo_source_root=source_root,
            max_parallel_jobs=1,
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_json(url: str) -> tuple[dict, object]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - loopback test server
        return json.load(response), response.headers


def post_json(url: str, payload: dict, *, origin: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test server
        return json.load(response)


def test_web_console_serves_product_ui_and_executes_strict_preview(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins on 1 April 2026.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 4, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
            headers = response.headers
        status, _ = get_json(base_url + "/api/status")
        preview = post_json(
            base_url + "/api/preview",
            {"run_id": "web_preview", "job": job},
        )

    assert 'href="/folders"' in html
    assert 'href="/processes"' in html
    assert 'href="/governance"' in html
    assert 'href="/connections"' in html
    assert "Know what your documents prove." in html
    assert "EVIDENCE CHAIN" in html
    assert "ORIGIN" in html
    assert "ACTION" in html
    assert "PRODUCT MAP" in html
    assert "Folders" in html
    assert "Artifacts" in html
    assert 'id="targetRoots"' in html
    element_ids = re.findall(r'\sid="([^"]+)"', html)
    required_ids = {
        "jobForm",
        "workflow",
        "runId",
        "customRunId",
        "runIdState",
        "inputRoots",
        "targetRoots",
        "outputDir",
        "questions",
        "promptLibraryButton",
        "promptSaveButton",
        "privacy",
        "actionMode",
        "modelId",
        "budget",
        "parameters",
        "analysisScale",
        "executionMode",
        "providerId",
        "providerModel",
        "providerTokens",
        "providerTimeout",
        "providerRoute",
        "providerTransport",
        "externalApprovalRow",
        "externalApproval",
        "providerHint",
        "workflowHint",
        "previewButton",
        "runButton",
        "result",
        "artifactStudio",
        "artifactGallery",
        "artifactRefresh",
        "folderDialog",
        "promptLibraryDialog",
        "draftInbox",
        "draftSelect",
        "draftLoad",
        "researchNotebook",
        "notebookSelect",
        "notebookName",
        "notebookGoal",
        "notebookSave",
        "notebookRuns",
        "systemState",
        "cloudBadge",
        "connectionPanel",
        "connectionLocal",
        "connectionProvider",
        "connectionTransfer",
        "connectionCloud",
        "connectionRegistry",
    }
    assert required_ids <= set(element_ids)
    assert len(element_ids) == len(set(element_ids))
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert status["cloud_proof"] is False
    assert status["live_runtime_ready"] is False
    assert status["provider_surface_enabled"] is True
    assert status["folder_picker_enabled"] is True
    assert status["artifact_surface_enabled"] is True
    assert status["draft_surface_enabled"] is True
    assert status["notebook_surface_enabled"] is True
    assert status["external_models_allowed"] is False
    # Bound to the contract itself: activating a workflow should not need a
    # magic number edited here as well.
    assert len(status["workflows"]) == len(SUPPORTED_WORKFLOWS)
    assert "document_registry" in status["workflows"]
    assert preview["ok"] is True
    assert preview["report"]["workflow"] == "evidence_analyst"
    assert preview["report"]["status"] == "planned"
    assert preview["report"]["metadata"]["cloud_proof"] is False
    assert preview["report"]["coverage"]["read_sources"] == 1


def test_web_api_preserves_the_medical_authority_block(tmp_path) -> None:
    documents = tmp_path / "medical-documents"
    documents.mkdir()
    (documents / "bericht.txt").write_text(
        "Befund: Schilddrüse vergrößert.\n", encoding="utf-8"
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

    with running_server(tmp_path) as base_url, pytest.raises(HTTPError) as captured:
        post_json(
            base_url + "/api/run",
            {"run_id": "web_medical_diagnosis", "job": job},
        )

    payload = json.load(captured.value)
    assert captured.value.code == 409
    assert payload["ok"] is False
    assert payload["report"]["status"] == "blocked"
    assert payload["report"]["errors"] == ["medical_authority_denied:diagnosis"]
    assert payload["report"]["metadata"]["medical_authority"] == "denied"
    assert payload["report"]["metadata"]["needs_user_input"] is True
    assert Path(payload["report_path"]).is_file()
    assert not tuple((tmp_path / "medical-output").glob("*.synopsis.md"))


@pytest.mark.parametrize(
    ("route", "page", "tab"),
    [
        ("/", "overview", ""),
        ("/folders", "folders", ""),
        ("/processes", "processes", "workflows"),
        ("/processes?tab=registry", "processes", "registry"),
        ("/processes?tab=artifacts", "processes", "artifacts"),
        ("/processes?tab=nonsense", "processes", "workflows"),
        ("/governance", "governance", "policies"),
        ("/governance?tab=rules", "governance", "rules"),
        ("/connections", "connections", ""),
    ],
)
def test_web_console_serves_each_area_and_tab_as_a_real_route(tmp_path, route, page, tab) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + route, timeout=5) as response,  # noqa: S310
    ):
        html = response.read().decode()

    assert response.status == 200
    # Page and tab are stamped by the server, so a section is never briefly
    # visible in the wrong room before the script runs.
    assert f'<body data-page="{page}" data-tab="{tab}">' in html
    assert 'data-page-link="folders"' in html
    assert 'data-page-link="processes"' in html
    assert 'data-page-section="folders processes governance connections"' in html


@pytest.mark.parametrize(
    ("old_route", "target"),
    [
        ("/document-center", "/folders"),
        ("/analysis", "/processes?tab=workflows"),
        ("/routines", "/processes?tab=workflows&tag=scheduled"),
        ("/artifacts", "/processes?tab=artifacts"),
        # A link that names one contract lands where single instruments live.
        ("/analysis?workflow=fact_distill", "/processes?tab=registry&workflow=fact_distill"),
        ("/document-center?workflow=smart_inbox", "/processes?tab=registry&workflow=smart_inbox"),
        # An unknown workflow is not echoed back into a URL.
        ("/analysis?workflow=../../etc", "/processes?tab=workflows"),
    ],
)
def test_the_old_routes_still_lead_somewhere(tmp_path, old_route, target) -> None:
    class KeepRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

    opener = build_opener(KeepRedirect)
    with running_server(tmp_path) as base_url, pytest.raises(HTTPError) as moved:
        opener.open(base_url + old_route, timeout=5)

    # 302 and not 301: an IA one release old should not be burned into a cache.
    assert moved.value.code == 302
    assert moved.value.headers["Location"] == target


def test_web_console_assets_expose_workflow_specific_defaults(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.js", timeout=5) as response,  # noqa: S310
    ):
        script = response.read().decode()

    assert "workflowDefaults" in script
    assert "target_roots: lines" in script
    assert 'evidence_level: "offline"' in script
    assert "result-summary" in script
    assert 'apiEndpoint = "provider-analyze"' in script
    assert "External providers require Privacy = allow_once." in script
    assert "Approve this external transfer once before running." in script
    assert "assignRunId" in script
    assert "loadArtifacts" in script
    assert "loadDraftInbox" in script
    assert "promptCatalogKey" in script
    assert "pageConfiguration" in script
    assert "configureRoutedPage" in script
    assert "renderConnectionStatus" in script


def test_web_console_css_keeps_evidence_labels_inside_their_cells(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.css", timeout=5) as response,  # noqa: S310
    ):
        stylesheet = response.read().decode()

    assert ".evidence-chain ol" in stylesheet
    assert "grid-template-columns:repeat(7,minmax(0,1fr))" in stylesheet
    assert "overflow-wrap:anywhere" in stylesheet
    assert "a:focus-visible,button:focus-visible" in stylesheet
    assert "word-break:break-word" in stylesheet
    assert ".approval-gate" in stylesheet
    assert ".provider-contract" in stylesheet
    assert ".workflow-map" in stylesheet
    assert ".privacy-center" in stylesheet
    assert ".artifact-gallery" in stylesheet
    assert ".voyage-scene.analysis-lab" in stylesheet
    assert ".research-notebook" in stylesheet
    assert ".notebook-sonar" in stylesheet
    assert 'body[data-tab="workflows"]' in stylesheet
    assert ".area-tabs" in stylesheet
    assert ".library-filter" in stylesheet
    assert ".governance-register" in stylesheet
    assert ".exception-row" in stylesheet
    assert ".connection-registry" in stylesheet
    assert ".command-bridge" in stylesheet
    assert ".task-card" in stylesheet
    assert ".home-glance,.task-cards,.echo-check" in stylesheet
    assert ".form-grid>*{min-width:0}" in stylesheet
    assert 'body[data-page="governance"]' in stylesheet
    # Pin the effect, not its formatting: the porthole must have a branch that
    # stops every drifter and mote when the reader asked for reduced motion.
    assert "@media(prefers-reduced-motion:reduce)" in stylesheet
    assert ".porthole-life .drifter,.porthole-life .mote{animation:none}" in stylesheet
    # Narrow viewports must collapse the tile, instrument and card grids to one
    # column; two cramped columns were still readable but clipped their captions.
    assert "@media(max-width:600px){" in stylesheet
    assert (
        ".glance-tiles,.bridge-panel,.task-card-list,.bridge-doctrine ol,.bridge-gauges"
        "{grid-template-columns:minmax(0,1fr)}"
    ) in stylesheet


def test_web_console_rejects_cross_origin_posts(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        pytest.raises(HTTPError) as captured,
    ):
        post_json(
            base_url + "/api/preview",
            {"run_id": "cross_origin", "job": {}},
            origin="https://attacker.example",
        )

    assert captured.value.code == 403
    assert json.load(captured.value)["error"] == "origin_rejected"


def test_non_loopback_binding_requires_explicit_exposure(tmp_path) -> None:
    config = WebAppConfig(
        base_dir=tmp_path,
        execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
    )

    with pytest.raises(PermissionError, match="explicit network exposure"):
        build_server(config, host="0.0.0.0", port=0)


def test_web_console_action_gate_uses_the_shared_explicit_approval_name(tmp_path) -> None:
    args = build_parser().parse_args(["serve", "--allow-root", str(tmp_path), "--approve-actions"])

    assert args.approve_actions is True


def test_local_folder_picker_is_allow_root_bounded(tmp_path) -> None:
    documents = tmp_path / "documents"
    child = documents / "child"
    child.mkdir(parents=True)

    with running_server(tmp_path) as base_url:
        roots = post_json(base_url + "/api/folders", {"path": None})
        listing = post_json(base_url + "/api/folders", {"path": str(documents)})
        with pytest.raises(HTTPError) as captured:
            post_json(base_url + "/api/folders", {"path": str(tmp_path.parent)})

    assert roots["roots"] == [{"name": tmp_path.name, "path": str(tmp_path)}]
    assert listing["current"]["path"] == str(documents)
    assert {entry["path"] for entry in listing["directories"]} == {str(child)}
    assert captured.value.code == 400


def test_artifact_studio_lists_verified_runs_and_serves_registered_files(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 16, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        run = post_json(base_url + "/api/run", {"run_id": "artifact_run", "job": job})
        catalog = post_json(base_url + "/api/artifacts", {"output_dir": "output"})
        ledger_path = catalog["runs"][0]["ledger_path"]
        query = urlencode({"output_dir": "output", "path": ledger_path})
        with urlopen(base_url + "/api/artifact?" + query, timeout=5) as response:  # noqa: S310
            ledger = json.load(response)

    assert run["report"]["status"] == "executed"
    assert catalog["runs"][0]["verification"]["valid"] is True
    assert catalog["runs"][0]["verification"]["checked_artifacts"] >= 1
    assert ledger["run_id"] == "artifact_run"


def test_local_api_assigns_a_run_id_when_the_caller_omits_it(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 16, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        preview = post_json(base_url + "/api/preview", {"job": job})

    assert preview["report"]["run_id"].startswith("api_")


def test_artifact_studio_does_not_serve_an_artifact_from_a_failed_ledger(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 16, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        post_json(base_url + "/api/run", {"run_id": "tampered_artifact", "job": job})
        initial = post_json(base_url + "/api/artifacts", {"output_dir": "output"})
        artifact = next(item for item in initial["runs"][0]["artifacts"] if item["available"])
        Path(artifact["path"]).write_text("tampered", encoding="utf-8")
        catalog = post_json(base_url + "/api/artifacts", {"output_dir": "output"})
        query = urlencode({"output_dir": "output", "path": artifact["path"]})
        with pytest.raises(HTTPError) as captured:
            urlopen(base_url + "/api/artifact?" + query, timeout=5)  # noqa: S310

    assert catalog["runs"][0]["verification"]["valid"] is False
    assert all(not item["available"] for item in catalog["runs"][0]["artifacts"])
    assert captured.value.code == 400


def test_api_saved_draft_loads_for_browser_review_without_approvals(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["Inspect the full corpus."],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 256, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        created = post_json(
            base_url + "/api/drafts",
            {
                "name": "Model prepared analysis",
                "job": job,
                "provider": {
                    "provider_id": "ollama",
                    "model": "qwen3",
                    "max_output_tokens": 32768,
                    "timeout_seconds": 1800,
                },
            },
        )
        drafts, _ = get_json(base_url + "/api/drafts")
        loaded, _ = get_json(
            base_url + "/api/draft?" + urlencode({"id": created["draft"]["draft_id"]})
        )

    assert drafts["drafts"][0]["name"] == "Model prepared analysis"
    assert loaded["draft"]["job"]["parameters"]["max_chunks"] == 256
    assert loaded["draft"]["approval_state"]["external_transfer"] is False
    assert loaded["draft"]["approval_state"]["file_actions"] is False


def test_research_notebook_saves_scope_and_links_a_verified_run(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"max_chunks": 256, "formats": ["md"]},
    }

    with running_server(tmp_path) as base_url:
        created = post_json(
            base_url + "/api/notebooks",
            {
                "name": "Coverage investigation",
                "goal": "Establish the effective date with exact evidence.",
                "job": job,
                "provider": None,
            },
        )
        run = post_json(base_url + "/api/run", {"run_id": "notebook_run", "job": job})
        linked = post_json(
            base_url + "/api/notebook-run",
            {
                "notebook_id": created["notebook"]["notebook_id"],
                "run_id": "notebook_run",
            },
        )
        notebooks, _ = get_json(base_url + "/api/notebooks")
        loaded, _ = get_json(
            base_url + "/api/notebook?"
            + urlencode({"id": created["notebook"]["notebook_id"]})
        )

    assert run["report"]["status"] == "executed"
    assert notebooks["notebooks"][0]["run_count"] == 1
    assert loaded["notebook"]["approval_state"]["external_transfer"] is False
    assert linked["notebook"]["runs"][0]["run_id"] == "notebook_run"
    assert linked["notebook"]["runs"][0]["verification"]["valid"] is True


def public_demo_job(**overrides):
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "evidence_analyst",
        "input_roots": ["demo://synthetic-home"],
        "target_roots": [],
        "output_dir": "demo://ephemeral",
        "questions": ["When does coverage begin?"],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "model_budget_usd": 0,
        "parameters": {
            "max_chunks": 8,
            "formats": ["md", "txt"],
            "conflict_scan": True,
        },
    }
    job.update(overrides)
    return job


def test_public_demo_executes_only_synthetic_ephemeral_work(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "policy.txt").write_text("Coverage begins on 1 April 2026.", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url):
        status, _ = get_json(base_url + "/api/status")
        result = post_json(
            base_url + "/api/run",
            {"job": public_demo_job()},
        )

    serialized = json.dumps(result)
    assert status["mode"] == "public-synthetic-demo"
    assert status["public_demo"] is True
    assert status["read_only"] is True
    assert status["synthetic_only"] is True
    assert status["provider_surface_enabled"] is False
    assert status["external_models_allowed"] is False
    assert status["providers"] == []
    assert "smart_inbox" not in status["workflows"]
    assert result["ok"] is True
    assert result["report"]["status"] == "executed"
    assert result["report_path"] is None
    assert result["demo_constraints"] == {
        "ephemeral_output": True,
        "external_models_allowed": False,
        "file_actions_allowed": False,
        "synthetic_only": True,
    }
    assert str(tmp_path) not in serialized
    assert "nemofold-public-demo-" not in serialized
    assert result["report"]["run_id"].startswith("demo_")


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"input_roots": ["C:/private"]}, "input_roots are server-controlled"),
        ({"output_dir": "C:/private/output"}, "output_dir is server-controlled"),
        ({"action_mode": "apply"}, "action_mode must be dry_run"),
        ({"model_id": "nvidia/nemotron"}, "does not accept a model_id"),
        ({"workflow": "smart_inbox"}, "workflow is unavailable"),
    ],
)
def test_public_demo_rejects_authority_expansion(tmp_path, override, error) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "source.txt").write_text("Synthetic evidence.", encoding="utf-8")

    with (
        running_public_demo(source_root) as (_, base_url),
        pytest.raises(HTTPError) as captured,
    ):
        post_json(base_url + "/api/run", {"job": public_demo_job(**override)})

    assert captured.value.code == 400
    assert error in json.load(captured.value)["detail"]


def test_public_demo_rejects_external_and_action_capabilities(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()

    with pytest.raises(ValueError, match="forbids external models"):
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(
                allowed_roots=(str(source_root),),
                external_models_allowed=True,
                apply_actions_allowed=True,
                max_external_cost_usd=1,
            ),
            public_demo=True,
            demo_source_root=source_root,
        )


def test_public_demo_rejects_unknown_request_authority(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "source.txt").write_text("Synthetic evidence.", encoding="utf-8")

    with (
        running_public_demo(source_root) as (_, base_url),
        pytest.raises(HTTPError) as captured,
    ):
        post_json(
            base_url + "/api/run",
            {"run_id": "must_not_be_silently_ignored", "job": public_demo_job()},
        )

    assert captured.value.code == 400
    assert "unknown request fields: run_id" in json.load(captured.value)["detail"]


def test_public_demo_bounds_the_operator_selected_corpus(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    for index in range(101):
        (source_root / f"source-{index}.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="bounded corpus limits"):
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(source_root),)),
            public_demo=True,
            demo_source_root=source_root,
        )


def test_public_demo_rejects_work_when_all_bounded_slots_are_busy(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "source.txt").write_text("Synthetic evidence.", encoding="utf-8")

    with running_public_demo(source_root) as (server, base_url):
        assert server.demo_slots.acquire(blocking=False) is True
        try:
            with pytest.raises(HTTPError) as captured:
                post_json(base_url + "/api/run", {"job": public_demo_job()})
        finally:
            server.demo_slots.release()

    assert captured.value.code == 429
    assert json.load(captured.value)["error"] == "demo_busy"


def test_public_demo_has_a_separate_capability_minimal_cli() -> None:
    args = build_parser().parse_args(
        ["serve-demo", "--demo-root", "examples/synthetic-home", "--max-parallel-jobs", "2"]
    )

    assert args.command == "serve-demo"
    assert args.demo_root == "examples/synthetic-home"
    assert args.max_parallel_jobs == 2
    assert not hasattr(args, "approve_actions")
    assert not hasattr(args, "allow_external_models")


def test_public_demo_cli_rejects_a_symlinked_corpus_root(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    linked_root = tmp_path / "linked-home"
    try:
        linked_root.symlink_to(source_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    assert main(["serve-demo", "--demo-root", str(linked_root)]) == 2


def test_draft_and_notebook_lists_reject_out_of_root_stores_with_json(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(documents),)),
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        for endpoint, error_code in (
            ("/api/drafts", "draft_inbox_unavailable"),
            ("/api/notebooks", "notebook_store_unavailable"),
        ):
            with pytest.raises(HTTPError) as captured:
                get_json(base_url + endpoint)
            assert captured.value.code == 400
            payload = json.load(captured.value)
            assert payload["ok"] is False
            assert payload["error"] == error_code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_theme_scene_assets_ship_with_the_package(tmp_path) -> None:
    scenes = (
        "document-center",
        "analysis-lab",
        "folder-routines",
        "artifact-studio",
        "connections",
    )
    with running_server(tmp_path) as base_url:
        for scene in scenes:
            url = f"{base_url}/assets/theme-{scene}.jpg"
            with urlopen(url, timeout=5) as response:  # noqa: S310 - loopback test server
                assert response.headers["Content-Type"] == "image/jpeg"
                assert len(response.read()) > 10_000


def test_every_registered_static_route_resolves_inside_the_package() -> None:
    from nemofold.webapp import STATIC_ROUTES, WEB_ROOT

    assert STATIC_ROUTES
    for route, (filename, content_type) in STATIC_ROUTES.items():
        assert route.startswith("/assets/")
        assert filename.is_file(), f"{route} points at a missing file: {filename.name}"
        assert WEB_ROOT in filename.parents
        assert content_type


def test_loopback_server_rejects_non_local_host_header(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        request = Request(
            base_url + "/api/preview",
            data=json.dumps({"job": {}}).encode(),
            headers={"Content-Type": "application/json", "Host": "evil.example:8765"},
            method="POST",
        )
        with pytest.raises(HTTPError) as captured:
            urlopen(request, timeout=5)  # noqa: S310 - loopback test server

    assert captured.value.code == 403
    assert json.load(captured.value)["error"] == "host_rejected"


def test_request_handler_bounds_socket_reads_with_a_timeout() -> None:
    from nemofold.webapp import NemoFoldRequestHandler

    assert NemoFoldRequestHandler.timeout == 30


def test_corpus_glance_reports_bounded_home_overview(tmp_path) -> None:
    documents = tmp_path / "documents"
    (documents / "nested").mkdir(parents=True)
    (documents / "a.txt").write_text("alpha", encoding="utf-8")
    (documents / "b.md").write_text("bravo", encoding="utf-8")
    (documents / "nested" / "c.md").write_text("charlie", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        result = post_json(base_url + "/api/corpus-glance", {"path": str(documents)})
        default = post_json(base_url + "/api/corpus-glance", {})
        with pytest.raises(HTTPError) as captured:
            post_json(base_url + "/api/corpus-glance", {"path": str(tmp_path.parent)})

    assert result["ok"] is True
    assert result["total_files"] == 3
    assert result["by_format"] == {"md": 2, "txt": 1}
    assert [entry["name"] for entry in result["newest"]]
    assert result["truncated"] is False
    assert default["ok"] is True
    assert captured.value.code == 400
    assert json.load(captured.value)["error"] == "corpus_glance_rejected"


def test_command_bridge_reads_the_authority_the_server_was_started_with(tmp_path) -> None:
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(
                allowed_roots=(str(tmp_path),),
                apply_actions_allowed=True,
                external_models_allowed=True,
                max_external_cost_usd=2.5,
            ),
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    try:
        with urlopen(base_url + "/governance", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        status, _ = get_json(base_url + "/api/status")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert 'id="commandBridge"' in html
    assert 'id="bridgeActionGate"' in html
    assert "AUTHORITY BEFORE INFERENCE" in html
    assert status["apply_actions_allowed"] is True
    assert status["external_models_allowed"] is True
    assert status["max_external_cost_usd"] == 2.5
    assert status["approved_roots"] == [str(tmp_path)]
    assert status["approved_root_count"] == 1


def test_public_demo_status_withholds_root_locations_but_keeps_the_count(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "note.txt").write_text("Coverage begins in April.", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url):
        status, _ = get_json(base_url + "/api/status")

    assert status["approved_roots"] == []
    assert status["approved_root_count"] == 1
    assert status["apply_actions_allowed"] is False
    assert status["max_external_cost_usd"] == 0.0


def test_the_scene_follows_the_tab_and_the_schedule_filter(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.js", timeout=5) as response,  # noqa: S310
    ):
        script = response.read().decode()

    # D-036b: the scenes did not disappear with the rooms, they moved to the
    # tabs and to the schedule filter.
    assert 'if (currentTab === "artifacts") return "artifacts";' in script
    assert 'if (currentTab === "registry") return "registry";' in script
    assert 'return activeTag === "scheduled" ? "scheduled" : "workflows";' in script
    # Line endings differ per checkout, so compare on normalised whitespace.
    flat = " ".join(script.split())
    for key, artwork in (
        ("scheduled", "folder-routines"),
        ("workflows", "analysis-lab"),
        ("artifacts", "artifact-library"),
        ("folders", "document-center"),
    ):
        assert f'{key}: {{ className: "{artwork}"' in flat, key
    # A standing routine never claims NemoFold installed anything.
    assert "NemoFold registers nothing and starts nothing by itself" in script


def test_use_cases_come_first_and_single_instruments_live_in_the_registry(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/folders", timeout=5) as response:  # noqa: S310
            folders = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    # Folders keeps the corpus overview and the use cases bound to it.
    assert 'id="homeGlance"' in folders
    assert 'data-folder-target="homeGlanceRoot"' in folders
    assert 'data-page-section="folders"' in folders
    assert 'data-page-section="overview folders processes"' in folders
    # The single instruments are one collapsed advanced view in the registry,
    # not a card deck repeated in every room.
    assert (
        'id="taskCards" class="task-cards" aria-labelledby="taskCardsTitle" '
        'data-page-section="processes" data-page-tab="registry"'
    ) in folders
    assert "SINGLE INSTRUMENTS · ADVANCED" in folders
    # The engine room is their editor and follows them.
    assert 'data-page-section="processes" data-page-tab="registry"' in folders
    assert "workflowCards" in script
    assert "renderTaskCards" in script
    assert "loadHomeGlance" in script
    assert "loadEcho" in script
    assert "prepareWorkflow" in script
    assert "renderLibraryFilter" in script


def test_artifact_catalog_reports_when_each_ledger_was_written(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "folder_digest",
        "input_roots": ["documents"],
        "output_dir": "output",
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
    }

    with running_server(tmp_path) as base_url:
        post_json(base_url + "/api/run", {"run_id": "echo_run", "job": job})
        catalog = post_json(base_url + "/api/artifacts", {"output_dir": "output"})

    run = next(item for item in catalog["runs"] if item["run_id"] == "echo_run")
    assert run["workflow"] == "folder_digest"
    assert isinstance(run["recorded_at"], str)
    assert run["recorded_at"].endswith("+00:00")


def test_corpus_glance_feeds_the_document_center_home_module(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    (documents / "notes.md").write_text("# notes", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        glance = post_json(base_url + "/api/corpus-glance", {"path": str(documents)})

    assert glance["total_files"] == 2
    assert glance["by_format"] == {"md": 1, "txt": 1}
    assert len(glance["newest"]) == 2
    assert glance["truncated"] is False


def test_engine_room_is_a_drawer_rather_than_a_permanent_page_footer(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/document-center", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()
        with urlopen(base_url + "/assets/app.css", timeout=5) as response:  # noqa: S310
            stylesheet = response.read().decode()

    assert 'id="engineRoom"' in html
    assert 'class="engine-drawer"' in html
    assert 'data-open="false"' in html
    assert 'id="engineHandle"' in html
    assert 'aria-controls="engineRoom"' in html
    assert 'id="jobForm"' in html
    # The permanent footer placement is gone with its grid.
    assert "workspace-grid" not in html
    assert "workspace-grid" not in stylesheet
    # Scope ledger now lives inside the drawer behind a collapsed anchor.
    assert 'data-collapse="scopeLedger"' in html
    assert 'id="scopeLedger" class="collapse-panel scope-rail" hidden' in html
    for symbol in ("icon-wheel", "icon-stethoscope", "icon-radar", "icon-lifebuoy"):
        assert f'id="{symbol}"' in html
    assert "setEngineDrawer" in script
    assert "toggleCollapse" in script
    assert '.engine-drawer[data-open="true"]{visibility:visible;transform:none}' in stylesheet


def test_engine_room_opens_with_the_central_controls_only(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/analysis", timeout=5) as response,  # noqa: S310
    ):
        html = response.read().decode()

    # Central controls stay outside every collapse panel.
    for control in ('id="workflow"', 'id="questions"', 'id="inputRoots"', 'id="previewButton"'):
        assert control in html
    # Secondary blocks start collapsed behind an instrument anchor.
    for group in ("grpRunIdentity", "grpOutputs", "grpAuthority", "grpProvider", "scopeLedger"):
        assert f'data-collapse="{group}"' in html
        assert f'id="{group}"' in html
        assert f'aria-controls="{group}"' in html
    assert html.count('aria-expanded="false"') >= 5
    assert html.count("collapse-panel") >= 5
    assert 'id="grpAuthority" class="collapse-panel form-grid" hidden' in html
    assert 'id="draftInbox"' in html.split('id="grpRunIdentity"', 1)[1]
    assert 'id="runId"' in html.split('id="grpRunIdentity"', 1)[1]
    assert 'id="outputDir"' in html.split('id="grpOutputs"', 1)[1]
    assert "Diagnose exact scope" in html


def test_porthole_is_one_svg_and_explainers_start_collapsed(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/analysis", timeout=5) as response,  # noqa: S310
    ):
        html = response.read().decode()

    # One SVG overlay carries every creature; the loose mote divs are gone.
    assert '<svg class="porthole-life"' in html
    assert '<i class="mote' not in html
    assert html.count('class="drifter') == 3
    assert html.count('class="mote') == 5
    # Explainer sections start collapsed behind a lifebuoy anchor.
    for group in ("trustBoundaryDetail", "bridgeDoctrine"):
        assert f'data-collapse="{group}"' in html
        assert f'<div id="{group}" class="collapse-panel" hidden>' in html
    assert 'class="instrument-icon radar"' in html


def test_drawer_is_a_modal_overlay_only_on_narrow_viewports(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/assets/app.css", timeout=5) as response:  # noqa: S310
            stylesheet = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    # Below 680px the drawer takes the whole surface and locks the page behind it.
    assert ".engine-drawer{width:100vw;border-left:0}" in stylesheet
    assert 'body[data-engine-room="open"]{overflow:hidden}' in stylesheet
    # role/aria-modal are set only for that overlay, never for the side panel.
    assert "syncDrawerModality" in script
    assert '"(max-width: 680px)"' in script
    assert 'drawer.setAttribute("aria-modal", "true")' in script
    assert 'drawer.removeAttribute("aria-modal")' in script
    # Escape closes and focus returns to whatever opened the drawer.
    assert 'event.key === "Escape"' in script
    assert "engineReturnFocus" in script


def test_overview_folds_its_documentation_behind_the_ships_chart(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.css", timeout=5) as response:  # noqa: S310
            stylesheet = response.read().decode()

    # The chart itself is the control, and it starts folded.
    assert 'id="chartToggle"' in html
    assert 'data-collapse="chartDetail"' in html
    assert 'aria-controls="chartDetail"' in html
    assert '<div id="chartDetail" class="chart-detail" hidden>' in html
    assert 'data-open="false"' in html
    assert "THE SHIP'S CHART" in html
    assert "url('/assets/theme-chart.jpg')" in stylesheet

    # Everything explanatory still exists - it moved, it was not deleted.
    folded_away = html.split('id="chartDetail"', 1)[1]
    for marker in (
        "Cloud proof: false",
        "EVIDENCE CHAIN",
        "ORIGIN",
        "ACTION",
        "PRODUCT MAP",
        "one contract per instrument.",  # a count here goes stale silently
        "ROADMAP:",
    ):
        assert marker in folded_away, marker
    # The hero keeps one sentence and the area cards stay in the open.
    assert (
        '<p class="lede">NemoFold turns approved folders into traceable working memory.</p>'
        in html
    )
    hero_and_cards = html.split('id="chartDetail"', 1)[0]
    assert 'class="product-areas"' in hero_and_cards
    assert "Governance" in hero_and_cards


def test_captains_desk_plans_and_prepares_drafts_without_running_anything(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.txt").write_text("Coverage begins in April.", encoding="utf-8")
    request = {
        "text": (
            "Unfall mit Hyundai und schreib mir eine mail an zuständigen "
            "versicherungsberater füge bild ein als entwurf"
        ),
        "context": {"input_roots": [str(documents)]},
    }

    with running_server(tmp_path) as base_url:
        status, _ = get_json(base_url + "/api/status")
        plan = post_json(base_url + "/api/wizard", request)
        prepared = post_json(base_url + "/api/wizard-prepare", request)
        inbox, _ = get_json(base_url + "/api/drafts")

    assert status["wizard_surface_enabled"] is True
    # Planning alone writes nothing.
    assert plan["ok"] is True
    assert plan["prepared"] is False
    assert plan["drafts"] == []
    assert plan["executed"] is False
    assert plan["cloud_proof"] is False
    assert [step["workflow"] for step in plan["steps"]][-1] == "controlled_email"

    # Preparing writes drafts and only drafts.
    assert prepared["prepared"] is True
    assert len(prepared["drafts"]) == len(plan["steps"])
    assert prepared["drafts"][0]["name"].startswith("Voyage 1/")
    prepared_ids = {item["draft_id"] for item in prepared["drafts"]}
    assert prepared_ids <= {item["draft_id"] for item in inbox["drafts"]}
    for entry in inbox["drafts"]:
        if entry["draft_id"] in prepared_ids:
            assert entry["source"] == "wizard"


def test_captains_desk_refuses_a_request_it_cannot_turn_into_a_step(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        plan = post_json(
            base_url + "/api/wizard",
            {"text": "wie ist das wetter morgen in bernau"},
        )
        with pytest.raises(HTTPError) as refused:
            post_json(
                base_url + "/api/wizard-prepare",
                {"text": "wie ist das wetter morgen in bernau"},
            )

    assert plan["steps"] == []
    assert plan["matched"] is False
    assert refused.value.code == 400
    assert json.load(refused.value)["error"] == "wizard_nothing_to_prepare"


def test_captains_desk_is_absent_in_the_public_demo(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "note.txt").write_text("Coverage begins in April.", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url):
        status, _ = get_json(base_url + "/api/status")
        with pytest.raises(HTTPError) as refused:
            post_json(base_url + "/api/wizard", {"text": "bündle die unterlagen"})

    assert status["wizard_surface_enabled"] is False
    assert refused.value.code == 404


def test_captains_desk_is_closed_on_a_network_exposed_server(tmp_path) -> None:
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
            exposed_to_network=True,
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(HTTPError) as refused:
            post_json(f"http://{host}:{port}/api/wizard", {"text": "bündle die unterlagen"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert refused.value.code == 403
    assert json.load(refused.value)["error"] == "wizard_surface_loopback_only"


def test_captains_desk_is_served_on_the_overview_only(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        pages = {}
        for route in ("/", "/folders"):
            with urlopen(base_url + route, timeout=5) as response:  # noqa: S310
                pages[route] = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    overview = pages["/"]
    assert 'id="captainsDesk"' in overview
    assert 'data-page-section="overview"' in overview
    assert 'id="deskRequest"' in overview
    assert 'id="deskRoots"' in overview
    assert 'aria-live="polite"' in overview
    assert "ASK THE CAPTAIN" in overview
    # One desk, one place: the markup is shared, the section is overview-scoped.
    assert 'id="captainsDesk"' in pages["/folders"]
    assert 'data-page-section="overview"' in pages["/folders"]
    # The desk states its limit in the surface itself, not only in the docs.
    assert "It plans only: nothing is executed" in overview
    for symbol in ("askTheCaptain", "prepareVoyage", "renderVoyagePlan", "wizardSurfaceEnabled"):
        assert symbol in script


def test_wizard_prepare_answers_when_the_draft_inbox_is_out_of_scope(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    # Allow only the source folder, so the draft inbox itself is out of scope.
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(documents),)),
        ),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(HTTPError) as refused:
            post_json(
                f"http://{host}:{port}/api/wizard-prepare",
                {"text": "schreib eine mail als entwurf", "context": {"input_roots": []}},
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # A refusal must arrive as an answer, never as a dropped connection.
    assert refused.value.code == 400
    body = json.load(refused.value)
    assert body["error"] == "wizard_draft_rejected"
    assert "allow roots" in body["detail"]


def test_use_case_library_lists_presets_and_copies_one(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text("Beitrag: 148 Euro", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        status, _ = get_json(base_url + "/api/status")
        listed, _ = get_json(base_url + "/api/voyages")
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
                "name": "Meine Faktenlage",
            },
        )
        after, _ = get_json(base_url + "/api/voyages")
        deleted = post_json(
            base_url + "/api/voyage-delete", {"voyage_id": copied["voyage"]["voyage_id"]}
        )

    assert status["voyage_surface_enabled"] is True
    # Shipped specialists are visible from the first listing and read-only.
    shipped = [item for item in listed["voyages"] if item["source"] == "preset"]
    assert shipped and all(item["editable"] is False for item in shipped)
    assert all(item["voyage_id"].startswith("preset_") for item in shipped)

    assert copied["voyage"]["name"] == "Meine Faktenlage"
    assert copied["voyage"]["steps"][0]["job"]["action_mode"] == "dry_run"
    assert any(item["editable"] for item in after["voyages"])
    assert deleted["deleted"] is True


def test_use_case_library_refuses_to_delete_a_shipped_specialist(tmp_path) -> None:
    with running_server(tmp_path) as base_url, pytest.raises(HTTPError) as refused:
        post_json(base_url + "/api/voyage-delete", {"voyage_id": "preset_fact_digest_pdf"})

    assert refused.value.code == 400
    assert "read-only sources" in json.load(refused.value)["detail"]


def test_use_case_library_is_absent_in_the_public_demo(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "note.txt").write_text("x", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url):
        status, _ = get_json(base_url + "/api/status")
        with pytest.raises(HTTPError) as refused:
            post_json(base_url + "/api/voyages", {"name": "x", "steps": []})

    assert status["voyage_surface_enabled"] is False
    assert refused.value.code == 404


def test_running_a_saved_voyage_returns_a_dossier_over_its_steps(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text(
        "Die Deckung beginnt am 1. April 2026.\nDer Beitrag betraegt 148 Euro.",
        encoding="utf-8",
    )

    with running_server(tmp_path) as base_url:
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        run = post_json(
            base_url + "/api/voyage-run", {"voyage_id": copied["voyage"]["voyage_id"]}
        )

    assert run["ok"] is True
    assert run["status"] == "executed"
    assert run["stopped_at"] is None
    assert len(run["steps"]) == 1
    step = run["steps"][0]
    assert step["workflow"] == "fact_distill"
    assert step["status"] == "executed"
    assert step["artifact_count"] >= 1
    # A chained step never escalates on its own, and says which model ran.
    assert step["model_used"] == "nemofold-local-core"
    # The note now covers all three levels, not just the step's own setting.
    assert "No preference was set at any level" in step["model_note"]
    assert step["model_level"] == "default"
    assert step["rights"] == "draft_only"
    assert step["rights_level"] == "default"
    assert run["model_authority"] == "links_win"
    assert run["run_level_override"] is None
    assert Path(run["dossier_path"]).is_file()


def test_web_voyage_result_exposes_the_same_verified_handoff_as_cli_and_mcp(
    tmp_path,
) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text("Befund: Schilddrüse unauffällig.", encoding="utf-8")
    steps = []
    for order, workflow in enumerate(("fact_distill", "folder_digest"), start=1):
        step = {
            "workflow": workflow,
            "job": {
                "schema": "nemofold.job.v1",
                "workflow": workflow,
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out" / f"0{order}-{workflow}"),
                "privacy_mode": "local_only",
                "action_mode": "dry_run",
                "parameters": {"formats": ["md"]} if order == 1 else {},
            },
        }
        if order == 2:
            step["handoff"] = {"format": "markdown"}
        steps.append(step)

    with running_server(tmp_path) as base_url:
        saved = post_json(base_url + "/api/voyages", {"name": "Verified edge", "steps": steps})
        run = post_json(
            base_url + "/api/voyage-run",
            {"voyage_id": saved["voyage"]["voyage_id"], "run_id": "web_edge"},
        )

    assert run["ok"] is True
    edge = run["steps"][1]["handoff"]
    assert edge["schema"] == "nemofold.artifact-handoff.v1"
    assert edge["producer_run_id"] == "web_edge_01"
    assert edge["format"] == "markdown"


def test_library_edit_returns_a_diff_and_writes_only_on_a_separate_save(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text("Beitrag: 148 Euro", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        voyage_id = copied["voyage"]["voyage_id"]
        edit = post_json(
            base_url + "/api/voyage-edit",
            {"voyage_id": voyage_id, "text": "füge am Ende einen Tagesbericht ein"},
        )
        listed_before, _ = get_json(base_url + "/api/voyages")
        saved = post_json(
            base_url + "/api/voyages",
            {
                "voyage_id": voyage_id,
                "name": copied["voyage"]["name"],
                "steps": edit["steps_after"],
            },
        )

    # The edit is a proposal: it names the change and writes nothing.
    assert edit["applied"] is False
    assert edit["applicable"] is True
    assert edit["before"] == ["fact_distill"]
    assert edit["after"] == ["fact_distill", "daily_arrivals"]
    unchanged = next(
        item for item in listed_before["voyages"] if item["voyage_id"] == voyage_id
    )
    assert unchanged["workflows"] == ["fact_distill"]

    # Applying is an ordinary save, so it passes the same validation.
    assert [step["workflow"] for step in saved["voyage"]["steps"]] == [
        "fact_distill",
        "daily_arrivals",
    ]


def test_library_edit_explains_an_unmappable_request(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()

    with running_server(tmp_path) as base_url:
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        edit = post_json(
            base_url + "/api/voyage-edit",
            {
                "voyage_id": copied["voyage"]["voyage_id"],
                "text": "füge einen Anonymisierungsschritt ein",
            },
        )

    assert edit["applicable"] is False
    assert edit["before"] == edit["after"]
    assert any("privacy gate" in note for note in edit["notes"])


def test_a_run_level_override_is_reported_and_changes_nothing_stored(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text("Beitrag: 148 Euro.", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        run = post_json(
            base_url + "/api/voyage-run",
            {
                "voyage_id": copied["voyage"]["voyage_id"],
                "model_override": {"provider": "ollama", "model": "qwen3"},
            },
        )
        listed, _ = get_json(base_url + "/api/voyages")

    assert run["run_level_override"] == "ollama:qwen3"
    # The override was accepted at the run level, and fact_distill is
    # deterministic, so the step reports the local core and says why - rather
    # than crediting a model that was never asked anything.
    assert run["steps"][0]["model_level"] == "run-override"
    assert run["steps"][0]["model_used"] == "nemofold-local-core"
    assert "uses no model" in run["steps"][0]["model_note"]
    # Nothing about the stored voyage moved.
    entry = next(
        item for item in listed["voyages"] if item["voyage_id"] == copied["voyage"]["voyage_id"]
    )
    assert entry["overrides_links"] is False


def test_the_wizard_offers_to_keep_an_unfulfillable_plan_as_a_reservation(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        plan = post_json(
            base_url + "/api/wizard",
            {"text": "dokument das bilingual vorliegt regelmäßig abgleichen"},
        )
        simple = post_json(base_url + "/api/wizard", {"text": "bündle die unterlagen"})

    assert plan["reservation"]["suggested"] is True
    assert plan["reservation"]["missing_capability"] == "bilingual_sync"
    assert "becomes runnable once that instrument exists" in plan["reservation"]["note"]
    # A plan that needs nothing new is not turned into a reservation.
    assert simple["reservation"]["suggested"] is False


def test_one_saved_voyage_is_read_through_its_own_endpoint(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text("Beitrag: 148 Euro", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_daily_arrivals",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        voyage_id = copied["voyage"]["voyage_id"]
        detail, _ = get_json(base_url + f"/api/voyage?id={voyage_id}")
        with pytest.raises(HTTPError) as refused:
            get_json(base_url + "/api/voyage?id=voyage_does_not_exist")

    assert detail["voyage"]["voyage_id"] == voyage_id
    assert [step["workflow"] for step in detail["voyage"]["steps"]] == ["daily_arrivals"]
    # The room and the routine travel with the copy.
    assert detail["voyage"]["tags"] == ["folder-watch", "scheduled"]
    assert detail["voyage"]["schedule"]["cadence"] == "daily"
    assert refused.value.code == 400


def test_the_voyage_read_endpoint_is_absent_in_the_public_demo(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "note.txt").write_text("x", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url), pytest.raises(HTTPError) as refused:
        get_json(base_url + "/api/voyage?id=voyage_x")

    assert refused.value.code == 404


def test_the_policy_register_saves_binds_and_lists_its_exceptions(tmp_path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "police.txt").write_text("Beitrag: 148 Euro", encoding="utf-8")

    with running_server(tmp_path) as base_url:
        status, _ = get_json(base_url + "/api/status")
        rule = post_json(
            base_url + "/api/policies",
            {
                "name": "Anhänge nie ohne Bestätigung",
                "form": "rule",
                "statements": ["Ein Anhang geht nur mit Bestätigung."],
            },
        )
        profile = post_json(
            base_url + "/api/policies",
            {
                "name": "Standardrechte",
                "form": "policy",
                "kind": "rights_profile",
                "statements": ["Entwurf bleibt der Normalfall."],
                "body": {"rights": "draft_only"},
                "applies_by_default": True,
            },
        )
        copied = post_json(
            base_url + "/api/voyage-preset",
            {
                "preset_id": "preset_fact_digest_pdf",
                "input_roots": [str(documents)],
                "output_dir": str(tmp_path / "out"),
            },
        )
        voyage_id = copied["voyage"]["voyage_id"]
        bound = post_json(
            base_url + "/api/policy-bind",
            {
                "policy_id": rule["policy"]["policy_id"],
                "target": "voyage",
                "voyage_id": voyage_id,
            },
        )
        # A voyage that departs from the default shows up in the overview.
        post_json(
            base_url + "/api/voyages",
            {
                "voyage_id": voyage_id,
                "name": copied["voyage"]["name"],
                "steps": copied["voyage"]["steps"],
                "rights": "send_with_confirmation",
                "policy_refs": [rule["policy"]["policy_id"]],
            },
        )
        register, _ = get_json(base_url + "/api/policies")
        single, _ = get_json(base_url + f"/api/policy?id={rule['policy']['policy_id']}")
        removed = post_json(
            base_url + "/api/policy-delete", {"policy_id": profile["policy"]["policy_id"]}
        )

    assert status["policy_surface_enabled"] is True
    assert bound["policy"]["bindings"][0]["voyage_id"] == voyage_id
    assert single["policy"]["name"] == "Anhänge nie ohne Bestätigung"
    assert register["default_rights"] == "draft_only"
    assert [row["subject"] for row in register["exceptions"]] == ["rights"]
    assert register["exceptions"][0]["voyage_id"] == voyage_id
    assert register["exceptions"][0]["value"] == "send_with_confirmation"
    assert removed["deleted"] is True


def test_the_policy_register_is_absent_in_the_public_demo(tmp_path) -> None:
    source_root = tmp_path / "synthetic-home"
    source_root.mkdir()
    (source_root / "note.txt").write_text("x", encoding="utf-8")

    with running_public_demo(source_root) as (_, base_url):
        status, _ = get_json(base_url + "/api/status")
        with pytest.raises(HTTPError) as listed:
            get_json(base_url + "/api/policies")
        with pytest.raises(HTTPError) as written:
            post_json(base_url + "/api/policies", {"name": "x", "statements": ["y"]})

    assert status["policy_surface_enabled"] is False
    assert listed.value.code == 404
    assert written.value.code == 404


def test_governance_and_library_reads_refuse_a_network_exposed_server(tmp_path) -> None:
    server = build_server(
        WebAppConfig(
            base_dir=tmp_path,
            execution=ExecutionConfig(allowed_roots=(str(tmp_path),)),
            exposed_to_network=True,
        ),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    codes = {}
    try:
        for path in ("/api/policies", "/api/policy?id=policy_x", "/api/voyage?id=voyage_x"):
            with pytest.raises(HTTPError) as refused:
                get_json(f"http://{host}:{port}{path}")
            codes[path] = refused.value.code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Present but refused over the network, unlike the demo where they are absent.
    assert set(codes.values()) == {403}


def test_governance_can_be_written_from_the_surface_it_is_read_on(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/governance?tab=rules", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    # Writing a rule, binding it and taking the binding back are all on the page
    # that shows the register, not in a separate admin surface.
    for control in ('id="policyForm"', 'id="policyName"', 'id="policyKind"',
                    'id="policyStatements"', 'id="policyDefault"', 'id="policySave"'):
        assert control in html, control
    for symbol in ("savePolicy", "deletePolicy", "bindPolicy", "renderPolicyBinder",
                   "editPolicy", "resetPolicyForm"):
        assert symbol in script, symbol
    # The tab decides the shape, so nobody has to learn a discriminator.
    assert 'form: currentTab === "rules" ? "rule" : "policy"' in script


def test_a_voyage_states_what_governs_it_and_can_run_once_with_another_model(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/processes?tab=workflows", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    assert 'id="libraryGovernance"' in html
    assert 'id="libraryRunOptions"' in html
    assert 'id="libraryOverrideProvider"' in html
    assert 'id="libraryOverrideModel"' in html
    # The raised right is stated in words, not only as a coloured row.
    assert "This voyage may send on your behalf once a delivery adapter exists" in script
    assert "renderVoyageGovernance" in script
    assert "runOverride" in script
    # A per-run choice never rewrites what is stored, and the page says so.
    assert "This applies to this run only" in html
    assert "run_level_override" in script


def test_the_workflows_tab_leads_with_what_the_product_is_for(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/processes?tab=workflows", timeout=5) as response,  # noqa: S310
    ):
        html = response.read().decode()

    # D-037: the room where work is chosen leads with the core sentence, and the
    # library sits under it.
    assert "Documents become data. NemoFold makes knowledge usable." in html
    assert "NemoFold adapts to your use cases — a growing library, not fine-tuning." in html
    assert html.index("Documents become data") < html.index("The work you kept.")
    # The boundary claim did not disappear; it stopped being the headline.
    assert "<h2 id=\"boundaryTitle\">Reasoning may travel. Authority does not.</h2>" not in html
    assert "Reasoning may travel. Authority does not: a worker receives selected" in html
    assert "Reasoning may travel; authority does not." in html


def test_the_registry_offers_every_contract_the_server_supports(tmp_path) -> None:
    from nemofold.job_io import SUPPORTED_WORKFLOWS

    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/processes?tab=registry", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    # The registry claims to hold every contract, so a contract without a card
    # or without an option would be one this claim quietly excludes.
    for workflow in sorted(SUPPORTED_WORKFLOWS):
        assert f">{workflow}</option>" in html, workflow
        assert f"  {workflow}: {{\n    title:" in script.replace("\r\n", "\n"), workflow
    assert "const registryGroups" in script
    assert "NOT YET GROUPED" in script


def test_a_run_that_asked_back_is_rendered_with_answer_fields(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/processes?tab=registry", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    assert 'id="askBack"' in html
    assert 'id="askBackList"' in html
    assert 'id="askBackApply"' in html
    assert "THE RUN ASKED BACK" in html
    assert "It stopped rather than guess." in html
    # The answers become declared parameters of the same contract rather than
    # hidden state, so a draft would carry them like any other setting.
    assert "renderAskBack" in script
    assert "applyAnswers" in script
    assert "parameters.answers" in script


def test_the_connections_page_states_the_web_gate(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        status, _ = get_json(base_url + "/api/status")
        with urlopen(base_url + "/connections", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    assert status["web_search_adapter"] == "tavily"
    assert status["web_search_allowed"] is False
    assert status["web_search_proven"] is False
    assert "web_search_key_present" in status
    assert 'id="connectionWeb"' in html
    # Configurable and proven are different things, and the row says which.
    assert "gate open" in script and "gate closed" in script
    assert "unproven" in script


def test_a_policy_can_be_bound_from_the_library_entry(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.js", timeout=5) as response,  # noqa: S310
    ):
        script = response.read().decode()

    # A rule you can only attach from the register is one you attach less often
    # than you meant to.
    assert "renderEntryBinder" in script
    assert "loadKnownPolicies" in script
    assert "Bind a rule to this voyage" in script


def test_the_surface_states_no_contract_count_that_can_go_stale(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        with urlopen(base_url + "/", timeout=5) as response:  # noqa: S310
            html = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    # A spelled-out count goes quietly false the next time a contract is added,
    # and it already had: the registry said sixteen while offering twenty-six.
    for stale in ("sixteen", "Sixteen", "seventeen", "eighteen", "twenty"):
        assert stale not in html, stale
        assert stale not in script, stale
