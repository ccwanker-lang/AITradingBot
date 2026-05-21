# Monster Crypto Bot — Claude Intelligence Handboek

Dit bestand maakt Claude direct volledig ingevoerd in het project én in professionele trading. Elke nieuwe sessie begint met alle kennis die nodig is om slimme beslissingen te maken.

---

## ONTHOUD ALTIJD — Lees dit eerst

### Services herstarten
ALTIJD via `sudo systemctl` — NOOIT `kill`, `pkill` of `pgrep`.
```bash
sudo systemctl restart cryptobot.service   # bot herstarten
sudo systemctl restart dashboard.service   # dashboard herstarten
sudo systemctl status cryptobot.service    # status bekijken
```
Beide zijn system-level services (geen `--user` flag nodig).

### Roadmap (afgesproken 2026-05-20)
- **Week 1 t/m 2026-05-27**: NIETS aanpassen. Bot draait met MIN_CONFIDENCE=0.46. Wacht op 20 nieuwe trades (42 → 62 closed). Meet of WR richting 50% gaat.
- **Week 2 (~2026-05-27)**: Correlatie-filter bouwen — BTC/ETH/SOL zijn 90% gecorreleerd, max 1 positie tegelijk.
- **Week 3 (~2026-06-03)**: LSTM per-symbool (alleen als 50+ closed trades, val_acc target >43%).

### Huidige config (2026-05-20)
| Parameter | Waarde |
|-----------|--------|
| MIN_CONFIDENCE | 0.46 |
| ATR_SL_MULT | 2.5 |
| ATR_TP_MULT | 5.0 |
| RL_WEIGHT | 0.10 |
| LSTM_WEIGHT | 0.00 (val_acc 37.2% ≈ random, uitgeschakeld) |
| LIVE | false (altijd paper trading) |

### Geïnstalleerde agents (.claude/agents/)
`bot-monitor`, `bot-optimizer`, `bot-trainer`, `bot-cleanup`, `bot-reporter`, `bot-debugger`, `bot-backtest`, `bot-analyst`, `bot-watcher`

### Geïnstalleerde cron jobs (24/7 automatisering)
- `08:00` dagelijks — `monitor_alert.py` (gezondheidscheck + Telegram)
- `09:00` zondag — weekrapport
- `03:00` maandag — `auto_trainer.py`
- `04:00` maandag — `auto_cleanup.py`
- `*/6 uur` — `auto_optimizer.py`
- `*/15 min` — `auto_watcher.py` (setup alerts bij 4+ confluences)

---

## SLASH COMMANDO'S

### `check`
Als de gebruiker het woord **check** typt (alleen of als eerste woord), voer dan een **grondige diagnose** uit van de volledige bot:

> **BELANGRIJK — Geen onderbrekingen tijdens check:**
> Voer alle stappen hieronder volledig automatisch uit zonder om bevestiging te vragen.
> Geen enkel bash-commando, bestandslees of code-aanpassing tijdens de check mag wachten op "ja" van de gebruiker.
> Voer alles door van stap 1 t/m 7, geef daarna pas het eindrapport aan de gebruiker.

**Stap 1 — Voer automatisch het check-rapport uit:**
```bash
venv/bin/python tools/check_report.py
```
Dit rapport geeft automatisch: processstatus, portfolio, officiële win rate (per entry gecombineerd), confidence-buckets, strategie-prestaties, model gezondheid, risicopatronen, config-geschiedenis en code sanity checks.

**Stap 2 — Lees de kritieke codebestanden:**
`strategies/signals.py`, `execution/paper_engine.py`, `bot.py` (confluence + filters), `risk/manager.py`, `agent/lstm_predictor.py`

**Stap 3 — Analyseer op basis van rapport + code:**
- **Processstatus**: bot actief? training actief? recente fouten?
- **Win rate**: officiële WR (per entry) + recente trend (stijgend/dalend?)
- **Confidence-verdeling**: zijn er buckets met WR <35%? → verhoog MIN_CONFIDENCE
- **TP1 reach rate**: <30% = entries te vroeg / ATR te krap / signalen te zwak
- **Per-regime WR**: welk regime presteert slecht? bugs in regime-logica?
- **Per-symbool WR**: welk symbool trekt de WR omlaag?
- **Strategie gewichten**: slecht presterende strategieën met hoog gewicht?
- **LSTM val_acc**: <38% = LSTM geeft ruis → overweeg hertrainen
- **RL model leeftijd**: >96u oud → overweeg hertrainen
- **Verliesreeks**: >5 op rij = systemisch probleem, niet pech
- **Exit redenen**: >60% STOP-LOSS = ATR_SL_MULT te krap of slechte entries
- **Code bugs**: TP1>TP2, counter-trend filter, confluence drempels

**Stap 4 — Geef gerangschikte lijst van problemen:**
**HOOG** (win rate killers, direct aanpakken) → **MEDIUM** → **LAAG**

**Stap 5 — Concrete fix per probleem** (exacte code of .env waarde)

