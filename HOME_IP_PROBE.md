# Home-IP-Gate-Test — Raspberry Pi

**Zweck:** Beweisen, dass die private Home-Leitung (über den Always-On-Pi) StepStone +
Indeed lädt, an denen die Hetzner-Datacenter-IP scheitert. Gate vor Weg A: erst wenn
dieser Test grün ist, lohnt der Bau der autossh-Reverse-Tunnel-Infra.

## Stufe 0 — Sichtprüfung im Home-Browser (vor dem Skript)

Öffne diese URLs im Browser auf einem Gerät in deinem Heimnetz (dieselbe Leitung wie
der Pi). Laden sie ohne 403 / „Just a moment" / Verbindungsabbruch?

- Indeed (Suche): https://de.indeed.com/jobs?q=softwareentwickler&l=Berlin
- StepStone (Suche): https://www.stepstone.de/jobs/softwareentwickler/in-berlin
- StepStone (Detail): eine echte Stellen-Detail-URL von stepstone.de

Laden alle → weiter zum Skript. Blockt schon der Browser → Home-IP löst das Gate nicht,
Weg A ist tot bevor er beginnt.

> `TARGET_URLS` oben in `home_ip_probe.py` bei Bedarf auf aktuelle/echte URLs anpassen
> (v. a. die Detail-URL — sie ist der eigentliche HTTP2-Block-Fall).

## Pi-Setup (einmalig)

```bash
# Raspberry Pi OS (64-bit empfohlen), Python 3 vorinstalliert.
sudo apt update && sudo apt install -y python3-pip
pip3 install playwright
python3 -m playwright install chromium
python3 -m playwright install-deps   # Chromium-Systembibliotheken
```

Nur `home_ip_probe.py` auf den Pi kopieren (scp/git-checkout) — keine weitere
job-scanner-Env nötig.

## Ausführen

```bash
python3 home_ip_probe.py; echo "exit=$?"
```

Ausgabe: eine Zeile pro URL (`PASS`/`FAIL`, Portal, Status, ggf. Fehler) + Gate-Zeile.

**Exit-Code:**
- `0` → **Gate PASS**: Indeed UND StepStone laden über die Home-IP. Weg A bauen
  (autossh-Reverse-Tunnel + microsocks → nächstes Roadmap-Item).
- `1` → **Gate FAIL**: mindestens ein Portal blockt weiterhin. Weg A liefert keinen
  Vorteil — Alternative prüfen.

## Nicht Teil dieses Tests

autossh-Tunnel, SOCKS5-Proxy, `browser.py --proxy-server`, Firecrawl-Failover,
systemd-Dauerbetrieb — alles nachgelagert, erst nach grünem Gate.
