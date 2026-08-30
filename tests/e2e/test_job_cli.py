from __future__ import annotations

import json
from pathlib import Path

import nemofold.cli as cli_module
from nemofold.cli import main


def write_bundle_job(tmp_path: Path) -> Path:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "a.txt").write_text("Alpha evidence.", encoding="utf-8")
    (documents / "b.md").write_text("Beta evidence.", encoding="utf-8")
    job = {
        "schema": "nemofold.job.v1",
        "workflow": "bundle_export",
        "input_roots": ["documents"],
        "output_dir": "output",
        "questions": [],
        "privacy_mode": "local_only",
        "action_mode": "dry_run",
        "parameters": {"bundle_name": "case_bundle"},
    }
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    return path


def test_preview_run_and_verify_share_the_public_job_contract(tmp_path, capsys) -> None:
    job = write_bundle_job(tmp_path)
    allow_root = str(tmp_path)

    preview_exit = main(
        ["preview", "--job", str(job), "--allow-root", allow_root, "--run-id", "preview_1"]
    )
    preview = json.loads(capsys.readouterr().out)

    assert preview_exit == 0
    assert preview["status"] == "planned"
    assert preview["workflow"] == "bundle_export"
    assert preview["source_count"] == 2
    assert not (tmp_path / "output" / "bundles" / "case_bundle.zip").exists()

    run_exit = main(["run", "--job", str(job), "--allow-root", allow_root, "--run-id", "run_1"])
    run = json.loads(capsys.readouterr().out)
    report_path = Path(run["report_path"])

    assert run_exit == 0
    assert run["status"] == "executed"
    assert (tmp_path / "output" / "bundles" / "case_bundle.zip").is_file()

    verify_exit = main(["verify", str(report_path)])
    verification = json.loads(capsys.readouterr().out)
    assert verify_exit == 0
    assert verification["valid"] is True
    assert verification["checked_artifacts"] == 4


def test_run_refuses_external_model_when_no_live_adapter_is_configured(tmp_path, capsys) -> None:
    job = write_bundle_job(tmp_path)
    payload = json.loads(job.read_text(encoding="utf-8"))
    payload.update(
        {
            "workflow": "evidence_analyst",
            "questions": ["What is supported?"],
            "privacy_mode": "allow_once",
            "model_id": "nvidia/nemotron",
            "model_budget_usd": 1.0,
        }
    )
    payload["parameters"] = {}
    job.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "run",
            "--job",
            str(job),
            "--allow-root",
            str(tmp_path),
            "--allow-external-models",
            "--max-external-cost-usd",
            "1.0",
            "--run-id",
            "external_blocked",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["errors"] == ["external_runtime_unavailable"]
    assert result["cloud_proof"] is False


def test_verify_detects_a_tampered_job_artifact(tmp_path, capsys) -> None:
    job = write_bundle_job(tmp_path)
    main(["run", "--job", str(job), "--allow-root", str(tmp_path), "--run-id", "run_2"])
    capsys.readouterr()
    artifact = tmp_path / "output" / "bundles" / "case_bundle.txt"
    artifact.write_text("tampered", encoding="utf-8")

    exit_code = main(["verify", str(tmp_path / "output" / "ledger" / "run_2.json")])
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert result["valid"] is False
    assert "artifact_hash_mismatch:case_bundle.txt" in result["errors"]