**Stap 6 — Sla config snapshot op** vóór en na fixes:
```bash
venv/bin/python tools/config_tracker.py snapshot "baseline voor fixes: [omschrijving]"
```

**Stap 7 — Top-3 aanbevelingen** om win rate het snelst te verhogen

**Doel van check:** win rate zo hoog mogelijk maken voor live trading. Officiële WR target: ≥45% met PF ≥1.5

---

## KRITIEKE REGELS

- **Altijd paper trading** (`python bot.py`) — NOOIT `--live` suggereren zonder expliciete toestemming van de gebruiker
- Communiceer altijd in het **Nederlands**
- Bot moet **altijd handelen** — inactiviteit is een bug, niet een feature
- Bij twijfel: voeg de feature toe, de gebruiker wil maximale performance
- Geef altijd exacte commando's — geen aannames over terminal kennis
- **Session limieten bewaken:** De gebruiker heeft een Pro plan met sessielimieten. Als je ziet dat het gebruik hoog is (>70%), geef dan aan het einde van je antwoord een korte melding zodat de gebruiker weet dat de sessie bijna vol is. De gebruiker kan zijn verbruik zien in de terminal onderaan: "Plan usage limits — Current session — X% used — Resets in X hr"

### Parameterwijzigingen — ALTIJD bijhouden

Bij **elke** wijziging aan een parameter (`.env`, `bot.py`, `signals.py`, `paper_engine.py`, of welk bestand dan ook) **moet** je het volgende doen:

1. **Config snapshot vóór de wijziging:**
   ```bash
   venv/bin/python tools/config_tracker.py snapshot "beschrijving voor fix"
   ```

2. **Update `memory/project_config_history.md`** met exact:
   - Welke parameter, in welk bestand
   - Oude waarde → nieuwe waarde
   - Reden voor de wijziging
   - Risico (wat kan er misgaan)
   - Resultaat: "TBD — meten bij volgende check"

3. **Config snapshot ná de wijziging:**
   ```bash
   venv/bin/python tools/config_tracker.py snapshot "beschrijving na fix"
   ```

Dit geldt voor ALLES: `.env` waarden, confluence drempels, regime multipliers, strategie gewichten, SL/TP ratios, LSTM drempels, AdaptiveWeight settings — elk getal dat verandert.

**Nooit meer dan 1 parameter tegelijk wijzigen** zodat het effect meetbaar blijft.

Het doel: als een wijziging verkeerd uitpakt, weet je exact wat je moet terugdraaien en naar welke waarde.

---

## 1. PROJECT ARCHITECTUUR

### Bestandsstructuur

```
crypto_bot/
├── bot.py                    # MonsterBot klasse + main loop
├── config.py                 # Config.from_env() laadt .env
├── data/
│   ├── fetcher.py            # CCXT: OHLCV + prijs ophalen
│   ├── features.py           # 60+ technische indicatoren toevoegen
│   ├── orderbook.py          # Bid/ask imbalans, whale detectie
│   ├── sentiment.py          # Fear & Greed + CryptoCompare nieuws
│   └── funding_rate.py       # Funding rate modifier
├── strategies/
│   ├── signals.py            # SignalCombiner, ConfidenceBrain, AdaptiveWeightTracker
│   ├── smart_money.py        # SMC: Order Blocks, FVG, Liquidity Sweeps
│   ├── support_resistance.py # S/R niveaus via pivot points
│   ├── ichimoku.py           # Ichimoku cloud systeem
│   ├── wyckoff.py            # Wyckoff fases: Spring, Upthrust, Accumulatie
│   ├── volume_profile.py     # POC, Value Area High/Low
│   ├── market_structure.py   # HH/HL, LH/LL, BOS, CHoCH
│   ├── grid_trading.py       # Grid levels in ranging markt
│   ├── momentum_rotation.py  # Best presterende munt selecteren
│   ├── anomaly.py            # Abnormale marktomstandigheden detectie
│   └── regime.py             # Marktregime: bull/bear/ranging/high_vol
├── agent/
│   ├── lstm_predictor.py     # PyTorch LSTM + Attention voor prijsrichting
│   ├── trainer.py            # LSTM + RL training orchestrator
│   └── environment.py        # Gym environment voor PPO agent
├── execution/
│   ├── paper_engine.py       # Paper trading: LONG + SHORT + partial close
│   └── live_engine.py        # Live trading via CCXT (voorzichtig!)
├── risk/
│   ├── manager.py            # Kelly + ATR positiebepaling, SL/TP/trailing
│   └── portfolio.py          # Portfolio tracking
├── backtesting/
│   └── engine.py             # Backtesting op historische data
├── monitoring/
│   ├── logger.py             # Trade logging naar JSON
│   ├── telegram_bot.py       # Telegram two-way interface
│   └── report.py             # Dagelijkse en weekelijkse rapporten
└── dashboard/
    └── app.py                # Flask web dashboard
```

### Hoe te starten

