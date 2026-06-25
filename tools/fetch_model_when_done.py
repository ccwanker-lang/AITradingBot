#!/usr/bin/env python3
"""
Wacht tot een LSTM training op de desktop klaar is en kopieert het model terug.
Detectie via twee methoden:
  1. Primair:   log bevat "KLAAR" of "val_acc_<model>="
  2. Secundair: model-bestand bestaat op desktop EN is recenter dan start van dit script

Gebruik:
  python tools/fetch_model_when_done.py --log training_dual_run1.log --model dual
  python tools/fetch_model_when_done.py --log training_15m_run3.log  --model 15m
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_BASE   = Path(__file__).parent.parent
_CONFIG = Path(__file__).parent / "remote_trainer_config.json"

# Model-naam → bestandsnaam op desktop
_MODEL_FILES = {
    "15m":  "models/lstm_15m.pt",
    "1h":   "models/lstm_1h.pt",
    "dual": "models/lstm_dual.pt",
    "both": "models/lstm_1h.pt",   # voor "both" kopieer beide
}
_HEALTH_FILES = {
    "15m":  "logs/lstm_15m_health.json",
    "1h":   "logs/lstm_1h_health.json",
    "dual": "logs/lstm_dual_health.json",
}


def _log(msg: str):
    print(f"{datetime.now().strftime('%H:%M:%S')} | {msg}", flush=True)
    try:
        with open(_BASE / "logs" / "fetch_model_monitor.log", "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {msg}\n")
    except Exception:
        pass


def _load_config() -> dict:
    return json.loads(_CONFIG.read_text())


def _telegram(msg: str, cfg: dict):
    try:
        from dotenv import load_dotenv; load_dotenv(_BASE / ".env")
    except ImportError:
        pass
    import os
    token   = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
    req  = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _ssh_run(cfg: dict, cmd: str, timeout: int = 20) -> tuple[int, str]:
    r = subprocess.run(
        ["ssh", "-i", cfg["ssh_key"], "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=10", f"{cfg['desktop_user']}@{cfg['desktop_ip']}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _get_log(cfg: dict, log_file: str) -> str:
    project = cfg["desktop_project_path"].replace("\\", "/")
    rc, out = _ssh_run(cfg, f'type "{project}\\logs\\{log_file}"', timeout=30)
    return out if rc == 0 else ""


def _model_exists_on_desktop(cfg: dict, model_rel: str) -> bool:
    project = cfg["desktop_project_path"].replace("\\", "/")
    rc, _   = _ssh_run(cfg, f'if exist "{project}\\{model_rel}" echo YES', timeout=15)
    return rc == 0 and "YES" in _


def _scp_from_desktop(cfg: dict, remote_rel: str, local_path: Path) -> bool:
    project = cfg["desktop_project_path"].replace("\\", "/")
    # -O = legacy SCP-protocol. De SFTP-modus van Windows OpenSSH kapt downloads
    # af op exact 200 KB → corrupt model (25-06-2026). _sync_models_back gebruikt
    # daarom ook al -O. Zonder dit laadt torch.load het bestand niet.
    r = subprocess.run(
        ["scp", "-O", "-i", cfg["ssh_key"], "-o", "StrictHostKeyChecking=no",
         f"{cfg['desktop_user']}@{cfg['desktop_ip']}:{project}/{remote_rel}",
         str(local_path)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        size = local_path.stat().st_size // 1024
        _log(f"  {local_path.name} terug op Pi ({size} KB)")
        return True
    _log(f"  SCP mislukt: {r.stderr[:100]}")
    return False


def _fetch_all(cfg: dict, model_key: str) -> bool:
    models_dir = _BASE / "models"
    models_dir.mkdir(exist_ok=True)
    ok = True

    files_to_copy = []
    if model_key == "both":
        files_to_copy = [("models/lstm_1h.pt",  models_dir / "lstm_1h.pt",
                          "logs/lstm_1h_health.json",  _BASE / "logs" / "lstm_1h_health.json"),
                         ("models/lstm_15m.pt", models_dir / "lstm_15m.pt",
                          "logs/lstm_15m_health.json", _BASE / "logs" / "lstm_15m_health.json")]
    else:
        model_rel  = _MODEL_FILES.get(model_key, f"models/lstm_{model_key}.pt")
        health_rel = _HEALTH_FILES.get(model_key, f"logs/lstm_{model_key}_health.json")
        files_to_copy = [(model_rel,  models_dir / Path(model_rel).name,
                          health_rel, _BASE / "logs" / Path(health_rel).name)]

    for model_rel, model_local, health_rel, health_local in files_to_copy:
        if not _scp_from_desktop(cfg, model_rel, model_local):
            ok = False
        _scp_from_desktop(cfg, health_rel, health_local)  # health is optioneel

    return ok


def _read_val_acc(cfg: dict, model_key: str) -> float:
    health_rel = _HEALTH_FILES.get(model_key, "")
    if not health_rel:
        return 0.0
    local = _BASE / "logs" / Path(health_rel).name
    try:
        return json.loads(local.read_text()).get("val_acc", 0.0)
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log",   default="training_dual_run1.log",
                        help="Naam van het trainingslogbestand op de desktop")
    parser.add_argument("--model", default="dual",
                        choices=["1h", "15m", "dual", "both"],
                        help="Welk model wordt verwacht")
    args = parser.parse_args()

    cfg       = _load_config()
    start_ts  = time.time()
    max_wait  = 6 * 3600    # 6 uur — royaal genoeg voor elke training
    interval  = 30          # poll elke 30 seconden

    _log(f"Monitor gestart | log={args.log} | model={args.model} | desktop={cfg['desktop_ip']}")

    while time.time() - start_ts < max_wait:
        log_text = _get_log(cfg, args.log)
        elapsed  = (time.time() - start_ts) / 60

        # Primaire detectie: "KLAAR" in log
        done_via_log = "KLAAR" in log_text or f"val_acc_{args.model}=" in log_text

        # Secundaire detectie: model-bestand bestaat op desktop
        model_rel     = _MODEL_FILES.get(args.model, f"models/lstm_{args.model}.pt")
        done_via_file = _model_exists_on_desktop(cfg, model_rel)

        if done_via_log or done_via_file:
            source = "log" if done_via_log else "bestand"
            _log(f"Training klaar gedetecteerd via {source} na {elapsed:.0f} min!")

            ok = _fetch_all(cfg, args.model)

            val_acc = _read_val_acc(cfg, args.model)
            status  = "OK" if val_acc >= 0.50 else ("~ OK" if val_acc >= 0.44 else "ZWAK")

            if ok:
                msg = (f"<b>LSTM {args.model.upper()} training klaar</b>\n"
                       f"val_acc: {val_acc:.1%}  [{status}]\n"
                       f"Model terug op Pi na {elapsed:.0f} min\n"
                       f"<i>Inbouwen Fase 4a op 23 juli 2026</i>")
                _telegram(msg, cfg)
                _log(f"Klaar. val_acc={val_acc:.1%}  model={model_rel}")
            else:
                _telegram(f"<b>LSTM {args.model.upper()} klaar maar SCP mislukt</b>\n"
                           "Handmatig ophalen nodig.", cfg)
                _log("Model ophalen mislukt")
            return

        # Voortgangsupdate
        last_lines = [l for l in log_text.strip().splitlines() if l.strip()]
        last = last_lines[-1][-90:] if last_lines else "wachten op output..."
        _log(f"Nog bezig ({elapsed:.0f}min) — {last}")
        time.sleep(interval)

    _log(f"Timeout na {max_wait/3600:.0f}u — controleer desktop handmatig")
    _telegram(f"Monitor timeout na {max_wait/3600:.0f}u — handmatig controleren", cfg)


if __name__ == "__main__":
    main()
