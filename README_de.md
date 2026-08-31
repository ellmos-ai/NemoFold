# NemoFold

[English](README.md) | Deutsch

[![CI](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml/badge.svg)](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml)
[MIT-Lizenz](LICENSE) · Python 3.11+ · Local-first

NemoFold ist ein privater, evidenzorientierter Dokumentenagent. Er verwandelt
ausdrücklich freigegebene Ordner in ein dauerhaftes Arbeitsgedächtnis, hält Aussagen
bis zu ihren Fundstellen rückverfolgbar und macht Dateiaktionen reversibel.

Arbeitsslogan: **Your files. Your rules. Your agent.**

Dieses Repository enthält die neue Wettbewerbsimplementierung für den Nebius x NVIDIA
Global AI Hackathon. Der lokale Kern ist bewusst ohne Cloud-Konto nutzbar. Die
Integration mit NemoClaw, OpenShell, Nemotron und Nebius wird erst dann als belegt
gekennzeichnet, wenn ein echter, bereinigter Laufzeitnachweis vorliegt.

NemoFold macht aus Dokumenten Daten — es macht Wissen überhaupt erst nutzbar. Die
Dokument-Workflows sind Kompositionen aus vier geteilten Bausteinen: schemagebundene
Feldextraktion, Deduplikation, die das Gestrichene behält, abschnittsweise
Zusammenführung mit sichtbaren Konflikten und ein Delta gegen einen benannten
Snapshot. Weil diese Bausteine geteilt sind statt in einem Workflow eingeschlossen,
lassen sie sich auch für Fälle verketten, für die noch niemand einen Workflow
geschrieben hat.

Es passt sich Ihren Usecases auf zwei ehrliche Arten an: Das Captain's Desk plant aus
einem einfachen Satz neue Kombinationen vorhandener Bausteine, und jede vorbereitete
Fahrt wird zu einem wiederverwendbaren Entwurf. Das ist die ganze Lerngeschichte — eine
wachsende Bibliothek von Fahrten, kein Modell, das auf Ihren Dateien trainiert. Es wird
nichts feinjustiert, und nichts aus Ihren Dokumenten verlässt den Rechner ohne Ihre
Freigabe für genau diesen Transfer.

Derselbe Kern trägt beide Enden: Alltagsarbeit auf dem Laptop mit einem kleinen lokalen
Modell und eine Datenanalystin, die Nemotron über die Nebius Token Factory auf einen
großen Korpus richtet. Der Evidenzvertrag ändert sich dabei nicht — nur der Arbeiter.

## Was implementiert ist

| Workflow | Lokales Ergebnis |
|---|---|
| Smart Inbox | Dateiendungsbasierter Ablageplan, Alles-oder-nichts-Kollisionsgate, protokollierte Verschiebungen, Fortsetzen und Rückgängig |
| Naming, Format & Retention | Regelauflösung, Namens- und Aufbewahrungsprüfungen, Dry-Run, reversible Verschiebe-/Kopiervorgänge sowie Konvertierungskopien für TXT/MD/RST |
| Cleanup Rules | Manuelle Massenablage plus lesbare Vorschläge, die nur aus expliziten Korrekturen entstehen und sich nie selbst aktivieren |
| Mail-to-Case | Schreibgeschützte lokale EML-Aufnahme, quellengebundenes Falldossier, Manifest und gehashte Anlagenextraktion |
| Controlled Email | Lokaler RFC-822-Entwurf und exakter Freigabe-Hash; Versandwünsche blockieren ohne unmittelbare Bestätigung und belegten Serveradapter |
| Universal Bundle | Deterministisches Textbündel, Manifest, ZIP, Hashes und explizite Einträge für nicht unterstützte oder unlesbare Dateien |
| Continuous Folder Digest | Dauerhafte Bestands-Snapshots mit neuen, geänderten, unveränderten und gelöschten Quell-IDs |
| Evidence Analyst | Persistenter SQLite-FTS-Index, mehrere Fragen, exakte Zitate, Quellenkatalog, Zeilen-/Seitenfundstellen, Abdeckung und Berichte |
| Version Resolver | Auflösung je Dateifamilie, explizite Priorität für Gültigkeit/Datum/Version, benannter Dateizeit-Fallback und Zeilenvergleich |
| Contact Monitor | Quellenzitierte Kontakt- und Zuständigkeitskandidaten, Vergleich benannter Snapshots und keine automatische Löschung |
| Report & Artifact Studio | Validierter Analysevertrag, ausgegeben als Markdown, TXT, PDF, DOCX und ODT |
| Document Registry | Deklarierte Spalten aus jedem freigegebenen Dokument in einer Tabelle; jede gefüllte Zelle behält Quelle und Zeile, eine unbeantwortete Zelle bleibt leer, Ausgabe als JSON, CSV und vollständige Berichtsfamilie |
| Fact Distill | Zitierfähige Sätze je Quelle; wiederholte Aussagen werden aus den Befunden gestrichen, jede gestrichene Fundstelle bleibt in einem eigenen Anhang sichtbar |
| Synopsis Merge | Abschnittsweise Zusammenführung mehrerer Dokumente mit Quellanker je Absatz; abweichende Labels erscheinen als Konfliktblöcke statt als stille Entscheidung |
| Daily Arrivals | Vergleich gegen einen benannten Snapshot mit Name, Größe, Zeit und Kurzinhalt je neuer Datei, Eigentümer wo die Plattform ihn nennen kann, plus selbst zu installierende Aufgabendatei |
| NemoClaw Platform & Proof | Pfadfreie, gehashte Auftragspakete mit Fail-closed-Adapter für die Nebius Token Factory und unabhängig prüfbarem Ergebnisbeleg; der echte Wettbewerbslauf ist weiterhin offen |

