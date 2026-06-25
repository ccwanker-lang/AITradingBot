#!/usr/bin/env python3
"""
Remote LSTM Trainer — offload training naar Windows desktop
===========================================================
Hoe het werkt:
  1. Ping Windows desktop (192.168.1.192)
  2. Check cooldown — train max 1× per N uur (default 24u)
  3. SCP: sync broncode Pi → desktop (geen .env, geen logs, geen venv)
  4. SSH: start training op desktop (cmd /c python bot.py --train)
  5. SCP: kopieer modellen terug (lstm_predictor.pt + crypto_ppo.zip)
  6. Bot herstart veilig als geen open posities

Vereisten Windows desktop (eenmalige setup):
  1. OpenSSH Server inschakelen:
       Settings → Apps → Optional Features → OpenSSH Server → Install
       Services → OpenSSH SSH Server → Startup: Automatic → Start
  2. SSH public key toevoegen:
       Pi:      cat ~/.ssh/id_rsa.pub   (kopieer deze regel)
       Windows: zet die regel in C:\\Users\\alexc\\.ssh\\authorized_keys
                (maak de .ssh map aan als die niet bestaat)
  3. Python + PyTorch installeren op desktop:
       https://pytorch.org/get-started/locally/
       pip install ccxt pandas numpy ta scikit-learn stable-baselines3
  4. .env aanmaken op desktop (C:\\Users\\alexc\\crypto_bot\\.env):
       SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT
       TIMEFRAME=1h
       CAPITAL=1000
       LIVE=false
       (API keys NIET nodig — training gebruikt Binance publieke OHLCV)

Config: tools/remote_trainer_config.json
Log:    logs/remote_trainer.log
State:  logs/remote_trainer_state.json
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_BASE               = Path(__file__).parent.parent
_LOGS               = _BASE / "logs"
_STATE_FILE         = _LOGS / "remote_trainer_state.json"
_LOG_FILE           = _LOGS / "remote_trainer.log"
_LOCK_FILE          = _LOGS / "remote_trainer.lock"
_CONFIG             = Path(__file__).parent / "remote_trainer_config.json"
_DAILY_SUCCESS_FILE = _LOGS / "last_remote_train_success.txt"  # Legacy — per-model files zijn nu leidend
_SUCCESS_FILE = {
    "1h":   _LOGS / "last_remote_train_success_1h.txt",
    "15m":  _LOGS / "last_remote_train_success_15m.txt",
    "both": _LOGS / "last_remote_train_success.txt",
}

# Model bestanden die terug naar Pi gekopieerd worden
_MODEL_FILES = ["lstm_predictor.pt", "crypto_ppo.zip", "lstm_1h.pt", "lstm_15m.pt"]

# Health-JSON's met edge-metriek (balanced_acc/edge). Staan in logs/ op de desktop
# (niet models/), dus apart gesynct. Bug 24-06-2026: ontbraken in de sync waardoor
# de Pi-tooling (check_report/vault/auto_optimizer) altijd verouderde val_acc zonder
# edge las. lstm_1h_health.json is de eerste in de lees-prioriteit van die tools.
_HEALTH_FILES = ["lstm_1h_health.json", "lstm_15m_health.json"]

_DEFAULT_CONFIG = {
    "desktop_ip":           "192.168.1.192",
    "desktop_user":         "alexc",
    "ssh_key":              "/home/pi/.ssh/id_rsa",
    "desktop_project_path": "C:/Users/alexc/crypto_bot",
    "python_cmd":           "python",
    "min_interval_hours":   24,
    "ssh_timeout_s":        7200,
    "enabled":              True,
    "only_lstm":            True,
    "notify_telegram":      True,
}


# ── Logging ─────────────────────────────────────────────────────────────────

def _log(msg: str, level: str = "INFO"):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {level:5s} | {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Config & State ───────────────────────────────────────────────────────────

def _load_config() -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if _CONFIG.exists():
        try:
            cfg.update(json.loads(_CONFIG.read_text()))
        except Exception as e:
            _log(f"Config leesfout: {e} — gebruik defaults", "WARN")
    return cfg


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        _log(f"State schrijffout: {e}", "WARN")


# ── Telegram ─────────────────────────────────────────────────────────────────

def _telegram(msg: str, cfg: dict):
    if not cfg.get("notify_telegram"):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(_BASE / ".env")
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


# ── Lock ─────────────────────────────────────────────────────────────────────

def _acquire_lock() -> bool:
    if _LOCK_FILE.exists():
        try:
            age = time.time() - _LOCK_FILE.stat().st_mtime
            if age < 7200:          # Lock ouder dan 2u → stale, verwijderen
                _log(f"Lock actief ({age/60:.0f}min oud) — training loopt al", "WARN")
                return False
            _log(f"Stale lock gevonden ({age/3600:.1f}u oud) — verwijderd", "WARN")
        except Exception:
            pass
    _LOCK_FILE.write_text(str(int(time.time())))
    return True


def _release_lock():
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── Daily rate-limiter ───────────────────────────────────────────────────────

def _today_already_trained(model: str = "both") -> bool:
    """True als vandaag al succesvol getraind is voor dit model."""
    today = datetime.now().strftime("%Y-%m-%d")
    f = _SUCCESS_FILE.get(model, _DAILY_SUCCESS_FILE)
    try:
        return f.read_text().strip() == today
    except Exception:
        return False


def _mark_daily_success(model: str = "both"):
    """Schrijf vandaag's datum naar success-file — ALLEEN na volledig succes."""
    today = datetime.now().strftime("%Y-%m-%d")
    f = _SUCCESS_FILE.get(model, _DAILY_SUCCESS_FILE)
    f.write_text(today)
    _log(f"Success geregistreerd: {today} (model={model})")


