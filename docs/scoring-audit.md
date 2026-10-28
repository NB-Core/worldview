# Worldview Scoring-Audit

## Ergebnis und reproduzierbarer Vergleich

Die vorhandenen SQLite-Beobachtungen bleiben unverändert. Kein Refresh auf der
mitgelieferten Datenbank, kein Rebuild und keine Migration bestehender Werte.
`score_snapshots` ist eine additive Tabelle, die beim normalen Schema-Init entsteht.

Reproduktion im Repository: `python scripts/scoring_audit.py`.
Vollständige Ergebnisse: [score-comparison.json](score-comparison.json).
Letzter Datenstand: **13.05.2026**. Keine dieser Zahlen beschreibt den Oktober 2026.

| Modell auf identischer Datenbank | Valuation | Sentiment | Macro Risk | Worldview |
|---|---:|---:|---:|---:|
| Original v1 | 92,84 | 70,78 | 83,04 | 16,72 |
| Nur Richtungsfehler korrigiert | 92,84 | 70,78 | 63,73 | 22,51 |
| v2 am Datenbankdatum, mit Qualitätsfiltern | 97,13 | 70,78 | 63,73 | 20,79 |
| v2 heute | N/A | N/A | N/A | N/A |

Der isolierte Anstieg um 5,79 Punkte folgt vollständig aus korrigierten
Credit-Spread-Richtungen: niedrige Spreads wurden bisher als hoher Stress gewertet.
Die Differenz von −1,72 Punkten zwischen Richtungsfix und v2 entsteht durch das
Entfernen von Index/GDP-Proxy, relativer Marktbreite und Konzentration aus der
fundamentalen Bewertung. Keine Gewichte wurden für ein gewünschtes Ergebnis angepasst.
Der neue echte Market-Cap/GDP-Indikator hat noch keine Beobachtungen in dieser
Datenbank und trägt deshalb nichts bei. Heute sind die alten Reihen veraltet.

## Nachgewiesene Fehler

* Globale Polaritätsrichtung wurde unabhängig vom Block verwendet. Credit Spreads
  brauchen im Sentiment −1, im Macro Risk +1. `score_directions` überschreibt die
  Richtung pro Kennzahl und Block. Live- und historische Berechnung beachten dies.
* `CHF=X` ist USD/CHF, nicht CHF/USD: niedriger Kurs bedeutet stärkerer Franken.
  Daher im Sentiment direkte Richtung: niedriges USD/CHF = niedriger Sentiment-Score.
* Indexstand/BIP ist kein Marktwert/BIP. Die behauptete Gleichwertigkeit historischer
  Perzentile wurde entfernt; alte ID und Rezept bleiben kompatibel erhalten.
* Eine einzige Beobachtung wurde zu 50 umgedeutet. v2 verlangt mindestens 20
  vorangehende endliche Beobachtungen und schließt fehlende/stale Daten aus.
* Kursniveaus, Konzentrationsgewichte und fundamentale Multiples wurden unter
  „Valuation“ vermischt. v2 trennt diese Größen; Sektoren ohne Fundamentaldaten
  haben Valuation und Regime N/A statt einer scheinbaren Fundamentalbewertung.
* Dashboardtexte enthielten unbelegte Prognosen, Handlungsempfehlungen und eine
  falsche Value-Trap-Semantik. Jetzt beschreiben sie die mathematischen Definitionen.

Vollständige Zuordnung aller konfigurierten Kennzahlen (auch ungenutzter):
[indicator-directions.md](indicator-directions.md). Realzinsen, USD-Stärke,
Zinskurven, Wohnungsbau, Energie und Rezessionswahrscheinlichkeiten bleiben
bewusst einfache, teils regimeabhängige Modellannahmen. Eine hohe/stark steigende
Zinskurve ist beispielsweise nach einer Inversion nicht automatisch gesund.
Gold/Öl ist ein relatives Preisverhältnis, kein eindeutig identifizierter Angebotsschock.

