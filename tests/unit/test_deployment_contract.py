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


def test_both_module_paths_start_the_command_line() -> None:
    """`python -m nemofold.cli` used to exit zero and do nothing at all.

    A silent success is the one outcome this product argues against everywhere
    else, and it is the likelier of the two spellings for anyone who has just
    read an import path.
    """
    import subprocess
    import sys

    for module in ("nemofold", "nemofold.cli"):
        finished = subprocess.run(
            [sys.executable, "-m", module, "providers"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert finished.returncode == 0, f"{module}: {finished.stderr}"
        assert '"providers"' in finished.stdout, f"{module} produced no output"


def test_a_direct_reference_stays_buildable() -> None:
    """A git-pinned extra silently breaks `python -m build` without this flag.

    The failure appears only when a distribution is built, which is the one step
    most likely to happen when there is no time left to investigate it.
    """
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads(
        Path(__file__).resolve().parents[2].joinpath("pyproject.toml").read_text(encoding="utf-8")
    )
    extras = pyproject["project"].get("optional-dependencies", {})
    direct = [
        requirement
        for group in extras.values()
        for requirement in group
        if "@ git+" in requirement or "@ https://" in requirement
    ]

    if direct:
        assert pyproject["tool"]["hatch"]["metadata"]["allow-direct-references"] is True, (
            f"direct references need the flag: {direct}"
        )
        # Every direct reference is pinned: a moving branch would make two
        # installs of the same version disagree about what they installed.
        for requirement in direct:
            revision = requirement.rsplit("@", 1)[-1]
            assert len(revision) == 40 and all(
                character in "0123456789abcdef" for character in revision
            ), f"not pinned to a commit: {requirement}"
