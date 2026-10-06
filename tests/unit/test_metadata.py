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
        "Notice",
        "Third-Party Licenses",
        "Third-Party Licenses (Text)",
        "Marketing Log",
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

    for num in range(1, 19):
        sec_anchor = f'id="sec-{num:02d}"'
        assert sec_anchor in readme_en, f"README.md missing {sec_anchor}"
        assert sec_anchor in readme_de, f"README_de.md missing {sec_anchor}"


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
    assert "Level 1 SBOM" in lic_text
    assert "2026-09-26" in lic_text


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
    assert ".pytest_temp/" in gi_text


def test_pyproject_pytest_hardening():
    """Verify pyproject.toml defines pytest minversion and norecursedirs."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    pytest_opts = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert pytest_opts.get("minversion") == "7.0"
    norecursedirs = pytest_opts.get("norecursedirs", [])
    expected_dirs = [
        ".git",
        ".pytest_cache",
        ".pytest_temp",
        "__pycache__",
        "build",
        "dist",
        ".venv",
    ]
    for expected_dir in expected_dirs:
        assert expected_dir in norecursedirs, f"Missing {expected_dir} in pytest norecursedirs"


def test_canonical_root_notice():
    """Verify canonical root NOTICE attribution file exists with valid copyright and license."""
    notice_path = REPO_ROOT / "NOTICE"
    assert notice_path.is_file(), "Missing canonical root NOTICE file"
    notice_text = notice_path.read_text(encoding="utf-8")
    assert "NemoFold" in notice_text
    assert "Lukas Geiger" in notice_text
    assert "ellmos-ai" in notice_text
    assert "open-bricks" in notice_text
    assert "MIT License" in notice_text


def test_pyproject_keywords_and_license_files():
    """Verify pyproject.toml contains 20 saturated keywords and license-files declaration."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project_data = data.get("project", {})
    keywords = project_data.get("keywords", [])
    assert len(keywords) == 20, f"Expected exactly 20 keywords, got {len(keywords)}: {keywords}"
    expected_sample = [
        "ai-agents",
        "evidence-first",
        "reversible-actions",
        "zero-egress",
        "local-first",
    ]
    for expected_kw in expected_sample:
        assert expected_kw in keywords, f"Missing keyword: {expected_kw}"

    license_files = project_data.get("license-files", [])
    assert "LICENSE" in license_files
    assert "NOTICE" in license_files
    assert "THIRD_PARTY_LICENSES.md" in license_files
    assert "THIRD_PARTY_LICENSES.txt" in license_files


def test_marketing_log_and_audit():
    """Verify local MARKETING-LOG.txt is present and documents Pfad B audit."""
    marketing_path = REPO_ROOT / "MARKETING-LOG.txt"
    assert marketing_path.is_file(), "Missing local MARKETING-LOG.txt"
    marketing_text = marketing_path.read_text(encoding="utf-8")
    assert "ellmos-ai/NemoFold" in marketing_text
    assert "2026-09-26" in marketing_text
    assert "INV-LOCAL-01" in marketing_text
    assert "INV-SLA-10" in marketing_text
    assert "[PERSONA-01]" in marketing_text


def test_changelog_unreleased_entry():
    """Verify CHANGELOG.md carries an [Unreleased] section for Pfad B 2026-09-26."""
    changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog_text
    assert "2026-09-26" in changelog_text
    assert "NOTICE" in changelog_text
    assert "Level 1 SBOM" in changelog_text


def test_auto_assign_and_label_sync_workflows():
    """Verify canonical auto-assign.yml, label-sync.yml, and labels.yml exist with guardrails."""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    auto_assign_file = workflows_dir / "auto-assign.yml"
    label_sync_file = workflows_dir / "label-sync.yml"
    labels_file = REPO_ROOT / ".github" / "labels.yml"

    assert auto_assign_file.is_file(), "Missing .github/workflows/auto-assign.yml"
    assert label_sync_file.is_file(), "Missing .github/workflows/label-sync.yml"
    assert labels_file.is_file(), "Missing .github/labels.yml"

    aa_text = auto_assign_file.read_text(encoding="utf-8")
    assert "actions/github-script@v7" in aa_text
    assert "timeout-minutes: 5" in aa_text
    assert "cancel-in-progress: true" in aa_text
    assert "pull-requests: write" in aa_text

    ls_text = label_sync_file.read_text(encoding="utf-8")
    assert "EndBug/label-sync@v2" in ls_text
    assert "timeout-minutes: 5" in ls_text
    assert "cancel-in-progress: true" in ls_text
    assert "config-file: .github/labels.yml" in ls_text
    assert "issues: write" in ls_text

    labels_text = labels_file.read_text(encoding="utf-8")
    for standard_label in [
        "bug",
        "enhancement",
        "good first issue",
        "help wanted",
        "documentation",
        "duplicate",
        "wontfix",
        "priority: high",
        "priority: low",
        "needs-triage",
        "stale",
    ]:
        has_label = (
            f"name: {standard_label}" in labels_text or f"name: '{standard_label}'" in labels_text
        )
        assert has_label, f"Missing label {standard_label} in labels.yml"


def test_third_party_licenses_plain_text():
    """Verify plain-text companion THIRD_PARTY_LICENSES.txt exists with Level 1 SBOM invariants."""
    txt_file = REPO_ROOT / "THIRD_PARTY_LICENSES.txt"
    assert txt_file.is_file(), "Missing THIRD_PARTY_LICENSES.txt"
    txt_content = txt_file.read_text(encoding="utf-8")

    assert "LEVEL 1 SBOM" in txt_content or "Level 1 SBOM" in txt_content
    assert "INV-LOCAL-01" in txt_content
    assert "INV-SLA-10" in txt_content
    assert "RunAsInvoker" in txt_content
    assert "Zero-Copyleft" in txt_content
    assert "2026-09-28" in txt_content

    # Verify cross-reference in NOTICE
    notice_text = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "THIRD_PARTY_LICENSES.txt" in notice_text


