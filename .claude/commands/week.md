# /week — Weekoverzicht

Geef een volledig weekoverzicht van de bot prestaties. Vergelijk met de vorige week en toon de roadmap status.

## Stappen

```bash
cd /home/pi/crypto_bot && venv/bin/python -c "
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

trades = json.loads(Path('logs/trades.json').read_text()) if Path('logs/trades.json').exists() else []
closed = [t for t in trades if t.get('type') in ('sell','cover')]

now = datetime.now()
week_ago = now - timedelta(days=7)
two_weeks_ago = now - timedelta(days=14)

def week_stats(trades_list, from_dt, to_dt):
    week = [t for t in trades_list if t.get('timestamp') and from_dt <= datetime.fromisoformat(str(t['timestamp'])[:19]) < to_dt]
    if not week: return None
    pnls = [t.get('pnl_pct',0) for t in week]
    wins = [p for p in pnls if p > 0]
    return {
        'n': len(week),
        'wr': len(wins)/len(pnls) if pnls else 0,
        'pnl': sum(pnls)*100,
        'avg': sum(pnls)/len(pnls)*100 if pnls else 0,
    }

this_week = week_stats(closed, week_ago, now)
last_week = week_stats(closed, two_weeks_ago, week_ago)

print('=== DEZE WEEK ===')
if this_week:
    print(f'Trades: {this_week[\"n\"]} | WR: {this_week[\"wr\"]:.1%} | Totaal PnL: {this_week[\"pnl\"]:+.2f}% | Gem: {this_week[\"avg\"]:+.2f}%')
else:
    print('Geen trades deze week')

print()
print('=== VORIGE WEEK ===')
if last_week:
    print(f'Trades: {last_week[\"n\"]} | WR: {last_week[\"wr\"]:.1%} | Totaal PnL: {last_week[\"pnl\"]:+.2f}% | Gem: {last_week[\"avg\"]:+.2f}%')
else:
    print('Geen trades vorige week')

print()
print('=== ALLE TIJDEN ===')
all_pnls = [t.get('pnl_pct',0) for t in closed]
all_wins = [p for p in all_pnls if p > 0]
all_loss = [p for p in all_pnls if p < 0]
print(f'Trades: {len(closed)} | WR: {len(all_wins)/len(all_pnls):.1%}' if all_pnls else 'Geen trades')
if all_wins: print(f'Gem win: {sum(all_wins)/len(all_wins)*100:+.2f}% | Gem verlies: {sum(all_loss)/len(all_loss)*100:+.2f}%')

print()
# Per symbool
by_sym = defaultdict(list)
for t in closed:
    by_sym[t.get('symbol','?')].append(t.get('pnl_pct',0))
print('=== PER SYMBOOL ===')
for sym, pnls in sorted(by_sym.items()):
    wins = [p for p in pnls if p > 0]
    print(f'{sym}: WR={len(wins)/len(pnls):.0%} n={len(pnls)} totaal={sum(pnls)*100:+.2f}%')
"
```

Lees ook de roadmap uit `memory/bot_changelog.md` (sectie Roadmap) en `memory/insights.md`.

## Output formaat

Geef een overzicht met:
1. **Deze week vs vorige week** — gaat het beter of slechter?
2. **Beste en slechtste symbool**
3. **Roadmap status** — wat staat er open voor week 1/2/3?
4. **Één aanbeveling** voor de komende week

Communiceer in het Nederlands.
