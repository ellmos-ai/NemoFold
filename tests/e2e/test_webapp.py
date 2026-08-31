from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from nemofold.application import ExecutionConfig
from nemofold.cli import build_parser, main
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

    assert 'href="/document-center"' in html
    assert 'href="/analysis"' in html
    assert 'href="/routines"' in html
    assert 'href="/artifacts"' in html
    assert 'href="/connections"' in html
    assert "Know what your documents prove." in html
    assert "EVIDENCE CHAIN" in html
    assert "ORIGIN" in html
    assert "ACTION" in html
    assert "PRODUCT MAP" in html
    assert "Document Center" in html
    assert "Artifact Studio" in html
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
    assert len(status["workflows"]) == 12
    assert preview["ok"] is True
    assert preview["report"]["workflow"] == "evidence_analyst"
    assert preview["report"]["status"] == "planned"
    assert preview["report"]["metadata"]["cloud_proof"] is False
    assert preview["report"]["coverage"]["read_sources"] == 1


@pytest.mark.parametrize(
    ("route", "page"),
    [
        ("/document-center", "document"),
        ("/analysis", "analysis"),
        ("/routines", "routines"),
        ("/artifacts", "artifacts"),
        ("/connections", "connections"),
        ("/governance", "governance"),
    ],
)
def test_web_console_serves_each_product_area_as_a_real_route(tmp_path, route, page) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + route, timeout=5) as response,  # noqa: S310
    ):
        html = response.read().decode()

    assert response.status == 200
    assert f'<body data-page="{page}">' in html
    assert 'data-page-link="document"' in html
    assert 'data-page-link="governance"' in html
    assert (
        'data-page-section="document analysis routines artifacts connections governance"' in html
    )


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
    assert 'body[data-page="analysis"]' in stylesheet
    assert ".route-workflows" in stylesheet
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


def test_storage_policy_moved_from_document_center_to_the_bridge(tmp_path) -> None:
    with (
        running_server(tmp_path) as base_url,
        urlopen(base_url + "/assets/app.js", timeout=5) as response,  # noqa: S310
    ):
        script = response.read().decode()

    document_line = next(line for line in script.splitlines() if "document: {title:" in line)
    governance_line = next(line for line in script.splitlines() if "governance: {title:" in line)

    assert "storage_policy" not in document_line
    assert "storage_policy" in governance_line


def test_each_area_serves_its_own_home_module_and_task_cards(tmp_path) -> None:
    with running_server(tmp_path) as base_url:
        pages = {}
        for route in ("/document-center", "/routines", "/analysis"):
            with urlopen(base_url + route, timeout=5) as response:  # noqa: S310
                pages[route] = response.read().decode()
        with urlopen(base_url + "/assets/app.js", timeout=5) as response:  # noqa: S310
            script = response.read().decode()

    document_page = pages["/document-center"]
    assert 'id="homeGlance"' in document_page
    assert 'data-folder-target="homeGlanceRoot"' in document_page
    assert 'id="echoCheck"' in document_page
    assert 'data-page-section="document"' in document_page
    assert 'id="taskCards"' in document_page
    assert 'data-page-section="document analysis routines governance"' in document_page
    assert "workflowCards" in script
    assert "renderTaskCards" in script
    assert "loadHomeGlance" in script
    assert "loadEcho" in script
    assert "prepareWorkflow" in script


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
