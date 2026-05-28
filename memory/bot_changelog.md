# Monster Bot — Wijzigingen & Beslissingen

Dit bestand wordt bijgehouden door de `bot-cleanup` agent.
Bevat alle relevante parameterwijzigingen, resultaten, en beslissingen.
Irrelevante oude snapshots worden hier samengevat zodat ze uit config_history.json verwijderd kunnen worden.

---

## Huidige Config (actueel)

| Parameter | Waarde | Gewijzigd op |
|-----------|--------|--------------|
| MIN_CONFIDENCE | 0.46 | 2026-05-20 |
| ATR_SL_MULT | 2.5 | 2026-05-12 |
| ATR_TP_MULT | 5.0 | 2026-05-12 |
| RL_WEIGHT | 0.10 | 2026-05-15 |
| LSTM_WEIGHT | 0.00 | 2026-05-19 (val_acc 37.2% ≈ random) |
| RETRAIN_HOURS | 84 | vast |
| SYMBOLS | BTC/USDT, ETH/USDT, SOL/USDT | vast |
| CAPITAL | 1000 USDT | vast |
| LIVE | false | altijd paper trading |
| MIN_POSITION_PCT | throttle≥50%→5%, throttle<50%→2% | 2026-05-28 — adaptief; voorkomt dat minimum de throttle-bescherming overschrijft |
| RSI_SHORT_BLOCK | 28 in bear_trend | 2026-05-28 — was 35 tenzij strength≥85%; blokkeerde shorts 13u |

---

## Mijlpalen

| Datum | Event | WR | PF | Notitie |
|-------|-------|----|----|---------|
| 2026-04-26 | Eerste trades | 20% | 0.45 | Bot net gestart |
| 2026-05-01 | Verbetering | 30% | — | — |
| 2026-05-07 | Grote sprong | 50% | 1.07 | 26 gesloten trades |
| 2026-05-12 | TP1/TP2 fix + counter-trend | 52.6% | 1.40 | Bugfixes — hoogste WR tot nu toe |
| 2026-05-13 | MIN_CONF 0.35→0.45, short confluence 2→3 | 35.5% | 1.27 | WR daalde: meer filters = minder trades maar slechter |
| 2026-05-14 | Short confluence 3→4 (WR shorts verbeteren) | 35.5% | 1.27 | Geen direct effect gemeten |
| 2026-05-15 | LSTM drempel fix + confluence shorts 4→3 + LSTM gewicht 20%→10% | 35.5% | 1.27 | Meerdere correcties op 1 dag |
| 2026-05-15 | LSTM gewicht 10%→5%, dubbele bot fix | 35.5% | 1.27 | Dubbele instantie was probleem |
| 2026-05-17 | MIN_CONF 0.55→0.28 (engine blokkeerde cf<0.35) | 40.0% | 1.33 | +4.5% WR — correct niveau gevonden |
| 2026-05-17 | MTF accumulation/ranging override | 40.0% | 1.33 | Bot handelt weer na 9.5u stilstand |
| 2026-05-17 | Fix A+B: LSTM drempel regime-afhankelijk + volume avg | 40.0% | 1.33 | LSTM_WEIGHT nog 5% |
| 2026-05-19 | LSTM_WEIGHT 0.05→0.00 (val_acc 37.2% ≈ random) | 37.8% | 1.31 | LSTM tijdelijk uitgeschakeld |
| 2026-05-20 | REGIME_CAP verhoogd + 4h BOS reversal fix | 42.5% | 1.34 | +4.7% WR — goede dag |
| 2026-05-20 | TP1 1.5R→1.2R + regime-exit min 2u holdtijd | 42.5% | 1.34 | Meer TP1 hits verwacht |
| 2026-05-20 | MIN_CONFIDENCE 0.28→0.46 | 41.5% | 1.34 | Verliesgevende bucket 0.35-0.45 geëlimineerd |
| 2026-05-20 | Regime "?" bug fix | 40.5% | 1.34 | 42 trades: WR 40.5%, PF 1.34, PnL -1.84% |
| 2026-05-25 | Ranging correlatie-lock (max 1 pos/groep BTC/ETH/SOL) | 32.7% | 1.047 | 52 trades; verliesstreek 12 in ranging door gecorreleerde posities |
| 2026-05-25 | Ranging TP2 mult 2.0→1.75 (via heal_config.json) | 32.7% | 1.047 | TP1-rate 19% = targets te ver; self-healer poort geopend |
| 2026-05-25 | Self-healer MIN_N 20→10 | 32.7% | 1.047 | Feedbackloop 7→3-4 dagen |
| 2026-05-25 | UPGRADE: 4H ADX Confidence Modifier (>25 trending/< 18 ranging × 0.80) | 32.7% | 1.047 | Zachte reducer voor mismatch oscillator/trend in trending/ranging |
| 2026-05-25 | UPGRADE: ATR Trailing Stop 1.5× (na 0.5× ATR winst) | 32.7% | 1.047 | SL beweegt mee met peak — lock-in profits |
| 2026-05-25 | UPGRADE: Vault Diagnostics Agent (tools/vault_diagnostics.py) | 32.7% | 1.047 | Per-symbool status badges in dashboard |
| 2026-05-25 | UPGRADE: Staleness Check 1h data (>90s na close → skip) | 32.7% | 1.047 | Dataprovider failure protection |
| 2026-05-26 | Ranging skip Filter 1c (ALLE entries in ranging geblokkeerd) | 37.7% | 1.058 | WR ranging 29% n=45; 24u geen trades want alle 3 symbolen in ranging |
| 2026-05-27 | Squeeze exception op ranging skip + Filter 8 ranging exemption | 37.7% | 1.058 | Bot handelt weer: ETH/SOL → accumulation+squeeze; SOL SHORT direct genomen |
| 2026-05-27 | Monitor inactiviteitscheck: alert bij >8u (warning) en >24u (probleem) | 37.7% | 1.058 | Design gap gedicht: agents detecteerden geen handelsdroogte |
| 2026-05-27 | Ranging RSI-zone filter (Filter 1d): long RSI<45, short RSI>55 | 37.7% | 1.058 | Voorkomt kopen aan top/shorten aan bodem van range; TP1 bereikt slechts 23% = te laat ingestapt |