def test_unsafe_run_id_is_rejected_before_any_artifact_path_is_built(tmp_path, capsys) -> None:
    job = write_bundle_job(tmp_path)

    exit_code = main(
        [
            "preview",
            "--job",
            str(job),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "../escape",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert "run_id must contain" in result["errors"][0]
    assert not any(tmp_path.glob("escape*"))


def test_resume_uses_stored_job_identity_and_does_not_repeat_completed_actions(
    tmp_path, capsys
) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    source = documents / "case.txt"
    source.write_text("case", encoding="utf-8")
    job = tmp_path / "action-job.json"
    job.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "storage_policy",
                "input_roots": ["documents"],
                "target_roots": ["archive"],
                "output_dir": "output",
                "questions": [],
                "privacy_mode": "local_only",
                "action_mode": "apply",
                "parameters": {"allowed_extensions": [".txt"]},
            }
        ),
        encoding="utf-8",
    )

    first_exit = main(
        [
            "run",
            "--job",
            str(job),
            "--allow-root",
            str(tmp_path),
            "--approve-actions",
            "--run-id",
            "recover_1",
        ]
    )
    first = json.loads(capsys.readouterr().out)
    assert first_exit == 2
    assert first["status"] == "failed"
    assert (tmp_path / "output" / "jobs" / "recover_1.json").is_file()

    archive = tmp_path / "archive"
    archive.mkdir()
    resume_args = [
        "resume",
        "recover_1",
        "--output",
        str(tmp_path / "output"),
        "--allow-root",
        str(tmp_path),
        "--approve-actions",
    ]
    resumed_exit = main(resume_args)
    resumed = json.loads(capsys.readouterr().out)
    repeated_exit = main(resume_args)
    repeated = json.loads(capsys.readouterr().out)

    assert resumed_exit == 0
    assert resumed["status"] == "executed"
    assert (archive / "case.txt").is_file()
    assert not source.exists()
    assert repeated_exit == 0
    assert repeated["status"] == "executed"
    assert (archive / "case.txt").read_text(encoding="utf-8") == "case"

    undo_args = [
        "undo",
        "recover_1",
        "--output",
        str(tmp_path / "output"),
        "--allow-root",
        str(tmp_path),
        "--approve-actions",
    ]
    undo_exit = main(undo_args)
    undo = json.loads(capsys.readouterr().out)
    repeated_undo_exit = main(undo_args)
    repeated_undo = json.loads(capsys.readouterr().out)

    assert undo_exit == 0
    assert undo["status"] == "executed"
    assert source.is_file()
    assert not (archive / "case.txt").exists()
    assert repeated_undo_exit == 0
    assert repeated_undo["status"] == "executed"
    verify_exit = main(["verify", undo["report_path"]])
    capsys.readouterr()
    assert verify_exit == 0


def test_preview_of_apply_job_builds_plan_without_requiring_action_approval(
    tmp_path, capsys
) -> None:
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    archive.mkdir()
    source = inbox / "case.txt"
    source.write_text("case", encoding="utf-8")
    job = tmp_path / "preview-action.json"
    job.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "storage_policy",
                "input_roots": ["inbox"],
                "target_roots": ["archive"],
                "output_dir": "output",
                "questions": [],
                "privacy_mode": "local_only",
                "action_mode": "apply",
                "parameters": {"allowed_extensions": [".txt"]},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "preview",
            "--job",
            str(job),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "preview_apply",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "planned"
    assert source.is_file()
    assert not (archive / "case.txt").exists()
    assert (tmp_path / "output" / "preview_apply.action-plan.json").is_file()

    run_args = [
        "run",
        "--job",
        str(job),
        "--allow-root",
        str(tmp_path),
        "--approve-actions",
        "--run-id",
        "preview_apply",
    ]
    run_exit = main(run_args)
    run_result = json.loads(capsys.readouterr().out)
    repeated_exit = main(run_args)
    repeated_result = json.loads(capsys.readouterr().out)

    assert run_exit == repeated_exit == 0
    assert run_result["status"] == repeated_result["status"] == "executed"
    assert not source.exists()
    assert (archive / "case.txt").is_file()


def test_apply_rejects_a_tampered_preview_action_plan(tmp_path, capsys) -> None:
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    outside = tmp_path / "outside"
    inbox.mkdir()
    archive.mkdir()
    outside.mkdir()
    source = inbox / "case.txt"
    source.write_text("case", encoding="utf-8")
    job = tmp_path / "tampered-preview-action.json"
    job.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "storage_policy",
                "input_roots": ["inbox"],
                "target_roots": ["archive"],
                "output_dir": "output",
                "questions": [],
                "privacy_mode": "local_only",
                "action_mode": "apply",
                "parameters": {"allowed_extensions": [".txt"]},
            }
        ),
        encoding="utf-8",
    )
    common = ["--job", str(job), "--allow-root", str(tmp_path), "--run-id", "tampered"]

    assert main(["preview", *common]) == 0
    capsys.readouterr()
    plan_path = tmp_path / "output" / "tampered.action-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["plans"][0]["target"] = str(outside / "case.txt")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    assert main(["run", *common, "--approve-actions"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert source.is_file()
    assert not (outside / "case.txt").exists()


