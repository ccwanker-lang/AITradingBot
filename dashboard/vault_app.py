"""
Vault-Tec Bunkerterminal — FastAPI micro-server op poort 8001.
Leest: logs/state.json, logs/heal_proposal.json, logs/bot_state.json, logs/bot_service.log
Start: python dashboard/vault_app.py
"""
import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Vault-Tec Terminal", docs_url=None, redoc_url=None)

BASE_DIR       = Path(__file__).parent.parent
LOG_DIR        = BASE_DIR / "logs"
HTML_FILE      = Path(__file__).parent / "vault.html"
STATE_FILE     = LOG_DIR / "state.json"
HEAL_FILE      = LOG_DIR / "heal_proposal.json"
BOT_STATE_FILE = LOG_DIR / "bot_state.json"
SERVICE_LOG    = LOG_DIR / "bot_service.log"
DIAG_FILE      = LOG_DIR / "vault_diagnostics.json"


def _read_json(path: Path, default=None):
    """Laad JSON; geeft default terug bij ontbrekend of corrupt bestand."""
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _tail_lines(path: Path, n: int = 200) -> list:
    """Lees de laatste n regels van een (groot) bestand zonder het volledig te laden."""
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf = b""
            pos = size
            block = 8192
            while pos > 0 and buf.count(b"\n") < n + 1:
                read = min(block, pos)
                pos -= read
                f.seek(pos)
                buf = f.read(read) + buf
            lines = buf.decode("utf-8", errors="replace").splitlines()
            return [l for l in lines[-n:] if l.strip()]
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
async def root():
    if HTML_FILE.exists():
        return HTMLResponse(HTML_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>vault.html niet gevonden</h1>", status_code=404)


@app.get("/api/vault_state")
async def vault_state():
    state    = _read_json(STATE_FILE)
    heal_raw = _read_json(HEAL_FILE)
    bot_raw  = _read_json(BOT_STATE_FILE)

    state["heal_proposal"] = {
        "status":         heal_raw.get("status"),
        "param":          heal_raw.get("param"),
        "proposed_value": heal_raw.get("proposed_value"),
        "reason":         heal_raw.get("reason"),
        "expires_at":     heal_raw.get("expires_at"),
        "wr":             heal_raw.get("wr"),
    }
    state["bot_state"] = {
        "circuit_breaker_until": bot_raw.get("circuit_breaker_until", 0.0),
        "daily_sl_count":        bot_raw.get("daily_sl_count", 0),
    }
    # Vault Diagnostics — per symbool status badge
    state["diagnostics"] = _read_json(DIAG_FILE, {})
    return JSONResponse(state)


@app.get("/api/logs")
async def get_logs(n: int = Query(default=200, le=500)):
    """Geeft de laatste n regels van bot_service.log terug als JSON."""
    lines = _tail_lines(SERVICE_LOG, n)
    return JSONResponse({"lines": lines, "file": SERVICE_LOG.name})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001,
                log_level="warning", access_log=False)
