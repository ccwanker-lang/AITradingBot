"""
Dashboard server — FastAPI webserver voor de Monster Bot.
Start met: python dashboard/app.py
Open dan: http://localhost:8000
"""
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Monster Bot Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent.parent
LOG_DIR  = BASE_DIR / "logs"
STATE_FILE = LOG_DIR / "state.json"

# ── Statische bestanden ────────────────────────────────────────────
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

# ── HTML Dashboard ─────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_file = Path(__file__).parent / "templates" / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html niet gevonden</h1>")


# ── Bot state ──────────────────────────────────────────────────────
@app.get("/api/state")
async def get_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return JSONResponse(data)
        except Exception:
            pass
    return JSONResponse({
        "running": False,
        "positions": {},
        "portfolio": {"total_value": 1000, "pnl_pct": 0, "free_capital": 1000},
        "signals": [],
        "last_update": None,
    })


# ── Trades history ─────────────────────────────────────────────────
@app.get("/api/trades")
async def get_trades(symbol: Optional[str] = None, limit: int = 500):
    trade_file = LOG_DIR / "trades.json"
    if not trade_file.exists():
        return JSONResponse([])
    try:
        trades = json.loads(trade_file.read_text(encoding="utf-8"))
        if symbol:
            trades = [t for t in trades if t.get("symbol") == symbol]
        return JSONResponse(trades[-limit:])
    except Exception:
        return JSONResponse([])


# ── Equity curve ───────────────────────────────────────────────────
@app.get("/api/equity")
async def get_equity():
    perf_file = LOG_DIR / "performance.json"
    if not perf_file.exists():
        return JSONResponse([])
    try:
        data = json.loads(perf_file.read_text(encoding="utf-8"))
        return JSONResponse(data[-2000:])
    except Exception:
        return JSONResponse([])


# ── OHLCV proxy van Binance ────────────────────────────────────────
@app.get("/api/ohlcv")
async def get_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 500):
    try:
        binance_sym = symbol.replace("/", "")
        interval_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
        }
        interval = interval_map.get(timeframe, "1h")
        url = f"https://api.binance.com/api/v3/klines"
        params = {"symbol": binance_sym, "interval": interval, "limit": limit}
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        candles = []
        for c in resp.json():
            candles.append({
                "time":  c[0] // 1000,
                "open":  float(c[1]),
                "high":  float(c[2]),
                "low":   float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            })
        return JSONResponse(candles)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Order book proxy van Binance ───────────────────────────────────
@app.get("/api/orderbook")
async def get_orderbook(symbol: str = "BTC/USDT", limit: int = 20):
    try:
        binance_sym = symbol.replace("/", "")
        url = f"https://api.binance.com/api/v3/depth"
        resp = requests.get(url, params={"symbol": binance_sym, "limit": limit}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return JSONResponse({
            "bids": [[float(p), float(q)] for p, q in data["bids"]],
            "asks": [[float(p), float(q)] for p, q in data["asks"]],
        })
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Stats samenvatting ─────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats():
    trade_file = LOG_DIR / "trades.json"
    if not trade_file.exists():
        return JSONResponse({"total_trades": 0, "win_rate": 0, "total_pnl": 0})
    try:
        trades = json.loads(trade_file.read_text(encoding="utf-8"))
        sells = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
        if not sells:
            return JSONResponse({"total_trades": len(trades), "closed_trades": 0, "win_rate": 0})
        pnls = [t["pnl_pct"] for t in sells]
        wins = [p for p in pnls if p > 0]
        return JSONResponse({
            "total_trades": len(trades),
            "closed_trades": len(sells),
            "win_rate": len(wins) / len(pnls) if pnls else 0,
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            "best_trade": max(pnls) if pnls else 0,
            "worst_trade": min(pnls) if pnls else 0,
            "total_pnl": sum(pnls),
        })
    except Exception:
        return JSONResponse({"total_trades": 0, "win_rate": 0, "total_pnl": 0})


if __name__ == "__main__":
    import uvicorn
    print("Dashboard gestart op http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
