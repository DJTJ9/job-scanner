# Firecrawl pro Member — Deploy-Notiz

Member hinterlegen einen eigenen Firecrawl-Key und nutzen ihn als Playwright-Failover
für ihre Custom-Portale/Career-Pages, ohne das geteilte ThinkShark-Kontingent zu belasten.

## Laufzeit-Dependency: cryptography

`cryptography` (Fernet-Verschlüsselung der Member-Keys) ist eine Laufzeit-Dependency.
Bereits systemweit installiert (v49.0.0):

```
python3 -c "import cryptography, jobscanner.crypto; print('ok')"   # → ok
```

Kein `requirements*.txt`/`pyproject.toml` im Repo — läuft gegen System-`/usr/bin/python3`.
Auf einem neuen Host: `pip3 install --break-system-packages cryptography`.

## JOBSCANNER_FERNET_KEY (Secret) — in BEIDE Env-Files

Der Klartext-Firecrawl-Key wird nie in der DB gespeichert, nur Fernet-Ciphertext in
`users.firecrawl_key_enc`. Server-Key aus `JOBSCANNER_FERNET_KEY`.

Einmalig einen Key erzeugen:

```
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Denselben Wert als `JOBSCANNER_FERNET_KEY=<wert>` in beide Env-Files eintragen:

- `/etc/jobscanner/web.env` — Web-Service (Encrypt beim Speichern + Validate)
- `/root/projekte/telegram-bot-army/.env` — Discover-Cron (Decrypt beim täglichen Scan)

Team-`FIRECRAWL_API_KEY` liegt bereits im Discover-`.env`.

**Rotation macht bestehende verschlüsselte Keys unbrauchbar → einmal setzen, stabil halten.**

## Restart (beim Patch-Schnitt)

```
sudo systemctl restart jobscanner-web
```

Discover-Cron (`jobscanner-discover.timer`) zieht `.env` beim nächsten Lauf automatisch.
Live-Smoke: `GET /einstellungen?tab=firecrawl` → 200, Firecrawl-Tab sichtbar.
