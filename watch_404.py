#!/usr/bin/env python3
"""
Daily 404 watcher for image paths.
Reads new access log lines since the last run, collects 404s for a given path prefix,
and sends a summary email.
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
from typing import Dict, Tuple

LOG_PATTERN = re.compile(
    r'(?P<remote>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) '
    r'(?P<proto>[^"]+)" (?P<status>\d{3}) \S+ "(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)

STATE_TEMPLATE = {"inode": None, "offset": 0}


def load_kv_config(path: str) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                cfg[key.strip().upper()] = value.strip()
    except FileNotFoundError:
        return {}
    return cfg


def derive_prefix_from_path(path: str) -> str:
    """Heuristic: strip common docroot folders to get a URL prefix."""
    if not path:
        return ""
    clean = path.rstrip("/")
    for marker in ("/httpdocs", "/htdocs", "/public", "/public_html"):
        if marker in clean:
            suffix = clean.split(marker, 1)[1]
            break
    else:
        suffix = "/" + os.path.basename(clean)
    if not suffix.startswith("/"):
        suffix = "/" + suffix
    return suffix or "/"


def parse_time(raw: str) -> dt.datetime:
    """Parse common log time format, return naive UTC datetime if no tz provided."""
    try:
        return dt.datetime.strptime(raw, "%d/%b/%Y:%H:%M:%S %z").astimezone(dt.timezone.utc)
    except ValueError:
        # Fallback: ignore tz
        try:
            return dt.datetime.strptime(raw, "%d/%b/%Y:%H:%M:%S")
        except ValueError:
            return dt.datetime.utcnow()


def load_state(path: str) -> Dict:
    if not os.path.exists(path):
        return STATE_TEMPLATE.copy()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return {**STATE_TEMPLATE, **data}
    except (json.JSONDecodeError, OSError):
        return STATE_TEMPLATE.copy()


def save_state(path: str, state: Dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def determine_start(log_path: str, state: Dict) -> Tuple[int, int]:
    """Return (offset, inode) to start reading from."""
    stat = os.stat(log_path)
    inode = stat.st_ino
    size = stat.st_size
    if state["inode"] == inode and 0 <= state["offset"] <= size:
        return state["offset"], inode
    return 0, inode


def scan_log(log_path: str, prefix: str, start_offset: int) -> Tuple[Dict, int]:
    hits: Dict[str, Dict] = {}
    offset = start_offset

    with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
        fh.seek(start_offset)
        for line in fh:
            offset = fh.tell()
            m = LOG_PATTERN.search(line)
            if not m:
                continue
            if m.group("status") != "404":
                continue
            path = m.group("path")
            if not path.startswith(prefix):
                continue
            ts = parse_time(m.group("time"))
            referer = m.group("referer") if m.group("referer") != "-" else ""
            entry = hits.setdefault(
                path,
                {"count": 0, "first": ts, "last": ts, "referrers": collections.Counter()},
            )
            entry["count"] += 1
            entry["first"] = min(entry["first"], ts)
            entry["last"] = max(entry["last"], ts)
            entry["referrers"][referer] += 1
    return hits, offset


def format_report(host: str, prefix: str, hits: Dict[str, Dict]) -> str:
    lines = []
    lines.append(f"404 report for {host}")
    lines.append(f"Watched prefix: {prefix}")
    lines.append("")
    for path in sorted(hits.keys()):
        entry = hits[path]
        lines.append(f"{path}")
        lines.append(f"  hits: {entry['count']}")
        lines.append(
            "  window: {0} to {1}".format(
                entry["first"].isoformat(), entry["last"].isoformat()
            )
        )
        for ref, count in entry["referrers"].most_common():
            label = ref if ref else "-"
            lines.append(f"  referrer[{count}]: {label}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def send_email(to_addr: str, subject: str, body: str, from_addr: str = "") -> bool:
    sender = from_addr or to_addr
    message = [
        f"From: {sender}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        "",
        body,
    ]
    payload = "\n".join(message)
    try:
        subprocess.run(["sendmail", "-t"], input=payload, text=True, check=True)
        return True
    except FileNotFoundError:
        print("sendmail not found; printing report instead:\n", file=sys.stderr)
        print(payload)
        return False
    except subprocess.CalledProcessError as exc:
        print(f"sendmail failed ({exc}); printing report instead:\n", file=sys.stderr)
        print(payload)
        return False


def parse_args() -> argparse.Namespace:
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--config", default="config", help="Config file with KEY=VALUE entries (PATH, SERVER, LOG, PREFIX, STATE, TO, FROM, SUBJECT)")
    config_ns, remaining = base.parse_known_args()
    cfg = load_kv_config(config_ns.config)

    def cfg_val(*keys):
        for key in keys:
            if key in cfg:
                return cfg[key]
        return None

    derived_prefix = cfg_val("PREFIX")
    if not derived_prefix:
        derived_prefix = derive_prefix_from_path(cfg_val("PATH") or "")

    parser = argparse.ArgumentParser(
        description="Collect 404s for a path prefix and send a daily summary email.",
        parents=[base],
    )
    parser.set_defaults(**vars(config_ns))
    parser.add_argument("--log", default=cfg_val("LOG"), required=cfg_val("LOG") is None, help="Path to access log")
    parser.add_argument(
        "--prefix",
        default=derived_prefix,
        required=not bool(derived_prefix),
        help="URL path prefix to watch (e.g. /static/img/)",
    )
    parser.add_argument(
        "--state",
        default=cfg_val("STATE") or ".404_state.json",
        help="Path to state file (stores inode/offset)",
    )
    parser.add_argument("--to", default=cfg_val("TO"), required=cfg_val("TO") is None, help="Recipient email address")
    parser.add_argument(
        "--from",
        dest="from_addr",
        default=cfg_val("FROM") or "",
        help="Sender email address (default: same as --to)",
    )
    parser.add_argument(
        "--host",
        default=cfg_val("SERVER") or cfg_val("HOST") or socket.gethostname(),
        help="Host label for the report",
    )
    parser.add_argument(
        "--subject",
        default=cfg_val("SUBJECT") or "",
        help="Email subject (default: 404 report for <host>)",
    )
    return parser.parse_args(remaining)


def main() -> int:
    args = parse_args()

    if not args.prefix.startswith("/"):
        print("--prefix must start with '/': got", args.prefix, file=sys.stderr)
        return 1
    if not os.path.exists(args.log):
        print("Log file not found:", args.log, file=sys.stderr)
        return 1

    state = load_state(args.state)
    start_offset, inode = determine_start(args.log, state)

    hits, new_offset = scan_log(args.log, args.prefix, start_offset)
    save_state(args.state, {"inode": inode, "offset": new_offset})

    if not hits:
        return 0

    subject = args.subject or f"404 report for {args.host}"
    body = format_report(args.host, args.prefix, hits)
    send_email(args.to, subject, body, args.from_addr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