# ── Ping ─────────────────────────────────────────────────────────────────────

def _ping(ip: str) -> bool:
    """Controleer of desktop bereikbaar is via TCP poort 22 (SSH).
    ICMP ping werkt niet — Windows firewall blokkeert dat standaard."""
    import socket
    try:
        with socket.create_connection((ip, 22), timeout=5):
            return True
    except OSError:
        return False


def _send_wol(mac: str):
    """Stuur Wake-on-LAN magic packet naar desktop."""
    import socket
    mac_clean = mac.replace(":", "").replace("-", "").upper()
    if len(mac_clean) != 12:
        _log(f"Ongeldig MAC-adres: {mac} — WoL overgeslagen", "WARN")
        return
    magic = bytes.fromhex("FF" * 6 + mac_clean * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic, ("255.255.255.255", 9))
    _log(f"WoL magic packet verstuurd naar {mac}")


def _wait_for_online(ip: str, timeout_s: int = 180) -> bool:
    """Wacht tot desktop online is na WoL. Controleert elke 10 seconden."""
    deadline = time.time() + timeout_s
    attempt  = 0
    while time.time() < deadline:
        if _ping(ip):
            _log(f"Desktop online na {attempt * 10}s ✓")
            return True
        attempt += 1
        _log(f"Wachten op desktop... ({attempt * 10}s/{timeout_s}s)")
        time.sleep(10)
    return False


def _shutdown_desktop(cfg: dict):
    """Shutdown met klikbare popup — Annuleren-knop roept shutdown /a aan."""
    import base64
    _log("Desktop afsluiten na training...")

    # Stap 1: shutdown inplannen (60 seconden)
    rc, out = _run_ssh(
        cfg,
        'shutdown /s /t 60 /c "Monster Bot: LSTM training klaar"',
        timeout=15,
    )
    if rc != 0:
        _log(f"Shutdown commando mislukt (rc={rc}): {out[:80]}", "WARN")
        return
    _log("Shutdown ingepland over 60 seconden ✓")

    # Stap 2: klikbare PowerShell popup als Base64 (omzeilt quote-hel via SSH→cmd→PS)
    # OK-knop  → niets doen, shutdown gaat door
    # Annuleren → shutdown /a, shutdown geannuleerd
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$r=[System.Windows.Forms.MessageBox]::Show("
        "'Monster Bot: LSTM training klaar.`n`n"
        "PC sluit af in 60 seconden.`n`n"
        "Klik Annuleren om de shutdown te stoppen.',"
        "'Monster Bot',"
        "[System.Windows.Forms.MessageBoxButtons]::OKCancel,"
        "[System.Windows.Forms.MessageBoxIcon]::Information);"
        "if($r -eq 'Cancel'){Start-Process 'shutdown' '/a'}"
    )
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")

    # start /B koppelt de popup los van de SSH-sessie — verschijnt direct op desktop
    _run_ssh(
        cfg,
        f'cmd /c "start /B powershell -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {encoded}"',
        timeout=10,
    )
    _log("Popup getoond — klik Annuleren om shutdown te stoppen ✓")


# ── SSH helpers ──────────────────────────────────────────────────────────────

def _ssh_opts(cfg: dict) -> list[str]:
    return [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
        "-i", cfg["ssh_key"],
        f"{cfg['desktop_user']}@{cfg['desktop_ip']}",
    ]