```bash
python bot.py              # Paper trading (altijd eerst!)
python bot.py --backtest   # Backtest op historische data
python bot.py --train      # LSTM + RL modellen trainen (~20 min)
python bot.py --live       # ECHT GELD — alleen na expliciete bevestiging
```

### Signaalflow (van data naar trade)

```
1. DataFetcher haalt OHLCV op (1h + 4h timeframes)
2. add_all_features() voegt 60+ indicatoren toe
3. 12 strategieën genereren elk een Signal(actie, confidence, reden)
4. AdaptiveWeightTracker past gewichten aan op basis van historische prestaties
5. SignalCombiner combineert: strategieën (50%) + RL (30%) + LSTM (20%)
6. Sentiment modifier (±15%), OrderBook modifier (±10%)
7. Regime multiplier (bear = 0.5x, high_vol = 0.4x, bull = 1.2x)
8. ConfidenceBrain beslist: actie + threshold (verlaagt bij inactiviteit)
9. Multi-timeframe filter: 1h signaal moet 4h trend volgen
10. Funding rate past confidence aan (±20%)
11. RiskManager berekent positiegrootte via Kelly + ATR
12. PaperEngine voert trade uit: entry, SL, TP1 (50% partial), TP2, trailing
```

---

## 2. ALLE 12 STRATEGIEËN

### 2.1 EMA Cross (gewicht: 11%)
**Logica:** EMA9 kruist boven/onder EMA21  
**Bullish:** EMA9 > EMA21, crossover = hogere confidence  
**Bearish:** EMA9 < EMA21, crossover = hogere confidence  
**Sterk bij:** trending markten, niet bij ranging  
**Zwak bij:** sideways chop — geeft veel fout signalen

### 2.2 Bollinger Mean Reversion (gewicht: 9%)
**Logica:** Prijs keert terug naar het midden van de Bollinger Bands  
**Bullish:** BB%B < 0.05 + RSI < 35 (oversold)  
**Bearish:** BB%B > 0.95 + RSI > 65 (overbought)  
**Bollinger Squeeze:** Banden smal = grote move aankomend (1.3x confidence)  
**Sterk bij:** ranging markten, mean-reverting assets  
**Zwak bij:** sterke trends — prijs kan lang buiten banden blijven

### 2.3 RSI Momentum (gewicht: 9%)
**Logica:** RSI divergentie + oversold/overbought recovery  
**Bullish:** RSI < 30 en stijgend (oversold recovery) — extra punt voor bullish divergentie  
**Bearish:** RSI > 70 en dalend (overbought pullback) — extra punt voor bearish divergentie  
**Divergentie:** Prijs maakt nieuw high maar RSI lager = bearish divergentie (omgekeerde koersverandering aankomend)  
**Sterk bij:** duidelijke trend exhaustion punten

### 2.4 MACD (gewicht: 8%)
**Logica:** MACD histogram richting en crossovers  
**Bullish:** histogram positief en groeiend, of crossover van negatief naar positief  
**Bearish:** histogram negatief en dalend, of crossover van positief naar negatief  
**Crossover confidence:** 0.75 — sterkste signaal  
**Sterk bij:** trendbevestiging en trendverandering detectie

### 2.5 Breakout (gewicht: 8%)
**Logica:** Prijs breekt boven 100-kaars resistance of onder support met volume  
**Bullish:** close > resistance + 0.1 ATR + volume_ratio > 1.5  
**Bearish:** close < support - 0.1 ATR + volume_ratio > 1.5  
**Volume is cruciaal:** Breakout zonder volume = valse uitbraak  
**Sterk bij:** consolidatiefases die eindigen met sterke candles

### 2.6 Smart Money Concepts — SMC (gewicht: 11%)
Institutionele traders laten bewuste sporen achter in de marktstructuur.

**Order Blocks (OB):**
- Bullish OB: laatste bearish kaars VOOR een sterke stijging (2%+)
- Bearish OB: laatste bullish kaars VOOR een sterke daling
- Als prijs terugkeert naar de OB-zone → trade in de richting van de originele move
- Waarom: instituten plaatsen resterende orders op die niveaus

**Fair Value Gaps (FVG):**
- Bullish FVG: gat tussen kaars 1 high en kaars 3 low (prijs springt omhoog)
- Bearish FVG: gat tussen kaars 1 low en kaars 3 high (prijs springt omlaag)
- Als prijs terugkeert om de gap te vullen → fade van de gap is de trade
- Minimum gap grootte: 0.2% van de prijs

**Liquidity Sweeps:**
- Prijs doorbreekt even een sleutelLevel dan keert snel terug
- Bullish sweep: prijs doorbreekt vorig low, sluit er boven → long
- Bearish sweep: prijs doorbreekt vorig high, sluit er onder → short
- Waarom: instituten triggeren retailstops om goedkoop in te stappen
- Sterkste signaal in SMC — confidence tot 0.80

