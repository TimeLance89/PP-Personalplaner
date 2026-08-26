# PP – Personalplaner

**PP** ist eine selbst gehostete interne Webanwendung zur Verwaltung und operativen Steuerung von Zeitarbeitspersonal über mehrere Abteilungen hinweg.

## Ziel

Der Administrator verwaltet Abteilungen, Zeitarbeitsfirmen, Personal, Zuteilungen und Bereichsleiter-Zugänge. Jeder Bereichsleiter sieht serverseitig ausschließlich die eigene Abteilung. Nicht mehr benötigtes Personal kann mit Datum, Grund und Ersatzwunsch abgemeldet werden; PP erstellt daraus automatisch eine vollständige E-Mail an die zuständige Zeitarbeitsfirma und protokolliert Versand und Historie.

PP soll dabei möglichst wenig Verwaltungsarbeit beim Benutzer lassen. Routinevorgänge können – wenn der Administrator dies freigibt – autonom überwacht, vorbereitet und ausgeführt werden. Personalentscheidungen selbst bleiben bewusst beim Menschen.

## Bereits umgesetzt

- Rollenmodell **Administrator / Bereichsleiter**
- harte Abteilungsgrenze für Bereichsleiter
- Abteilungen und Zeitarbeitsfirmen
- Zeitarbeiter-Stammdaten und Zuteilungen
- unzugeteiltes Personal in der Admin-Sicht
- frei definierbare Zusatzfelder für Personal und Abteilungen
- **Abwesenheiten und Krankentage durch Bereichsleiter erfassbar**
- Krankheit, Urlaub, unentschuldigte und sonstige Abwesenheiten als getrennte Arten
- ganztägige sowie halbtägige Abwesenheiten
- Arbeitstage Montag–Freitag statt bloßer Kalendertage in der Auswertung
- serverseitige Prüfung, dass der komplette Abwesenheitszeitraum zur Zuteilung des Bereichsleiters gehört
- Monatsauswertung pro Abteilung und als Gesamtbetrieb
- automatische Vormonats-Snapshots unabhängig vom Autonomiegrad
- CSV-Export der Monatsberichte
- Reports nach Mitarbeiter, Zeitarbeitsfirma, Bereich, Abwesenheits- und Krankentagen
- konfigurierbare Abmeldegründe
- Abmeldeworkflow mit Wirksamkeitsdatum, Erläuterung und Ersatzwunsch
- globale Admin-Regeln für Standarddatum, Pflichtbegründung und Ersatzwunsch
- frei bearbeitbare Betreff- und Nachrichtenvorlage für Abmeldungen
- E-Mail-Vorschau vor der endgültigen Abmeldung
- Versand über **SMTP oder ein verbundenes Microsoft-365-/Office-Konto**
- Microsoft Graph OAuth mit delegierten Berechtigungen `Mail.Send` und `User.Read`
- Standard-CC/BCC, Reply-To und zusätzlicher Mail-Footer
- Testmail direkt aus der Admin-Oberfläche
- sichtbarer Mailstatus und erneuter Versand bei Fehlern
- Firmen-/Standort- und Ansprechpartnerdaten in der Admin-Oberfläche
- **Autonomie-Modi: Manuell, Assistent, Regelbetrieb und Autopilot**
- automatischer Retry fehlgeschlagener Abmelde-Mails
- automatische Erkennung von Fristen, unzugeteiltem Personal und auslaufenden Einsätzen
- **PP Work Inbox** mit Trennung zwischen „Du entscheidest“, „PP kümmert sich“ und „Beobachten“
- automatische Vorbereitung von Entscheidungen vor dem Ende einer befristeten Zuteilung
- direkte Verlängerung eines Einsatzes aus dem vorbereiteten Entscheidungsvorgang
- automatische Neuplanung des nächsten Prüfpunktes nach einer Verlängerung
- tägliche, benutzerspezifische Briefings für Administratoren und Bereichsleiter
- optionale Briefing-E-Mail pro Benutzer; In-App-Briefing funktioniert immer
- serverseitige Abteilungsbegrenzung auch für Inbox und Briefings
- automatisches Deduplizieren erledigter oder bereits durch eine Abmeldung entschiedener Vorgänge
- Not-Aus für alle autonomen Aktionen
- Audit-Log für administrative und personalrelevante Aktionen
- Admin-Funktion zum Beenden anderer aktiver Sitzungen
- konfigurierbare Audit-Aufbewahrung mit manueller und optional automatischer Bereinigung
- Argon2id-Passworthashing, serverseitige Sitzungen, CSRF-Schutz und Login-Rate-Limit
- responsive Warehouse-/Fashion-Tech-Oberfläche für Desktop, Tablet und Smartphone
- SQLite-Persistenz im NAS-Datenvolume
- gehärteter Docker-Container mit Healthcheck und restriktiver Dateiumask
- GitHub Actions für Python-Tests, JavaScript-Syntaxprüfung und Docker-Build

