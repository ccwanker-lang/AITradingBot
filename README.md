# Monster Crypto Bot

Een zelf-lerende crypto trading bot gebouwd in Python voor de Raspberry Pi.
Combineert **12 professionele trading strategieën** met **LSTM + Reinforcement Learning (PPO)** en een volledig geautomatiseerde risico- en kwaliteitslaag.

---

## Hoe het werkt — Signaalflow

```
Binance OHLCV (15m + 1h + 4h + 1D)
    ↓
Feature Engineering (60+ technische indicatoren)
    ↓
┌──────────────────────┬─────────────┬──────────────┐
│  12 Strategieën      │  RL (PPO)   │  LSTM+Attn   │
│  (60–70% gewicht)    │  (8–12%)    │  (8–20%)     │
│  regime-afhankelijk  │  per regime │  per regime  │
└──────────┬───────────┴──────┬──────┴──────┬───────┘
           └──────────────────┘             │
                  SignalCombiner ←──────────┘
                  + Sentiment (±15%)
                  + OrderBook (±10%)
                  + StatArb (±15% in ranging)
                       ↓
          Regime Detectie met hysteresis
          (bull/bear/ranging/high_vol/accumulation)
                       ↓
          8 Confluence Filters (zie hieronder)
                       ↓
          Setup Grading (A+/A/B/C + edge score)
                       ↓
          Meta-throttle (schaal positie bij slechte periode)
                       ↓
          Microstructure check (spread te groot → blokkeer)
                       ↓
          PaperEngine: entry + SL + TP1 (50%) + TP2 + trailing
```

---

## De 8 Confluence Filters

Elke potentiële trade passeert deze filters voordat hij uitgevoerd wordt:

| # | Filter | Wat het doet |
|---|--------|--------------|
| 1 | Regime richting | Geen shorts in bull_trend, geen longs in bear_trend |
| 1b | 1D macro filter | Blokkeert longs als zowel 1D als 4h bearish zijn |
| 1c | Ranging skip | Slaat alle entries in ranging over (WR=29%) — uitzondering: Bollinger squeeze |
| 1d | Ranging RSI-zone | In ranging: only long bij RSI <45, only short bij RSI >55 |
| 2 | SL cooldown | 4u na stop-loss geen herinstap in dezelfde richting |
| 3 | BOS veto | MarketStructure BOS blokkeert tegendraadse trade |
| 4 | Minimale confluence | Shorts: altijd 3 strategieën eens; longs: 2 in zwakke regimes |
| 5 | RSI extremen | Geen shorts bij RSI <28 (bear_trend) of <35 (overig); geen longs bij RSI >72 |
| 5b | Lokaal extreme | Geen short binnen 1.5% van lokaal dieptepunt, geen long bij hoogtepunt |
| 6 | Volume bevestiging | Minimaal 0.50× gemiddeld volume (0.30× in sterke bear_trend) |
| 7 | Verliesstreak | Na 3 verliezen op rij: hogere confidence drempel vereist |
| 8 | Noise index | Bij 2+ ruis-indicatoren (ADX/volume/BB squeeze): geen trade |

---

## De 12 Strategieën

| Strategie | Basisgewicht | Sterk in regime | Specialiteit |
|-----------|-------------|-----------------|--------------|
| EMA Cross | 11% | bull/bear | Trendvolging |
| Smart Money Concepts | 11% | alle | Order Blocks, FVG, Liquidity Sweeps |
| Bollinger Mean Reversion | 9% | ranging | Oversold/overbought bounce |
| RSI Momentum | 9% | ranging | Divergentie + recovery |
| Wyckoff | 9% | accumulation | Spring, Upthrust, Accumulatie/Distributie |
| MACD | 8% | bull/bear | Trendbevestiging en -wissel |
| Breakout | 8% | bull/bear | Uitbraak boven/onder 100-kaars range + volume |
| Support & Resistance | 8% | alle | Pivot points S/R |
| Volume Profile | 8% | alle | POC, VAH/VAL niveaus |
| Ichimoku | 7% | bull/bear | Wolk-analyse, sterk op crypto |
| Market Structure | 7% | bull/bear | HH/HL, LH/LL, BOS, CHoCH |
| Grid Trading | 5% | ranging | Aanvulling bij zijwaartse markt |

Gewichten zijn **basisgewichten** — de AdaptiveWeightTracker past ze automatisch aan op basis van historische prestaties (0.3× minimum, 2.0× maximum, exponentieel gewogen over laatste 150 trades).

---

## Marktregimes

