# 404 RHT

Lightweight daily watcher for missing images under a specific path. Parses webserver access logs, records 404s for that path, and sends a single daily summary email listing missing files and their referrers.

## Quick start

Prereqs: Python 3.8+, `sendmail` (or compatible MTA) available on `PATH`.

Example:

```
python3 watch_404.py \
  --log /var/log/nginx/access.log \
  --prefix /static/img/ \
  --state /var/lib/404-rht/state.json \
  --to alerts@example.com \
  --from monitor@example.com \
  --host web01
```

Add a cron entry to send once per day, e.g. 07:00:

```
0 7 * * * /usr/bin/python3 /opt/404-rht/watch_404.py --log /var/log/nginx/access.log --prefix /static/img/ --state /var/lib/404-rht/state.json --to alerts@example.com --from monitor@example.com --host web01 >> /var/log/404-rht.log 2>&1
```

In Produktion (kent) läuft der Cron täglich um 07:00 CET aus `/etc/cron.d/404-rht`.

## Config file support

You can provide a simple `config` file (KEY=VALUE) to avoid long CLI flags:

```
PATH=/var/www/vhosts/web125.kent.kundenserver42.de/httpdocs/gx4802/images
SERVER=kunt.kundenserver42.de
LOG=/var/log/nginx/access.log
TO=alerts@example.com
FROM=monitor@example.com
STATE=/var/lib/404-rht/state.json
IMAGES_ONLY=true
IMAGE_EXT=png,jpg,jpeg,gif,webp,avif,ico,bmp,tiff   # Steuerung der erlaubten Bild-Endungen
EXCLUDE_PREFIX=/public/theme/images,/images/icons/status
```

- `PATH` (or `PREFIX`) is used as the URL path prefix; if it looks like a filesystem path, the script heuristically derives a URL prefix (e.g. strips `/httpdocs` → `/gx4802/images`).
- `SERVER` sets the host label in reports.
- `IMAGES_ONLY`/`IMAGE_EXT` beschränken den Report auf bestimmte Bild-Endungen.
- `EXCLUDE_PREFIX` (kommagetrennt) filtert bekannte, zu ignorierende Pfad-Präfixe.
- Other keys map directly to the flags of the same name. CLI flags always override config entries.
- Place the script wherever you want (`DIR`), keep `config` alongside it, and point Cron to that location.

## How it works

- Reads only new lines since the last run (offset stored in `--state` JSON file with inode tracking to survive logrotate).
- Detects 404 responses; optionally restricts to a prefix and/or image extensions.
- Aggregates per missing path: total hits, first/last seen timestamps, and referrers with counts.
- Sends an HTML report via `sendmail -t` if any misses occurred; exits quietly otherwise.

## Notes

- Tested against common Nginx/Apache combined log formats (`"$method $path HTTP/1.1" $status ... "referer"`).
- If `sendmail` is unavailable, the script prints the email body to stdout so Cron logs still show the report.
- Adjust `--prefix` to match the public URL path of your image directory (leading slash required).
