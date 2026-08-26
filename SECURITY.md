# Sicherheit

PP verwaltet personenbezogene Beschäftigtendaten und ist deshalb für ein internes, selbst gehostetes Netz gedacht.

- Den Port `8780` nicht direkt ins öffentliche Internet veröffentlichen.
- Für externen Zugriff einen abgesicherten Reverse Proxy oder Tunnel mit HTTPS verwenden.
- `PP_COOKIE_SECURE=true` aktivieren, sobald PP ausschließlich über HTTPS erreichbar ist.
- `PP_ALLOWED_HOSTS` auf die tatsächlich verwendeten Hostnamen beschränken.
- `.env` und `data/` niemals committen oder öffentlich weitergeben.
- Bereichsleiterrechte werden serverseitig auf genau die zugewiesene Abteilung eingeschränkt.
- Passwörter werden mit Argon2id gehasht; Sitzungen verwenden zufällige Tokens und CSRF-Schutz.
- SMTP-Passwörter, Microsoft Client Secrets sowie OAuth Access-/Refresh-Tokens werden von der Admin-API nicht im Klartext zurückgegeben und ausschließlich im persistenten `data/`-Bereich gespeichert.
- Die Secrets sind damit vor Git-/Frontend-Leaks geschützt, aber nicht als Ersatz für verschlüsselte NAS-Datenträger oder sichere Dateiberechtigungen zu verstehen. Der komplette `data/`-Ordner ist als sensibel zu behandeln.
- Der Docker-Einstieg setzt eine restriktive Dateiumask (`077`); der NAS-Benutzer bzw. `PUID/PGID` sollte exklusiven Zugriff auf das PP-Datenverzeichnis haben.
- Bei Microsoft-365-OAuth muss die Callback-Adresse über HTTPS erreichbar und exakt als Redirect URI in Microsoft Entra registriert sein.
- Für produktive Nutzung regelmäßige, zugriffsgeschützte Backups des `data/`-Ordners erstellen und Wiederherstellung testen.