## Fachliches Modell

```text
Zeitarbeitsfirma
      │
      └── Zeitarbeiter ── Zuteilung ── Abteilung ── Bereichsleiter
                             │
                             ├── Abwesenheit
                             │     ├── Art
                             │     ├── Von / Bis
                             │     ├── ganzer / halber Tag
                             │     └── Monatsbericht
                             │
                             ├── Abmeldung
                             │     ├── Wirksamkeitsdatum
                             │     ├── Grund
                             │     ├── Ersatz ja/nein
                             │     └── E-Mail + Versandstatus
                             │
                             └── Workflow Center
                                   ├── geplanter Prüfpunkt
                                   ├── vorbereitete Entscheidung
                                   ├── PP Work Inbox
                                   └── Tagesbriefing
```

Eine Person wird bei einer Abmeldung nicht gelöscht. Die bestehende Zuteilung erhält ein Enddatum und der Vorgang bleibt nachvollziehbar.

## Abwesenheiten & Krankentage

Bereichsleiter können unter **Abwesenheiten** ausschließlich für Personal ihrer eigenen Abteilung Einträge erfassen. Der Zeitraum muss vollständig innerhalb einer passenden Zuteilung liegen. PP verhindert überlappende Einträge für dieselbe Person.

Standardmäßig stehen folgende Arten zur Verfügung:

- Krankheit
- Urlaub
- Unentschuldigt
- Arzttermin / sonstige Abwesenheit

Ein Eintrag kann ganztägig, vormittags oder nachmittags sein. Für Berichte zählt PP nur Montag bis Freitag; halbe Tage werden mit `0,5` gezählt. Wochenenden erhöhen die Krankentage nicht.

Bei Krankheit soll bewusst **keine Diagnose** dokumentiert werden. Eine sachliche Notiz ist optional, wird aber nicht in den Monatsbericht übernommen.

## Monatsberichte

Unter **Berichte** können Bereichsleiter ihre eigene Abteilung und Administratoren wahlweise einzelne Abteilungen oder den Gesamtbetrieb auswerten.

Ein Monatsbericht enthält unter anderem:

- Anzahl der Abwesenheitseinträge
- betroffene Mitarbeiter
- gesamte Abwesenheitstage
- Krankentage
- Aufteilung nach Abwesenheitsart
- Auswertung je Mitarbeiter
- Zeitarbeitsfirma und Abteilung

Nach Beginn eines neuen Monats erzeugt PP automatisch einen Snapshot des Vormonats – einmal für jede aktive Abteilung und zusätzlich für den Gesamtbetrieb. Diese Berichtserzeugung läuft auch im manuellen Autonomie-Modus, weil sie zur Dokumentation gehört. Bei nachträglichen Korrekturen kann ein Monatsbericht erneut abgeschlossen werden. Zusätzlich steht ein CSV-Export bereit.

## Autonomie-Modell

Unter **System → Autonomie & Regeln** kann der Administrator festlegen, wie selbstständig PP arbeiten darf:

1. **Manuell** – keine Hintergrundüberwachung; alle Vorgänge werden bewusst durch Benutzer ausgelöst.
2. **Assistent** – PP überwacht und bereitet vor, führt aber keine externen Aktionen selbst aus.
3. **Regelbetrieb** – ausdrücklich freigegebene Verwaltungsaktionen werden selbstständig ausgeführt, z. B. Retry einer fehlgeschlagenen Abmelde-Mail.
4. **Autopilot** – zusätzlich darf PP freigegebene technische Selbstpflege durchführen.

Der **Not-Aus** stoppt sämtliche autonomen Aktionen sofort.

PP trifft keine autonome Entscheidung darüber, welcher Mensch abgemeldet werden soll. Das System darf die Entscheidung vorbereiten und nach einer menschlichen Entscheidung die administrative Folgearbeit übernehmen.

## PP Work Inbox

Der Control Tower zeigt eine kompakte Arbeits-Inbox mit drei Zuständen:

- **Du entscheidest** – z. B. ein befristeter Einsatz läuft aus und muss verlängert oder beendet werden.
- **PP kümmert sich** – ein freigegebener Routinevorgang wird bereits automatisch bearbeitet.
- **Beobachten** – PP überwacht einen Termin oder Status, ohne dass aktuell eine Entscheidung erforderlich ist.

Befristete Zuteilungen können automatisch mehrere Tage vor dem Enddatum vorbereitet werden. Wird der Einsatz verlängert, aktualisiert PP das Enddatum und plant den nächsten Prüfpunkt neu. Existiert bereits eine wirksame Abmeldung, wird ein redundanter Verlängerungsentscheid automatisch geschlossen.

## Tagesbriefing

PP erzeugt auf Wunsch jeden Morgen ein Briefing pro aktivem Benutzer. Das Briefing ist rollen- und abteilungsbezogen und enthält unter anderem:

- aktuell eingesetztes Personal
- offene Entscheidungen
- Vorgänge, die PP gerade selbst bearbeitet
- kommende Abmeldungen
- fehlgeschlagene Kommunikation
- für Administratoren zusätzlich unzugeteiltes Personal

Die Uhrzeit, der Vorschauzeitraum und die automatische Vorbereitung auslaufender Einsätze sind in der Admin-Oberfläche konfigurierbar. Für jeden Benutzer kann separat eine E-Mail-Adresse hinterlegt und der E-Mail-Versand aktiviert werden. Automatische Briefing-Mails werden nur im **Regelbetrieb** oder **Autopilot** versendet; in PP selbst steht das Briefing unabhängig davon bereit.

## Schnellstart mit Docker

```bash
cp .env.example .env
mkdir -p data
docker compose up -d --build
```

Anschließend `http://<NAS-IP>:8780` öffnen. Details: [docs/NAS.md](docs/NAS.md).

## Ersteinrichtung

Ist noch kein Benutzer vorhanden, zeigt PP die Ersteinrichtung. Ohne explizites `PP_SETUP_TOKEN` erzeugt PP beim Start einen sicheren Token unter:

```text
data/setup-token.txt
```

Mit diesem Token wird der erste Administrator angelegt. Danach ist die Setup-Route gesperrt.

## Admin-Verwaltung

Unter **Verwaltung** stehen getrennte Bereiche zur Verfügung:

- **Unternehmen** – Firma, Standort, Adresse und zentrale Kontaktdaten
- **Autonomie & Regeln** – Autonomiegrad, Retry-Regeln, Fristen, Briefing und vorbereitete Entscheidungen
- **E-Mail & Microsoft 365** – Versandweg, SMTP, Microsoft OAuth, CC/BCC, Reply-To und Testmail
- **Abmeldeprozess** – globale Vorgaben und Mailvorlagen
- **Abteilungen** – Organisationsstruktur
- **Zeitarbeitsfirmen** – Kontakte der Personaldienstleister
- **Bereichsleiter** – Benutzer und Abteilungszuordnung
- **Zusatzfelder** – eigene Stammdatenfelder
- **Abmeldegründe** – auswählbare Gründe
- **Sicherheit & Daten** – Sitzungen und Audit-Aufbewahrung

## Microsoft 365 / Office

PP kann Nachrichten über das Microsoft-Konto versenden, das ein Administrator in der Oberfläche verbindet. Dafür wird in Microsoft Entra eine App-Registrierung mit einem **Web Redirect URI** benötigt. PP zeigt die exakt einzutragende Redirect URI in der Admin-Oberfläche an.

Benötigte delegierte Microsoft-Graph-Berechtigungen:

- `Mail.Send`
- `User.Read`

Zusätzlich wird `offline_access` angefordert, damit PP das Zugriffstoken für spätere automatische Mails erneuern kann. Nach erfolgreicher Verbindung zeigt PP Name und E-Mail-Adresse des verbundenen Kontos an. Die Abmeldung wird über Microsoft Graph als dieses Konto gesendet.

Für den OAuth-Callback sollte PP über eine abgesicherte HTTPS-Adresse erreichbar sein. Bei externer Erreichbarkeit muss der Host außerdem in `PP_ALLOWED_HOSTS` eingetragen und `PP_COOKIE_SECURE=true` gesetzt werden.

## SMTP

Alternativ kann PP weiterhin klassisch über SMTP versenden. SMTP-Server, Port, Benutzer, Passwort und Absender können vollständig in der Admin-Oberfläche hinterlegt werden; `.env`-Werte dienen weiterhin als Start-/Fallbackwerte.

## Persistenz und Geheimnisse

Personaldaten, Abwesenheitsdaten, Monatsberichte, Workflow-Daten und Systemkonfiguration liegen ausschließlich im persistenten `data/`-Verzeichnis. Dazu gehören auch sensible Werte wie SMTP-Passwort, Microsoft Client Secret und OAuth-Tokens. Diese Werte werden nicht in Git gespeichert und von der Admin-API nicht im Klartext zurückgegeben.

Der Container startet mit einer restriktiven Dateiumask (`077`). Der `data/`-Ordner ist trotzdem wie eine Datenbank mit Zugangsdaten zu behandeln: Zugriffsrechte begrenzen und regelmäßig sichern.

## Datenschutz

PP enthält personenbezogene Daten. Abwesenheits- und insbesondere Krankheitsdaten sind besonders schützenswert. Es sollten keine Diagnosen oder unnötigen medizinischen Details gespeichert werden. PP sollte nur intern bzw. hinter einer abgesicherten HTTPS-Zugangsschicht betrieben werden. Es sollten nur Datenfelder angelegt werden, die für die Personaldisposition tatsächlich erforderlich sind. Details: [SECURITY.md](SECURITY.md).