def _run_ssh(cfg: dict, cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(
            _ssh_opts(cfg) + [cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -2, str(e)


# ── Bestand sync ─────────────────────────────────────────────────────────────

def _sync_to_desktop(cfg: dict) -> bool:
    """
    Kopieer broncode Pi → Windows desktop via SCP.
    Slaat over: .env, logs/, venv/, __pycache__, *.pyc, .git/, models/
    (models staan al op desktop of worden aangemaakt door training)
    """
    dest_path = cfg["desktop_project_path"].replace("\\", "/")
    host      = f"{cfg['desktop_user']}@{cfg['desktop_ip']}"
    scp_base  = ["scp", "-i", cfg["ssh_key"], "-o", "StrictHostKeyChecking=no"]

    # Eerst project-map aanmaken via SSH (zonder quotes in pad)
    _run_ssh(cfg, f'mkdir "{dest_path}" 2>NUL & echo ok', timeout=15)

    _log("SCP broncode naar desktop...")
    errors = []

    dirs_to_sync = [
        "strategies", "execution", "risk", "data",
        "agent", "monitoring", "backtesting", "analytics",
        "tools", "dashboard",
    ]
    root_files = [
        "bot.py", "config.py", "requirements.txt",
    ]

    # Geen aanhalingstekens rondom het Windows-pad in SCP destination —
    # Windows OpenSSH accepteert forward-slash paden zonder quotes.
    for item in root_files:
        src = str(_BASE / item)
        if not Path(src).exists():
            continue
        r = subprocess.run(
            scp_base + [src, f"{host}:{dest_path}/"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            errors.append(f"{item}: {r.stderr[:80]}")

    for d in dirs_to_sync:
        src = str(_BASE / d)
        if not Path(src).is_dir():
            continue
        r = subprocess.run(
            scp_base + ["-r", src, f"{host}:{dest_path}/"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            errors.append(f"{d}/: {r.stderr[:80]}")

    if errors:
        _log(f"SCP fouten ({len(errors)}): {errors[:3]}", "WARN")
        if len(errors) > len(dirs_to_sync) // 2:
            _log("Te veel SCP fouten — sync mislukt", "ERROR")
            return False

    _log(f"Broncode gesynchroniseerd naar {cfg['desktop_ip']}:{dest_path} ✓")
    return True


def _sync_models_back(cfg: dict) -> bool:
    """Kopieer getrainde modellen van desktop terug naar Pi."""
    dest_path  = cfg["desktop_project_path"].replace("\\", "/")
    models_dir = _BASE / "models"
    models_dir.mkdir(exist_ok=True)
    _dual      = cfg.get("dual_model_training", False)

    # Verplicht: lstm_predictor.pt + crypto_ppo.zip
    # Optioneel: lstm_1h.pt + lstm_15m.pt (alleen bij dual_model_training)
    required = {"lstm_predictor.pt", "crypto_ppo.zip"}
    success  = 0
    for model_file in _MODEL_FILES:
        remote = f"{cfg['desktop_user']}@{cfg['desktop_ip']}:{dest_path}/models/{model_file}"
        dest   = models_dir / model_file
        tmp    = models_dir / (model_file + ".tmp")
        # -O = legacy (rcp) protocol: Windows OpenSSH SFTP-backend kapt binaire
        # bestanden af op exact 200 KiB (bug 13-06-2026). Naar .tmp + verifiëren
        # vóór overschrijven, zodat een corrupte download nooit het live model raakt.
        r = subprocess.run(
            ["scp", "-O", "-i", cfg["ssh_key"], "-o", "StrictHostKeyChecking=no",
             remote, str(tmp)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            level = "WARN" if model_file in required else "INFO"
            note  = "ophalen mislukt" if model_file in required else "niet aanwezig op desktop (optioneel)"
            _log(f"  {model_file} {note}: {r.stderr[:80]}", level)
            continue

        # Integriteitscheck: .pt via torch.load, .zip via zipfile
        ok, why = _verify_model(tmp)
        if not ok:
            tmp.unlink(missing_ok=True)
            _log(f"  {model_file} CORRUPT na download ({why}) — live model NIET overschreven", "WARN")
            continue

        tmp.replace(dest)
        size = dest.stat().st_size // 1024
        _log(f"  {model_file} terug op Pi ({size} KB) ✓ geverifieerd")
        success += 1

    # ── Health-JSON's (edge-metriek) van desktop logs/ → Pi logs/ ──────────
    # Optioneel: tellen NIET mee voor de success-vlag (modellen zijn leidend).
    logs_dir = _BASE / "logs"
    logs_dir.mkdir(exist_ok=True)
    for health_file in _HEALTH_FILES:
        remote = f"{cfg['desktop_user']}@{cfg['desktop_ip']}:{dest_path}/logs/{health_file}"
        dest   = logs_dir / health_file
        tmp    = logs_dir / (health_file + ".tmp")
        r = subprocess.run(
            ["scp", "-O", "-i", cfg["ssh_key"], "-o", "StrictHostKeyChecking=no",
             remote, str(tmp)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            _log(f"  {health_file} niet opgehaald (optioneel): {r.stderr[:80]}", "INFO")
            continue
        ok, why = _verify_model(tmp)
        if not ok:
            tmp.unlink(missing_ok=True)
            _log(f"  {health_file} CORRUPT na download ({why}) — niet overschreven", "WARN")
            continue
        tmp.replace(dest)
        _log(f"  {health_file} terug op Pi ✓ (edge-metriek)")

    return success > 0


def _verify_model(path) -> tuple[bool, str]:
    """Controleer of een gedownload model geldig is (niet afgekapt/corrupt)."""
    # Downloads landen op een .tmp-pad; strip dat zodat de extensiecheck de
    # échte bestandssoort ziet (anders viel .zip.tmp/.json.tmp door naar torch.load).
    name = str(path)
    if name.endswith(".tmp"):
        name = name[:-4]
    try:
        if name.endswith(".zip"):
            import zipfile
            z = zipfile.ZipFile(path)
            if z.testzip() is not None:
                return False, "bad zip entry"
        elif name.endswith(".json"):
            import json as _json
            _json.loads(Path(path).read_text(encoding="utf-8"))
        else:  # .pt
            import torch
            torch.load(path, map_location="cpu", weights_only=False)
        return True, "ok"
    except Exception as e:
        return False, str(e)[:60]


# ── Eenmalige desktop bootstrap ─────────────────────────────────────────────

# Overige packages (zonder torch — die installeren we apart met CUDA-wheel)
_PIP_PACKAGES = (
    "pandas numpy ta ccxt scikit-learn "
    "stable-baselines3 python-dotenv rich gymnasium shimmy"
)

# PyTorch met CUDA-ondersteuning. PyPI geeft standaard de CPU-only build —
# die gebruikt de RTX-GPU NIET. De --index-url wheel bevat de CUDA-runtime.
# cu121 werkt op alle RTX 30/40-series (incl. 4080 Ti, Ada Lovelace).
# Aanpasbaar via config-key "torch_cuda_index".
_DEFAULT_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu121"

def _resolve_ip(cfg: dict) -> None:
    """Werk cfg['desktop_ip'] bij naar het huidige IP via het MAC-adres."""
    _mac = cfg.get("wol_mac", "")
    if _mac and _mac != "VUL_HIER_MAC_IN":
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from find_desktop import resolve_desktop_ip
            found = resolve_desktop_ip(_mac, hint=cfg.get("desktop_ip"), log=_log)
            if found:
                if found != cfg.get("desktop_ip"):
                    _log(f"Desktop-IP gewijzigd: {cfg.get('desktop_ip')} → {found} (via MAC)")
                cfg["desktop_ip"] = found
        except Exception as e:
            _log(f"MAC-discovery faalde ({e}) — gebruik IP {cfg.get('desktop_ip')}", "WARN")


def train_now(cfg: dict, model: str = "beast") -> bool:
    """Forceer NU een training (sync → train op desktop → modellen terug → bot herstart).
    Negeert de dagelijkse rate-limiter. Bedoeld voor een handmatige run.

    Gebruik:  venv/bin/python tools/remote_trainer.py --train-now beast
    """
    _resolve_ip(cfg)
    if not _ping(cfg["desktop_ip"]):
        _log(f"Desktop niet bereikbaar op {cfg['desktop_ip']} — staat hij aan?", "ERROR")
        return False

    gpu = _check_gpu(cfg)
    _log(f"Rekenkracht desktop: {gpu}")
    if gpu.startswith("CPU"):
        _log("⚠ GPU niet actief — draai eerst 'tools/remote_trainer.py --setup-gpu'", "WARN")

    if not _acquire_lock():
        return False
    try:
        _log(f"Forceer training (model={model}) — broncode synchroniseren...")
        if not _sync_to_desktop(cfg):
            _log("Sync naar desktop mislukt", "ERROR")
            return False

        project = cfg["desktop_project_path"].replace("\\", "/")
        py_cmd  = cfg["python_cmd"]
        ssh_cmd = (
            f'cmd /c "set PYTHONIOENCODING=utf-8 && '
            f'cd /d {project} && {py_cmd} tools/train_desktop.py --model {model}"'
        )
        _telegram(f"🖥️ <b>Handmatige GPU-training</b>\nModel: {model}\nGPU: {gpu}", cfg)
        _log(f"Training starten op desktop: {ssh_cmd}")
        rc, out = _run_ssh(cfg, ssh_cmd, timeout=int(cfg.get("ssh_timeout_s", 86400)))
        _log(f"Training output (laatste 500): {out[-500:]}")
        # Windows OpenSSH geeft soms een niet-nul exit-code (gezien: rc=9) bij het
        # SLUITEN van de sessie terwijl de training zélf netjes klaar is. Tolereer
        # dat als de output de succesmarkers toont, anders blijven modellen op de
        # desktop hangen (bug 23-06-2026 — handmatige sync nodig). Fallback: live-log.
        _SUCCESS_MARKERS = ("=== KLAAR ===", "val_acc_beast", "val_acc=")
        if rc != 0:
            _log_text = out
            if not any(m in _log_text for m in _SUCCESS_MARKERS):
                _log_text += "\n" + fetch_live_progress(cfg)
            if any(m in _log_text for m in _SUCCESS_MARKERS):
                _log(f"SSH-sessie sloot met rc={rc} maar training is geslaagd "
                     f"(succesmarker in log) — wordt als succes behandeld.", "WARN")
            else:
                _log(f"Training mislukt (rc={rc})", "ERROR")
                _telegram(f"❌ Handmatige training mislukt (rc={rc})\n<code>{out[-200:]}</code>", cfg)
                return False

        if _sync_models_back(cfg):
            _log("Modellen terug op Pi ✓")
            _telegram("✅ <b>Handmatige training klaar</b>\nModellen bijgewerkt op Pi.", cfg)
            _safe_restart_bot()
            return True
        _log("Training OK maar modellen terugkopiëren mislukt", "ERROR")
        return False
    finally:
        _release_lock()


def setup_gpu(cfg: dict) -> bool:
    """Eénmalige actie ná installatie van de NVIDIA-kaart: vervang de CPU-build
    van PyTorch door de CUDA-build en verifieer dat de GPU gezien wordt.

    Gebruik:  venv/bin/python tools/remote_trainer.py --setup-gpu
    """
    _resolve_ip(cfg)

    if not _ping(cfg["desktop_ip"]):
        _log(f"Desktop niet bereikbaar op {cfg['desktop_ip']} — staat hij aan?", "ERROR")
        return False

    py_cmd     = cfg["python_cmd"]
    cuda_index = cfg.get("torch_cuda_index", _DEFAULT_TORCH_CUDA_INDEX)

    _log("GPU-setup: CPU-PyTorch verwijderen...")
    _run_ssh(cfg, f'cmd /c "{py_cmd} -m pip uninstall -y torch torchvision torchaudio"', timeout=300)

    _log(f"GPU-setup: CUDA-PyTorch installeren (index={cuda_index})...")
    _telegram("⚙️ <b>GPU-setup</b>\nCUDA-PyTorch installeren op desktop... (~10-20 min)", cfg)
    rc, out = _run_ssh(
        cfg,
        f'cmd /c "{py_cmd} -m pip install torch torchvision torchaudio --index-url {cuda_index}"',
        timeout=1800,
    )
    if rc != 0:
        _log(f"GPU-setup: install mislukt (rc={rc}): {out[-300:]}", "ERROR")
        _telegram(f"❌ GPU-setup mislukt\n<code>{out[-200:]}</code>", cfg)
        return False

    gpu = _check_gpu(cfg)
    _log(f"GPU-setup klaar — torch ziet: {gpu}")
    ok = gpu.startswith("CUDA")
    _telegram(
        f"{'✅' if ok else '⚠️'} <b>GPU-setup klaar</b>\nPyTorch device: {gpu}\n"
        f"{'Training draait nu op de GPU.' if ok else 'GPU NIET gezien — check driver/CUDA.'}",
        cfg,
    )
    return ok


def _check_gpu(cfg: dict) -> str:
    """Vraag de desktop of PyTorch de CUDA-GPU ziet. Retourneert leesbare status."""
    py_cmd = cfg["python_cmd"]
    probe = (
        "import torch;"
        "print('CUDA' if torch.cuda.is_available() else 'CPU- only',"
        "torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
    )
    rc, out = _run_ssh(cfg, f'cmd /c "{py_cmd} -c \\"{probe}\\""', timeout=60)
    out = out.strip()
    if rc == 0 and out:
        return out.splitlines()[-1].strip()
    return f"onbekend (rc={rc})"


def _bootstrap_desktop(cfg: dict) -> bool:
    """
    Richt de Windows desktop eenmalig in:
      - Maakt project/models/logs mappen aan
      - Installeert alle Python dependencies via pip
      - Maakt een minimale .env aan (als die nog niet bestaat)
    Wordt automatisch uitgevoerd bij de eerste succesvolle SSH-verbinding.
    """
    project  = cfg["desktop_project_path"].replace("/", "\\")
    py_cmd   = cfg["python_cmd"]
    _log("Bootstrap: mappen aanmaken op desktop...")

    # Subdirectories aanmaken (if not exist — veilig om meerdere keren te draaien)
    for subdir in ["models", "logs"]:
        win_sub = f"{project}/{subdir}"
        rc, out = _run_ssh(cfg, f'mkdir "{win_sub}" 2>NUL & echo ok', timeout=15)
        if rc == 0:
            _log(f"  Map OK: {win_sub}")
        else:
            _log(f"  Map aanmaken mislukt ({subdir}): {out[:80]}", "WARN")

    # .env aanmaken als die er nog niet is
    env_path = f"{project}\\.env"
    rc, out  = _run_ssh(cfg, f'cmd /c "if not exist \\"{env_path}\\" echo bestaat_niet"', timeout=10)
    if "bestaat_niet" in out or rc != 0:
        _log("Bootstrap: .env aanmaken op desktop...")
        env_lines = [
            "SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT",
            "TIMEFRAME=1h",
            "CAPITAL=1000",
            "LIVE=false",
            "MULTI_ASSET=true",
            "MIN_CONFIDENCE=0.46",
        ]
        # Schrijf elke regel via echo (>> = append)
        first = True
        for line in env_lines:
            op      = ">" if first else ">>"
            rc, out = _run_ssh(cfg, f'cmd /c "echo {line} {op} \\"{env_path}\\""', timeout=10)
            first   = False
        _log("  .env aangemaakt ✓")
    else:
        _log("  .env bestaat al — niet overschreven")

    # Python packages installeren
    _log("Bootstrap: pip install dependencies (kan 5-15 min duren)...")
    _telegram("⚙️ <b>Desktop bootstrap</b>\nPython packages + CUDA-PyTorch installeren... (~5-15 min)", cfg)

    rc, out = _run_ssh(cfg, f'cmd /c "{py_cmd} -m pip install --upgrade pip"', timeout=120)

    # PyTorch met CUDA als aparte stap (grote download, eigen index-url)
    cuda_index = cfg.get("torch_cuda_index", _DEFAULT_TORCH_CUDA_INDEX)
    _log(f"Bootstrap: CUDA-PyTorch installeren (index={cuda_index})...")
    torch_cmd = (
        f'cmd /c "{py_cmd} -m pip install torch torchvision torchaudio '
        f'--index-url {cuda_index}"'
    )
    rc_t, out_t = _run_ssh(cfg, torch_cmd, timeout=1800)  # 30 min — CUDA-wheel is groot
    if rc_t != 0:
        _log(f"Bootstrap: CUDA-PyTorch install mislukt (rc={rc_t}): {out_t[-300:]}", "ERROR")
        _telegram(f"❌ CUDA-PyTorch install mislukt\n<code>{out_t[-200:]}</code>", cfg)
        return False

    # Overige packages
    pip_cmd = f'cmd /c "{py_cmd} -m pip install {_PIP_PACKAGES}"'
    rc, out = _run_ssh(cfg, pip_cmd, timeout=900)   # 15 min timeout

    if rc != 0:
        _log(f"Bootstrap: pip install mislukt (rc={rc}): {out[-300:]}", "ERROR")
        _telegram(f"❌ Desktop bootstrap pip mislukt\n<code>{out[-200:]}</code>", cfg)
        return False

    # Verifieer dat CUDA echt beschikbaar is op de GPU
    gpu = _check_gpu(cfg)
    _log(f"Bootstrap: pip install voltooid ✓ — {gpu}")
    _telegram(f"✅ <b>Desktop bootstrap klaar</b>\nAlle packages geïnstalleerd.\nGPU: {gpu}", cfg)
    return True


# ── Veilige bot herstart ─────────────────────────────────────────────────────

def _safe_restart_bot():
    """Herstart bot alleen als er geen open posities zijn."""
    try:
        state_data = json.loads((_LOGS / "state.json").read_text())
        open_pos   = state_data.get("positions", {})
        if not open_pos:
            _log("Geen open posities — bot herstarten voor nieuw model...")
            subprocess.run(["sudo", "systemctl", "restart", "cryptobot.service"],
                           timeout=30, check=True)
            _log("Bot herstart — nieuw LSTM model geladen ✓")
        else:
            syms = list(open_pos.keys())
            _log(f"Open posities ({syms}) — bot NIET herstart. Model geladen bij volgende herstart.")
    except Exception as e:
        _log(f"Bot herstart overgeslagen: {e}", "WARN")


# ── Live voortgang opvragen ──────────────────────────────────────────────────

def fetch_live_progress(cfg: dict) -> str:
    """
    Haalt de laatste regels op uit training_live.log op de desktop.
    Gebruik: venv/bin/python tools/remote_trainer.py --progress
    """
    project  = cfg["desktop_project_path"].replace("\\", "/")
    log_path = f"{project}/logs/training_live.log"

    # Windows: type commando + laatste N regels via meer/findstr
    rc, out = _run_ssh(
        cfg,
        f'cmd /c "type \\"{log_path}\\" 2>NUL"',
        timeout=15,
    )
    if rc != 0 or not out.strip():
        return "Geen live log beschikbaar (training nog niet gestart of al klaar)"

    lines = [l for l in out.strip().splitlines() if l.strip()]
    last  = lines[-30:]  # laatste 30 regels

    # Vind laatste epoch regel voor snelle samenvatting
    epoch_lines = [l for l in last if "epoch" in l.lower() or "val_acc" in l.lower() or "fold" in l.lower()]
    summary = epoch_lines[-1] if epoch_lines else last[-1] if last else "geen output"

    return f"Laatste activiteit: {summary}\n\n" + "\n".join(last)


# ── Hoofdlogica ──────────────────────────────────────────────────────────────

def main(model_override: str | None = None):
    cfg   = _load_config()
    state = _load_state()

    if model_override:
        cfg["train_model"]        = model_override
        cfg["dual_model_training"] = True

    active_model = cfg.get("train_model", "both")

    if not cfg.get("enabled", True):
        _log("Remote trainer uitgeschakeld (enabled=false) — exit")
        return

    # ── Stap 0: Desktop-IP dynamisch vinden via MAC (DHCP wisselt het IP) ─────
    _resolve_ip(cfg)

    # ── Stap 1: Rate-limiter — max 1 training per dag per model ───────────────
    if _today_already_trained(active_model):
        _log(f"Model '{active_model}' is vandaag al getraind. Cooldown actief.")
        return

    # ── Stap 2: Wake-on-LAN + bereikbaarheidcheck ────────────────────────────
    _wol_enabled = cfg.get("wol_enabled", False)
    _wol_mac     = cfg.get("wol_mac", "")
    _wol_wait    = int(cfg.get("wol_wait_s", 180))

    if not _ping(cfg["desktop_ip"]):
        if _wol_enabled and _wol_mac and _wol_mac != "VUL_HIER_MAC_IN":
            _log("Desktop offline — WoL magic packet versturen...")
            _telegram("🌙 <b>Wake-on-LAN</b>\nDesktop wakker maken voor training...", cfg)
            _send_wol(_wol_mac)
            _log(f"Wachten tot desktop online is (max {_wol_wait}s)...")
            if not _wait_for_online(cfg["desktop_ip"], _wol_wait):
                _log("Desktop niet online na WoL — training overgeslagen", "WARN")
                _telegram("⚠️ WoL verstuurd maar desktop niet bereikbaar — training overgeslagen", cfg)
                return
        else:
            # Geen WoL ingesteld — geruisloos afsluiten
            return

    _log(f"Desktop online ✓ — start training sessie ({datetime.now().strftime('%H:%M')})")

    # ── Stap 3: Vergrendelen (lock)
    if not _acquire_lock():
        return

    try:
        # ── Stap 4: SSH verbinding testen
        rc, out = _run_ssh(cfg, "echo ping", timeout=10)
        if rc != 0:
            _log(f"SSH verbinding mislukt (rc={rc}): {out} — check SSH key setup", "ERROR")
            return

        # GPU-status loggen (alleen na bootstrap; torch moet geïnstalleerd zijn)
        if state.get("setup_done"):
            _gpu = _check_gpu(cfg)
            _log(f"Rekenkracht desktop: {_gpu}")
            if _gpu.startswith("CPU"):
                _log("⚠ GPU niet actief — training draait op CPU (traag). "
                     "Check CUDA-PyTorch installatie op desktop.", "WARN")

        # ── Stap 5: Eerste keer bootstrap (eenmalig)
        if not state.get("setup_done"):
            _log("Eerste succesvolle verbinding — bootstrap desktop omgeving...")
            ok = _bootstrap_desktop(cfg)
            if ok:
                state["setup_done"] = True
                _save_state(state)
                _log("Bootstrap klaar — bij volgende ping start de training automatisch")
            else:
                _log("Bootstrap mislukt — controleer Python installatie op desktop", "ERROR")
            return  # Eerst keer alleen bootstrap, training bij volgende ping

        # ── Stap 6: Check of Python al draait op desktop
        rc, out = _run_ssh(cfg, 'tasklist /FI "IMAGENAME eq python.exe" /NH 2>NUL', timeout=15)
        if "python.exe" in out.lower():
            _log("Python draait al op desktop — training mogelijk bezig — skip")
            return

        _log("Start remote training sessie")
        state["last_training_start"] = time.time()
        state["status"]              = "syncing"
        _save_state(state)
        _profile    = cfg.get("train_profile", "desktop_heavy")
        _dual_model = cfg.get("dual_model_training", False)  # True = 1h + 15m apart
        _model_flag = cfg.get("train_model", "both")         # "1h", "15m", of "both"

        if _dual_model:
            _telegram(
                f"🖥️ <b>Remote training gestart</b>\n"
                f"Modus: Dual model (1h + 15m)\n"
                f"1h: Transformer 356 epochs · 365d · 4h features\n"
                f"15m: BiLSTM 356 epochs · 180d · horizon 12u\n"
                f"RL 300k timesteps (na 1h training)", cfg
            )
        else:
            _telegram(
                f"🖥️ <b>Remote training gestart</b>\n"
                f"Profiel: <code>{_profile}</code> — Desktop online\n"
                f"LSTM 150 epochs · 365d data · hidden=256 · bidirectioneel\n"
                f"RL 300k timesteps", cfg
            )

        # ── Stap 7: Sync broncode
        if not _sync_to_desktop(cfg):
            state["status"] = "sync_failed"
            _save_state(state)
            _telegram("❌ Remote training: sync naar desktop mislukt", cfg)
            return

        # ── Stap 8: Training uitvoeren op desktop
        project = cfg["desktop_project_path"].replace("\\", "/")
        py_cmd  = cfg["python_cmd"]

        if _dual_model:
            # Dual-model: gebruik train_desktop.py (1h + 15m apart)
            ssh_cmd = (
                f'cmd /c "set PYTHONIOENCODING=utf-8 && '
                f'cd /d {project} && {py_cmd} tools/train_desktop.py --model {_model_flag}"'
            )
        else:
            # Klassiek: bot.py --train met TRAIN_PROFILE
            _epochs  = int(cfg.get("train_epochs", 150))
            ssh_cmd = (
                f'cmd /c "set PYTHONIOENCODING=utf-8 && '
                f'set LSTM_TRAIN_EPOCHS={_epochs} && '
                f'set TRAIN_PROFILE={_profile} && '
                f'cd /d {project} && {py_cmd} bot.py --train"'
            )

        _log(f"SSH training commando: {ssh_cmd}")
        state["status"]              = "training"
        state["training_started_at"] = datetime.now().isoformat()
        _save_state(state)

        rc, out = _run_ssh(cfg, ssh_cmd, timeout=int(cfg["ssh_timeout_s"]))

        _log(f"Training output (laatste 500 tekens): {out[-500:]}")

        # Windows OpenSSH geeft soms een niet-nul exit-code (gezien: rc=9) bij het
        # SLUITEN van de sessie terwijl de training zélf netjes klaar is. Tolereer
        # dat als de output de succesmarkers toont, anders blijven modellen op de
        # desktop hangen én slaat de desktop niet af (bug 25-06-2026). Zelfde
        # tolerantie als train_now(); fallback op live-log als output afgekapt is.
        _SUCCESS_MARKERS = ("=== KLAAR ===", "val_acc_beast", "val_acc=")
        _training_ok = rc == 0
        if not _training_ok:
            _check_text = out
            if not any(m in _check_text for m in _SUCCESS_MARKERS):
                _check_text += "\n" + fetch_live_progress(cfg)
            if any(m in _check_text for m in _SUCCESS_MARKERS):
                _log(f"SSH-sessie sloot met rc={rc} maar training is geslaagd "
                     f"(succesmarker in log) — wordt als succes behandeld.", "WARN")
                _training_ok = True

        if _training_ok:
            _log("Training voltooid ✓")
            state["status"] = "syncing_back"
            _save_state(state)

            # ── Stap 9: Modellen terug naar Pi
            if _sync_models_back(cfg):
                state["status"]             = "done"
                state["last_training_end"]  = datetime.now().isoformat()
                state["last_success"]       = datetime.now().isoformat()
                _save_state(state)
                _mark_daily_success(active_model)  # Pas nu datum schrijven — training EN model sync geslaagd
                # Sla val_acc op zodat dashboard het live toont
                _m = __import__("re").search(r"val_acc=([\d.]+)%", out)
                if _m:
                    (_LOGS / "lstm_health.json").write_text(
                        __import__("json").dumps({"val_acc": float(_m.group(1))/100, "ts": datetime.now().isoformat()})
                    )
                _log("Remote training volledig afgerond ✓ Modellen op Pi bijgewerkt")
                _shutdown = cfg.get("shutdown_after_training", False)
                _telegram(
                    "✅ <b>Remote training voltooid</b>\n"
                    "LSTM modellen bijgewerkt op Pi.\n"
                    f"{'🔌 Desktop wordt afgesloten.' if _shutdown else ''}\n"
                    f"<i>{datetime.now().strftime('%H:%M')}</i>", cfg
                )
                # ── Stap 9: Desktop afsluiten (als ingesteld)
                if _shutdown:
                    _shutdown_desktop(cfg)
                # ── Stap 10: Veilige bot herstart
                _safe_restart_bot()
            else:
                state["status"] = "model_sync_failed"
                _save_state(state)
                _log("Training OK maar modellen terug kopiëren mislukt", "ERROR")
                _telegram("⚠️ Training klaar maar modellen terug kopiëren mislukt — handmatig controleren", cfg)
        else:
            _log(f"Training mislukt op desktop (rc={rc})", "ERROR")
            state["status"]     = "training_failed"
            state["last_error"] = out[-500:]
            _save_state(state)
            _telegram(f"❌ Remote training mislukt (rc={rc})\n<code>{out[-200:]}</code>", cfg)

    finally:
        _release_lock()


if __name__ == "__main__":
    import sys as _sys
    _args = _sys.argv[1:]
    if _args and _args[0] == "--progress":
        _cfg = _load_config()
        print(fetch_live_progress(_cfg))
    elif _args and _args[0] == "--setup-gpu":
        _cfg = _load_config()
        _ok = setup_gpu(_cfg)
        _sys.exit(0 if _ok else 1)
    elif _args and _args[0] == "--train-now":
        _cfg   = _load_config()
        _model = _args[1] if len(_args) > 1 else "beast"
        _ok    = train_now(_cfg, _model)
        _sys.exit(0 if _ok else 1)
    else:
        _model = None
        if "--model" in _args:
            idx = _args.index("--model")
            if idx + 1 < len(_args):
                _model = _args[idx + 1]
        main(model_override=_model)