De bot detecteert het regime met **hysteresis** (3 opeenvolgende detecties voor een wissel) en past SL/TP, actieve strategieën en confluence drempels automatisch aan.

| Regime | SL | TP | Actieve strategieën | Confluence drempel |
|--------|----|----|--------------------|--------------------|
| bull_trend | 2.0× ATR | 5.0× ATR | EMA, MACD, Breakout, MarStr, SMC, Ichimoku, SR, Wyckoff | 0.15 |
| bear_trend | 2.5× ATR | 5.0× ATR | EMA, MACD, Breakout, MarStr, SMC, Ichimoku, SR, Wyckoff | 0.10 |
| ranging | 1.5× ATR | 2.0× ATR | Bollinger, RSI, SR, Grid, VolumeProfile, Wyckoff, SMC | 0.13 |
| high_vol | 3.0× ATR | 6.0× ATR | SMC, Wyckoff, MarStr, SR, VolumeProfile | 0.35 |
| accumulation | 1.8× ATR | 3.5× ATR | Wyckoff, VolumeProfile, SMC, SR, Bollinger, RSI, MarStr | 0.13 |

---

## AI Modellen

### LSTM Predictor (0% gewicht — momenteel uitgeschakeld)
- **Architectuur:** LSTM → Attention → Dense → 3-klasse output (omlaag/neutraal/omhoog)
- **Input:** 60+ features over venster van 60 kaarsen
- **Drempel:** confidence < 0.38 → LSTM genegeerd (anders ruis)
- **Auto-retrain:** elke 84 uur (2× per week)
- **Status:** uitgeschakeld (val_acc 35.1% ≈ random — hertrainen aanbevolen voor re-activatie)

### RL PPO Agent (10% gewicht in ranging, 8% in trend)
- **Algoritme:** Proximal Policy Optimization (stable-baselines3)
- **Reward:** Sortino ratio (bestraft downside volatiliteit zwaarder dan Sharpe)
- **Acties:** 0=wacht, 1=long, 2=short, 3=sluit

### Multi-timeframe analyse
```
1D  → macro trend filter (macro bias in ranging)
4h  → hoofd trend filter (longs geblokkeerd als 4h bearish)
1h  → signaal en entry timing
15m → micro-trend fijn-afstemming (±5% confidence, geen veto)
```

---

## Risicobeheer

| Mechanisme | Waarde | Uitleg |
|------------|--------|--------|
| Min confidence | 0.46 | Trades onder deze drempel worden geblokkeerd |
| Positiebepaling | Grade-gebaseerd (A+/A/B/C) | SetupClassifier bepaalt positiegrootte, niet de Kelly-formule |
| Meta-throttle | 25–100% | Schaalt positie automatisch terug bij slechte WR of verliesstreak |
| **Minimum positie (throttle ≥50%)** | **5% van portfolio** | Vloer tijdens normale markt (~$49 bij $980) |
| **Minimum positie (throttle <50%)** | **2% van portfolio** | Lagere vloer tijdens verliesstreak — throttle-bescherming blijft intact |
| Max portfolio risico | 2% per trade | Positie begrensd door ATR-risico |
| Confidence cap | 0.75 | Onrealistische hoge confidence wordt afgekapt |
| Partial close TP1 | 50% op 1.2R | Helft sluiten → breakeven stop zetten |
| ATR trailing stop | 1.5× ATR | Beweegt mee met peak, start pas na 0.5× ATR winst |
| SL cooldown | 4 uur | Na SL: geen herinstap in dezelfde richting |
| Max drawdown stop | 15% | Bot stopt volledig bij 15% portefeuille verlies |
| Time-based exit | 24u + <0.5% | Stale trades gesloten na 24 uur stilstand |
| Correlatie limiet | max 2 | Nooit meer dan 2 posities in dezelfde richting |
| Ranging correlatie-lock | max 1 | BTC/ETH/SOL zijn >90% gecorreleerd — max 1 positie in ranging |
| Pyramiding | max 2× | Bijkopen op winnende positie, minimaal 2× ATR winst |

---

## Setup Grading

Elke trade krijgt een kwaliteitsscore (0–4 punten) die de positiegrootte bepaalt:

| Punt | Voorwaarde |
|------|------------|
| +1 | ≥5 technische strategieën eens met actie |
| +1 | Regime strength ≥ 0.60 |
| +1 | Confidence ≥ 0.50 |
| +1 | Volume ratio ≥ 1.20 |