### 2.7 Support & Resistance (gewicht: 8%)
**Logica:** Pivot points berekenen historische S/R levels  
**Entry:** Koop vlak boven support, short vlak onder resistance  
**Bevestiging:** Meerdere touches van een level = sterker level  
**Sterk bij:** alle marktomstandigheden als extra filter

### 2.8 Ichimoku Cloud (gewicht: 7%)
**Componenten:**
- Tenkan-sen (9): snelle lijn
- Kijun-sen (26): basis lijn — support/resistance
- Senkou Span A + B: de wolk (toekomstige S/R)
- Chikou Span: lagging lijn (bevestiging)

**Bullish:** Prijs boven wolk + Tenkan > Kijun + wolk stijgend  
**Bearish:** Prijs onder wolk + Tenkan < Kijun + wolk dalend  
**Sterk in:** Aziatische sessies, werkt goed op crypto  
**Wolk dikte:** dikke wolk = sterke S/R zone

### 2.9 Wyckoff Methode (gewicht: 9%)
Richard Wyckoff ontdekte dat grote spelers (composite man) de markt manipuleren in herkenbare patronen.

**Spring (conf: 0.88 — sterkste signaal):**
- Prijs doorbreekt support + sluit er boven + hoog volume
- Grote spelers triggeren retailstops, dan kopen ze zelf
- Actie: LONG — dit is een van de betrouwbaarste setups in trading

**Upthrust (conf: 0.88):**
- Prijs doorbreekt resistance + sluit er onder + hoog volume
- Distributie: grote spelers verkopen aan retailtraders die de breakout kopen
- Actie: SHORT

**Accumulation (conf: 0.65):**
- Lage volatiliteit + volume daalt + prijs consolidiert boven steun
- Grote spelers kopen stilletjes op voordat prijs stijgt
- Actie: LONG — geduld, de move komt

**Distribution (conf: 0.65):**
- Lage volatiliteit + volume daalt + prijs consolideert onder weerstand
- Grote spelers verkopen stilletjes voordat prijs daalt
- Actie: SHORT

**Sign of Strength (SOS):** Stijging op hoog volume na accumulation = markup fase begint  
**Sign of Weakness (SOW):** Daling op hoog volume na distribution = markdown fase begint

### 2.10 Volume Profile (gewicht: 8%)
**Point of Control (POC):** Prijsniveau met het meeste volume — sterke magneet  
**Value Area High (VAH):** Bovengrens van 70% van het volume  
**Value Area Low (VAL):** Ondergrens van 70% van het volume  
**Logic:** Prijs tendeert naar POC, VAH/VAL zijn S/R niveaus  
**Low Volume Nodes (LVN):** Prijs beweegt snel door zones met weinig volume  
**Sterk bij:** identifying key levels voor SL/TP plaatsing

### 2.11 Market Structure (gewicht: 7%)
Fundamenteel concept — bepaalt de trend via swing points.

**Bullish structuur (HH + HL):**
- Higher Highs: elk swing high hoger dan vorige
- Higher Lows: elk swing low hoger dan vorige
- Actie: alleen longs nemen, koop op pullback naar HL zone

**Bearish structuur (LH + LL):**
- Lower Highs: elk swing high lager dan vorige
- Lower Lows: elk swing low lager dan vorige
- Actie: alleen shorts nemen, short op rally naar LH zone

**Break of Structure (BOS) — conf: 0.85:**
- Bullish BOS: prijs breekt boven vorig swing high = trend verandert naar bullish
- Bearish BOS: prijs breekt onder vorig swing low = trend verandert naar bearish
- Sterk signaal — trendverandering bevestiging

**Change of Character (CHoCH) — conf: 0.70:**
- Na bearish structuur: eerste higher high = vroeg keersignaal
- Vroeger signaal dan BOS maar minder betrouwbaar

### 2.12 Grid Trading (gewicht: 5%)
**Logica:** Vaste koop/verkooporders op regelmatige afstand van de prijs  
**Werkt bij:** ranging markten zonder duidelijke trend  
**Voorzichtig:** In trending markt kan grid verliesgevend worden  
**Gebruik:** Laagste gewicht (5%) — alleen als andere strategieën neutraal zijn

---

## 3. MARKTREGIMES

De RegimeDetector bepaalt de marktomstandigheid. Dit beïnvloedt ALLE strategieën.

| Regime | Multiplier | Betekenis | Strategie aanpak |
|--------|-----------|-----------|-----------------|
| BULL_TREND | 1.2x | Stijgende trend, hoog volume | Meer kopen, longs aanhouden |
| BEAR_TREND | 0.5x | Dalende trend | Minder kopen, shorts prefereren |
| RANGING | 1.0x | Zijwaarts, geen trend | Mean reversion, grid trading |
| HIGH_VOL | 0.4x | Extreme volatiliteit | Minimale posities, grotere SL |
| ACCUMULATION | 1.1x | Stille opbouw fase | Voorzichtig beginnen met longs |

**Regel:** In HIGH_VOL regime: vergroot ATR-multiplier voor SL, verklein positie  
**Regel:** In BEAR_TREND: 4h filter blokkeert bijna alle longs → bot gaat short  

