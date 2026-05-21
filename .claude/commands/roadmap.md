# /roadmap — Roadmap status

Toon de huidige roadmap status en wat er nog open staat.

## Stappen

Lees de volgende bestanden:
- `memory/bot_changelog.md` (sectie Roadmap en Mijlpalen)
- `memory/insights.md` (meest recente analyse)

```bash
cd /home/pi/crypto_bot && venv/bin/python -c "
import json
from pathlib import Path
from datetime import datetime

trades = json.loads(Path('logs/trades.json').read_text()) if Path('logs/trades.json').exists() else []
closed = [t for t in trades if t.get('type') in ('sell','cover')]
pnls = [t.get('pnl_pct',0) for t in closed]
wins = [p for p in pnls if p > 0]
wr = len(wins)/len(pnls) if pnls else 0

print(f'Vandaag: {datetime.now().strftime(\"%Y-%m-%d\")}')
print(f'Closed trades: {len(closed)} (target week 1: 62)')
print(f'Win Rate: {wr:.1%} (target: richting 50%)')
print(f'Voortgang: {len(closed)-42} nieuwe trades sinds MIN_CONF=0.46 (doel: 20)')
"
```

## Output formaat

Geef een duidelijk overzicht:

**Week 1 (t/m 2026-05-27) — [ACTIEF/KLAAR]**
- Hoeveel nieuwe trades zijn er bijgekomen?
- Gaat de WR richting 50%?
- Wat is de conclusie: doorgaan of aanpassen?

**Week 2 (~2026-05-27) — Correlatie-filter**
- Kort wat dit inhoudt
- Is het al eerder dan gepland nodig?

**Week 3 (~2026-06-03) — LSTM per symbool**
- Zijn er al 50+ closed trades?
- Wat is de huidige LSTM val_acc status?

**Backlog**
- Ranging WR verbeteren
- TP1 reach rate verhogen
- Tijdstip-filter slechte uren

Communiceer in het Nederlands.