## Datenqualität, Regime und API

Die Worldview-Formel und `penalize_greed` bleiben bestehen. Fehlt ein Block,
bleibt der Headline-Score N/A. Verfügbare Indikatoren werden innerhalb eines
Blocks nach ihren bisherigen Gewichten renormalisiert. Coverage und tatsächliche
Beiträge sind sichtbar; geringe Abdeckung und Einzelindikator-Blöcke warnen.

20 Vorbeobachtungen begrenzen lediglich die Rangauflösung auf höchstens fünf
Prozentpunkte. Das ist eine technische Mindestanforderung, **kein Nachweis eines
repräsentativen Marktzyklus**. Anpassbar per `min_history`. Operationales Ablaufalter:
7/21/75/200 Kalendertage für täglich/wöchentlich/monatlich/quartalsweise,
überschreibbar mit `max_age_days`. Diese Toleranzen sind keine behaupteten
Veröffentlichungskalender. Jede Kennzahl liefert Beobachtungsdatum, Alter,
Stichprobengröße und Warnung; Fetch-Fehler bleiben in den vorhandenen Run-Logs.

Die alte `quadrant`-Eigenschaft bleibt mit 50er-Grenze erhalten. Das zusätzliche
`field_details.regime` verwendet einschließlich 45–55 auf einer der beiden
Achsen TRANSITION. BUY/TRAP/BUBBLE sind beschreibende Legacy-Namen; keine
Handelsaufträge und kein Nachweis einer Value Trap oder Spekulationsblase.
Abstände zu 50 und zur Übergangszone sind als numerische Werte sichtbar.

`/api/snapshot.json` ergänzt `model_version`, `legacy_v1`, `quality`,
`field_details` und `changes`. Bestehende Schlüssel bleiben erhalten; veränderte
v2-Bewertung kann absichtlich null sein. Preis-/relative Niveaus und Konzentration
stehen unter den zusätzlichen Blöcken in `field_details`.
`legacy_v1` verwendet die ursprünglichen Felder, Polaritäten und Ein-Punkt-Regel.

Vergleiche nach 7/14/30 Tagen nutzen vorhandene v2-Snapshots, höchstens drei Tage
vor dem Zieltag; andernfalls N/A. Differenzen pro Block, vorheriges Regime und
`small_move` sind enthalten. `small_move` bedeutet maximal zwei Scorepunkte
Bewegung über die Blöcke, **keine statistische Signifikanz**. Diese Kennzeichnung
wird zusammen mit den exakten Änderungen gezeigt, nicht als neuer Scoreparameter.
Erste historische Vergleiche werden erst nach dem Sammeln echter Snapshots möglich.

`/api/history.json` und `/history` bleiben die Historienwege. Erfasste Snapshots
haben Vorrang; ohne solche Daten werden nur tägliche gehandelte Marktpreise auf
Beobachtungsdatum rekonstruiert. Makro-, abgeleitete und langsam veröffentlichte
Reihen ohne Veröffentlichungs-/Vintage-Nachweise sind in dieser strengen
Rekonstruktion ausgeschlossen. Deshalb kann der historische Gesamt-Score N/A sein.
`/api/history.json?legacy=true` liefert explizit **unverifizierte** Rückrechnungen
mit referenzdatierten, möglicherweise revidierten Reihen, niemals einen belastbaren
Point-in-time-Backtest. Keine Rückdatierung künstlicher Snapshots.

## Echte Market-Cap/GDP-Reihe und weitere Fundamentaldaten

