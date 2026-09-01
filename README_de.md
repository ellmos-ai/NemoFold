# NemoFold

[English](README.md) | Deutsch

[![CI](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml/badge.svg)](https://github.com/ellmos-ai/NemoFold/actions/workflows/ci.yml)
[MIT-Lizenz](LICENSE) · Python 3.11+ · Local-first

**Aus Dokumenten werden Daten. NemoFold macht Wissen nutzbar.**

NemoFold passt sich Ihren Usecases an — eine wachsende Bibliothek, kein Finetuning.

NemoFold ist ein privater, evidenzorientierter Dokumentenagent. Er verwandelt
ausdrücklich freigegebene Ordner in ein dauerhaftes Arbeitsgedächtnis, hält Aussagen
bis zu ihren Fundstellen rückverfolgbar und macht Dateiaktionen reversibel.

Arbeitsslogan: **Your files. Your rules. Your agent.**

Dieses Repository enthält die neue Wettbewerbsimplementierung für den Nebius x NVIDIA
Global AI Hackathon. Der lokale Kern ist bewusst ohne Cloud-Konto nutzbar. Die
Integration mit NemoClaw, OpenShell, Nemotron und Nebius wird erst dann als belegt
gekennzeichnet, wenn ein echter, bereinigter Laufzeitnachweis vorliegt.

Die Dokument-Workflows sind Kompositionen aus vier geteilten Bausteinen: schemagebundene
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

## Meine Usecases: die Fahrten-Bibliothek

Ein Plan, den Sie behalten, bekommt einen Namen. Die Übersicht trägt die Bibliothek:
gespeicherte Fahrten neben fünf Spezialisten, die NemoFold mitbringt — Faktendestillat
als PDF, Themenbündel mit Belegen, Tagesbericht, Verzeichnistabelle und
Angebotssynopse. Ein Spezialist ist ein schreibgeschützter Ausgangspunkt: Er trägt
Workflows und Parameter, aber keinen Pfad. Eine mitgelieferte Datei kann deshalb nie
einen Ordner auf Ihrem Rechner benennen und nie von selbst laufen. Beim Kopieren wird
sie an Ihre freigegebenen Roots gebunden und ist danach ein gewöhnlicher, bearbeitbarer
Eintrag.

Bearbeiten geht auf zwei Wegen, und beide enden in etwas, das Sie bestätigen. In der
Detailansicht ordnen oder entfernen Sie Schritte von Hand und speichern. Oder Sie
fragen den Kapitän — „füge zwischen Schritt 2 und 3 einen Tagesbericht ein" — und
erhalten die Schrittliste vorher und nachher als Diff mit Übernehmen-Knopf. Geschrieben
wird die Bibliothek erst beim Übernehmen, und was das Desk nicht zuordnen kann, wird
beantwortet statt geraten: Anonymisierung etwa gehört zum Datenschutz-Gate jedes
Schritts und ist kein eigener Schritt.

Eine Fahrt auszuführen heißt: Schritte der Reihe nach, jeder durch dieselben Gates und
mit eigenem Ledger, und ein Gesamt-Dossier verlinkt sie. Ein blockierter Schritt stoppt
die Kette dort, damit nichts Nachgelagertes auf einem unfertigen Ergebnis läuft. Ging
es gut, sehen Sie eine ruhige Zeile und die Details einen Klick entfernt; ging es
schief, liegen Schritte, Gates und Modelle offen vor Ihnen.

Eine Modellpräferenz kann auf drei Ebenen stehen, und die spezifischste gewinnt: Glied,
Kette, lokaler Default. Eine Kette kann stattdessen erklären, dass sie ihre Glieder
überschreibt — gedacht für datenschutzkritische Arbeit, die lokal bleiben muss, was ein
Glied auch sagt. Eine solche Fahrt trägt in der Bibliothek ein Warnzeichen und die
Begründung, die ihr Besitzer hinterlegt hat. Für einen einzelnen Lauf lässt sich außerdem
ein Modell für die ganze Fahrt wählen: Der Override gilt einmalig, erscheint im Dossier
und lässt die gespeicherten Einstellungen unberührt.

Über allem steht eine Regel, die kein Modus, kein Override und keine Einstellung
aufheben kann: Eine als local-only erklärte Kette ist ein Deckel. Eine exponiertere
Einstellung darunter gewinnt nicht und verliert auch nicht still — sie stoppt die Kette
und fragt nach, denn still zu erweitern, wer Ihre Dokumente sieht, ist das eine
Versagen, das sich dieses Produkt nicht leisten kann. Auch für sich erteilt eine
Präferenz keine Erlaubnis: Externmodell-Gate, Freigabe je Lauf und Budget entscheiden
weiterhin.

Das Dossier nennt das tatsächlich gelaufene Modell — nicht immer das bevorzugte — und
sagt, welcher der drei Fälle vorlag. Die meisten Workflows arbeiten deterministisch und
haben überhaupt keinen Reasoning-Worker; eine Präferenz darauf bleibt gespeichert und
wird als nicht anwendbar ausgewiesen, statt ihr Arbeit zuzuschreiben, die sie nicht
geleistet hat. Ein lokaler Worker beim Evidence Analyst wird wirklich gefragt, denn ein
lokaler Endpunkt braucht keine Transferfreigabe je Lauf. Ein externer stoppt die Kette
und verweist darauf, diesen Schritt einzeln zu starten, denn ein Kettenlauf erteilt nie
eine Freigabe je Lauf.

Jeder Eintrag trägt Themen-Tags — so findet ein Usecase den Raum, in den er gehört —
und er kann einen Zeitplan tragen. Ein Zeitplan ist eine erklärte Absicht und nicht mehr:
Er hält fest, wann Sie die Fahrt laufen lassen wollen, ergänzt das abgeleitete Tag
`scheduled`, damit der Routinenfilter ihn findet, und sagt das in der gespeicherten Datei
über sich selbst. NemoFold registriert keine Aufgabe in Ihrem Betriebssystem und startet
nichts von allein.

Manche Usecases lassen sich noch nicht bedienen. Sie werden trotzdem aufbewahrt, mit dem
Instrument benannt, auf das sie warten, und getrennt von den lauffähigen gelistet — ein
festgehaltener Wunsch ist mehr wert als ein abgelehnter, solange ihn niemand für etwas
Lauffähiges hält.

## Fall-Chronik

Vier Analysekerne machen aus einem Ordner voller Aussagen, Berichte und Verträge
Strukturen, die sich bis zu einem Satz zurückverfolgen lassen: wer vorkommt, welche
Verbindungen tatsächlich dastehen, wann jemand verortet ist und wo ihn gar nichts
verortet. Sieben Workflows setzen darauf auf — Person Registry, Relation Model,
Person Timeline, Coverage Timeline, Alibi Weave, Contradiction Synopsis und Corpus
Query.

Keiner davon zieht einen rechtlichen Schluss, und jeder Bericht sagt das in seinen
eigenen Metadaten. Was entsteht, ist: was die Dokumente sagen, wer es sagt, und wo sie
schweigen. Das Interessante ist meistens das Schweigen.

Vier Regeln tragen das meiste, und jede ist eine Verweigerung.

Eine Person steht im Register, weil ein Dokument sie unter einem benannten Feld
deklariert — nie, weil etwas nach einem Namen aussah. Eine Kante existiert, weil ein
Satz sie behauptet; zwei in einem Satz genannte Personen werden als genau das gezeigt
und nicht mehr, und jede Kante trägt ihren Satz. Eine Zeit, die die Quellen offen
lassen, bleibt unbestimmt und wird als Band gezeichnet: Ein Punkt, der gesetzt wurde,
damit das Diagramm fertig aussieht, ist hinterher nicht mehr von einem Punkt zu
unterscheiden, der wirklich dastand. Und eine Selbstauskunft bleibt eine Linie — eine
zweite kommt nur dazu, wenn eine andere Quelle die Anwesenheit behauptet und sich
selbst am selben Ort innerhalb des Toleranzfensters verortet; beide Sätze werden
gezeigt, damit Sie diesen Schluss beurteilen statt ihn zu übernehmen.

Das Register hat eine identifizierte Form, eine pseudonyme Form ohne Namen, Alias und
Zitat, und eine lokale Identitätskarte. Die pseudonyme Form darf reisen; die Karte ist
die eine Datei, die es nicht darf, und sie sagt das über sich selbst.

Die Abbildungen sind deterministisches SVG: Gleiche Eingabe, gleiche Bytes — nur so
kann ein Run-Ledger ein Bild hashen und es auch meinen. Jede trägt ihre Legende in
Worten und nicht nur als Strichart, damit nichts an der Farbe hängt.

In `examples/synthetic-case/` liegen zwölf kurze, frei erfundene Dokumente — jedes in
der ersten Zeile als erfunden gekennzeichnet — mit einem blauen VW Golf, einem
fraglichen Wochenende, einem fremdbestätigten Alibi, einer Person, die niemand
bestätigt, und zwei Widersprüchen. Jeder Fall-Chronik-Test läuft darauf, und die Demo
auch.

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

Übersicht und vier Arbeitsbereiche besitzen eigene, direkt aufrufbare Routen statt
Sprüngen innerhalb einer langen Seite: `/`, `/folders`, `/processes`, `/governance` und
`/connections`. Analysis, Routines und Artifacts waren einmal eigene Räume — damit
entschied die Tür, durch die man kam, darüber, was man sehen konnte. Sie sind jetzt drei
Untertabs von Processes & Workflows: `?tab=workflows`, `?tab=registry` und
`?tab=artifacts`. Die alten Routen führen weiterhin irgendwohin: `/document-center`,
`/analysis`, `/routines` und `/artifacts` leiten auf ihren Nachfolger um, und ein Link,
der einen einzelnen Vertrag nennt, landet im Register mit genau diesem Vertrag.

Verändert hat sich, was vorn steht, nicht die Räume. Usecase-Kacheln sind das
Primärobjekt, thematisch über Tags filterbar, und eine Routine ist schlicht ein Usecase
mit Zeitplan und dem abgeleiteten Tag `scheduled` — dieser Filter macht aus dem Bullauge
das Echolot und holt die letzten Routineläufe nach vorn. Die Einzelinstrumente, also die
sechzehn Jobverträge für sich, leben in einem nicht-thematischen Register, dessen Editor
der Maschinenraum ist. Folders ist das Zuhause der Ordner: welche überwacht werden, was
tatsächlich an Bord ist, und welche Usecases daran hängen. Die Übersicht selbst bleibt
bewusst karg — eine Überschrift, ein Satz und die Bereichskarten — und faltet
Grenz-Kacheln, Evidenzkette, Vertragsregister und Roadmap hinter eine alte Seekarte, die
sich per Klick oder Enter aufklappt. Nichts wird entfernt; die Dokumentation verschmutzt
nur nicht mehr die Oberfläche.

Governance zeigt die Autorität, mit der dieser Server gestartet wurde — Gates für
Dateiaktionen, externe Modelle und Netzexposition, freigegebene Roots, Budgetgrenze und
vertraglich erfasste Workflows. Gates werden dort gelesen, nicht erteilt: Ein
geschlossenes Gate verlangt weiterhin einen Neustart mit dem passenden Flag. Darunter
liegen die beiden Register aus dem nächsten Abschnitt. Artifacts öffnet ausgeführte oder
blockierte Ledger und prüft jeden erfassten Artefakthash. Connections ist eine reine
Statusseite und trennt konfigurierte Adapter, ausgeführte Providerläufe, Transfers und
Cloud-Nachweise sichtbar voneinander. Das Register enthält weiterhin alles, was es immer
enthielt: erklärbare Cleanup Rules, schreibgeschützten Mail-to-Case-Ingest, kontrollierte
E-Mail-Entwürfe, den quellengebundenen Contact Monitor, deterministische
Bundle-Vorbereitung, Datenschutz-Preflight, Evidence Analyst, wiederverwendbare
Prompt-Sammlungen und persistente Research Notebooks. Ein Modell kann dieselben
Einstellungen über `draft-save`, MCP oder die Loopback-Draft-API zur Browserprüfung
vorbereiten; Freigaben werden dabei immer zurückgesetzt.

### Regeln und Policies

Eine Regel ist ein einzelner Satz, den man sich merken kann — „Anhänge verlassen das
Haus nie ohne Bestätigung". Eine Policy ist ein Regelwerk, näher an einem kleinen Skill:
mehrere Sätze und, wo ein Workflow sie konsumieren kann, zusätzlich ein maschinenlesbarer
Körper. Beide liegen unter Governance auf den Untertabs Rules und Policies, und beide
tragen die Liste der Stellen, an die sie gebunden sind. Genau darum geht es: Eine Regel,
die an sechs Fahrten hängt, bleibt EIN Objekt — wer sie ändert, ändert alle sechs, und
die Regel selbst zeigt, welche sechs das sind. Denselben Satz in sechs Fahrten zu
kopieren ist der Weg, auf dem eine Regel still aufhört, eine Regel zu sein.

Das Register zeigt, was in der Regel gilt, und darunter, wo eine gespeicherte Fahrt
davon abweicht: eine Kette, die ihre Glieder überschreibt, Versandrechte oberhalb des
Standardprofils, ein Schritt, der weiter senden darf als seine Kette. Die Abweichung
bleibt bei der Fahrt, die sie gemacht hat, denn dort ändert man sie — und die Fahrt sagt
es in Worten, bevor Sie sie starten.

Eine Policy erteilt nichts. `cleanup_rules` ist der erste Workflow, der eine konsumiert,
und er füllt nur, was der Jobvertrag leer gelassen hat: Im Vertrag stehende Regeln
gewinnen weiterhin, und das Dossier nennt, welcher von beiden entschieden hat.
Freigegebene Roots, Datenschutzmodus, Aktionsmodus und die Freigaben je Lauf bleiben
das, was tatsächlich entscheidet.

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