---

## Geprobeerd & Effect

| Wat | Resultaat | Beslissing |
|-----|-----------|-----------|
| MIN_CONF 0.35→0.45 | WR daalde initieel | Doorgewerkt, uiteindelijk 0.46 |
| LSTM gewicht 0.20→0.10→0.05→0.00 | val_acc 37.2% ≈ random | Uitgeschakeld (0.00) |
| RL gewicht 0.30→0.10 | Conservatiever, stabielere signalen | Bewaard op 0.10 |
| ATR_TP 4.0→5.0 | Meer ruimte voor winners | Bewaard op 5.0 |
| ATR_SL 2.0→2.5 | Minder valse stops | Bewaard op 2.5 |
| TP1 multiplier 1.5R→1.2R | Meer TP1 hits verwacht | Bewaard |
| Ranging TP fix (1.5x ATR) | TP dichterbij in ranging | Bewaard |
| Short confluence 3→4→3 | Geen duidelijk effect | Teruggezet op 3 |
| MTF filter bypass accumulation/ranging | Bot handelt weer | Bewaard |
| REGIME_CAP verhoogd | +4.7% WR | Bewaard |
| 4h BOS reversal detectie | Betere trendfiltering | Bewaard |
| MIN_CONF 0.28→0.46 | Verliesgevend bucket geëlimineerd | Bewaard op 0.46 |

---

## Gearchiveerde Snapshots

Snapshots die hieronder staan zijn verwijderd uit config_history.json
maar hier bewaard als referentie.

### Verwijderd op 2026-05-20 (cleanup run)