Die gemeinsamen Kerne sind Laufzeit, Policy-/Privacy-Gate, Laufjournal und
Wiederherstellung, Evidenz-Engine, providerneutraler Adapterkern, MCP-Oberfläche und
Artefaktexport. Die lokale Extraktion unterstützt Textdateien, JSON, CSV, HTML, PDF,
DOCX und ODT. Nicht unterstützte oder unlesbare Dateien bleiben als sichtbare
Abdeckungslücken erhalten.

Cloud-Kosten, Uploads, echte NemoClaw-/Nebius-Ausführung und weitere Änderungen an
Devpost bleiben getrennte menschliche Freigabegates.

![NemoFold Captain-Nemo-Konsole](docs/media/nemofold-console.png)

## Installation

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m nemofold --help
```

Jeder Nicht-Demo-Befehl verwendet denselben strikten JSON-Vertrag
`nemofold.job.v1`. Siehe
[`schemas/nemofold-job-v1.schema.json`](schemas/nemofold-job-v1.schema.json) und
das Verzeichnis [`examples/jobs`](examples/jobs).

## Offline-Nachweis

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold demo --input examples\synthetic-home --output run-reports\demo
```

Der Bericht weist bewusst `cloud_proof: false` aus. So lässt sich der
Fail-closed-Pfad ausführen:

```powershell
python -m nemofold demo --input examples\synthetic-home --output run-reports\blocked `
  --scenario blocked-external
```

Die normale Demo erzeugt ein Text-/Manifest-/ZIP-Bündel, einen Ordner-Digest,
Kontextbelege, einen SQLite-FTS-Index, Markdown-/TXT-/PDF-/DOCX-/ODT-Berichte und ein
Laufjournal. Sie verschiebt eine synthetische Inbox-Datei und macht den Vorgang wieder
rückgängig, um die Reversibilität zu belegen.

## Einen echten lokalen Auftrag ausführen

```powershell
$runId = "local_analysis_1"
python -m nemofold preview --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id $runId
python -m nemofold run --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id $runId
python -m nemofold verify run-reports\evidence-local\ledger\$runId.json
```

`preview` ruft kein externes Modell auf und führt keine Dateiaktionen aus. Bei einem
Auftrag mit externem Modell schreibt es das genaue pseudonymisierte Kontextpaket, das
den Rechner verlassen dürfte, und protokolliert `transfer_performed: false`. Ein
späteres `run` blockiert weiterhin, solange kein echter externer Laufzeitadapter und
keine ausdrücklichen Datenschutz-, Modell- und Kostengates vorhanden sind.

`nemofold package` verwandelt einen `allow_once`-Auftrag in ein gehashtes, pfadfreies
lokales NemoClaw-Verzeichnis und validiert es sofort. Es führt weiterhin keinen Upload
aus und protokolliert `transfer_performed: false`; siehe
[NemoClaw-Integration](docs/nemoclaw-integration.md).

## Jedes unterstützte Modell über denselben Evidenzkern nutzen

NemoFold kann ausschließlich den lokal ausgewählten und pseudonymisierten
Evidenzkontext an Ollama, LM Studio, eine persönliche Codex-/Claude-Code-CLI oder die
offiziellen OpenAI-/Anthropic-APIs übergeben. Aussagen werden nur angenommen, wenn
jedes Zitat im ausgehenden Kontext der zugehörigen Frage vorkommt. Die Providerwahl ist
Laufzeitkonfiguration und verändert den strikten Auftragsvertrag nicht.

```powershell
python -m nemofold providers
python -m nemofold analyze-provider --job examples\jobs\evidence-local.json `
  --allow-root $PWD --run-id ollama_1 --provider ollama --model qwen3
```

