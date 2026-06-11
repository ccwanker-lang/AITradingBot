# Post-Cooldown Checklist — Definitief Aanvalsplan
**Opgesteld:** 2026-06-03 | **Herzien:** 2026-06-11 (uitgevoerd door Claude)
**Ingangsdatum:** 2026-06-11 (cooldown verlopen — FASE 1 ACTIEF)
**Principe:** één wijziging per 2 weken · minimaal 10 trades per fase · meetbaar effect per stap

> **PLAN REVISIE 11 juni:** Grid (27%→61% WR) en Wyckoff (29%→67% WR) zijn NIET verwijderd —
> data heeft de aanname volledig omgedraaid. MomentumRotation was al niet aanwezig in code.

---

## Baseline meten op 11 juni (VOOR elke aanpassing)

```bash
venv/bin/python tools/check_report.py
```

| Metric | Waarde nu | Doel na alle stappen |
|---|---|---|
| Overall WR | ~45% | ≥55% |
| Post-skip WR | ~54% | ≥58% |
| Profit Factor | ~1.9 | ≥2.20 |
| TP1 reach rate | 28% | ≥35% |

---

## FASE 1 — 11 juni: Cleanup + Confidence Cap ✅ UITGEVOERD

### Wat (uitgevoerd 2026-06-11)
1. ~~**Grid verwijderen**~~ — **GEANNULEERD**: WR was 27%, nu 61% (2.00x gewicht) — BEHOUDEN
2. **StatArb verwijderd** ✅ — ranging geblokkeerd, nul meerwaarde; import/init/update/veto weg
3. ~~**Momentum Rotation verwijderen**~~ — **AL NIET AANWEZIG** in code
4. **Confidence Cap 0.75→0.68** ✅ — ≥0.70 bucket had 36% WR (n=11); cap verlaagd
5. **Auto-optimizer 1×/dag** ✅ — was 4×/dag (`*/6`), nu `0 6 * * *`

### Baseline (snapshot #21)
- WR: 45.1% (32W/39L/71 trades) | PF: 2.025 | R/R: 2.40:1
- Wacht op **10 nieuwe trades**, dan check_report.py voor effect meting

### Confidence Cap implementatie
In `bot.py`, vlak na de confidence berekening:
```python
# Confidence Cap — ≥0.68 is overfit-zone (WR 25% op n=8 trades)
if confidence >= 0.68:
    confidence = 0.67
```

### Auto-optimizer cron
```bash
crontab -e
# Verander:  */6 * * * *  →  0 6 * * *   (1× per dag om 06:00)
```

### signals.py: Grid + StatArb + MomentumRotation verwijderen
- Verwijder imports: `GridTradingStrategy`, `StatArbAnalyzer`, `MomentumRotation`
- Verwijder uit `strategies`-lijst in `SignalCombiner.__init__`
- Verwijder `"Grid"` uit alle `_REGIME_WEIGHTS` en `_REGIME_ACTIVE_STRATEGIES` dicts
- Verwijder het volledige StatArb modifier-blok in `combine()`
- Verwijder `stat_arb_action`, `stat_arb_confidence`, `stat_arb_reason` parameters

### Git commit
```bash
venv/bin/python tools/config_tracker.py snapshot "voor fase1: cleanup + confidence cap"
git add strategies/signals.py bot.py
git commit -m "perf: fase1 — verwijder Grid/StatArb/MomRot + confidence cap 0.68"
venv/bin/python tools/config_tracker.py snapshot "na fase1: cleanup + cap actief"
sudo systemctl restart cryptobot.service
```

### Verwacht effect
- Minder ruis in signaalberekening
- Overfit-zone gesneden → geen entries meer op "te zeker" signalen
- Geen directe WR-klap verwacht (waren al inactief)

### Meet na fase 1
Wacht op **10 nieuwe trades**, dan `check_report.py`.

### Rollback trigger
```
Als WR na 10 trades < 42% EN PF < 1.5
→ git revert HEAD
→ sudo systemctl restart cryptobot.service
```

---

## FASE 2 — ~25 juni: Bollinger verwijderen (Wyckoff HEROVERWEGEN)

### Wat & waarom
- **Wyckoff:** Was 29% WR → nu **67% WR (2.00x gewicht, n=6)** — TOP strategie! BEHOUDEN tenzij WR daalt.
- **Bollinger:** 40% WR (0.39x gewicht, n=10) — zwak, maar niet verlieslatend. Evalueer op data.

### signals.py wijziging
- Verwijder imports + entries voor `BollingerMeanReversionStrategy` en `WyckoffStrategy`
- Verwijder uit alle `_REGIME_WEIGHTS` en `_REGIME_ACTIVE_STRATEGIES`

### Git commit
```bash
venv/bin/python tools/config_tracker.py snapshot "voor fase2: Wyckoff+Bollinger weg"
git add strategies/signals.py
git commit -m "perf: fase2 — verwijder Wyckoff en Bollinger (aantoonbaar verlieslatend)"
venv/bin/python tools/config_tracker.py snapshot "na fase2: 8 strategieën actief"
sudo systemctl restart cryptobot.service
```

### Verwacht effect
- WR +2–5% doordat ruis-signalen confluence-score niet meer verlagen
- Resterende 8 strategieën: EMA_Cross, RSI, MACD, Breakout, SMC, SR, Ichimoku, VolumeProfile, MarketStructure

### Rollback trigger
```
Als WR na 10 trades < (fase1-baseline − 5%)
→ git revert HEAD
```

---

## FASE 3 — ~9 juli: C-grade blokkering activeren

### Wat
C-grade skip is al gedeeltelijk ingebouwd (`analytics/setup_classifier.py` regel 108).
Conditie `has_reliable_edge` vereist ≥5 samples. Tegen juli zijn die er.

