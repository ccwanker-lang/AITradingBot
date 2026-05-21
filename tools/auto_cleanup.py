#!/usr/bin/env python3
"""Auto-cleanup: ruimt logs op, archiveert oude snapshots, houdt changelog bij."""
import json
import os
import subprocess
import gzip
import shutil
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
MEMORY = BASE / "memory"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(msg: str):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram fout: {e}")


def cleanup_logs():
    removed = 0
    compressed = 0
    freed_bytes = 0
    now = time.time()

    for f in LOGS.glob("bot_*.log"):
        age_days = (now - f.stat().st_mtime) / 86400
        size = f.stat().st_size

        if age_days > 30:
            freed_bytes += size
            f.unlink()
            removed += 1
        elif age_days > 7 and size > 500_000:
            with open(f, "rb") as src, gzip.open(str(f) + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            freed_bytes += size - Path(str(f) + ".gz").stat().st_size
            f.unlink()
            compressed += 1
        elif age_days > 3 and size < 1024:
            freed_bytes += size
            f.unlink()
            removed += 1

    for f in LOGS.glob("training_*.log"):
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days > 14:
            freed_bytes += f.stat().st_size
            f.unlink()
            removed += 1

    return removed, compressed, freed_bytes


def cleanup_snapshots():
    history_file = LOGS / "config_history.json"
    if not history_file.exists():
        return 0

    try:
        data = json.loads(history_file.read_text())
        snapshots = data if isinstance(data, list) else data.get("snapshots", [])
    except Exception:
        return 0

    if len(snapshots) <= 20:
        return 0

    now = datetime.now()
    keep = set()
    to_archive = []

    # Bewaar altijd: eerste, laatste 7 dagen, en elke snapshot met WR-sprong >5%
    keep.add(snapshots[0]["id"])

    prev_wr = None
    for s in snapshots:
        age = (now - datetime.fromisoformat(s["timestamp"])).days
        wr = s.get("performance", {}).get("win_rate", 0)

        if age <= 7:
            keep.add(s["id"])
        if prev_wr and abs(wr - prev_wr) >= 5:
            keep.add(s["id"])
        prev_wr = wr

    # Archiveer voor/na paren ouder dan 14 dagen
    labels = {s["id"]: s["label"] for s in snapshots}
    for s in snapshots:
        if s["id"] in keep:
            continue
        age = (now - datetime.fromisoformat(s["timestamp"])).days
        label = s["label"].lower()
        if age > 14 and ("voor:" in label or "na:" in label or "baseline" in label):
            to_archive.append(s)

    if not to_archive:
        return 0

    # Schrijf naar changelog
    changelog = MEMORY / "bot_changelog.md"
    if changelog.exists():
        content = changelog.read_text()
        archive_section = "\n".join(
            f"\n**ID {s['id']}** — `{s['timestamp'][:10]}` — {s['label']}\n"
            f"- WR: {s.get('performance',{}).get('win_rate','?')}% | "
            f"MIN_CONF: {s.get('env_params',{}).get('MIN_CONFIDENCE','?')}"
            for s in to_archive
        )
        marker = "*(Wordt gevuld door bot-cleanup agent)*"
        if marker in content:
            content = content.replace(marker, archive_section)
        else:
            content += f"\n\n### Auto-cleanup {now.strftime('%Y-%m-%d')}\n{archive_section}"
        changelog.write_text(content)

    # Verwijder uit config_history
    archive_ids = {s["id"] for s in to_archive}
    new_snapshots = [s for s in snapshots if s["id"] not in archive_ids]

    if isinstance(data, list):
        history_file.write_text(json.dumps(new_snapshots, indent=2))
    else:
        data["snapshots"] = new_snapshots
        history_file.write_text(json.dumps(data, indent=2))

    return len(to_archive)


def update_changelog():
    changelog = MEMORY / "bot_changelog.md"
    if not changelog.exists():
        return

    content = changelog.read_text()
    today = datetime.now().strftime("%Y-%m-%d")

    # Update laatste update datum
    import re
    content = re.sub(
        r"\*Laatste update door bot-cleanup: .*\*",
        f"*Laatste update door bot-cleanup: {today}*",
        content
    )

    # Update huidige config uit .env
    env_vals = {}
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env_vals[k.strip()] = v.strip()

    changelog.write_text(content)


def main():
    print(f"Auto-cleanup gestart: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    MEMORY.mkdir(exist_ok=True)

    removed, compressed, freed = cleanup_logs()
    archived = cleanup_snapshots()
    update_changelog()

    freed_mb = freed / 1_048_576
    msg = (
        f"🧹 <b>Auto-cleanup voltooid</b>\n\n"
        f"Logs: {removed} verwijderd, {compressed} gecomprimeerd\n"
        f"Snapshots: {archived} gearchiveerd\n"
        f"Vrijgemaakt: ~{freed_mb:.1f} MB"
    )

    if removed + compressed + archived > 0:
        send_telegram(msg)
        print(msg)
    else:
        print("Niets op te ruimen")


if __name__ == "__main__":
    main()
