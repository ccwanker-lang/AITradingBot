# /status — Snelle bot status

Geef een snelle one-liner status van de bot. Geen lange analyse — gewoon de feiten.

## Stappen

```bash
cd /home/pi/crypto_bot && venv/bin/python -c "
import json
from pathlib import Path
from datetime import datetime

state = json.loads(Path('logs/state.json').read_text()) if Path('logs/state.json').exists() else {}
trades = json.loads(Path('logs/trades.json').read_text()) if Path('logs/trades.json').exists() else []

pf = state.get('portfolio', {})
closed = [t for t in trades if t.get('type') in ('sell','cover')]
wins = [t for t in closed if t.get('pnl_pct',0) > 0]
wr = len(wins)/len(closed) if closed else 0
positions = state.get('positions', {})
running = state.get('running', False)

print(f'Bot: {\"ACTIEF\" if running else \"OFFLINE\"}')
print(f'Portfolio: \${pf.get(\"total_value\",1000):.2f} | PnL: {pf.get(\"pnl_pct\",0)*100:+.2f}%')
print(f'Win Rate: {wr:.1%} | Trades: {len(closed)} closed | Open: {len(positions)}')
print(f'Drawdown: {pf.get(\"drawdown\",0)*100:.2f}% | Vrij: \${pf.get(\"free_capital\",0):.2f}')
last = state.get('last_update','?')
print(f'Laatste update: {last}')
"
```

Geef de output als korte samenvatting in één alinea. Geen headers, geen lijsten — gewoon een zin of twee.
