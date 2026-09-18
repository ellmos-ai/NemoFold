# Security Policy / Sicherheitsrichtlinie

[English](#english) | [Deutsch](#deutsch)

---

<a id="english"></a>
## English

### Supported Versions

| Version | Supported | Notes |
|:---:|:---:|:---|
| `0.2.x` | :white_check_mark: | Current active release branch (`main`) |
| `0.1.x` | :white_check_mark: | Initial release branch |
| `< 0.1.0` | :x: | Historical competition snapshots |

### Local-First & Zero-Egress Architecture

NemoFold is designed with a strict **local-first**, **least-privilege**, and **verifiable evidence** model:
- **Local Execution & Unprivileged User Mode**: Original files, persistent SQLite FTS5 indices, policy configurations, and action journals run entirely in unprivileged user space (`RunAsInvoker`). Zero administrator or root elevation required.
- **Zero-Egress Data Sovereignty**: Documents, extracted text, and personal data never leave the host system unless an operator explicitly approves a specific outbound transfer.
- **Fail-Closed Budgeting**: Model budgets and server-side cost limits must be finite, non-negative values; `NaN`, infinity, booleans, and negative values fail before provider execution.
- **Reversible File Actions**: Mutating operations require pre-flight dry-run review and are logged to an append-only journal with instant resume and undo capabilities.

### Vulnerability Response & SLA

We take security disclosures seriously and commit to:
- **Initial Response SLA**: Within **48 hours** of receiving a valid disclosure.
- **Triage & Status Update**: Within **5 business days** with an assessment and remediation roadmap.
- **Fix & Advisory Release**: Coordinated release of security patch alongside a public GitHub Security Advisory.

### Reporting a Vulnerability

If you discover a potential security vulnerability in NemoFold:

1. **Do NOT** open a public issue or discussion.
2. Submit a report privately via **GitHub Security Advisories**:
   - Navigate to the [Security Tab](https://github.com/ellmos-ai/NemoFold/security/advisories/new).
3. Alternatively, contact the maintainers directly via email:
   - `security@ellmos.ai`
   - `security@open-bricks.org`
   - `support@lukasgeiger.com`
   - `lukas@open-bricks.org`

Please include in your report:
- Affected version, CLI/API/MCP entry point, and expected security invariant.
- Steps to reproduce or a minimal synthetic reproduction (no real Nebius API keys or private corpuses needed).
- Potential impact and any proposed remediations.
- **Never** include real secrets, private documents, host paths, or personal data.

### Product Security Boundaries

- Local paths are restricted to operator-provided allow roots.
- File actions require an explicit apply gate, a deterministic plan, and a reversible journal.
- External packages must pass path, secret, schema, hash, and budget gates.
- Generic provider calls receive only pseudonymized selected chunks. Local HTTP providers are restricted to loopback; API keys are environment-only; subscription CLI bridges run in temporary read-only sessions without inherited provider API keys.
- Model budgets and server-side cost limits must be finite, non-negative values; `NaN`, infinity, booleans, and negative values fail before provider execution.
- CLI, HTTP, and MCP share the same root, privacy, transfer, quote, and action gates. The HTTP provider route is loopback-only; network-exposed servers and the public demo expose none of the generic provider surface.
- The web console is loopback-only unless network exposure is explicitly enabled.
- The separate public demo mode reads only an operator-selected synthetic fixture, forces local-only dry-run authority, removes model/action capabilities, caps parallel work, uses per-request temporary output, and redacts host paths from responses.
- Generic provider execution can produce a validated quote-bound receipt but never a competition proof. Live Nebius/Nemotron execution remains unproven until the dedicated sanitized runtime receipt validates.

---

<a id="deutsch"></a>
## Deutsch

### Unterstützte Versionen

| Version | Unterstützt | Hinweise |
|:---:|:---:|:---|
| `0.2.x` | :white_check_mark: | Aktueller Entwicklungs- und Release-Zweig (`main`) |
| `0.1.x` | :white_check_mark: | Ursprünglicher Release-Zweig |
| `< 0.1.0` | :x: | Historische Wettbewerbs-Snapshots |

### Local-First- & Zero-Egress-Architektur

NemoFold folgt einem konsequenten **Local-First**-, **Least-Privilege**- und **Evidenz**-Sicherheitskonzept:
- **Lokale Ausführung & Unprivilegierter User-Mode**: Originaldokumente, persistente SQLite-FTS5-Indizes, Richtlinien und Aktionsjournale laufen vollständig im unprivilegierten Benutzerkontext (`RunAsInvoker`) ohne Root- oder Administratorrechte.
- **Datenschutz & Zero-Egress**: Lokale Dateien, extrahierte Texte und persönliche Daten verlassen den Rechner niemals ohne explizite Freigabe für genau diesen Transfer.
- **Fail-Closed Budget-Schutz**: Modell-Budgets und Server-Kostenlimits müssen endliche, nicht-negative Zahlen sein; ungültige Werte stoppen den Aufruf vor der Ausführung.
- **Reversible Dateiaktionen**: Mutierende Operationen erfordern eine Vorab-Prüfung (Dry-Run) und werden in einem append-only Journal mit sofortiger Undo-/Resume-Möglichkeit protokolliert.

### Reaktionszeiten & SLA

Wir nehmen Sicherheitsmeldungen sehr ernst und garantieren:
- **Erste Rückmeldung (SLA)**: Innerhalb von **48 Stunden** nach Eingang einer validen Meldung.
- **Triage & Statusupdate**: Innerhalb von **5 Werktagen** mit technischer Bewertung und Behebungsfahrplan.
- **Fix & Advisory-Release**: Koordinierte Veröffentlichung des Patches zusammen mit einem GitHub Security Advisory.

### Schwachstelle melden

Wenn Sie eine potenzielle Sicherheitslücke in NemoFold entdecken:

1. Eröffnen Sie bitte **kein** öffentliches GitHub-Issue und keine öffentliche Diskussion.
2. Melden Sie die Schwachstelle vertraulich über **GitHub Security Advisories**:
   - [Sicherheitsbericht vertraulich einreichen](https://github.com/ellmos-ai/NemoFold/security/advisories/new)
3. Alternativ per E-Mail an das Sicherheitsteam:
   - `security@ellmos.ai`
   - `security@open-bricks.org`
   - `support@lukasgeiger.com`
   - `lukas@open-bricks.org`

Bitte geben Sie die betroffene Version, den Einstiegspunkt (CLI/API/MCP) und eine minimale synthetische Reproduktion an. Fügen Sie **niemals** reale API-Schlüssel, vertrauliche Dokumente oder echte Hostpfade bei.
