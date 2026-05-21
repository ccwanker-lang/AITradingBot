# /analyse — Diepe patroonanalyse

Voer een volledige patroonanalyse uit van alle closed trades. Schrijf bevindingen naar memory/insights.md en stuur een Telegram-samenvatting.

## Instructie

Voer de bot-analyst agent uit. Die agent doet het volgende:
1. Laadt alle closed trades en analyseert: WR per uur, per weekdag, per exit-reden, revenge trading, verliesreeksen, trade duur
2. Analyseert signaalcombinaties: welke strategieën winnen, welke verliezen
3. Schrijft een nieuwe sectie toe aan `/home/pi/crypto_bot/memory/insights.md`
4. Stuurt een Telegram-samenvatting

Gebruik de instructies uit `.claude/agents/bot-analyst.md` om de analyse uit te voeren.

## Minimumvereiste

Minimaal 20 closed trades nodig. Minder dan dat: meld dit aan de gebruiker en stop.

Communiceer in het Nederlands.