Derselbe Dienst ist über `POST /api/provider-analyze` und den stdio-MCP-Server
verfügbar:

```powershell
codex mcp add nemofold -- python -m nemofold mcp --base-dir $PWD --allow-root $PWD
claude mcp add --scope user nemofold -- python -m nemofold mcp `
  --base-dir $PWD --allow-root $PWD
```

Lokale Provider sind auf Loopback beschränkt. Externe Adapter verlangen `allow_once`,
ein serverseitiges Gate für externe Modelle und eine Freigabe je Übertragung. Schlüssel
werden nur aus Umgebungsvariablen gelesen. Generische Providerbelege werden niemals
zum Nebius-Wettbewerbsnachweis; dafür bleibt ausschließlich der nächste Abschnitt
zuständig. Siehe [Provideradapter, lokale API und MCP](docs/providers-and-mcp.md).

## Freigegebener Lauf über die Nebius Token Factory

### Modellwahl und Beitrag der Token Factory

Das konfigurierte Modell ist NVIDIA Nemotron 3 Super
(`nvidia/nemotron-3-super-120b-a12b`), bereitgestellt über die
[Nebius Token Factory](https://nebius.com/services/token-factory/nemotron). Die Wahl
ist bewusst: Die Gewichte sind unter der NVIDIA Open License vollständig offen (der
Hackathon verlangt ein offenes NVIDIA-Modell); das Agentic-Reasoning- und
Instruction-Following-Profil passt zu NemoFolds striktem, JSON-gebundenem
Evidenzvertrag; das lange Kontextfenster trägt ein komplettes begrenztes
Evidenzpaket in einer Anfrage; und das hybride MoE-Design (rund 12B aktive von 120B
Parametern) hält die konservative Kostenobergrenze pro Aufruf weit unter dem
Job-Budget. Der Adapter erzwingt das Präfix `nvidia/nemotron-` doppelt — im
Preflight und erneut vor dem Transport.

Die Token Factory steuert den einen Schritt bei, den das Produkt lokal nicht leisten
kann: einen starken gehosteten Reasoning-Durchgang über das vorbereitete
Evidenzbündel. Alles andere — Originale, Pfade, Index, Richtlinien, Journal und
Verifikation — bleibt auf dem lokalen Rechner; nur pseudonymisierte begrenzte Chunks
passieren das Gate, und das bereinigte Ergebnis wird in die lokal verifizierte
Belegkette zurückgebunden. Ein echter bezahlter Lauf bleibt ein ausdrückliches
Nutzer-Gate und wird nirgends in diesem Repository behauptet.

Der Live-Adapter ist ein getrenntes Gate für einen irreversiblen Datentransfer. Er
akzeptiert nur den offiziellen HTTPS-Ursprung der Nebius Token Factory, lehnt
Weiterleitungen ab, prüft vor der Anfrage eine konservative Kostengrenze, liest den
Schlüssel ausschließlich aus `NEBIUS_API_KEY` und verweigert die Wiederholung eines
Pakets, das bereits `result.json` oder einen dauerhaften Übertragungsversuch enthält.
Nach dem Kostengate und vor jedem Beleg bestätigt er die exakte Modell-ID gegen den
Live-Katalog `/v1/models`. Dieser Aufruf ist ein autorisierter Metadatenabruf ohne
Auftragsinhalt; eine zurückgezogene oder vertippte Modell-ID bricht deshalb ohne Beleg
ab und lässt das Paket vollständig lauffähig. Ein bestätigter Katalog schreibt
`model_catalog_checked: true` ins Ergebnis, und der Verifizierer weist ein Ergebnis
zurück, das etwas anderes behauptet.

```powershell
$env:NEBIUS_API_KEY = "<session-only-key>"
python -m nemofold token-factory-preflight <package-directory> `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 8192
python -m nemofold token-factory-run <package-directory> `
  --approve-live-transfer `
  --input-price-usd-per-million <current-input-rate> `
  --output-price-usd-per-million <current-output-rate> `
  --max-completion-tokens 8192 `
  --declared-nemoclaw-version <captured-installed-version>
