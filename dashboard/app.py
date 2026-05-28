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

@app.get("/analytics", response_class=HTMLResponse)
async def analytics():
    html_file = Path(__file__).parent / "analytics.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>analytics.html niet gevonden</h1>")

@app.get("/api/trades")
async def get_trades():
    trades_file = LOG_DIR / "trades.json"
    if trades_file.exists():
        try:
            return JSONResponse(json.loads(trades_file.read_text(encoding="utf-8")))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse([])


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


# ── OHLCV proxy van Binance — gepagineerd voor volledige geschiedenis ─
@app.get("/api/ohlcv")
async def get_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 1000):
    try:
        binance_sym = symbol.replace("/", "")
        interval_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
        }
        interval = interval_map.get(timeframe, "1h")
        url = "https://api.binance.com/api/v3/klines"

        # Binance max = 1000 per request; pagineer voor grotere limieten
        all_raw = []
        remaining = min(limit, 5000)
        end_time = None

        while remaining > 0:
            fetch_n = min(remaining, 1000)
            params = {"symbol": binance_sym, "interval": interval, "limit": fetch_n}
            if end_time is not None:
                params["endTime"] = end_time
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_raw = batch + all_raw          # prepend zodat volgorde klopt
            remaining -= len(batch)
            end_time = batch[0][0] - 1         # volgende pagina eindigt vóór deze batch
            if len(batch) < fetch_n:
                break                          # geen oudere data meer

        candles = [
            {
                "time":   c[0] // 1000,
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            }
            for c in all_raw
        ]
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
        # Alleen finale exits tellen (sell/cover) — één telling per trade-entry.
        # partial_tp1/tp2 zijn dezelfde trade en tellen niet apart mee voor win rate.
        all_closed = [t for t in trades if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2") and "pnl_pct" in t]
        closed = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
        if not closed:
            return JSONResponse({"total_trades": len(trades), "closed_trades": 0, "win_rate": 0})
        pnls = [t["pnl_pct"] for t in closed]
        wins = [p for p in pnls if p > 0]
        all_pnls = [t["pnl_pct"] for t in all_closed]
        return JSONResponse({
            "total_trades": len(trades),
            "closed_trades": len(closed),
            "win_rate": len(wins) / len(pnls) if pnls else 0,
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0,
            "best_trade": max(all_pnls) if all_pnls else 0,
            "worst_trade": min(all_pnls) if all_pnls else 0,
            "total_pnl": sum(all_pnls),
        })
    except Exception:
        return JSONResponse({"total_trades": 0, "win_rate": 0, "total_pnl": 0})


# ── Stats per regime ──────────────────────────────────────────────────
@app.get("/api/regime_stats")
async def get_regime_stats():
    trade_file = LOG_DIR / "trades.json"
    if not trade_file.exists():
        return JSONResponse({})
    try:
        trades = json.loads(trade_file.read_text(encoding="utf-8"))
        closed = [
            t for t in trades
            if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2")
            and "pnl_pct" in t
        ]
        if not closed:
            return JSONResponse({})

        from collections import defaultdict
        by_regime: dict = defaultdict(list)
        by_type:   dict = defaultdict(list)

        for t in closed:
            regime = t.get("regime") or "onbekend"
            trade_type = "long" if t.get("direction", 1) == 1 else "short"
            by_regime[regime].append(t["pnl_pct"])
            by_type[trade_type].append(t["pnl_pct"])

        def stats_for(pnls: list) -> dict:
            wins   = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            wr     = len(wins) / len(pnls) if pnls else 0
            avg_w  = sum(wins)   / len(wins)   if wins   else 0
            avg_l  = sum(losses) / len(losses) if losses else 0
            exp    = wr * avg_w + (1 - wr) * avg_l
            return {
                "n":          len(pnls),
                "win_rate":   round(wr,  4),
                "avg_pnl":    round(sum(pnls) / len(pnls), 4),
                "expectancy": round(exp, 6),
                "avg_win":    round(avg_w, 4),
                "avg_loss":   round(avg_l, 4),
                "total_pnl":  round(sum(pnls), 4),
            }

        return JSONResponse({
            "by_regime": {r: stats_for(p) for r, p in by_regime.items()},
            "by_type":   {t: stats_for(p) for t, p in by_type.items()},
            "overall":   stats_for([t["pnl_pct"] for t in closed]),
        })
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Vault Diagnostics — per-symbool status + RSI zone log + Filter 1d stats ──
@app.get("/api/vault")
async def get_vault():
    diag_file = LOG_DIR / "vault_diagnostics.json"
    if diag_file.exists():
        try:
            return JSONResponse(json.loads(diag_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return JSONResponse({})


# ── Monte Carlo simulatie ──────────────────────────────────────────────
@app.get("/api/monte_carlo")
async def get_monte_carlo(n_simulations: int = 2000, n_trades: int = 100):
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from analytics.monte_carlo import MonteCarloSimulator
        mc = MonteCarloSimulator(str(LOG_DIR / "trades.json"))
        result = mc.run(n_simulations=n_simulations, n_trades=n_trades)
        if result is None:
            return JSONResponse({"error": "Onvoldoende trades (min 10 nodig)"})
        return JSONResponse(result.to_dict())
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    print("Dashboard gestart op http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
