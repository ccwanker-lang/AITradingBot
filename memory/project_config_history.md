
## 2026-06-15 — RSI-overbought regime-fix (snapshot #40→#41)

- **Wat**: `bot.py:1788-1801` Filter 5 — RSI-overbought long-blokkade regime-bewust gemaakt
- **Oud**: `elif action == 1 and rsi_now > 72:` → álle longs geblokkeerd bij RSI>72, ongeacht regime
- **Nieuw**: `_rsi_long_block = 82 if regime.regime.value == "bull_trend" else 72` en `elif action == 1 and rsi_now > _rsi_long_block:`
- **Reden**: bot opende 0 posities tijdens sterke bull-run (15 juni). state.json no_trade_reasons toonde BTC/ETH/SOL alle drie "RSI overbought — geen longs". Regime was bull_trend 89-97%. In sterke trend blijft RSI lang >72 → bot mist exact de move. Asymmetrie: short-blokkade (regel 1795) was al regime-bewust (28 in bear vs 35), long-blokkade niet.
- **Drempel-effect (RSI dit moment)**: BTC 74 → vrijgegeven ✓ | ETH 89 → nog geblokkeerd (terecht, extreem) | SOL 84 → nog geblokkeerd
- **Risico**: bot koopt iets later in de trend; bij 82 nog steeds bescherming tegen de absolute top. Mogelijk meer longs in pump → meten op WR/SL-hit.
- **Wijziging**: 1 parameter (long-blokkade drempel). Geen andere wijziging.
- **Resultaat**: TBD — meten bij volgende check (longs in bull_trend, WR-effect)

## 2026-06-13 — Fase A bugfixes (Fable 5 review, snapshot #30→#31)

Geen parameterwijzigingen — alleen bugfixes zonder trading-impact:

| Fix | Bestand | Oud → Nieuw |
|-----|---------|-------------|
| A1 Pyramid KeyError | bot.py:2041 | `result['stop_loss']` crash → eigen PYRAMID-melding, .get() overal |
| A2 _strong_bear NameError | bot.py:1791 | binnen if-blok → erbuiten (Filter 6 gebruikt het ook) |
| A3 Heal datum | bot.py:921 | _cmd_heal_status poort 27/05 → 11/06 (gelijk aan approve_heal) |
| A4 Daily SL melding | bot.py:1136 | "geen trades tot morgen" (onwaar, pauze uit) → eerlijke waarschuwing; pause_until wordt niet meer gezet |
| A5 Vault val_acc | vault_app.py:70 | lstm_health.json (bestaat niet) → lstm_1h_health.json eerst |
| A6 get_status dedup | bot.py:1239 | 3× per tick → 1× (_tick_status) |
| A7 engine_state cap | paper_engine.py:391 | trade_history volledig → laatste 500 (SD-kaart bescherming) |

Reden: review 13 juni (memory/fable5_upgrade_plan.md). Risico: minimaal — geen beslislogica geraakt.
Resultaat: TBD — meten bij volgende check. Volgende stap: Fase B1 (short-fee fix).

## 2026-06-13 — B1: Short-fee fix (snapshot #32→#33)

- **Wat**: `paper_engine.py` `_close_position` + `_partial_close` (short branch)
- **Oud**: `pnl = (entry - price) * size * (1 - fee)` — fee op PnL: verliezen werden kléiner, winsten bijna fee-vrij
- **Nieuw**: `pnl = (entry - price) * size - (size * price * fee)` — fee over terugkoop-notional zoals bij longs
- **Reden**: 53/71 trades zijn shorts → alle metingen waren geflatteerd (~1.1 USDT te positief per $1000-positie)
- **Baseline vóór fix**: WR 42.3%, PF 2.028, 71 trades — historische trades blijven ongewijzigd, alleen NIEUWE shorts krijgen eerlijke fees
- **Risico**: WR/PF dalen licht op nieuwe trades — dat is meet-correctie, geen prestatie-verlies
- **Verificatie**: numerieke test win (+49.00 ✓) en verlies (−51.00 ✓, was −49.90)
- **Resultaat**: TBD — vergelijk PF na 20 nieuwe shorts met baseline