**ID 2** — `2026-05-12T23:28:07` — baseline gecorrigeerd: finale WR 35.7% / gecombineerd 52.6%
- Zelfde dag als ID 1, gecorrigeerde baseline. Config identiek aan ID 1. Gearchiveerd als dubbel.

**ID 3** — `2026-05-12T23:38:20` — voor fix: MIN_CONF=0.35 geeft WR 39.3%
- Voor-snapshot van MIN_CONF 0.35→0.45 fix. Na-snapshot (ID 4) aanwezig. Gearchiveerd.

**ID 4** — `2026-05-12T23:40:13` — na fix: MIN_CONF=0.45
- Na-snapshot van bovenstaande. Config al lang veranderd. Gearchiveerd.

**ID 5** — `2026-05-13T21:23:25` — baseline voor fixes 13 mei: WR 38.7%, MIN_CONF 0.45
- Voor-snapshot. Na-snapshot (ID 6) aanwezig. Gearchiveerd.

**ID 6** — `2026-05-13T21:24:22` — na fixes 13 mei: MIN_CONF 0.45→0.55, short confluence 2→3
- Na-snapshot. Config daarna verder gewijzigd. WR verandering <5%. Gearchiveerd.

**ID 7** — `2026-05-13T22:38:34` — baseline voor ranging TP fix: TP1>TP2 bug
- Voor-snapshot. Na-snapshot (ID 8) aanwezig. Gearchiveerd.

**ID 8** — `2026-05-13T22:38:48` — na ranging TP fix: ranging (1.5,2.0)→(1.5,2.5)
- Na-snapshot. Gearchiveerd.

**ID 9** — `2026-05-13T22:39:08` — baseline voor LSTM drempel fix: val_acc 33.8%
- Voor-snapshot. Na-snapshot (ID 10) aanwezig. Gearchiveerd.

**ID 10** — `2026-05-13T22:39:30` — na LSTM drempel fix: 0.38→0.50
- Na-snapshot. Gearchiveerd.

**ID 11** — `2026-05-14T14:14:53` — baseline check 14 mei: WR 38.7%, PF 1.207
- Dubbele baseline, identieke config als ID 10. Gearchiveerd.

**ID 12** — `2026-05-14T14:16:32` — baseline voor short confluence fix: WR 38.7%, shorts 33%
- Voor-snapshot. Na-snapshot (ID 13) aanwezig. Gearchiveerd.

**ID 13** — `2026-05-14T14:16:40` — na short confluence fix: 3→4
- Na-snapshot. Gearchiveerd.

**ID 14** — `2026-05-15T10:45:49` — baseline voor LSTM drempel fix: bot tradt niet
- Voor-snapshot. Na-snapshot (ID 15) aanwezig. Gearchiveerd.

**ID 15** — `2026-05-15T10:45:59` — na LSTM drempel fix: 0.50→0.42
- Na-snapshot. Gearchiveerd.

**ID 16** — `2026-05-15T10:55:06` — baseline voor confluence shorts fix: 4→3
- Voor-snapshot. Na-snapshot (ID 17) aanwezig. Gearchiveerd.

**ID 17** — `2026-05-15T10:55:17` — na confluence shorts fix: 4→3
- Na-snapshot. Gearchiveerd.

**ID 18** — `2026-05-15T11:14:28` — baseline voor LSTM gewicht fix: 20%→10%
- Voor-snapshot. Na-snapshot (ID 19) aanwezig. Gearchiveerd.

**ID 19** — `2026-05-15T11:16:28` — na 3 fixes: LSTM gewicht 20%→10%, daily SL limiet, logging
- Na-snapshot van 3 gelijktijdige fixes. Gearchiveerd.

**ID 20** — `2026-05-15T20:21:41` — baseline voor dubbele bot fix + LSTM_WEIGHT 0.10→0.05
- Voor-snapshot. Na-snapshot (ID 21) aanwezig. Gearchiveerd.

**ID 21** — `2026-05-15T20:33:43` — na fixes: dubbele bot opgelost + LSTM_WEIGHT 0.10→0.05
- Na-snapshot. Gearchiveerd.

