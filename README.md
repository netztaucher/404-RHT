# 404 RHT

Leichter Daily-Watcher für fehlende Bilder. Liest Webserver-Access-Logs, sammelt 404er für Bildpfade und verschickt täglich eine HTML-Zusammenfassung mit Referrer-Gruppierung und Trefferzahlen. Notwehr gegen seltsame Fehler im Gambio-Shop.

## Schnellstart

Voraussetzungen: Python 3.8+, `sendmail` (oder kompatibles MTA) im `PATH`.

Beispiel:

```
python3 watch_404.py \
  --log /var/log/nginx/access.log \
  --prefix /static/img/ \
  --state /var/lib/404-rht/state.json \
  --to alerts@example.com \
  --from monitor@example.com \
  --host web01
```

Cron täglich 07:00 CET (Produktion kent: `/etc/cron.d/404-rht`):

```
0 7 * * * /usr/bin/python3 /opt/404-rht/watch_404.py --log /var/log/nginx/access.log --prefix /static/img/ --state /var/lib/404-rht/state.json --to alerts@example.com --from monitor@example.com --host web01 >> /var/log/404-rht.log 2>&1
```

## Config-Datei

`config` (KEY=VALUE) reduziert die CLI-Flags:

```
PATH=/var/www/vhosts/web125.kent.kundenserver42.de/httpdocs/gx4802/images
PREFIX=/
SERVER=kent.kundenserver42.de
LOG=/var/log/nginx/access.log
TO=alerts@example.com
FROM=monitor@example.com
STATE=/var/lib/404-rht/state.json
IMAGES_ONLY=true
IMAGE_EXT=png,jpg,jpeg,gif,webp,avif,ico,bmp,tiff   # Bild-Endungen
EXCLUDE_PREFIX=/public/theme/images,/images/icons/status
```

- `PATH`/`PREFIX` setzen den beobachteten URL-Pfad; Filesystem-Pfade werden heuristisch in URLs übersetzt (z. B. `/httpdocs` → `/gx4802/images`).
- `SERVER` steuert den Hostnamen im Report.
- `IMAGES_ONLY`/`IMAGE_EXT` begrenzen auf gewünschte Bild-Endungen.
- `EXCLUDE_PREFIX` (kommagetrennt) blendet bekannte Pfad-Präfixe aus.
- Alle übrigen Keys entsprechen den CLI-Flags; Flags überschreiben die Config. Script und `config` können gemeinsam liegen, Cron zeigt darauf.

## Funktionsweise

- Liest nur neue Logzeilen seit dem letzten Lauf (State: JSON mit inode/offset, logrotate-sicher).
- Findet 404-Responses; optional per Prefix und Bild-Endungen gefiltert; ignoriert definierte Prefixe.
- Aggregiert pro fehlender Datei: Trefferzahl, Zeitfenster, Referrer (mit Counts), Referrer-Linkliste sortiert nach Treffern.
- Sendet einen HTML-Report via `sendmail -t`; keine Funde → stiller Exit.

## Hinweise

- Getestet mit gängigen Nginx/Apache Combined Logs (`"$method $path HTTP/1.1" $status ... "referer"`).
- Ohne `sendmail` wird der Report auf stdout gedruckt (sichtbar im Cron-Log).
- `--prefix` sollte mit `/` beginnen, wenn genutzt.