## 2026-06-13 — B2: Breakeven-label (snapshot #34→#35)

- **Wat**: `paper_engine.py _close_position` — als exit=STOP-LOSS en SL binnen ±0.05% van entry → reason="BREAKEVEN"
- **Reden**: breakeven-stops (SL naar entry verplaatst op halverwege TP1) telden als verlies + STOP-LOSS → WR pessimistischer dan echt, en triggerden onterecht SL-cooldown (4u) + daily SL teller
- **Neveneffect (gewenst)**: BREAKEVEN triggert GEEN SL-cooldown en GEEN daily SL teller meer (bot.py checkt reason=="STOP-LOSS")
- **Telegram**: ⚖️ emoji voor BREAKEVEN exits
- **Verificatie**: test SL-op-entry → BREAKEVEN (pnl −0.20% = fees), echte SL → STOP-LOSS ✓
- **Meting**: in check-rapporten verschijnt BREAKEVEN nu als aparte exit-reden; echte WR = wins / (wins + echte losses excl. breakeven)
- **Resultaat**: TBD — meten bij volgende check

## 2026-06-13 — C1: LSTM drempel herkalibratie + gewicht (snapshot #36→#37)

- **Aanleiding**: nieuw 1h-LSTM (val_acc 78.9%) hersteld na corrupte scp-overdracht. Meting op 1026 voorspellingen (laatste 500 candles × 3 symbolen): model is binair (2-klasse) en sterk **overconfident** — mediaan conf = **1.000**, mean 0.967, p10 0.899, min 0.500. Bearish skew (BTC 234/108, SOL 255/87).
- **Wijziging 1 — gate-floor** (`strategies/signals.py:420`): `_lstm_min_conf = 0.35/0.42 (regime-afh.)` → **`0.55` (vlak)`. Oude gates deden niets (binaire conf altijd ≥0.5). 0.55 mut alleen de zeldzame ~split-voorspellingen.
- **Wijziging 2 — gewicht** (`.env:22`): `LSTM_WEIGHT=0.10` → **`0.05`**. Model duwt nu bij élk signaal mee (conf-grootte onbruikbaar, was eerder vaak gemuted) + bearish skew → halvering compenseert zonder nieuwe parameters.
- **Reden**: conf-magnitude is geen bruikbare fijnregelaar voor dit verzadigde model; de richting (78.9%) is het signaal. Optie 3 gekozen door Overseer.
- **Risico**: LSTM kan netto bearish bias toevoegen; daarom gewicht gehalveerd. Bij WR-daling: LSTM_WEIGHT→0.00 of floor terug.
- **Terugdraaien**: `signals.py` floor → `0.35/0.42`-regel; `.env` LSTM_WEIGHT → 0.10.
- **Resultaat**: TBD — meten na 10 nieuwe trades (check_report.py)

## 2026-06-14 — LSTM_WEIGHT 0.05 → 0.10
- **Bestand:** `.env`, parameter `LSTM_WEIGHT`
- **Oud → nieuw:** 0.05 → 0.10
- **Reden:** Handboek (Fase 1, 11 juni) noteert LSTM heringeschakeld naar 0.10 na val_acc 65.6%, maar `.env` stond nog op 0.05. Inconsistentie rechtgezet op verzoek Overseer.
- **Risico:** LSTM krijgt meer gewicht in de combiner (strategie 50% + RL 10% + LSTM 10%). Bij ruis-predicties kan dit valse signalen versterken. Val_acc 65.6% is echter ruim boven random.
- **Resultaat:** TBD — meten bij volgende check (let op WR-trend + LSTM-bijdrage in entry_reasons)