---

## 4. RISICOBEHEER — DE WISKUNDE

### 4.1 Kelly Criterium

```
Kelly_f = (win_rate × odds - (1 - win_rate)) / odds
odds = avg_win_R / avg_loss_R

Voorbeeld: 55% win rate, 2:1 R/R
Kelly = (0.55 × 2 - 0.45) / 2 = 0.325 (32.5%)
Fractional Kelly (0.25x) = 8.1% van portfolio per trade
```

**Waarom fractional Kelly:** Volledige Kelly is te agressief — een slechte streak kan catastrofaal zijn. De bot gebruikt 0.25x Kelly.

### 4.2 ATR-Gebaseerde SL/TP

```
ATR (Average True Range, 14 perioden) = gemiddelde dagelijkse volatiliteit

Stop Loss  = entry_price - (ATR × atr_sl_mult)  # default: 2.0x ATR
Take Profit = entry_price + (ATR × atr_tp_mult)  # default: 4.0x ATR
Risk/Reward = 1:2 (4.0 / 2.0)

Bij hogere volatiliteit → ATR groter → SL verder weg → kleinere positie
```

### 4.3 Positiebepaling

```python
stop_loss_pct = (ATR × atr_sl_mult) / price
risk_size = max_portfolio_risk / stop_loss_pct  # max 2% risico
position_pct = min(kelly_f, risk_size, max_position_pct) × confidence
invest = portfolio_value × position_pct
```

**Maximaal risico per trade:** 2% van portfolio  
**Maximale positie:** 90% van portfolio (nooit alles in één trade)  
**Minimum confidence:** 0.28 (anders geen trade)

### 4.4 Partial Close + Pyramiding

**Partial close (50% op TP1):** Halve positie sluiten bij eerste target → risk-free trade  
**Trailing stop:** Beweegt mee omhoog maar nooit omlaag (5% trailing)  
**Pyramiding:** Max 2x extra positie toevoegen aan winnende trade  
**Take Profit 2 (TP2):** Tweede target op 2x de afstand van TP1

### 4.5 Drawdown Bescherming

**Max drawdown stop:** 15% — bot stopt bij dit verlies  
**Trailing drawdown:** Berekend vanaf portfolio peak  
**Herstellogica:** Na stop → wacht tot markt normaliseert, herstart manual  

---

## 5. CONFIDENCEBRAIN — ANTI-PARALYSIS SYSTEEM

Het gevaarlijkste dat een bot kan doen is niets doen terwijl de markt beweegt.

```python
# Threshold daalt naarmate bot langer niets doet
threshold = 0.12 × (1 - idle_factor × 0.60)
# Na 8 uur inactiviteit: threshold = 0.12 × 0.40 = 0.048

# Boldness (0.65) versterkt effectieve score
effective_score = score × (1 + 0.65 × 0.30) = score × 1.195

# Na 6+ uur inactiviteit: regime hint override
if idle_hours > 6 and abs(score) < threshold × 1.5:
    effective_score += regime_direction × threshold × 0.8
```

**Tuning richtlijnen:**
- `boldness` te hoog (>0.80) → bot is roekeloos, handelt op rommel
- `boldness` te laag (<0.40) → bot bevriест, mist kansen
- `min_confidence` te hoog (>0.45) → bot handelt bijna nooit
- `min_confidence` te laag (<0.20) → te veel slechte trades

**Backtest resultaat -17.1% was veroorzaakt door te lage threshold.** Aanbevolen waarden:
- `min_confidence`: 0.32 - 0.40
- `boldness`: 0.55 - 0.70
- `max_idle_hours`: 6 - 10

---

## 6. AI/ML COMPONENTEN

### 6.1 LSTM Predictor (gewicht: 20%)

```
Architectuur: LSTM → Attention → Dense → Sigmoid
Input: 60+ features, window van 60 kaarsen
Output: 0.0 - 1.0 (kans op stijging)
Drempel: >0.55 = bullish, <0.45 = bearish

Attention mechanisme: leert welke tijdstappen het meest relevant zijn
Training: binaire classificatie (stijgt prijs de volgende kaars?)
Auto-retrain: elke X uur (configureerbaar via RETRAIN_HOURS)
```

### 6.2 RL PPO Agent (gewicht: 30%)

```
Algoritme: Proximal Policy Optimization (stable-baselines3)
Acties: 0 = hold, 1 = buy, 2 = sell
Reward: Sortino ratio (straft downside volatiliteit zwaarder)
Observatie: 20-kaars window van alle features
Training: ~100k stappen op historische data

Sortino vs Sharpe: Sortino ratio is beter voor trading omdat
het alleen negatieve volatiliteit bestraft, niet de positieve.
```

### 6.3 Feature Engineering (60+ features)

