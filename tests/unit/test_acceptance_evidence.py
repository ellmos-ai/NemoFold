"""The evidence export must stay faithful to the run it exports."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nemofold.acceptance_evidence import (
    EVIDENCE_ROOT_TOKEN,
    EvidenceExportError,
    _find_bundle_register,
    _relativize,
    collect_gate_test_nodes,
    export_gate_evidence,
    exported_gate_ids,
)
from nemofold.acceptance_gates import artifact_manifest_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_bundle(root: Path) -> Path:
    """Write a minimal bundle whose reports carry the run directory's own path."""
    run_dir = root / "run"
    files = {
        "inputs/source.txt": "Ein Beleg mit Umlauten: Prüfung bestanden.\n",
        "outputs/result.md": f"Ergebnis unter {run_dir}\\outputs\\result.md\n",
        "outputs/handoff.json": json.dumps(
            {"produced_at": f"{run_dir}/outputs/handoff.json"}, ensure_ascii=False
        )
        + "\n",
        "outputs/ledger/positive.json": json.dumps(
            {
                "run_id": "fake_positive_01",
                "status": "executed",
                "artifacts": [{"path": str(run_dir / "outputs" / "result.md")}],
            },
            ensure_ascii=False,
        )
        + "\n",
        "outputs/ledger/negative.json": json.dumps(
            {"run_id": "fake_negative_01", "status": "blocked", "artifacts": []},
            ensure_ascii=False,
        )
        + "\n",
    }
    for relative, content in files.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")

    inputs = [{"path": "inputs/source.txt", "sha256": _sha(run_dir / "inputs/source.txt")}]
    outputs = [{"path": "outputs/result.md", "sha256": _sha(run_dir / "outputs/result.md")}]
    receipt = {
        "run_id": "fake_positive_01",
        "input_sha256": artifact_manifest_sha256(inputs),
        "output_sha256": artifact_manifest_sha256(outputs),
        "input_artifacts": inputs,
        "output_artifacts": outputs,
        "handoff_receipts": [
            {
                "producer": "reader",
                "consumer": "writer",
                "artifact_path": "outputs/handoff.json",
                "artifact_sha256": _sha(run_dir / "outputs/handoff.json"),
                "status": "verified",
                "evidence": "Der Übergabebeleg wurde hashgebunden weitergereicht.",
            }
        ],
        "run_report": {
            "path": "outputs/ledger/positive.json",
            "sha256": _sha(run_dir / "outputs/ledger/positive.json"),
            "status": "executed",
            "verified": True,
        },
        "result_checks": [
            {"name": "beleg_gefunden", "passed": True, "evidence": "Der Beleg wurde zitiert."}
        ],
        "negative_path": {
            "case": "kein_beleg",
            "run_id": "fake_negative_01",
            "status": "blocked",
            "blocked_as_expected": True,
            "evidence": "Ohne Beleg stoppte die Kette vor der Übergabe.",
            "run_report": {
                "path": "outputs/ledger/negative.json",
                "sha256": _sha(run_dir / "outputs/ledger/negative.json"),
            },
        },
    }
    (run_dir / "gate-register.g01.json").write_text(
        json.dumps(
            {
                "gates": [
                    {
                        "gate_id": "G01",
                        "evidence": {"test_nodes": [], "run_receipts": [receipt]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="",
    )
    return run_dir


def test_relativize_replaces_every_spelling_of_the_run_directory() -> None:
    root = Path(r"C:\Users\Someone\run")
    text = (
        r"C:\Users\Someone\run\a.json"
        + " | "
        + r"C:\\Users\\Someone\\run\\b.json"
        + " | C:/Users/Someone/run/c.json"
    )

    result = _relativize(text, root)

    assert "Someone" not in result
    assert result.count(EVIDENCE_ROOT_TOKEN) == 3


def test_export_rewrites_paths_hashes_and_strips_the_run_directory(tmp_path: Path) -> None:
    run_dir = _fake_bundle(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()

    receipt = export_gate_evidence("G01", run_dir, repo)

    exported = repo / "examples" / "acceptance-evidence" / "g01"
    assert (exported / "outputs" / "result.md").is_file()
    for path in exported.rglob("*"):
        if path.is_file():
            assert str(run_dir) not in path.read_text(encoding="utf-8")

    assert receipt["output_artifacts"][0]["path"] == (
        "examples/acceptance-evidence/g01/outputs/result.md"
    )
    assert receipt["output_artifacts"][0]["sha256"] == _sha(exported / "outputs" / "result.md")
    assert receipt["output_sha256"] == artifact_manifest_sha256(receipt["output_artifacts"])
    assert receipt["input_sha256"] == artifact_manifest_sha256(receipt["input_artifacts"])
    assert receipt["run_id"] == "fake_positive_01"
    assert receipt["negative_path"]["blocked_as_expected"] is True


def test_export_refuses_a_bundle_without_a_register(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(EvidenceExportError, match="bundle_register_missing"):
        export_gate_evidence("G01", tmp_path / "empty", tmp_path)


def test_find_bundle_register_accepts_both_naming_conventions(tmp_path: Path) -> None:
    alternate = tmp_path / "evidence"
    alternate.mkdir()
    (alternate / "nf_fin_gates_g08.json").write_text("{}", encoding="utf-8")

    assert _find_bundle_register(tmp_path, "G08").name == "nf_fin_gates_g08.json"


def test_collect_gate_test_nodes_reads_real_test_functions() -> None:
    nodes = collect_gate_test_nodes(REPO_ROOT, "G01")

    assert nodes
    for node in nodes:
        relative, _, selector = node["node"].partition("::")
        assert selector.startswith("test_")
        assert (REPO_ROOT / relative).is_file()
        assert node["file_sha256"] == _sha(REPO_ROOT / relative)

    with pytest.raises(EvidenceExportError, match="no_test_nodes_found"):
        collect_gate_test_nodes(REPO_ROOT, "G99")


def test_exported_gate_ids_lists_the_committed_directories() -> None:
    assert "G01" in exported_gate_ids(REPO_ROOT)
    assert exported_gate_ids(REPO_ROOT / "does-not-exist") == ()