**IDs 22-28** — `2026-05-16T23:48:56` t/m `2026-05-17T00:13:27` — cluster van 7 voor-snapshots op 16/17 mei
- RSI short-block fix, local-low fix, volume filter fix, volume_ratio fix, MIN_CONFIDENCE fix, local-low 0.95 fix.
- Alle voor-snapshots waarvan de na-snapshots aanwezig waren. Gearchiveerd als cluster.

**ID 29** — `2026-05-17T00:14:18` — na alle fixes: bot handelt weer (SOL short @ 86.54)
- Eindresultaat van de cluster. MIN_CONF 0.28 ingesteld. Gearchiveerd (bewaard via mijlpaal in changelog).

**IDs 30-38** — `2026-05-17T13:50:50` t/m `2026-05-17T14:57:02` — cluster 17 mei middag
- MTF accumulation/ranging fix + override + threshold fixes. WR 40.0%, PF 1.33.
- Alle voor/na-paren aanwezig. Gearchiveerd als cluster.

**ID 39** — `2026-05-17T16:03:59` — baseline check 17 mei 16u: WR 42.9%, PF 1.268
- Dubbele baseline check, identieke config. Gearchiveerd.

**IDs 40-41** — `2026-05-17T17:30:57` t/m `2026-05-17T17:31:20` — Fix A+B
- LSTM drempel regime-afhankelijk + Filter 8 volume avg. Gearchiveerd.

---

## Roadmap

### Week 1 — tot 2026-05-27 (DEZE WEEK — NIETS AANPASSEN)
- [ ] Laat bot draaien met MIN_CONFIDENCE=0.46
- [ ] Wacht op 20 nieuwe trades (nu: 42 closed → target: 62)
- [ ] Meet of WR richting 50% gaat
- [ ] Geen parameters aanpassen — ook niet als je de neiging voelt

### Week 2 — 2026-05-27 (CORRELATIE-FILTER)
- [ ] Correlatie-filter bouwen in bot.py
- [ ] Logica: als BTC/ETH/SOL >90% gecorreleerd zijn, max 1 positie tegelijk
- [ ] Backtest draaien voor/na vergelijking

### Week 3 — 2026-06-03 (LSTM PER SYMBOOL — alleen als 50+ closed trades)
- [ ] Check: zijn er 50+ closed trades?
- [ ] Drie aparte LSTM-modellen trainen: BTC, ETH, SOL
- [ ] LSTM_WEIGHT terug naar 0.15 als val_acc >43%

## Openstaande Acties (backlog)
- [ ] Ranging market WR verbeteren (nu 35%) — hogere confluence-drempel in ranging
- [ ] TP1 reach rate verhogen (nu 26%)
- [ ] Tijdstip-filter: slechte liquiditeitsuren blokkeren (zo 00:00-06:00 UTC)

---

*Laatste update door bot-cleanup: 2026-05-25*

## 2026-05-25 — Noodingreep: correlatie-lock + TP2 fix + feedbackloop

**Aanleiding:** Verliesstreek van 12 op rij, 94% verliezen in ranging regime door gelijktijdige gecorreleerde posities.

### Wijzigingen:
1. **Ranging correlatie-lock** (`bot.py` r.1698): Max 1 positie per gecorreleerde groep (BTC/ETH/SOL) in ranging regime. Blokkeert gelijktijdige verliezen door >90% correlatie.
2. **ranging_tp2_mult 2.0→1.75** (`logs/heal_config.json`): Self-healer override handmatig toegepast. TP1-rate was 19% = targets te ver in ranging markt.
3. **Self-healer MIN_N 20→10** (`tools/self_healer.py`): Feedbackloop versneld van ~7 naar ~3-4 dagen.
4. **Dashboard vault.html**: Correlatie-Guard kamer (F-2½) toegevoegd, panic-mode animaties voor vault boys bij streak ≤-5, HEALER gate toont "ACTIEF".

**Snapshots:** #29 (voor) / #30 (na)
