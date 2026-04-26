# 🤖 Self-Learning Crypto Bot

Een professionele, zelf-lerende crypto trading bot gebouwd in Python.
Combineert **echte trader strategieën** met **Reinforcement Learning (PPO)**.

---

## 🏗️ Architectuur

```
Data (Binance OHLCV)
    ↓
Feature Engineering (RSI, MACD, Bollinger, EMA, ATR, VWAP...)
    ↓
┌─────────────────────┬──────────────────────────┐
│  Trader Strategieën │  RL Agent (PPO)           │
│  - EMA Cross        │  - Leert van miljoenen    │
│  - Bollinger Bands  │    historische momenten   │
│  - RSI Momentum     │  - Reward: Sharpe ratio   │
│  - MACD             │  - Verbetert zichzelf     │
│  - Breakout         │    continu                │
└──────────┬──────────┴──────────────┬────────────┘
           └──────────┬──────────────┘
                Signal Combiner (gewogen ensemble)
                      ↓
              Risicobeheer (Kelly + ATR stop-loss)
                      ↓
              Order Uitvoering (paper / live)
```

---

## 📦 Installatie

```bash
# 1. Kloon of kopieer de bestanden
cd crypto_bot

# 2. Maak een virtual environment
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate          # Windows

# 3. Installeer dependencies
pip install -r requirements.txt
```

---

## 🚀 Gebruik

### Stap 1: Train de RL agent

```bash
# Train op BTC/USDT, 1-uur kaarsen, 500.000 stappen
python training/train.py --symbol BTC/USDT --timeframe 1h --steps 500000

# Meerdere assets tegelijk trainen (aanbevolen)
python training/train.py --symbol ETH/USDT --timeframe 4h --steps 300000
```

Training duurt 15-60 minuten afhankelijk van je hardware.
Het beste model wordt automatisch opgeslagen in `models/crypto_ppo_best/`.

### Stap 2: Backtest (controleer resultaten)

```bash
python training/train.py --symbol BTC/USDT --backtest-only --model models/crypto_ppo_best/best_model
```

### Stap 3: Paper trading (ALTIJD eerst doen!)

```bash
# Start de bot in paper trading modus
python bot.py --symbol BTC/USDT --paper --capital 1000 --interval 60

# Of met ETH
python bot.py --symbol ETH/USDT --paper --timeframe 15m --interval 15
```

### Stap 4: Live trading (op eigen risico!)

```bash
# Maak een Binance API key aan (lees-only + handelen, GEEN opnames)
python bot.py --symbol BTC/USDT --live \
    --api-key JOUW_API_KEY \
    --api-secret JOUW_API_SECRET \
    --capital 100
```

---

## 📊 Trader Strategieën

| Strategie | Type | Werking |
|-----------|------|---------|
| EMA Cross | Trend following | Snel EMA kruist traag EMA |
| Bollinger Bands | Mean reversion | Koop bij onderband, verkoop bij bovenband |
| RSI Momentum | Momentum | Oversold/overbought + divergentie |
| MACD | Trend bevestiging | Histogram groei/krimp |
| Breakout | Breakout | Uitbraak uit consolidatie met volume |

---

## 🧠 Reinforcement Learning (PPO)

De RL agent leert door te **handelen op historische data** en de reward te maximaliseren:

- **State**: 20 kaarsen × features + portfolio status (positie, PnL, drawdown)
- **Actie**: Hold (0), Buy (1), Sell (2)
- **Reward**: Sharpe ratio-gebaseerd + straf voor grote drawdown
- **Algoritme**: Proximal Policy Optimization (PPO) via Stable Baselines3

Na training heeft de agent miljoenen marktmomenten gezien en geleerd welke patronen winstgevend zijn.

---

## 🛡️ Risicobeheer

- **Kelly Criterium**: Optimale positie grootte (25% fractional Kelly)
- **ATR Stop-Loss**: Stop 2x ATR onder entry prijs
- **Max Drawdown Stop**: Trading stopt bij 15% drawdown
- **Trailing Stop**: Beschermt winsten bij stijgende prijs
- **Min Confidence**: Trades alleen boven 30% confidence

---

## ⚠️ Disclaimer

- Start ALTIJD met paper trading
- Crypto trading is extreem risicovol
- Backtests ≠ toekomstige resultaten
- Gebruik nooit geld dat je niet kunt missen
- De auteur is niet verantwoordelijk voor financieel verlies

---

## 📁 Projectstructuur

```
crypto_bot/
├── bot.py                    # Hoofdbot (live/paper trading)
├── requirements.txt
├── data/
│   └── features.py           # Technische indicator berekeningen
├── strategies/
│   └── signals.py            # Trader strategieën + signal combiner
├── agent/
│   └── environment.py        # Gymnasium RL environment
├── risk/
│   └── manager.py            # Risicobeheer (Kelly, stop-loss)
├── training/
│   └── train.py              # Training script voor RL agent
└── models/                   # Opgeslagen getrainde modellen
```