| Grade | Score | Positie | Toelichting |
|-------|-------|---------|-------------|
| A+ | 4 | 15% | Optimale setup — alles klopt |
| A | 3 | 12% | Sterke setup |
| B | 2 | 8% | Gemiddelde setup |
| C | 0–1 | 5% | Zwak — alleen als edge positief is |

C-grade met negatieve edge score wordt volledig overgeslagen.

---

## Huidige Performance (mei 2026)

| Metric | Waarde | Status |
|--------|--------|--------|
| Win Rate | 38.9% | Stijgend na ranging-skip fix |
| Profit Factor | 1.116 | Positief |
| Portfolio PnL | -1.98% | Stabiel |
| Max Drawdown | 2.12% | Laag |
| Gesloten trades | 54 | Opbouwend |
| Beste regime | bear_trend | 83% WR (n=6) |
| Slechtste regime | ranging | 29% WR (n=45) → overgeslagen |

**Actieve config:**
```
MIN_CONFIDENCE=0.46  ATR_SL=2.5×  ATR_TP=5.0×
RL_WEIGHT=0.10  LSTM_WEIGHT=0.00  SHORT_CONFLUENCE=3
RANGING=skip (WR te laag)  RSI_SHORT_BLOCK=28 in bear_trend
```

---

## Installatie

```bash
git clone <repo>
cd crypto_bot
python -m venv venv
source venv/bin/activate        # Linux/Mac
# of: venv\Scripts\activate     # Windows
pip install -r requirements_pi.txt  # Raspberry Pi
# of: pip install -r requirements.txt
```

---

## Gebruik

```bash
# Paper trading starten
nohup venv/bin/python bot.py > logs/bot_$(date +%Y%m%d).log 2>&1 &

# Modellen trainen (~20-40 min op Pi)
nohup venv/bin/python bot.py --train > logs/training_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# Trainen + daarna bot automatisch herstarten
bash restart_after_train.sh &

# Backtesting
venv/bin/python bot.py --backtest

# Live trading — ALLEEN na expliciete beslissing
venv/bin/python bot.py --live
```

---

## Configuratie (.env)

