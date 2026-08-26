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
- globale Admin-Regeln für Standarddatum, Pflichtbegründung und Ersatzwunsch
- frei bearbeitbare Betreff- und Nachrichtenvorlage für Abmeldungen
- E-Mail-Vorschau vor der endgültigen Abmeldung
- Versand über **SMTP oder ein verbundenes Microsoft-365-/Office-Konto**
- Microsoft Graph OAuth mit delegierten Berechtigungen `Mail.Send` und `User.Read`
- Standard-CC/BCC, Reply-To und zusätzlicher Mail-Footer
- Testmail direkt aus der Admin-Oberfläche
- sichtbarer Mailstatus und erneuter Versand bei Fehlern
- Firmen-/Standort- und Ansprechpartnerdaten in der Admin-Oberfläche
- Audit-Log für administrative und personalrelevante Aktionen
- Admin-Funktion zum Beenden anderer aktiver Sitzungen
- konfigurierbare Audit-Aufbewahrung mit manueller Bereinigung
- Argon2id-Passworthashing, serverseitige Sitzungen, CSRF-Schutz und Login-Rate-Limit
- responsive Weboberfläche für Desktop, Tablet und Smartphone
- SQLite-Persistenz im NAS-Datenvolume
- gehärteter Docker-Container mit Healthcheck und restriktiver Dateiumask
- GitHub Actions für Python-Tests, JavaScript-Syntaxprüfung und Docker-Build

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

## Admin-Verwaltung

Unter **Verwaltung** stehen getrennte Bereiche zur Verfügung:

- **Unternehmen** – Firma, Standort, Adresse und zentrale Kontaktdaten
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

Personaldaten und Systemkonfiguration liegen ausschließlich im persistenten `data/`-Verzeichnis. Dazu gehören auch sensible Werte wie SMTP-Passwort, Microsoft Client Secret und OAuth-Tokens. Diese Werte werden nicht in Git gespeichert und von der Admin-API nicht im Klartext zurückgegeben.

Der Container startet mit einer restriktiven Dateiumask (`077`). Der `data/`-Ordner ist trotzdem wie eine Datenbank mit Zugangsdaten zu behandeln: Zugriffsrechte begrenzen und regelmäßig sichern.

## Datenschutz

PP enthält personenbezogene Daten. Es sollte nur intern bzw. hinter einer abgesicherten HTTPS-Zugangsschicht betrieben werden. Es sollten nur Datenfelder angelegt werden, die für die Personaldisposition tatsächlich erforderlich sind. Details: [SECURITY.md](SECURITY.md).
