# /fix — Grootste probleem vinden en één fix voorstellen

Detecteer het één grootste probleem van de bot en stel één concrete fix voor. Pas NIETS automatisch aan — alleen analyseren en adviseren.

## Stappen

```bash
cd /home/pi/crypto_bot && venv/bin/python tools/auto_optimizer.py
```

Lees daarna ook:
```bash
cd /home/pi/crypto_bot && venv/bin/python tools/check_report.py 2>&1 | head -60
```

## Regels

- Stel MAXIMAAL één wijziging voor
- Noem de exacte waarde: "verander MIN_CONFIDENCE van 0.46 naar 0.50"
- Leg uit waarom: welk patroon in de data rechtvaardigt dit?
- Herinner aan de roadmap: als we in week 1 zitten (t/m 2026-05-27), geef dan aan dat we eigenlijk niets aanpassen deze week
- Geef ook aan hoe je het resultaat meet: "na 10 nieuwe trades vergelijk je de WR"

Communiceer in het Nederlands.
