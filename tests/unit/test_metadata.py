"""Contract tests for repository metadata, discoverability, bilingual parity, and legal notices."""

from pathlib import Path
import re
import tomllib
import nemofold

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_version_consistency():
    """Verify version 0.2.0 consistency across all release and metadata files."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    pyproject_version = pyproject_data["project"]["version"]
    assert pyproject_version == "0.2.0", f"pyproject.toml version {pyproject_version} != 0.2.0"
    assert nemofold.__version__ == "0.2.0", f"nemofold.__version__ {nemofold.__version__} != 0.2.0"

    changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.0 - 2026-09-18" in changelog_text, "CHANGELOG.md missing 0.2.0 release header"

    llms_text = (REPO_ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "Version: 0.2.0" in llms_text, "llms.txt missing Version: 0.2.0"


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
        "Marketing Log",
        "Parent Organization",
        "Umbrella Ecosystem",
        "LLM Ready",
    ]

    for key in expected_keys:
        assert key in urls, f"Missing project URL key: {key}"
        val = urls[key]
        assert isinstance(val, str) and val.startswith("https://"), f"URL for {key} must start with https://, got {val}"


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
    """Verify that both README.md and README_de.md have all 18 numbered sections with reciprocal anchors."""
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


def test_marketing_log_structure():
    """Verify MARKETING-LOG.txt includes all 9 required canonical sections."""
    marketing_text = (REPO_ROOT / "MARKETING-LOG.txt").read_text(encoding="utf-8")
    assert "1. EXECUTIVE SUMMARY & VALUE PROPOSITION" in marketing_text
    assert "2. TARGET AUDIENCES & PERSONAS" in marketing_text
    assert "3. SEARCH PHRASES & DISCOVERABILITY KEYWORDS" in marketing_text
    assert "4. COMPARATIVE MATRIX VS. ALTERNATIVES" in marketing_text
    assert "5. SIBLING TOOLS & UMBRELLA ECOSYSTEM MATRIX" in marketing_text
    assert "6. GOVERNANCE & RUNTIME INVARIANTS" in marketing_text
    assert "7. VISUAL ARCHITECTURE & DUAL MERMAID DIAGRAMS" in marketing_text
    assert "8. THIRD-PARTY LICENSES & TRANSPARENCY SUMMARY" in marketing_text
    assert "9. RELEASE & VERIFICATION AUDIT" in marketing_text
