# Sicherheit

PP verwaltet personenbezogene Beschäftigtendaten und ist deshalb für ein internes, selbst gehostetes Netz gedacht.

- Den Port `8780` nicht direkt ins öffentliche Internet veröffentlichen.
- Für externen Zugriff einen abgesicherten Reverse Proxy oder Tunnel mit HTTPS verwenden.
- `PP_COOKIE_SECURE=true` aktivieren, sobald PP ausschließlich über HTTPS erreichbar ist.
- `PP_ALLOWED_HOSTS` auf die tatsächlich verwendeten Hostnamen beschränken.
- `.env` und `data/` niemals committen oder öffentlich weitergeben.
- Bereichsleiterrechte werden serverseitig auf genau die zugewiesene Abteilung eingeschränkt.
- Passwörter werden mit Argon2id gehasht; Sitzungen verwenden zufällige Tokens und CSRF-Schutz.
- Für produktive Nutzung regelmäßige Backups des `data/`-Ordners erstellen.
