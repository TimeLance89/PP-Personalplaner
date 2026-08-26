# PP – Autonomie & Automation

PP ist so aufgebaut, dass der Administrator selbst festlegt, wie viel Routinearbeit das System übernehmen darf. Autonomie ist standardmäßig **aus**.

## Stufen

### 0 – Manuell

- keine zyklischen Automationsläufe
- Benutzer lösen alle Vorgänge selbst aus
- sinnvoll für Ersteinrichtung und Tests

### 1 – Assistent

PP prüft den Datenbestand selbstständig und erzeugt eine **Automation Inbox**, führt aber keine externen Aktionen aus.

Aktuell überwacht PP unter anderem:

- fehlgeschlagene Abmelde-Mails
- bevorstehende Abmeldungen
- aktive Zeitarbeiter ohne Zuteilung
- befristete Einsätze, die in Kürze enden

### 2 – Regelbetrieb

Zusätzlich zur Überwachung führt PP ausdrücklich freigegebene, administrative Regeln selbst aus.

Aktuell:

- fehlgeschlagene Abmelde-Mails nach konfigurierbarer Wartezeit automatisch erneut senden
- maximale Zahl der automatischen Versandversuche begrenzen
- jeden Automationslauf und jede automatische Versandaktion protokollieren

### 3 – Autopilot

Zusätzlich zum Regelbetrieb darf PP freigegebene technische Selbstpflege übernehmen.

Optional:

- abgelaufene Sitzungen automatisch entfernen
- Audit-Daten nach der konfigurierten Aufbewahrungszeit bereinigen

## Bewusste Grenze

PP automatisiert **administrative Ausführung**, nicht die Personalentscheidung selbst.

Das System entscheidet nicht eigenständig anhand von Leistung, Fehlzeiten, persönlichen Merkmalen oder ähnlichen Daten, dass ein Zeitarbeiter abgemeldet werden soll. Eine solche Entscheidung wird durch einen berechtigten Menschen bzw. eine zuvor ausdrücklich hinterlegte sachliche Vorgabe getroffen. Danach kann PP den freigegebenen Ablauf – Kommunikation, Fristen, Wiederholungen und Protokollierung – automatisch erledigen.

## Not-Aus

Unter `System → Autonomie & Regeln` steht ein zentraler **NOT-AUS** zur Verfügung. Sobald er aktiviert wird:

- werden keine automatischen Aktionen ausgeführt,
- bestehende Daten und Automation-Ereignisse bleiben erhalten,
- der Scheduler bleibt technisch verfügbar, führt aber keine Regeln aus.

Der Administrator kann die Autonomie anschließend bewusst wieder fortsetzen.

## NAS-Betrieb

Die Automation läuft direkt im PP-Container und benötigt keinen externen Cloud-Worker. Der Prüfintervall ist konfigurierbar. Nach einem Container-Neustart startet der Automationsdienst zusammen mit PP erneut und liest seine Regeln und Historie aus der persistenten SQLite-Datenbank im `data/`-Volume.

## Nachvollziehbarkeit

PP speichert:

- Automationsläufe
- erkannte Ereignisse und deren Status
- automatische Mail-Retry-Versuche
- relevante Aktionen zusätzlich im Audit-Log

Damit bleibt nachvollziehbar, was PP erkannt und was es tatsächlich selbst ausgeführt hat.
