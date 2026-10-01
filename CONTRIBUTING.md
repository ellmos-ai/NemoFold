# Contributing to NemoFold / Mitwirken an NemoFold

Welcome! We welcome contributions to `NemoFold` (Private, evidence-first document agent with persistent local memory, exact citations, and reversible actions from [ellmos-ai](https://github.com/ellmos-ai)). To preserve local-first privacy, evidence-grounded trust boundaries, air-gapped process isolation, single-writer filesystem safety, and compliance across multi-host environments, all contributions must adhere to the quality standards and operational invariants defined below.

---

## English

### 1. General Principles & Quality Gates
1. **100% Local-First & Zero-Egress (`INV-LOCAL-01`)**: Core agent execution loop, document indexing, persistent SQLite FTS5 stores, and workflow composition operate strictly offline using standard libraries. Zero outbound network sockets, zero telemetry, and zero phone-home tracking. Cloud inference (e.g. Nebius Token Factory) occurs only upon explicit user command vector and dedicated approval flag.
2. **Byte-Exact Evidence Citation (`INV-EVID-02`)**: Claims, summaries, and extracted facts are accepted only when verbatim quotes match source text byte-for-byte; line and page locators must be preserved.
3. **Reversible Actions & Journaled Undo (`INV-ACTION-03`)**: File mutations require pre-flight dry-run validation, atomic transaction handling, and provide complete reversible undo and resume via run journals.
4. **Multi-Tier Explicit Approval Gates (`INV-GATE-04`)**: File actions, external model transfers, cloud spend ceilings, and network exposure require explicit operator flags and fail closed.
5. **Path-Free Sanitized Packaging (`INV-ISOL-05`)**: Outbound packages strip host paths, secrets, symlinks, and unapproved files; preflight validates package before network transit.
6. **Provider-Neutral Loopback Surface (`INV-PROV-06`)**: Pluggable local and remote backends; unauthenticated interfaces, Captain's Desk, and web servers are restricted strictly to loopback (`127.0.0.1`).
7. **Composable Primitives & Voyages (`INV-POLICY-07`)**: Shared primitives (extraction, deduplication, section merge, delta snapshot) compose document workflows; reusable voyage drafts adapt without model fine-tuning.
8. **Unprivileged User-Mode Execution (`INV-RUNAS-08` / `RunAsInvoker`)**: All CLI runners, MCP servers, and background workers execute strictly within unprivileged user space. Administrative elevation (UAC/root/sudo) is strictly forbidden.
9. **Deterministic Artifacts & Ledgers (`INV-DET-09`)**: Deterministic SVG figures, structured reports, and cryptographic SHA-256 run ledgers guarantee reproducible audit trails.
10. **Cryptographic Auditability & Dual SLAs (`INV-SLA-10`)**: We commit to a 48h acknowledgment and 5-business-day triage SLA for security disclosures pursuant to [SECURITY.md](SECURITY.md).
11. **Version Freeze Discipline (`T-20260920-167562623`)**: Package version `0.2.1` is strictly frozen across `__init__.py`, `pyproject.toml`, and all manifests. Do not bump the version string. Document all advancements under `## [Unreleased]` in `CHANGELOG.md`.
12. **Clean Code & Regression Testing**: Every feature or fix must include regression tests in `tests/`. Keep test coverage at a 100% pass rate.
13. **Bilingual Parity**: Maintain synchronized structural and navigational parity across `README.md` and `README_de.md` (18-point dual anchors `sec-01` through `sec-18`).

### 2. Local Development Workflow (Plan D)
```bash
# Clone the repository (canonical Plan D location)
git clone https://github.com/ellmos-ai/NemoFold.git "C:\_Local_DEV\repos\NemoFold"
cd "C:\_Local_DEV\repos\NemoFold"

# Create virtual environment and install editable dev dependencies
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# Run comprehensive test suite
pytest -ra -v

# Run fast static code analysis
ruff check src tests

# Verify type annotations
python -m mypy src

# Check bytecode compilation
python -m compileall -q src tests

# Check whitespace and git diff cleanliness
git diff --check

# Verify version freeze compliance (must return 0 matches)
git diff -G"version = "
```

### 3. Submission Protocol
- Open an issue for architectural discussions before large refactoring.
- Keep provider API keys, tokens, and private credentials strictly outside the repository. Never commit real personal data, `.env` files, private documents, or absolute host paths.
- Ensure all 10 governance invariants (`INV-LOCAL-01` to `INV-SLA-10`) remain VERIFIED.
- Pull requests must target the `main` branch.

### 4. License
By contributing to `NemoFold`, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

## Deutsch

### 1. Grundsätze & Qualitäts-Tore
1. **100% Local-First & Zero-Egress (`INV-LOCAL-01`)**: Die primäre Agenten-Schleife, die Dokumenten-Indizierung, persistente SQLite FTS5 Speicher und die Workflow-Komposition arbeiten standardmäßig vollständig offline. Keine Telemetrie, keine externen Sockets, kein Phone-Home. Externe Cloud-Inferenz (z.B. Nebius Token Factory) erfolgt ausschließlich auf explizite Nutzeranweisung mit separater Gate-Freigabe.
2. **Byte-Exakte Evidenz-Zitate (`INV-EVID-02`)**: Behauptungen, Zusammenfassungen und extrahierte Fakten werden nur akzeptiert, wenn wörtliche Zitate Zeichen für Zeichen mit dem Quelltext übereinstimmen; Zeilen- und Seitennummern bleiben erhalten.
3. **Reversible Aktionen & Transaktionales Journal (`INV-ACTION-03`)**: Dateimodifikationen erfordern vorab eine Dry-Run-Validierung, atomare Transaktionen und bieten vollständige Undo- sowie Wiederaufnahme-Fähigkeiten über ein Ausführungs-Journal.
4. **Mehrstufige Freigabe-Tore (`INV-GATE-04`)**: Dateioperationen, externe Datenübertragungen, Cloud-Kosten-Obergrenzen und Netzwerkanbindungen erfordern explizite Bestätigungs-Flags und schließen im Zweifel fehl (Fail-Closed).
5. **Pfadfreie Bereinigte Pakete (`INV-ISOL-05`)**: Ausgehende Pakete entfernen automatisch Host-Pfade, API-Schlüssel, Symlinks und nicht freigegebene Dokumente vor dem Transfer.
6. **Provider-Neutrale Loopback-Schnittstelle (`INV-PROV-06`)**: Modulare lokale und externe Backends; unauthentifizierte Schnittstellen, Captain's Desk und Webserver lauschen strikt auf Loopback (`127.0.0.1`).
7. **Komponierbare Primitive & Voyages (`INV-POLICY-07`)**: Vier geteilte Grundbausteine (Extraktion, Deduplizierung, Abschnitts-Zusammenführung, Delta-Snapshots) bilden Workflows; wiederverwendbare Voyage-Entwürfe adaptieren Arbeitsabläufe ohne Modell-Fine-Tuning.
8. **Unprivilegierte Benutzer-Ausführung (`INV-RUNAS-08` / `RunAsInvoker`)**: Sämtliche CLI-Befehle, MCP-Server und Hintergrundprozesse laufen strikt im unprivilegierten Standard-Benutzerkontext. Administrative Rechte oder UAC-Elevationen sind verboten.
9. **Deterministische Artefakte & Protokolle (`INV-DET-09`)**: Deterministische SVG-Grafiken, strukturierte Auswertungsberichte und kryptographische SHA-256 Run-Ledger garantieren lückenlose Nachvollziehbarkeit.
10. **Kryptographische Auditierbarkeit & Duale SLAs (`INV-SLA-10`)**: Verbindliche Zusage von 48h Reaktionszeit und 5 Werktagen Triage-Bewertung gemäß [SECURITY.md](SECURITY.md).
11. **Version-Freeze-Disziplin (`T-20260920-167562623`)**: Paketversion `0.2.1` ist über alle Manifeste, Quelltexte und Badges hinweg strikt eingefroren. Kein Versions-Bump. Alle Weiterentwicklungen werden unter `## [Unreleased]` in `CHANGELOG.md` dokumentiert.
12. **Sauberer Code & Regressionstests**: Jede Änderung erfordert begleitende Tests in `tests/`. Die Testsuite muss zu 100% grün bleiben.
13. **Bilinguale Parität**: Strukturelle und navigatorische Parität zwischen `README.md` und `README_de.md` (18-Punkte Dual-Anker `sec-01` bis `sec-18`) ist zwingend einzuhalten.

### 2. Lokaler Entwicklungs-Workflow (Plan D)
```bash
# Klonen des Repositories (kanonischer Plan D Pfad)
git clone https://github.com/ellmos-ai/NemoFold.git "C:\_Local_DEV\repos\NemoFold"
cd "C:\_Local_DEV\repos\NemoFold"

# Virtuelle Umgebung erstellen und Entwicklungsabhängigkeiten installieren
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# Testsuite ausführen
pytest -ra -v

# Schnelle statische Code-Prüfung ausführen
ruff check src tests

# Typ-Annotationen prüfen
python -m mypy src

# Bytecode-Kompilierung validieren
python -m compileall -q src tests

# Whitespace- und Diff-Sauberkeit prüfen
git diff --check

# Versions-Freeze prüfen (darf keine Treffer liefern)
git diff -G"version = "
```

### 3. Einreichungsprotokoll (Pull Requests)
- Größere architektonische Anpassungen sollten vorab über ein GitHub Issue besprochen werden.
- Niemals echte persönliche Daten, `.env`-Dateien, vertrauliche Dokumente, absolute Host-Pfade oder API-Schlüssel committen.
- Alle 10 Governance-Invarianten (`INV-LOCAL-01` bis `INV-SLA-10`) müssen erfüllt bleiben.
- Pull Requests müssen gegen den `main`-Branch gestellt werden.

### 4. Lizenz
Mit dem Einreichen von Beiträgen zu `NemoFold` erklären Sie sich damit einverstanden, dass Ihre Beiträge unter der [MIT-Lizenz](LICENSE) lizenziert werden.