**Trend indicatoren:** EMA 9/21/50/200, MACD, MACD signal, MACD diff  
**Momentum:** RSI 14, Stochastic %K/%D, Williams %R, CCI  
**Volatiliteit:** ATR 14, Bollinger Bands (upper/lower/width/pct), Keltner Channels  
**Volume:** OBV, Volume ratio (vs 20-periode MA), VWAP  
**Structuur:** Pivot points, swing highs/lows, fractal levels  
**Kaarspatronen:** Doji, Hammer, Engulfing, Shooting Star  
**Custom:** Funding rate, Fear & Greed score, orderbook imbalans ratio  

---

## 7. MULTI-TIMEFRAME ANALYSE

**Principe:** Hogere tijdsframe = sterkere trend. Nooit tegen hogere TF in handelen.

```
4h chart: bepaalt de RICHTING (filter)
  ↓
1h chart: bepaalt het ENTRY MOMENT

Als 1h signaal = BUY maar 4h trend = BEARISH → actie = 0 (wachten)
Als 1h signaal = SELL maar 4h trend = BULLISH → actie = 0 (wachten)
Als 1h en 4h eens zijn → signaal doorgaan
```

**Implementatie in bot:**
```python
tf_trend = 1 if df_4h["ema_9"].iloc[-1] > df_4h["ema_21"].iloc[-1] else -1
if tf_trend != 0 and action != 0 and action != tf_trend:
    action = 0  # Filter: 1h en 4h oneens
```

**Uitbreiding mogelijk:** Week-chart als derde filter voor swing trades

---

## 8. SENTIMENT & EXTERNE SIGNALEN

### Fear & Greed Index
- Score 0-25: Extreme Fear → contrarian buy kans
- Score 25-45: Fear → voorzichtig bullish
- Score 55-75: Greed → voorzichtig bearish
- Score 75-100: Extreme Greed → contrarian sell kans
- Gebruikt als modifier (±15%), niet als primair signaal

### Funding Rate (Futures)
- Positief funding (longs betalen shorts): te veel longs → bearish druk
- Negatief funding (shorts betalen longs): te veel shorts → bullish druk
- Als funding rate confirmeert signaal → confidence ×1.2
- Als funding rate tegen signaal ingaat → confidence ×0.8

### Order Book Analyse
- Bid/ask imbalans: meer bids dan asks → bullish druk
- Whale detectie: grote orders die order book domineren
- Spreekt het signaal → extra 10% confidence
- Gebruikt als modifier (10%), niet als primair signaal

---

## 9. TRADING BESLISLOGICA — WANNEER HANDELEN

### Confluence Regels (hoe meer, hoe beter)

**Sterke LONG setup (minimum 3 van de volgende):**
1. EMA9 > EMA21 op beide 1h en 4h
2. RSI stijgend uit oversold zone (<35) of bullish divergentie
3. Prijs in Bullish Order Block zone
4. Wyckoff Spring of Accumulation fase
5. Bullish Market Structure (HH+HL) + pullback naar HL
6. Volume boven gemiddelde bij de move omhoog
7. Fear & Greed < 35 (sentiment contrarian)
8. Bullish liquidity sweep onder recent low

**Sterke SHORT setup (minimum 3 van de volgende):**
1. EMA9 < EMA21 op beide 1h en 4h
2. RSI dalend uit overbought zone (>65) of bearish divergentie
3. Prijs in Bearish Order Block zone
4. Wyckoff Upthrust of Distribution fase
5. Bearish Market Structure (LH+LL) + rally naar LH
6. Volume boven gemiddelde bij de move omlaag
7. Fear & Greed > 75 (sentiment contrarian)
8. Bearish liquidity sweep boven recent high

### Wanneer NIET handelen
- Regime = HIGH_VOL: geen normale posities, alleen kleine if nodig
- 1h en 4h eens niet: wachten op bevestiging
- Drawdown > 10%: positiegroottes halveren
- Drawdown > 15%: STOP (bot stopt automatisch)
- Anomalie detectie triggert: afhankelijk van ernst

### Entry/Exit Logica
- **Entry:** Altijd market order (crypto is 24/7 liquide)
- **SL:** Direct bij entry plaatsen — nooit zonder stop lopen
- **TP1 (50% positie):** Op 2x ATR afstand → partial close
- **TP2 (resterende 50%):** Op 4x ATR afstand of trailing stop
- **Trailing:** Volgt de prijs op 5% afstand, nooit omlaag

---

## 10. PARAMETEROVERZICHT & TUNING

### .env Configuratie