python -m nemofold verify-result <package-directory>
Remove-Item Env:\NEBIUS_API_KEY
```

Die beiden Preise sind Pflichtangaben, weil sich Preise ändern können. Sie müssen zum
Ausführungszeitpunkt aus der aktuellen Preisliste des Anbieters übernommen werden. Die
Reasoning-Modelle verbrauchen vor der JSON-Antwort Completion-Tokens für das Denken;
`--max-completion-tokens` deshalb großzügig wählen — das konservative Kostengate prüft
die resultierende Obergrenze weiterhin vor jeder Anfrage gegen das Job-Budget. Die
bereinigte `result.json` bindet die genaue Anfrage, die bereinigte Antwort
(`response_sha256` wird über den bereinigten Antwortkörper berechnet, nie über rohe
Anbieter-Bytes), Nutzung, Preisangaben, Kosten, Endpunkt, Modell, Zeitstempel und
Modellausgabe an das unveränderliche lokale Paket. Sie enthält weder Authorization-Header noch API-Schlüssel. Eine fehlgeschlagene
Anbieterantwort protokolliert `transfer_performed: true`, aber niemals
`cloud_proof: true`. Bricht die Verbindung ohne Antwort ab, bleibt die vor der Anfrage
geschriebene `transfer-attempt.json` erhalten, meldet einen unklaren Übertragungsstand
und blockiert eine unsichere automatische Wiederholung. Die Wiederaufnahme nach einem
verbrauchten Versuch ist bewusst, nicht destruktiv: Mit `nemofold package` ein frisches
unveränderliches Paket unter neuer `run_id` bauen und dieses ausführen. Vorhandene
Belege werden nie gelöscht — der gescheiterte Versuch bleibt prüfbar, das neue Paket
lauffähig.

`token-factory-preflight` führt keine Netzwerkanfrage aus und schreibt keinen
Übertragungsbeleg. Es validiert das unveränderliche Paket, den Endpunkt, das explizite
Nemotron-Modell, die JSON-Anfrage, die vom Aufrufer gelieferten aktuellen Preise, die
konservativen Maximalkosten, das Auftragsbudget, die Schutzregeln gegen Doppelläufe und
das Vorhandensein eines Sitzungsschlüssels. Seine Ausgabe hält `network_called`,
`transfer_performed` und `cloud_proof` stets auf false; ein erfolgreicher Preflight ist
Bereitschaft, kein Ausführungsnachweis und keine Transferfreigabe. Er meldet deshalb
`model_catalog_checked: false`: Den Katalog bestätigt `token-factory-run` als einziger
Befehl, der das Netz berühren darf.

Die Anfrage nutzt den dokumentierten `json_object`-Antwortmodus der Token Factory und
überträgt ausschließlich dokumentierte Chat-Completion-Parameter, denn ein einziges
undokumentiertes Feld, das der Endpunkt ablehnt, würde den einen freigegebenen Lauf für
einen HTTP 400 verbrauchen. NemoFold fügt sein vollständiges Ausgabeschema in die
begrenzte Nutzer-Nutzlast ein und validiert das zurückgegebene Objekt lokal. Damit hängt
der Evidenzvertrag nicht von modellspezifischer serverseitiger JSON-Schema-Erzwingung ab.

Die optional angegebene NemoClaw-Version ist nur Metadatum. Das Ergebnis protokolliert
`nemoclaw_proof: false`; nur ein separat erfasster, bereinigter Laufzeit-Log aus der
tatsächlichen Sandbox kann eine NemoClaw-Ausführung belegen. Die frühere Pre-Release-
Option `--nemoclaw-version` wurde bewusst entfernt, weil ihr Name einen Beleg
suggerierte; Skripte müssen stattdessen `--declared-nemoclaw-version` verwenden.

Aktionsaufträge verlangen zusätzlich `--approve-actions`. Ein abgeschlossener
Aktionslauf kann mit `nemofold undo <run-id> --output <dir> --allow-root <root>
--approve-actions` rückgängig gemacht werden. Fehlgeschlagene oder blockierte Aufträge
lassen sich mit `nemofold resume` unter Beibehaltung der ursprünglichen Auftragsidentität
und des Journals fortsetzen.

## Das Captain's Desk fragen

Die Übersicht der Konsole beginnt mit dem Captain's Desk: ein einfacher Satz hinein,
eine Kette vorbereiteter Auftragsentwürfe hinaus. Es plant und bereitet vor; es führt
nie aus, versendet nie und speichert keine Freigabe. Jeder vorbereitete Schritt bleibt
Dry-run, rein lokal und ohne Budget — unabhängig davon, was die Anfrage verlangt hat.

Auf `Unfall mit Hyundai und schreib mir eine mail an zuständigen versicherungsberater
füge bild ein als entwurf` bereitet das Desk den Contact Monitor vor — weil die Quellen
die zuständige Person bereits nennen könnten — und danach einen Controlled-Email-Entwurf,
dessen Betreff aus dem Satz stammt. Was es nicht weiß, fragt es: Empfänger, Absender und
welche freigegebene Datei angehängt werden soll, mit dem Hinweis, dass ein Anhang gehasht,
aber nie als Beleg zitiert wird.

Ebenso deutlich benennt das Desk seine Grenzen. Wer ein zweisprachiges Dokument
abgleichen will, erfährt, dass Bilingual Sync ein geplanter, kein aktiver Document
Service ist — und bekommt die ehrlichste heutige Annäherung vorbereitet: einen
Folder-Digest-Schnappschuss und einen Version-Resolver-Vergleich. Wer Wiederholung
verlangt, erhält die zwei wahrheitsgemäßen Wege: die vorbereiteten Entwürfe erneut
ausführen oder selbst eine Aufgabe im eigenen Betriebssystem einrichten, die die CLI
aufruft. NemoFold hat keinen eigenen Scheduler und startet sich nicht selbst — und
behauptet das folglich auch nicht.

Vorbereitete Fahrten landen in derselben Entwurfs-Inbox, in die auch CLI, MCP und die
lokale API schreiben, gekennzeichnet mit `source: wizard`. Ein Mensch öffnet jeden
Entwurf im Maschinenraum, ergänzt das Offene und führt ihn aus. Das Desk ist eine reine
Loopback-Fläche: in der öffentlichen Demo nicht vorhanden, auf einem netzexponierten
Server abgelehnt.

## Lokale Webkonsole öffnen

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold serve --allow-root $PWD --base-dir $PWD
```