### Check of skip al actief is
```bash
grep -A3 "skip = " analytics/setup_classifier.py
```

### Wijziging als samples er zijn
```python
# analytics/setup_classifier.py — als has_reliable_edge al ≥5 samples heeft:
skip = (grade == "C")   # was: skip = (grade == "C") and has_reliable_edge and not edge_positive
```

### Git commit
```bash
venv/bin/python tools/config_tracker.py snapshot "voor fase3: C-grade blokkering"
git add analytics/setup_classifier.py
git commit -m "perf: fase3 — blokkeer alle C-grade setups"
venv/bin/python tools/config_tracker.py snapshot "na fase3: C-grade actief"
sudo systemctl restart cryptobot.service
```

### Verwacht effect
- Minder trades (−10–15%)
- WR +3–6% doordat slechte setups eruit worden gefilterd

### Rollback trigger
```
Als bot >48u geen trades maakt → skip-conditie terug naar origineel
```

---

## FASE 4a — ~23 juli: 15m LSTM als FILTER activeren

### De hiërarchie (definitief vastgesteld)
```
4H  →  strategie  (waar gaan we naartoe?)
1H  →  tactiek    (wanneer instappen?)
15m →  executie   (is dit het juiste moment nu?)
```

De 1H structuur blijft het fundament. De 15m LSTM filtert slechte entry-timing eruit.
Blokkeert ALLEEN als 15m LSTM met >60% confidence tégen de 1H richting zit.
Neutraal of lage confidence = altijd doorgaan (niet blokkeren).

### Voorwaarde — ALLEEN activeren als
```bash
cat logs/lstm_15m_health.json
# val_acc moet ≥ 0.50 zijn (model is betrouwbaar genoeg als filter)
```

### Activatie in bot.py
```python
# In __init__ toevoegen (naast de bestaande self.lstm):
self.lstm_15m        = LSTMPredictor(model_path="models/lstm_15m.pt")
self.lstm_15m_active = Path("models/lstm_15m.pt").exists()

# In _analyze_symbol: verander:
_lstm_15m_active = False   # ← naar:
_lstm_15m_active = getattr(self, "lstm_15m_active", False)
```

### Timeout guardrail (al ingebouwd op 2026-06-04)
De 15m DataFetcher heeft een harde 3s timeout via `concurrent.futures`.
Bij timeout of fout: graceful skip, 1H flow gaat altijd door.

### Git commit
```bash
venv/bin/python tools/config_tracker.py snapshot "voor fase4a: 15m LSTM filter"
git add bot.py
git commit -m "feat: fase4a — 15m LSTM filter activeren (4H→1H→15m hiërarchie)"
venv/bin/python tools/config_tracker.py snapshot "na fase4a: 15m LSTM filter actief"
sudo systemctl restart cryptobot.service
```

### Verwacht effect
- Minder entries (−15–25%) — slechte timing wordt geblokkeerd
- WR +3–6% als val_acc ≥50%
- TP1 reach rate stijgt (betere entry-timing = minder SL-hits)

### Rollback trigger
```
Als WR na 10 trades < (fase3-baseline − 5%) OF bot >48u geen trades
→ _lstm_15m_active = False in bot.py
→ sudo systemctl restart cryptobot.service
```

---

## FASE 4b — na 50+ trades met 4a: 15m LSTM als SCORER

### Voorwaarde
- Fase 4a heeft minimaal 50 trades geproduceerd
- WR is gestegen t.o.v. fase 3 baseline
- val_acc ≥ 0.52

### Wijziging
Voeg 15m LSTM toe als gewogen bijdrage in `SignalCombiner.combine()`:
```python
# In .env toevoegen:
LSTM_15M_WEIGHT=0.10   # start voorzichtig

# In signals.py combine(): 15m LSTM bijdrage naast RL en 1H LSTM
lstm_15m_score = lstm_15m_action * lstm_15m_conf * lstm_15m_w
total_score += lstm_15m_score
```

### Rollback trigger
```
Als WR na 10 trades daalt t.o.v. fase 4a baseline
→ LSTM_15M_WEIGHT=0.00
→ sudo systemctl restart cryptobot.service
```

---

## Tijdlijn overzicht

```
11 jun  ── FASE 1: Grid + StatArb + MomRot weg + Conf Cap 0.68 + optimizer 1×/dag
           Wacht 2 weken + min. 10 trades
25 jun  ── FASE 2: Wyckoff + Bollinger weg              (verwacht WR +2–5%)
           Wacht 2 weken + min. 10 trades
 9 jul  ── FASE 3: C-grade blokkering                   (verwacht WR +3–6%)
           Wacht 2 weken + min. 10 trades
23 jul  ── FASE 4a: 15m LSTM als filter                 (verwacht WR +3–6%)
           Wacht op 50+ trades
??      ── FASE 4b: 15m LSTM als scorer                 (conditioneel)
```

---

## Go/No-Go op 11 juni

```bash
venv/bin/python tools/check_report.py 2>/dev/null | head -60
```

**Go** als: WR ≥45% post-skip EN geen open posities met verlies >5%
**No-Go** als: bot in verliesreeks (>3 op rij) — wacht tot markt stabiliseert

---

## Architectuurprincipes (definitief vastgesteld 2026-06-04)

1. **Eén wijziging per fase** — effect moet meetbaar zijn voordat volgende stap start
2. **2 weken + 10 trades minimum** per fase — geen haast
3. **15m is NOOIT primair** — 1H blijft de beslissingslaag, 15m is precisie
4. **Timeout guardrail** — 15m fetch max 3s, nooit de 1H flow blokkeren
5. **Rollback altijd klaar** — elke fase heeft een expliciete rollback trigger