```env
SYMBOL=BTC/USDT              # Primair handelspaar
SYMBOLS=BTC/USDT,ETH/USDT    # Multi-asset (komma-gescheiden)
TIMEFRAME=1h                  # Primaire tijdsframe
INTERVAL=60                   # Seconden tussen analyse cycli
CAPITAL=10000                 # Startkapitaal in USDT
LIVE=false                    # ALTIJD false houden tenzij expliciet gevraagd
MULTI_ASSET=true              # Meerdere munten tegelijk

MAX_DRAWDOWN=0.15             # 15% max verlies dan stop
MIN_CONFIDENCE=0.32           # Minimum signaalzekerheid voor trade
KELLY_FRACTION=0.25           # Fractie van Kelly (0.25 = voorzichtig)
ATR_SL_MULTIPLIER=2.0         # SL afstand in ATR eenheden
ATR_TP_MULTIPLIER=4.0         # TP afstand in ATR eenheden
TRAILING_STOP_PCT=0.05        # 5% trailing stop
MAX_POSITION_PCT=0.90         # Max 90% van kapitaal in één trade

RL_WEIGHT=0.30                # RL agent gewicht in combiner
LSTM_WEIGHT=0.20              # LSTM gewicht in combiner
RETRAIN_HOURS=84              # Auto-retrain interval (2× per week)

MODEL_PATH=models/rl_model    # RL model locatie
LSTM_PATH=models/lstm_model   # LSTM model locatie

TELEGRAM_TOKEN=...            # Telegram bot token
TELEGRAM_CHAT_ID=2143385750   # Telegram chat ID (let op: begint met 2)
```

### Welke Parameters het Meeste Impact Hebben

| Parameter | Effect | Richting voor meer trades | Richting voor veiligheid |
|-----------|--------|--------------------------|--------------------------|
| MIN_CONFIDENCE | Drempel voor trades | Verlagen naar 0.25 | Verhogen naar 0.40 |
| BOLDNESS (in signals.py) | ConfidenceBrain agressiviteit | Verhogen naar 0.75 | Verlagen naar 0.50 |
| ATR_SL_MULTIPLIER | Hoe ver SL staat | Verlagen naar 1.5 | Verhogen naar 2.5 |
| ATR_TP_MULTIPLIER | Hoe ver TP staat | Verhogen naar 5.0 | Verlagen naar 3.0 |
| KELLY_FRACTION | Positiegrootte | Verhogen naar 0.35 | Verlagen naar 0.15 |
| MAX_DRAWDOWN | Stop-loss op portfolio | Verhogen naar 0.20 | Verlagen naar 0.10 |

### Performance Metrics Interpretatie

| Metric | Slecht | Gemiddeld | Goed | Uitstekend |
|--------|--------|-----------|------|------------|
| Win Rate | <40% | 40-50% | 50-60% | >60% |
| Profit Factor | <1.0 | 1.0-1.5 | 1.5-2.0 | >2.0 |
| Sharpe Ratio | <0.5 | 0.5-1.0 | 1.0-2.0 | >2.0 |
| Sortino Ratio | <0.7 | 0.7-1.5 | 1.5-3.0 | >3.0 |
| Max Drawdown | >25% | 15-25% | 8-15% | <8% |
| Return/MDD | <1.0 | 1.0-2.0 | 2.0-4.0 | >4.0 |

**Profit Factor = total winst / total verlies.** Onder 1.0 = verlieslatend.  
**Sortino > Sharpe voor trading:** bestraft alleen downside volatiliteit.  
**Return/MDD ratio:** betere metric dan alleen return — houdt risico rekening.

---

## 11. BACKTEST RESULTATEN & BEKENDE PROBLEMEN

### Actuele Performance (2026-05-07)

| Metric | Waarde | Status |
|--------|--------|--------|
| Win Rate | 50.0% | GOED |
| Profit Factor | 1.07 | GEMIDDELD (stijgende lijn) |
| Portfolio PnL | -0.38% | NEUTRAAL |
| Max Drawdown | 0.5% | UITSTEKEND |
| Gesloten trades | 26 | OPBOUWEND |
| Open posities | 31 | NORMAAL (multi-asset) |

**Evolutie:** apr 26 (WR 20%, PF 0.45) → mei 1 (WR 30%) → mei 7 (WR 50%, PF 1.07)

**Huidige config:**
```env
MIN_CONFIDENCE=0.35
ATR_SL_MULT=2.5
ATR_TP_MULT=5.0
RL_WEIGHT=0.10
LSTM_WEIGHT=0.20
RETRAIN_HOURS=84
```

**Bot herstarten (correct commando):**
```bash
kill $(pgrep -f bot.py)
nohup /home/pi/crypto_bot/venv/bin/python bot.py > logs/bot_$(date +%Y%m%d).log 2>&1 &
```

### Bekende Issues

1. **LSTM val_acc 37.5%:** Drie symbolen samen getraind → model heeft moeite. Oplossing: per-symbool modellen of langer trainen.
2. **Grid Trading laag gewicht (5%):** Correct — grid werkt alleen in ranging markt.
3. **LSTM zonder training:** Als model niet gevonden → LSTM geeft (0, 0.0) terug → alleen strategieën en RL.

### Verbeteringsrichtingen

**Open (wachten op meer data):**
- Na 50+ closed trades: `grade_stats` analyseren (A vs B vs C win rate)
- Trade clustering heatmap (uur × dag × regime)
- Top 5 winstgevende setups identificeren

**Middellange termijn:**
- Per-symbool LSTM modellen (betere val_acc dan gecombineerd)
- Ensemble LSTM (3 modellen gemiddeld)
- Liquidity heatmap module