Öffne `http://127.0.0.1:8765`. Die Konsole verwendet denselben strikten Auftragsparser
und Anwendungsdienst wie die CLI. Sie bindet nur an Loopback, lehnt Cross-Origin-POSTs
ab und verlangt `--expose-network`, bevor sie eine Nicht-Loopback-Adresse verwendet.
Auch dann bleiben die autoritätstragenden Flächen Loopback-only: Ein netzexponierter
Server lehnt Job-Preview und -Ausführung ab, genau wie Drafts, Artifacts und Provider;
Hosting für andere Personen läuft über `serve-demo`. Preview ist der standardmäßige
sichere Pfad; Aktionsworkflows benötigen zusätzlich das serverseitige Gate
`--approve-actions`, bevor eine Apply-Anfrage erfolgreich sein kann.

Übersicht und sechs Arbeitsbereiche besitzen eigene, direkt aufrufbare Routen statt
Sprüngen innerhalb einer langen Seite: `/document-center`, `/analysis`, `/routines`,
`/artifacts`, `/connections` und `/governance`. Die Übersicht selbst bleibt bewusst
karg — eine Überschrift, ein Satz und die sechs Bereichskarten — und faltet
Grenz-Kacheln, Evidenzkette, Vertragsregister und Roadmap hinter eine alte Seekarte,
die sich per Klick oder Enter aufklappt. Nichts wird entfernt; die Dokumentation
verschmutzt nur nicht mehr die Oberfläche. Jeder Bereich beginnt mit dem, was dort
lebt, statt mit dem Jobformular: Das Document Center zählt den freigegebenen Korpus,
Folder Routines liest die letzten Routineläufe, und jeder Bereich bietet Aufgabenkarten,
die den Vertrag darunter vorbereiten. Die Command Bridge unter `/governance` zeigt die
Autorität, mit der dieser Server gestartet wurde — Gates für Dateiaktionen, externe
Modelle und Netzexposition, freigegebene Roots, Budgetgrenze und vertraglich erfasste
Workflows — und beherbergt die Storage Policies. Gates werden dort gelesen, nicht
erteilt: Ein geschlossenes Gate verlangt weiterhin einen Neustart mit dem passenden
Flag. Jede Arbeitsseite zeigt nur die fachlich passenden Workflows. Artifact Studio
öffnet unmittelbar den verifizierten Artefaktkatalog; Connections ist eine reine
Statusseite und trennt konfigurierte Adapter, ausgeführte Providerläufe, Transfers und
Cloud-Nachweise sichtbar voneinander.

