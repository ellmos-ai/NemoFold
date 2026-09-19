"""Contract tests for repository metadata, discoverability, bilingual parity, and legal notices."""

import re
import tomllib
from pathlib import Path

import nemofold

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_version_consistency():
    """Verify version 0.2.1 consistency across all release and metadata files."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    pyproject_version = pyproject_data["project"]["version"]
    assert pyproject_version == "0.2.1", f"pyproject.toml version {pyproject_version} != 0.2.1"
    assert nemofold.__version__ == "0.2.1", f"nemofold.__version__ {nemofold.__version__} != 0.2.1"

    changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.1 - 2026-09-19" in changelog_text, "CHANGELOG.md missing 0.2.1 release header"

    llms_text = (REPO_ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "Version: 0.2.1" in llms_text, "llms.txt missing Version: 0.2.1"


def test_pyproject_project_urls():
    """Verify all 10 canonical project URLs are present, HTTPS, and non-empty."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    urls = data.get("project", {}).get("urls", {})
    expected_keys = [
        "Documentation",
        "Repository",
        "Issues",
        "Changelog",
        "Security",
        "Third-Party Licenses",
        "Parent Organization",
        "Umbrella Ecosystem",
        "LLM Ready",
    ]

    for key in expected_keys:
        assert key in urls, f"Missing project URL key: {key}"
        val = urls[key]
        assert isinstance(val, str) and val.startswith("https://"), (
            f"URL for {key} must start with https://, got {val}"
        )


def test_pyproject_classifiers():
    """Verify PEP 621 classifiers are appropriately specified."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    classifiers = data.get("project", {}).get("classifiers", [])
    assert len(classifiers) >= 6, "Expected at least 6 PEP 621 classifiers"
    classifier_text = "\n".join(classifiers)

    assert "Development Status :: 4 - Beta" in classifier_text
    assert "License :: OSI Approved :: MIT License" in classifier_text
    assert "Programming Language :: Python :: 3" in classifier_text
    assert "Topic :: Office/Business" in classifier_text
    assert "Topic :: Scientific/Engineering :: Information Analysis" in classifier_text


def test_bilingual_readme_structural_parity():
    """Verify README.md and README_de.md share all 18 numbered sections with
    reciprocal anchors."""
    readme_en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readme_de = (REPO_ROOT / "README_de.md").read_text(encoding="utf-8")

    for section_num in range(1, 19):
        en_pattern = rf"## {section_num}\. [A-Z]"
        de_pattern = rf"## {section_num}\. [A-ZÄÖÜ]"
        assert re.search(en_pattern, readme_en), f"README.md missing section {section_num}"
        assert re.search(de_pattern, readme_de), f"README_de.md missing section {section_num}"

    key_anchors = [
        "1-overview--core-mission",
        "1-uebersicht--kernmission",
        "2-visual-architecture--dual-diagrams",
        "2-visuelle-architektur--duale-diagramme",
        "3-target-personas--discoverability",
        "3-zielgruppen--auffindbarkeit",
        "4-comparative-matrix-vs-alternatives",
        "4-vergleichsmatrix-gegenueber-alternativen",
        "5-governance--runtime-invariants",
        "5-governance--laufzeit-invarianten",
        "17-sibling-ecosystem--integration",
        "17-geschwister-oekosystem--integration",
        "18-transparency-licenses--security-policy",
        "18-transparenz-lizenzen--sicherheitsrichtlinie",
    ]

    for anchor in key_anchors:
        assert f'id="{anchor}"' in readme_en, f"README.md missing reciprocal anchor: {anchor}"
        assert f'id="{anchor}"' in readme_de, f"README_de.md missing reciprocal anchor: {anchor}"


def test_german_legal_notice():
    """Verify that README_de.md includes the statutory German disclaimer (§ 521 BGB)."""
    readme_de = (REPO_ROOT / "README_de.md").read_text(encoding="utf-8")
    assert "§ 521 BGB" in readme_de
    assert "Gefälligkeitsrecht" in readme_de
    assert "Vorsatz und grobe Fahrlässigkeit" in readme_de


def test_third_party_licenses_audit():
    """Verify THIRD_PARTY_LICENSES.md includes invariant compliance and zero-copyleft guarantee."""
    lic_text = (REPO_ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    assert "Zero-Copyleft Guarantee" in lic_text
    assert "INV-LOCAL-01" in lic_text
    assert "INV-SLA-10" in lic_text
    assert "MIT" in lic_text
    assert "Apache-2.0" in lic_text


def test_ci_workflow_guardrails():
    """Verify ci.yml enforces concurrency cancellation and a 15-minute job timeout."""
    ci_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), "Missing .github/workflows/ci.yml"
    ci_text = ci_path.read_text(encoding="utf-8")

    assert "cancel-in-progress: true" in ci_text
    assert "timeout-minutes: 15" in ci_text
    assert "permissions:\n  contents: read" in ci_text


def test_lifecycle_workflows_present():
    """Verify canonical stale.yml and welcome.yml workflows exist with timeouts."""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    stale_file = workflows_dir / "stale.yml"
    welcome_file = workflows_dir / "welcome.yml"

    assert stale_file.is_file(), "Missing .github/workflows/stale.yml"
    assert welcome_file.is_file(), "Missing .github/workflows/welcome.yml"

    stale_text = stale_file.read_text(encoding="utf-8")
    assert "actions/stale@v9" in stale_text
    assert "timeout-minutes: 10" in stale_text

    welcome_text = welcome_file.read_text(encoding="utf-8")
    assert "actions/first-interaction@v3" in welcome_text
    assert "timeout-minutes: 5" in welcome_text


def test_gitignore_multihost_and_locks():
    """Verify .gitignore guards multi-host sync conflicts and locks while keeping uv.lock."""
    gi_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*conflicted copy*" in gi_text
    assert "*-WORKSTATION*" in gi_text
    assert "LOCK" in gi_text
    assert "LOCK.*" in gi_text
    assert "!uv.lock" in gi_text


def test_pyproject_pytest_hardening():
    """Verify pyproject.toml defines pytest minversion and norecursedirs."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    pytest_opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert pytest_opts.get("minversion") == "7.0"
    norecursedirs = pytest_opts.get("norecursedirs", [])
    for expected_dir in [".git", ".pytest_cache", "__pycache__", "build", "dist", ".venv"]:
        assert expected_dir in norecursedirs, f"Missing {expected_dir} in pytest norecursedirs"