def test_external_preview_is_pseudonymized_and_never_marks_a_transfer(tmp_path, capsys) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "private.txt").write_text(
        "Contact analyst@example.org about Lukas Example.", encoding="utf-8"
    )
    job = tmp_path / "preview-external.json"
    job.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "evidence_analyst",
                "input_roots": ["documents"],
                "output_dir": "output",
                "questions": ["What did Lukas Example tell analyst@example.org?"],
                "privacy_mode": "preview",
                "action_mode": "dry_run",
                "model_id": "nvidia/nemotron",
                "model_budget_usd": 1.0,
                "parameters": {"pseudonymize_terms": ["Lukas Example"]},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "preview",
            "--job",
            str(job),
            "--allow-root",
            str(tmp_path),
            "--run-id",
            "external_preview",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    preview_path = tmp_path / "output" / "external_preview.external-preview.json"
    encoded = preview_path.read_text(encoding="utf-8")
    report = json.loads(
        (tmp_path / "output" / "ledger" / "external_preview.json").read_text(encoding="utf-8")
    )

    assert exit_code == 0
    assert result["status"] == "planned"
    assert "analyst@example.org" not in encoded
    assert "Lukas Example" not in encoded
    assert str(tmp_path) not in encoded
    assert json.loads(encoded)["transfer_performed"] is False
    assert report["metadata"]["execution_gate_allowed"] is False
    assert "external_models_disabled" in report["metadata"]["execution_gate_reasons"]


def test_package_command_requires_positive_gate_and_never_claims_transfer(tmp_path, capsys) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "case.txt").write_text(
        "Coverage begins in April for analyst@example.org.", encoding="utf-8"
    )
    job = tmp_path / "external-job.json"
    job.write_text(
        json.dumps(
            {
                "schema": "nemofold.job.v1",
                "workflow": "evidence_analyst",
                "input_roots": ["documents"],
                "output_dir": "output",
                "questions": ["When does coverage begin?"],
                "privacy_mode": "allow_once",
                "action_mode": "dry_run",
                "model_id": "nvidia/nemotron",
                "model_budget_usd": 1.0,
            }
        ),
        encoding="utf-8",
    )
    base_args = [
        "package",
        "--job",
        str(job),
        "--allow-root",
        str(tmp_path),
        "--run-id",
        "package_1",
    ]

    blocked_exit = main(base_args)
    blocked = json.loads(capsys.readouterr().out)
    packaged_exit = main(base_args + ["--allow-external-models", "--max-external-cost-usd", "1.0"])
    packaged = json.loads(capsys.readouterr().out)

    assert blocked_exit == 2
    assert "external_models_disabled" in blocked["errors"][0]
    assert packaged_exit == 0
    assert packaged["status"] == "packaged"
    assert packaged["transfer_performed"] is False
    assert packaged["cloud_proof"] is False
    assert (tmp_path / "output" / "nemoclaw-packages" / "package_1").is_dir()
    gate = json.loads(
        (tmp_path / "output" / "gates" / "package_1.json").read_text(encoding="utf-8")
    )
    assert gate["decision"]["allowed"] is True
    assert gate["transfer_performed"] is False


def test_token_factory_cli_does_not_hide_a_transfer_after_validation_failure(
    tmp_path, capsys, monkeypatch
) -> None:
    package = tmp_path / "package"
    package.mkdir()

    def transferred_then_failed(path, config, *, approve_live_transfer):
        assert approve_live_transfer is True
        result_path = Path(path) / "result.json"
        result_path.write_text(json.dumps({"transfer_performed": True}), encoding="utf-8")
        raise RuntimeError("post-transfer validation failed")

    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(cli_module, "run_token_factory_package", transferred_then_failed)

    exit_code = main(
        [
            "token-factory-run",
            str(package),
            "--approve-live-transfer",
            "--input-price-usd-per-million",
            "0.1",
            "--output-price-usd-per-million",
            "0.2",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["transfer_performed"] is True