def test_gitignore_multihost_and_lock_defense():
    """Verify .gitignore contains multi-host tokens, canonical locks, and OS/editor patterns."""
    gi_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*-IDEAPAD*" in gi_text
    assert "*_WORKSTATION*" in gi_text
    assert "*_WORKSTATION-LG*" in gi_text
    assert "*-WORKSTATION.*" in gi_text
    assert "*-WORKSTATION-LG.*" in gi_text
    assert "LOCK*.txt" in gi_text
    assert ".automation-lock" in gi_text
    assert "Desktop.ini" in gi_text
    assert ".pytest_tmp*/" in gi_text


def test_pyproject_pytest_norecursedirs_hardened():
    """Verify pytest norecursedirs includes .pytest_tmp* and .tox."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    ini_options = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    norecursedirs = ini_options.get("norecursedirs", [])
    assert ".pytest_tmp*" in norecursedirs
    assert ".tox" in norecursedirs


def test_bilingual_contributing_parity_and_invariants():
    """Verify CONTRIBUTING.md contains bilingual sections, 10 invariants, RunAsInvoker,
    and Plan D."""
    contrib_path = REPO_ROOT / "CONTRIBUTING.md"
    assert contrib_path.is_file(), "Missing CONTRIBUTING.md"
    content = contrib_path.read_text(encoding="utf-8")

    assert "## English" in content
    assert "## Deutsch" in content
    assert "RunAsInvoker" in content
    assert "T-20260920-167562623" in content
    assert "0.2.1" in content
    assert "Plan D" in content
    assert "MIT License" in content

    for inv in [
        "INV-LOCAL-01",
        "INV-EVID-02",
        "INV-ACTION-03",
        "INV-GATE-04",
        "INV-ISOL-05",
        "INV-PROV-06",
        "INV-POLICY-07",
        "INV-RUNAS-08",
        "INV-DET-09",
        "INV-SLA-10",
    ]:
        assert inv in content, f"Missing invariant {inv} in CONTRIBUTING.md"


def test_gitignore_extended_lock_defense():
    """Verify .gitignore includes extended lock patterns and host tokens."""
    gi_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "LOCK.dev.*" in gi_text
    assert "LOCK.antigravity.*" in gi_text
    assert "LOCK.bugsearch.*" in gi_text
    assert "TASKPLAN_*.md" in gi_text
    assert "*-IDEAPAD-GEI*" in gi_text


def test_level1_sbom_currency_20261001():
    """Verify THIRD_PARTY_LICENSES.md and THIRD_PARTY_LICENSES.txt document the 2026-10-01 audit."""
    md_text = (REPO_ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    txt_text = (REPO_ROOT / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")

    assert "2026-10-01" in md_text
    assert "2026-10-01" in txt_text
    assert "RunAsInvoker" in md_text
    assert "RunAsInvoker" in txt_text

    for inv in ["INV-LOCAL-01", "INV-RUNAS-08", "INV-SLA-10"]:
        assert inv in md_text
        assert inv in txt_text


def test_pfad_b_discoverability_audit_currency_20261003():
    """Verify Level 1 SBOM, badges, llms.txt, and MARKETING-LOG.txt document 2026-10-03 audit."""
    md_text = (REPO_ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    txt_text = (REPO_ROOT / "THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    readme_en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    readme_de = (REPO_ROOT / "README_de.md").read_text(encoding="utf-8")
    llms_text = (REPO_ROOT / "llms.txt").read_text(encoding="utf-8")
    marketing_text = (REPO_ROOT / "MARKETING-LOG.txt").read_text(encoding="utf-8")
    changelog_text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "2026-10-03" in md_text, "THIRD_PARTY_LICENSES.md missing 2026-10-03 audit date"
    assert "2026-10-03" in txt_text, "THIRD_PARTY_LICENSES.txt missing 2026-10-03 audit date"
    assert "Verified-2026--10--03" in readme_en
    assert "Last--Checked-2026--10--03" in readme_en
    assert "Verified-2026--10--03" in readme_de
    assert "Last--Checked-2026--10--03" in readme_de
    assert "Last-checked: 2026-10-03" in llms_text
    assert "9. IMPLEMENTED PFAD B DISCOVERABILITY & RE-AUDIT (2026-10-03)" in marketing_text
    assert "Pfad B Discoverability, Level 1 SBOM Re-Audit & Marketing Registry (2026-10-03)" in (
        changelog_text
    )


def test_event_workflows_group_concurrency_per_issue_or_pull_request():
    """A ref-wide group lets one newcomer's run cancel another's on the default branch."""
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    auto_assign = (workflows_dir / "auto-assign.yml").read_text(encoding="utf-8")
    welcome = (workflows_dir / "welcome.yml").read_text(encoding="utf-8")

    assert "group: ${{ github.workflow }}-${{ github.event.pull_request.number }}" in auto_assign
    assert "github.event.issue.number || github.event.pull_request.number" in welcome
    for text in (auto_assign, welcome):
        assert "group: ${{ github.workflow }}-${{ github.ref }}" not in text
    # An organization cannot be an assignee; the author is assigned instead.
    assert "repoData.owner.type === 'Organization'" in auto_assign
