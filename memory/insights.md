# Monster Bot — Inzichten & Patronen

Dit bestand wordt bijgehouden door de `bot-analyst` agent.
Bevat niet-voor-de-hand-liggende patronen uit de trade data.

---

## Analyse — 2026-05-20

**Data:** 42 gesloten trades | WR 40.5% | Gem. winst +1.44% | Gem. verlies -0.73%

### Beste handelstijden

| Uur (UTC) | WR   | Gem. PnL | n  |
|-----------|------|----------|----|
| 04u       | 100% | +1.04%   | 3  |
| 09u       | 67%  | +0.01%   | 3  |
| 18u       | 50%  | +1.22%   | 2  |
| 20u       | 50%  | +0.69%   | 4  |
| 22u       | 50%  | +0.07%   | 4  |

Uren 04u en 09u UTC zijn de meest winstgevende periodes. 04u UTC is ochtend Aziatische slotperiode / vroeg-Europese pre-market, 09u UTC is Europese opening — traditioneel momenten met gerichtere marktbewegingen.

**Beste weekdagen:** Woensdag (WR 64%, n=11), Maandag (WR 60%, n=5), Dinsdag (WR 50%).

### Slechtste handelstijden

| Uur (UTC) | WR  | Gem. PnL | n  |
|-----------|-----|----------|----|
| 02u       | 0%  | -1.56%   | 2  |
| 12u       | 0%  | -0.74%   | 3  |
| 23u       | 0%  | -0.32%   | 3  |
| 05u       | 25% | -0.48%   | 4  |

Uur 02u UTC is de stille Aziatische nacht, 12u UTC is lunchtijd Europa (lage liquiditeit), 23u UTC is laat-Amerikaanse avond voor marktsluit. **Aanbeveling: overweeg uur 02u, 12u en 23u te blokkeren** — alle drie hebben WR 0-25% met voldoende sample size (n>=2).

**Slechtste weekdagen:** Donderdag (WR 0%, n=5), Vrijdag (WR 14%, n=7). Dit is opvallend — crypto heeft historisch zwakke vrijdagen door weekendliquiditeitsvrees.

### Revenge trading

**Licht aanwezig maar niet alarmerend.**

- Na verlies: WR 38% (n=24)
- Na winst: WR 47% (n=17)
- Verschil: 9 procentpunt lagere WR na een verlies

De bot presteert merkbaar slechter na een verlies. Dit is geen klassieke revenge trading (groter gokken), maar wel een patroon dat wijst op slechte marktomstandigheden die opeenvolgend verlies veroorzaken — consistent met de bevinding van de langste verliesreeks van 8 op rij en 2 reeksen van 3+.

### Winnende signaalcombinaties

**Top performers (WR >= 50% met n >= 9):**

| Strategie     | WR  | Gem. PnL | n  |
|---------------|-----|----------|----|
| OrderBook     | 67% | +0.34%   | 9  |
| SMC           | 57% | +0.29%   | 14 |
| MarketStructure | 50% | +0.32% | 18 |
| EMA_Cross     | 50% | +0.60%   | 10 |

**Sterkste combinatie:** OrderBook + SMC signalen aanwezig tegelijkertijd. OrderBook detecteert institutionele druk, SMC detecteert order blocks en liquidity sweeps — dit zijn complementaire institutionele strategieën die samen het betrouwbaarste signaal geven.

### Verliezende signaalcombinaties

**Underperformers (WR < 40% met n >= 7):**

| Strategie | WR  | Gem. PnL | n  |
|-----------|-----|----------|----|
| Wyckoff   | 29% | -0.13%   | 7  |
| MACD      | 30% | -0.43%   | 10 |
| Grid      | 31% | +0.13%   | 13 |
| Bollinger | 33% | -0.06%   | 12 |
| RL_Agent  | 36% | +0.07%   | 25 |

MACD is de meest schadelijke strategie (WR 30%, gem. PnL -0.43%). Grid Trading scoort 31% WR — logisch want 81% van trades zijn in ranging regime, maar grid vereist nauwe ranges. De RL_Agent is aanwezig in 25 trades (bijna alles) maar scoort slechts 36% — dit is zorgwekkend want RL heeft 30% gewicht.

### Per-symbool karakteristieken

| Symbool   | WR  | Gem. PnL | SL-ratio | n  |
|-----------|-----|----------|----------|----|
| SOL/USDT  | 53% | +0.62%   | 33%      | 15 |
| BTC/USDT  | 38% | -0.11%   | 50%      | 8  |
| ETH/USDT  | 32% | -0.12%   | 42%      | 19 |

SOL is duidelijk het best presterende symbool (enige met WR > 50%). ETH is het slechtste symbool ondanks het hoogste aantal trades. BTC heeft de hoogste stop-loss ratio (50%) — elke 2e trade raakt de stop.

### Regime analyse

