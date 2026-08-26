# PP – Personalplaner

**PP** ist eine selbst gehostete interne Webanwendung zur Verwaltung von Zeitarbeitspersonal über mehrere Abteilungen hinweg.

## Ziel

Der Administrator verwaltet Abteilungen, Zeitarbeitsfirmen, Personal, Zuteilungen und Bereichsleiter-Zugänge. Jeder Bereichsleiter sieht serverseitig ausschließlich die eigene Abteilung. Nicht mehr benötigtes Personal kann mit Datum, Grund und Ersatzwunsch abgemeldet werden; PP erstellt daraus automatisch eine vollständige E-Mail an die zuständige Zeitarbeitsfirma und protokolliert Versand und Historie.

## Bereits umgesetzt

- Rollenmodell **Administrator / Bereichsleiter**
- harte Abteilungsgrenze für Bereichsleiter
- Abteilungen und Zeitarbeitsfirmen
- Zeitarbeiter-Stammdaten und Zuteilungen
- unzugeteiltes Personal in der Admin-Sicht
- frei definierbare Zusatzfelder für Personal und Abteilungen
- konfigurierbare Abmeldegründe
- Abmeldeworkflow mit Wirksamkeitsdatum, Erläuterung und Ersatzwunsch
- E-Mail-Vorschau vor der endgültigen Abmeldung
- automatischer SMTP-Versand an die hinterlegte Zeitarbeitsfirma
- sichtbarer Mailstatus und erneuter Versand bei Fehlern
- Audit-Log für administrative und personalrelevante Aktionen
- Argon2id-Passworthashing, serverseitige Sitzungen, CSRF-Schutz und Login-Rate-Limit
- responsive Weboberfläche für Desktop, Tablet und Smartphone
- SQLite-Persistenz im NAS-Datenvolume
- gehärteter Docker-Container mit Healthcheck
- GitHub Actions für Tests und Docker-Build

## Fachliches Modell

```text
Zeitarbeitsfirma
      │
      └── Zeitarbeiter ── Zuteilung ── Abteilung ── Bereichsleiter
                             │
                             └── Abmeldung
                                   ├── Wirksamkeitsdatum
                                   ├── Grund
                                   ├── Ersatz ja/nein
                                   └── E-Mail + Versandstatus
```

Eine Person wird bei einer Abmeldung nicht gelöscht. Die bestehende Zuteilung erhält ein Enddatum und der Vorgang bleibt nachvollziehbar.

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

## SMTP / automatische Abmeldung

Die Mail enthält standardmäßig:

- Name und optionale Kennnummer des Zeitarbeiters
- Abteilung
- Wirksamkeitsdatum
- Abmeldegrund und Freitext
- Ersatz erforderlich: ja/nein
- optionale Anforderungen an den Ersatz
- Name des auslösenden Bereichsleiters

Die Zugangsdaten des Mailservers gehören ausschließlich in `.env`, niemals in Git.

## Datenschutz

PP enthält personenbezogene Daten. Es sollte nur intern bzw. hinter einer abgesicherten HTTPS-Zugangsschicht betrieben werden. Es sollten nur Datenfelder angelegt werden, die für die Personaldisposition tatsächlich erforderlich sind. Details: [SECURITY.md](SECURITY.md).