Quelle bestätigt am 28.10.2026:
[FRED BOGZ1LM883164115Q](https://fred.stlouisfed.org/series/BOGZ1LM883164115Q),
Federal Reserve Financial Accounts: All Domestic Sectors; Public Corporate
Equities; Liability, Market Value Levels. Millionen USD, nicht saisonbereinigt,
quartalsweise. Die FRED-Seite führt Q4 1945 bis Q2 2026.
Nominales BIP: [FRED GDP](https://fred.stlouisfed.org/series/GDP), Milliarden USD,
saisonbereinigte Jahresrate. Formel: `MarketCap / 1000 / GDP * 100`.
Nur exakt gemeinsame Referenzperioden, keine tägliche Fortschreibung und kein
Index-Ersatz. Es handelt sich um inländische öffentliche Aktien, nicht um alle
privaten Unternehmen oder eine globale Aktienquote. Quartalsweise Perioden und
spätere Revisionen begrenzen historische Interpretation. FRED-Fetcher benötigt
weiterhin den vorhandenen kostenlosen API-Key; es erfolgt kein stiller Fremdabruf.

Nicht implementiert: belastbare historische ETF-KBV/ROE-, Forward-KGV-,
EV/EBITDA-, FCF-Yield-, Gewinnrevisions- und Kapitalrenditereihen. Ein aktuelles
Yahoo-Fundamental-Snapshot ohne historische Vergleichsbasis ist kein historisches
Perzentil. Es wurden weder künstliche Werte noch ein nicht belegtes kostenloses
Historienangebot angenommen. Finance, AI, Energy, Defense, Construction und
Defensive bleiben fundamental N/A. Die bisherigen Preise sind separat verfügbar.

Optionale nächste Schritte: lizenzierte oder archivierte konsistente Fundamental-
Zeitreihen, issuer-spezifische SEC-Finanzdaten mit Filing-Datum und Einheitenprüfung,
ETF-Holdings-Aggregation mit damaligen Gewichten, ALFRED-Vintages und tatsächliche
Release-Daten; Qualitätsgewichte nach Stichprobenspanne und Revisionen. Ein
Issuer-KBV ist noch kein ETF-KBV. Forward-Erwartungen und Revisionen erfordern
zusätzliche Datenquellen; dafür wird keine Scheingenauigkeit eingeführt.

## Prüfungen

* `pytest -q`: 145 bestanden, 1 übersprungen (FRED_API_KEY fehlt).
* `pytest -q -m 'not integration'`: 143 bestanden, 2 abgewählt (vor dem zusätzlichen 7-Tage-Regressionstest).
* `ruff check worldview tests scripts/scoring_audit.py`: bestanden.
* `mypy worldview`: bestanden, 29 Module.
* API-Tests prüfen HTML, Snapshot-JSON, Historie, Preise und 404-Verhalten auf
  temporären Datenbanken. Neue Tests sichern Richtungen, Grenzbereiche,
  Mindesthistorie, Alter, zukünftige Werte, Snapshot-Historie, Einheiten und Beiträge.
* Externe Warnungen: Starlette/httpx-Deprecation und yfinance/Pandas-Deprecation.
* In der Sandbox benötigt Starlettes threadbasierter Testclient Netzwerkfreigabe
  für seine interne Eventloop-Kommunikation; ohne diese kann er vor Requestbeginn hängen.

## Verbleibende Modellgrenzen

Historische Ränge hängen von Fenster, Trends und Quellenwechseln ab und sind
keine Renditewahrscheinlichkeiten. Überlappende Credit-Spreads und korrelierte
Volatilitätsindikatoren können Informationen mehrfach gewichten. Fundamentale
Multiples berücksichtigen Strukturwandel, Sektorzusammensetzung und nachhaltiges
Wachstum nur unvollständig. ERP verwendet eine vereinfachte Earnings-Yield-minus-
Treasury-Definition. Wiederholte niedrige/hohe Werte können extreme Ränge erzeugen.
Aktuelle Makrowerte sind teilweise revidiert; Beobachtungsdatum ist kein
Veröffentlichungsdatum. Erfasste Snapshots sichern künftig die tatsächlich
berechneten Ergebnisse; die alte Datenbank allein kann frühere Informationsstände
nicht beweisen. Der Nutzer trifft die Investmententscheidung.

## Übersicht je geänderter Datei

| Datei | Änderung |
|---|---|
| `.gitignore` | Lokale Umgebungen und generierte Caches ausschließen. |
| `config/fields.yaml` | v2: Fundamentaldaten von Preisniveau und Konzentration getrennt. |
| `config/fields_legacy.yaml` | Unveränderte ursprüngliche Felddefinitionen für v1. |
| `config/metrics.yaml` | Blockrichtungen, CHF-Korrektur, Legacy-Proxy-Kennzeichnung und echte Market-Cap/GDP-Quellen. |
| `docs/indicator-directions.md` | Audit-Ergebnis und reproduzierbare Nachweise. |
| `docs/score-comparison.json` | Audit-Ergebnis und reproduzierbare Nachweise. |
| `docs/scoring-audit.md` | Audit-Ergebnis und reproduzierbare Nachweise. |
| `scripts/scoring_audit.py` | Nur lesender reproduzierbarer Datenbankvergleich. |
| `tests/test_audit.py` | Neue fachliche Regressionstests. |
| `tests/test_db.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_fetchers.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_history.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_m4_fetchers.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_new_fetchers.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_scoring.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `tests/test_snapshot.py` | Zeitlich aktuelle Testdaten passend zur neu geprüften Staleness. |
| `tests/test_webapp.py` | Import-/Lint-Bereinigung; präzisere FK-Exception im DB-Test. |
| `worldview/analysis/composite.py` | Konfigurierbare Blockrichtungen, endliche Beiträge, Übergangsregime. |
| `worldview/analysis/history.py` | Blockrichtungen, Mindesthistorie, Ablauf von Forward-Fills, strenger Herkunftsfilter und erfasste Snapshots. |
| `worldview/analysis/legacy.py` | Explizite v1-Vergleichsberechnung. |
| `worldview/analysis/scoring.py` | Mindesthistorie, endliche Werte, zeitlicher Cutoff und Aktualitätsprüfung. |
| `worldview/analysis/transparency.py` | Beiträge, Gewichte, Coverage und Grenzabstände. |
| `worldview/config.py` | Kompatibles Laden und Validieren neuer Optionen. |
| `worldview/fetchers/_excel.py` | Bestehende Typ-/Lint-Probleme korrigiert; öffentliche Namen bleiben erhalten. |
| `worldview/fetchers/derived.py` | Falsche Buffett-Gleichsetzung entfernt; echte quartalsweise Marktkapitalisierung/BIP mit Einheitenprüfung. |
| `worldview/fetchers/fred.py` | Bestehende Typ-/Lint-Probleme korrigiert; öffentliche Namen bleiben erhalten. |
| `worldview/fetchers/ishares.py` | Bestehende Typ-/Lint-Probleme korrigiert; öffentliche Namen bleiben erhalten. |
| `worldview/fetchers/registry.py` | Bestehende Typ-/Lint-Probleme korrigiert; öffentliche Namen bleiben erhalten. |
| `worldview/fetchers/yfinance_fetcher.py` | Bestehende Typ-/Lint-Probleme korrigiert; öffentliche Namen bleiben erhalten. |
| `worldview/models.py` | Zusätzliche Konfigurationsfelder mit Defaults. |
| `worldview/snapshot.py` | Aktualitätsfilter und Persistenz tatsächlich berechneter v2-Scores. |
| `worldview/store/db.py` | Additive Snapshot-Persistenz und 7/14/30-Tage-Vergleiche. |
| `worldview/store/schema.sql` | Neue Tabelle, bestehende Tabellen und Daten unverändert. |
| `worldview/webapp/main.py` | Additive API-Metadaten, Qualitätsfilter, Legacy-Werte, historische Provenienz. |
| `worldview/webapp/templates/history.html` | Deskriptive Historiensemantik und deutliche Grenze unverifizierter Rekonstruktionen. |
| `worldview/webapp/templates/snapshot.html` | Deskriptive Texte, TRANSITION, Details für Beiträge, Coverage und Änderungen. |