| Regime      | WR   | Gem. PnL | n  |
|-------------|------|----------|----|
| bull_trend  | 100% | +2.65%   | 1  |
| accumulation| 100% | +0.01%   | 1  |
| bear_trend  | 67%  | +0.26%   | 6  |
| ranging     | 32%  | +0.06%   | 34 |

**Cruciaal inzicht:** 81% van alle trades (34/42) vindt plaats in ranging regime, maar WR is daar slechts 32%. Bear trend heeft WR 67% — de bot handelt beter in bear dan ranging. Dit suggereert dat ranging-detectie te breed is of dat de strategieën slecht gecalibreerd zijn voor zijwaartse markten.

### Exit-reden analyse

| Reden              | WR   | Gem. PnL | n  |
|--------------------|------|----------|----|
| TAKE-PROFIT-2      | 100% | +2.44%   | 8  |
| TIME-EXIT          | 100% | +0.36%   | 2  |
| regime_exit        | 50%  | -0.01%   | 12 |
| omgekeerd_signaal  | 33%  | +0.65%   | 3  |
| STOP-LOSS          | 0%   | -0.93%   | 17 |

40.5% van alle trades eindigt op stop-loss. Het doel is max 30%. Regime_exit (29% van trades) heeft WR 50% — dit is een neutrale uitgang die soms winst pakt maar even vaak niet. TP2 trades zijn veruit de beste (gem. +2.44%) maar slechts 19% van trades bereikt TP2.

### Stop-loss kwaliteit

- SL-hits: 17/42 trades (40.5%) — **te hoog, doel is <30%**
- Gem. SL verlies: -0.93%
- Grootste SL: -1.84%
- BTC heeft meeste SL relatief: 50% van BTC trades raakt SL

De stops staan niet te vroeg (SL verlies is beperkt tot -0.93% gem.), maar er zijn te veel SL-hits. Dit wijst op te krappe stops of te veel entries in de verkeerde richting.

### Meest opvallende bevinding

**De ranging-val:** 81% van de trades wordt genomen in ranging regime, maar slechts 32% wint. Tegelijkertijd scoort bear_trend 67% WR. De bot is in een paradox: hij handelt het meest wanneer de markt het slechtst voor hem is. De RL_Agent (30% gewicht, aanwezig in 60% van trades) scoort slechts 36% WR — hij draagt systematisch bij aan slechte beslissingen in ranging markten. Wanneer de markt treint (bear of bull) presteert de bot uitstekend, maar hij krijgt te weinig kansen in trendmarkten omdat de regime-detector te snel "ranging" classified.

### Aanbeveling

**Blokkeer uur 02u, 12u en 23u UTC + verhoog de ranging-regime-drempel.**

Het blokkeren van de 3 slechtste uren (0% WR, samen 8 trades) verwijdert direct verliesgevende handelsmomenten. Tegelijkertijd moet de regime-detector kritischer worden: nu gaat 81% van trades als "ranging", terwijl bear/bull trades veel beter presteren. Overweeg `RANGING_THRESHOLD` strenger te stellen zodat meer trades in bear/bull regime vallen waar de bot WR 67-100% haalt in plaats van 32%.

---

## Beste handelstijden (UTC)

Zie analyse 2026-05-20: **04u en 09u UTC** zijn meest winstgevend.

## Slechtste handelstijden (UTC)

Zie analyse 2026-05-20: **02u, 12u en 23u UTC** — WR 0%, blokkeer aanbevolen.

## Winnende signaalcombinaties

Zie analyse 2026-05-20: **OrderBook + SMC** is de sterkste combinatie (67% + 57% WR).

## Verliezende signaalcombinaties

Zie analyse 2026-05-20: **MACD en Wyckoff** zijn consistent verliesgevend in huidige markt.

## Entry timing analyse

Trade duur niet meetbaar (geen entry_time in gesloten trades), maar regime_exit patronen tonen dat veel trades te lang open staan in ranging markt.

## Stop-loss kwaliteit

Stops staan niet te vroeg (-0.93% gem. SL verlies is acceptabel), maar 40.5% SL-ratio is te hoog. Entries zijn te vaak fout gericht.

## Revenge trading patronen

Licht patroon aanwezig: WR 38% na verlies vs 47% na winst. Geen extreme revenge trading, wel een systeem dat lijdt in slechte marktomstandigheden (verliesreeksen van 8).

## Per-symbool karakteristieken

SOL outperformt (WR 53%), ETH underperformt (WR 32%). Overweeg ETH te deprioriteren of aparte parameters.

## Historische bevindingen

- **2026-05-20:** Eerste volledige analyse. 42 trades. WR 40.5%. Grootste probleem: ranging-regime trap (81% trades in ranging, slechts 32% WR). RL_Agent underperformt (36%). Beste strategie: OrderBook (67%). Beste symbool: SOL (53%). Aanbeveling: blokkeer uren 02u/12u/23u UTC.

---

*Laatste analyse: 2026-05-20 door bot-analyst*
