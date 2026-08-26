# NAS-Betrieb

PP ist für einen dauerhaften Betrieb auf einem NAS/Home-Server ausgelegt. Die Struktur orientiert sich am Betriebsmodell von RoyalDownloader: Anwendung im Container, persistenter Zustand außerhalb des Container-Layers.

## Docker Compose

```bash
cp .env.example .env
mkdir -p data
# PUID/PGID ggf. auf den NAS-Benutzer anpassen
docker compose up -d --build
curl --fail http://127.0.0.1:8780/api/health
```

Danach `http://<NAS-IP>:8780` öffnen. Beim ersten Start wird, sofern `PP_SETUP_TOKEN` leer ist, ein zufälliger Token unter `data/setup-token.txt` gespeichert und einmal in den Logs ausgegeben.

## Persistenz

Der komplette fachliche Zustand liegt in `./data` und wird nach `/app/data` gemountet. Dort befinden sich insbesondere:

- `personalplaner.sqlite3` – Stammdaten, Zuteilungen, Benutzer, Abmeldungen und Audit-Log
- `setup-token.txt` – nur für die initiale Einrichtung relevant

Container-Neubauten verändern diese Daten nicht.

## Rechte

Der Container läuft standardmäßig als `1000:1000`, mit read-only Root-Filesystem, ohne Linux-Capabilities und mit `no-new-privileges`.

Wenn der Container nicht startet:

```bash
sudo chown -R 1000:1000 data
```

Alternativ `PUID`/`PGID` in `.env` auf den NAS-Benutzer setzen.

## SMTP

Für automatische Abmeldungen müssen mindestens diese Werte gesetzt sein:

```dotenv
SMTP_HOST=smtp.example.de
SMTP_PORT=587
SMTP_USER=personalplanung@example.de
SMTP_PASSWORD=...
SMTP_FROM=personalplanung@example.de
SMTP_STARTTLS=true
```

Ohne SMTP wird eine Abmeldung trotzdem protokolliert und die Zuteilung mit dem gewünschten Enddatum versehen. Der Vorgang erhält den Status **Mail fehlgeschlagen** und kann nach Einrichtung des SMTP-Zugangs erneut versendet werden.

## Reverse Proxy / Tunnel

Für HTTPS beispielsweise:

```dotenv
PP_ALLOWED_HOSTS=personal.example.de
PP_COOKIE_SECURE=true
PP_BIND_ADDRESS=127.0.0.1
```

Der Reverse Proxy/Tunnel zeigt anschließend auf `http://127.0.0.1:8780`. Direkte öffentliche Freigaben des Ports sollten vermieden werden.

## Backup

Vor Updates reicht im ersten Schritt eine Sicherung von `.env` und `data/`. SQLite sollte für ein konsistentes Offline-Backup bei gestopptem Container kopiert werden.