**Lange termijn:**
- Meta-Learner (3× gespecialiseerde LSTM + XGBoost)
- Presets: "Range killer" / "Trend rider"
- Story per trade in dashboard

---

## 12. ADAPTIEVE GEWICHTEN — HOE HET SYSTEEM LEERT

```python
# Na elke gesloten trade wordt bijgewerkt:
for strategy_name, signal_action in last_signals.items():
    if signal_action != 0:  # Strategie had een mening
        correct = (signal_action × actual_pnl) > 0
        history[strategy_name].append(1.0 if correct else 0.0)

# Gewichtsmultiplier berekening (over laatste 40 trades):
accuracy = sum(history) / len(history)
multiplier = 0.5 + (accuracy - 0.40) / 0.20
# 40% accuracy → 0.5x | 50% accuracy → 1.0x | 60% accuracy → 1.5x
multiplier = max(0.3, min(2.0, multiplier))
```

**Gevolg:** Strategieën die consistent goed presteren → meer gewicht  
**Gevolg:** Slecht presterende strategieën → gewicht daalt maar nooit onder 0.3x  
**Reset:** Na herstart van de bot beginnen gewichten opnieuw op 1.0x  
**Minimaal 10 samples** nodig voordat gewicht aanpast

---

## 13. TELEGRAM INTERFACE

**Commando's die de gebruiker kan sturen:**
- `/bal` — Portfolio waarde, PnL%, drawdown, vrij kapitaal, regime
- `/stats` — Win rate, avg PnL, beste/slechtste trade
- `/posities` — Alle open posities met entry, huidige prijs, PnL, SL, TP
- `/stop` — Bot stopt (posities blijven open op exchange)

**Automatische meldingen:**
- Bij elke trade: symbool, richting, prijs, PnL
- Dagelijkse samenvatting om 08:00
- Weekrapport elke zondag 09:00 met equity grafiek
- Anomalie alerts bij extreme marktomstandigheden
- Error alerts bij technische fouten

**Telegram Chat ID:** 2143385750 (let op: begint met 2, niet 3)

---

## 14. TRADING PSYCHOLOGIE (voor de bot)

De grootste fouten die een trading bot maakt — en hoe ze hier vermeden worden:

**Overtrading:** Te veel trades nemen op zwakke signalen → `min_confidence` + `threshold`  
**Analysis Paralysis:** Nooit een trade nemen → `ConfidenceBrain` verlaagt threshold  
**Revenge Trading:** Na verlies te groot gokken → Kelly + max_portfolio_risk  
**FOMO:** In een al vergevorderde trend instappen → BOS check + multi-timeframe filter  
**Geen SL:** Verliesposities vasthouden → ATR-SL altijd direct bij entry  
**Pyramiding in verlies:** Extra kopen terwijl positie verliest → pyramiding alleen bij winst

---

## 15. MARKTCYCLUS BEGRIP

Crypto volgt een cyclisch patroon dat Wyckoff al in 1930 beschreef:

```
Accumulation → Markup → Distribution → Markdown → Accumulation (herhaling)
    ↑                                                        ↑
  (kopen)                                               (kopen opnieuw)
```

**Hoe te identificeren:**
- **Accumulation:** Lage volatiliteit, dalend volume, prijs consolideert
- **Markup:** Stijgende trend, hoger volume, HH+HL structuur
- **Distribution:** Lage volatiliteit bovenaan, afnemend volume
- **Markdown:** Dalende trend, hoger volume, LH+LL structuur

**Bitcoin Halving Cyclus:** Elke ~4 jaar halveert het mining reward → supply shock → bull run  
**Funding Rates:** Extreem hoge positieve funding = markt is te bullish = keer aankomend

---

## 16. SNEL STARTEN IN EEN NIEUWE SESSIE

Als je in een nieuwe sessie bent, controleer direct:

1. `python bot.py --backtest` om huidige performance te zien
2. Kijk naar win_rate en profit_factor — onder 1.0 = probleem
3. Check `logs/state.json` voor huidige bot status
4. Check `logs/performance.json` voor equity curve

**Meest voorkomende taken:**
- Bot presteert slecht: tune `MIN_CONFIDENCE` en herrun backtest
- Bot handelt niet: verlaag `MIN_CONFIDENCE` of `boldness` in ConfidenceBrain
- Nieuwe strategie toevoegen: maak klasse in `strategies/`, voeg toe aan `SignalCombiner.strategies` list
- Telegram werkt niet: check `TELEGRAM_TOKEN` en `TELEGRAM_CHAT_ID` in `.env`
- LSTM niet geladen: run `python bot.py --train` eerst

---

*Dit document bevat de complete trading intelligence en projectkennis voor de Monster Crypto Bot. Alle beslissingen worden genomen op basis van confluente signalen, strikte risicobeheer en adaptieve gewichten. De bot is gebouwd om consistent te handelen — nooit bevriezen, nooit overhandelen.*