```env
# Symbolen
SYMBOL=BTC/USDT
SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT
TIMEFRAME=1h
INTERVAL=60
CAPITAL=1000
MULTI_ASSET=true

# AI gewichten
RL_WEIGHT=0.10
LSTM_WEIGHT=0.00  # uitgeschakeld — heractiveren na hertraining (val_acc target >43%)

# Risico
MIN_CONFIDENCE=0.46
MAX_DRAWDOWN=0.15
ATR_SL_MULT=2.5
ATR_TP_MULT=5.0
KELLY_FRACTION=0.25
TRAILING_STOP_PCT=0.05

# Auto-hertraining
RETRAIN_HOURS=84

# Telegram notificaties
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## Telegram Commando's

| Commando | Functie |
|----------|---------|
| `/bal` | Portfolio, PnL, drawdown, vrij kapitaal, regime |
| `/stats` | Win rate, avg PnL, beste/slechtste trade |
| `/posities` | Open posities met entry, prijs, PnL, **ingezet bedrag**, SL, TP1 + TP2 |
| `/regime` | Huidig marktregime per symbool met kracht |
| `/signalen` | Laatste signalen per strategie met bijdrage |
| `/rolling` | Rolling win rate over laatste 10/20 trades |
| `/trades` | Laatste 8 gesloten trades |
| `/health` | CPU temp, RAM, schijfruimte, uptime |
| `/log` | Laatste fouten en waarschuwingen |
| `/stop` | Bot stoppen (posities blijven open) |

---

## Projectstructuur

```
crypto_bot/
├── bot.py                    # MonsterBot — main loop + 8 filters + trade logica
├── config.py                 # Config.from_env() — laadt .env
├── .env                      # Alle parameters (nooit committen met API keys)
├── data/
│   ├── fetcher.py            # CCXT: OHLCV ophalen + caching
│   ├── features.py           # 60+ technische indicatoren
│   ├── orderbook.py          # Bid/ask imbalans, whale detectie
│   ├── sentiment.py          # Fear & Greed + CryptoCompare nieuws
│   └── funding_rate.py       # Funding rate modifier (±20% confidence)
├── strategies/
│   ├── signals.py            # SignalCombiner, ConfidenceBrain, AdaptiveWeightTracker
│   ├── smart_money.py        # Order Blocks, FVG, Liquidity Sweeps
│   ├── support_resistance.py # Pivot points S/R
│   ├── ichimoku.py           # Ichimoku cloud
│   ├── wyckoff.py            # Spring, Upthrust, Accumulatie/Distributie
│   ├── volume_profile.py     # POC, VAH/VAL
│   ├── market_structure.py   # HH/HL, BOS, CHoCH
│   ├── grid_trading.py       # Grid levels
│   ├── momentum_rotation.py  # Beste munt selectie
│   ├── stat_arb.py           # Statistische arbitrage (z-score paar-divergentie)
│   ├── anomaly.py            # Abnormale marktomstandigheden detectie
│   └── regime.py             # Marktregime detectie met hysteresis
├── agent/
│   ├── lstm_predictor.py     # PyTorch LSTM + Attention (3-klasse)
│   ├── trainer.py            # LSTM + RL training orchestrator
│   └── environment.py        # OpenAI Gym environment voor PPO
├── execution/
│   ├── paper_engine.py       # Paper trading: LONG + SHORT + partial close + trailing
│   ├── live_engine.py        # Live trading via CCXT
│   └── microstructure.py     # Spread-aware entries, slippage check
├── risk/
│   ├── manager.py            # Kelly + ATR positiebepaling
│   ├── portfolio.py          # Portfolio tracking
│   └── meta_controller.py   # Auto-throttling op basis van recente prestaties
├── analytics/
│   ├── edge_detector.py      # Expectancy per setup-type
│   ├── setup_classifier.py   # A+/A/B/C grading + edge score
│   └── monte_carlo.py        # 2000× drawdown simulatie
├── backtesting/
│   └── walk_forward.py       # Walk-forward train/test split
├── monitoring/
│   ├── logger.py             # Trade logging naar JSON
│   ├── telegram_bot.py       # Telegram two-way interface
│   └── report.py             # Dagelijkse + weekelijkse rapporten
├── dashboard/
│   └── app.py                # Flask web dashboard (real-time)
└── tools/
    ├── check_report.py       # Volledige bot diagnose (gebruik: python tools/check_report.py)
    ├── config_tracker.py     # Config snapshot systeem (voor/na elke parameterwijziging)
    ├── filter_monitor.py     # Monitort actieve filters elke 15 min → Telegram bij verandering
    ├── btc_diagnose.py       # Diagnoseert waarom een symbool niet tradt (filter-voor-filter)
    ├── auto_optimizer.py     # Automatische parameter-optimalisatie (*/6 uur via cron)
    ├── auto_watcher.py       # Setup alerts bij 4+ confluences (*/15 min via cron)
    ├── monitor_alert.py      # Dagelijkse gezondheidscheck + Telegram (08:00 via cron)
    └── self_healer.py        # Detecteert en herstelt configuratieproblemen (07:00/19:00)
```

---

## Automatisering (Cron Jobs)

De bot draait volledig autonoom via systemd en cron:

| Tijdstip | Script | Functie |
|----------|--------|---------|
| `*/15 min` | `auto_watcher.py` | Setup alert als 4+ confluences actief zijn |
| `*/15 min` | `filter_monitor.py` | Telegram alert als filter-situatie verandert |
| `*/6 uur` | `auto_optimizer.py` | Controleert parameters en stelt aanpassingen voor |
| `08:00` dagelijks | `monitor_alert.py` | Gezondheidscheck + dagrapport naar Telegram |
| `09:00` zondag | `monitor_alert.py --weekly` | Weekrapport |
| `03:00` maandag | `auto_trainer.py` | LSTM + RL hertraining |
| `04:00` maandag | `auto_cleanup.py` | Log-archivering + opruimen |
| `07:00 + 19:00` | `self_healer.py` | Detecteert configuratieproblemen + herstelt |

De bot zelf draait als **systemd service** met automatische herstart:
```bash
sudo systemctl status cryptobot.service
sudo systemctl restart cryptobot.service
```

---

## Parameter Optimalisatie

De bot wordt getuned via een systematische feedbackloop:

```
Wijziging → Bot laten draaien (≥50 trades) → check → Resultaat meten
→ Vergelijken met vorige waarde → Bijsturen → herhalen
```

Alle wijzigingen worden bijgehouden in `memory/project_config_history.md` zodat je altijd kunt terugkijken welke waarde wanneer gebruikt werd en wat het resultaat was. Nooit meer dan 1 parameter tegelijk wijzigen.

**Diagnose starten:**
```bash
venv/bin/python tools/check_report.py
```

---

## Disclaimer

- Start ALTIJD met paper trading — nooit direct live
- Crypto trading is extreem risicovol
- Backtests en paper resultaten ≠ toekomstige live resultaten
- Gebruik nooit geld dat je niet kunt missen
