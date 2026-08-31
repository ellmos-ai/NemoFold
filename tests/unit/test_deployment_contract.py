from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_container_runs_only_the_bounded_public_demo() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY . ." not in dockerfile
    assert "COPY examples/synthetic-home ./examples/synthetic-home" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/api/status" in dockerfile
    assert "python -m nemofold serve-demo" in dockerfile
    assert "--demo-root /app/examples/synthetic-home" in dockerfile
    assert "--expose-network" in dockerfile
    assert "--max-parallel-jobs" in dockerfile
    assert "--approve-actions" not in dockerfile
    assert "--allow-external-models" not in dockerfile


def test_deployment_guide_keeps_external_evidence_open() -> None:
    guide = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert '"mode": "public-synthetic-demo"' in guide
    assert '"cloud_proof": false' in guide
    assert "does not claim a hosted URL" in guide
    assert "explicit user gate" in guide