Das Analysis Lab verbindet deterministische Bundle-Vorbereitung, Datenschutz-Preflight,
Evidence Analyst, wiederverwendbare Prompt-Sammlungen und persistente Research Notebooks.
Artifact Studio öffnet ausgeführte oder blockierte Ledger und prüft jeden erfassten
Artefakthash. Das Document Center enthält außerdem erklärbare Cleanup Rules,
schreibgeschützten Mail-to-Case-Ingest und kontrollierte E-Mail-Entwürfe; Folder Routines
umfasst den quellengebundenen Contact Monitor. Ein Modell kann dieselben Einstellungen
über `draft-save`, MCP oder die Loopback-Draft-API zur Browserprüfung vorbereiten;
Freigaben werden dabei immer zurückgesetzt.

Controlled Email behauptet in der Standardlaufzeit keinen Netzwerkversand. Der Workflow
schreibt den genauen Entwurf und Freigabedigest und blockiert eine Sendeanforderung, bis
derselbe Digest bestätigt wurde und ein separat belegter serverseitiger Mailadapter
existiert. Mail-to-Case akzeptiert freigegebene lokale `.eml`-Dateien; es verbindet sich
nicht still mit einem Postfach.

### Fähigkeitsminimale synthetische Demo starten

Nutze den getrennten Demo-Befehl, wenn Personen die Konsole erreichen könnten, die
keine lokale Dateibefugnis erhalten dürfen:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m nemofold serve-demo --demo-root examples\synthetic-home
```

`serve-demo` akzeptiert nur fünf schreibgeschützte Workflows über dem eingecheckten
synthetischen Korpus. Eingabe- und Ausgabe-Root, Workflow-Parameter, Datenschutzmodus,
Aktionsmodus, Modellzugriff und Budget werden serverseitig gesteuert. Jede Anfrage
erhält einen isolierten temporären Ausgabebereich, der nach Rückgabe der bereinigten
Antwort entfernt wird. Der Befehl bietet weder Dateiaktions- noch externe Modellflags
an und bindet weiterhin nur an Loopback, sofern nicht zugleich ein nicht lokaler Host
und `--expose-network` angegeben sind. Dies ist eine fähigkeitsminimale Hosting-
Oberfläche, kein Nachweis für einen Nebius-, Nemotron- oder NemoClaw-Lauf;
`cloud_proof` bleibt false.

## Vertrauensgrenze

- Originaldateien, absolute Pfade, persistenter Index, Policies, Journal, Validierung
  und Aktionen bleiben lokal.
- Nur ausgewählte Abschnitte, Fragen, künstliche Quell-IDs, Schema und ein begrenztes
  Budget dürfen in ein externes Paket gelangen.
- Der Paketvalidator lehnt Hostpfade, Secrets, nicht deklarierte Dateien, geänderte
  Hashes, Symlinks oder verbleibende sensible Muster ab – selbst wenn ein Manifest neu
  gehasht wurde.
- `cloud_proof: true` ist ohne erfolgreiche, schemakonforme Anbieterantwort, die an
  Laufzeitevidenz gebunden ist, ungültig. Das Repository enthält den Adapter und
  simulierte Tests, behauptet aber bewusst nicht, dass der noch offene echte
  Wettbewerbslauf erfolgreich war.

## Design und Integration

- [Ausrichtung der Evidence-Console-Oberfläche](docs/design-direction.md)
- [Architektur](docs/architecture.md)
- [Provideradapter, lokale API und MCP](docs/providers-and-mcp.md)
- [Fähigkeitsminimale Demo-Bereitstellung](docs/deployment.md)
- [NemoClaw-Integration](docs/nemoclaw-integration.md)
- [Produktgeschichte](docs/product-story.md)
- [Roadmap der Dokumentendienste](docs/document-services-roadmap.md)
- [Dreiminütige Jury-Demo](docs/jury-demo.md)
- [Jury-Designset und Nautilus-Markenkit](docs/media/designset/README.md)
- [Einreichungsbereitschaft](docs/submission-readiness.md)
- [Codekarte für den Wettbewerb](COMPETITION_CODE_MAP.md)
- [Software von Drittanbietern](THIRD_PARTY_LICENSES.md)
- [Sicherheitsrichtlinie](SECURITY.md)
- [Mitwirken](CONTRIBUTING.md)
- [Release-Gate](RELEASE_GATE.md)
