import requests
from pathlib import Path

# Token lezen uit .env
token = ""
for line in Path(".env").read_text(encoding="utf-8-sig").splitlines():
    if line.startswith("TELEGRAM_TOKEN="):
        token = line.split("=", 1)[1].strip()

print(f"Token: {token[:15]}...")

# Haal updates op — hierin zit jouw echte chat ID
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()

if not r.get("ok"):
    print(f"Fout: {r}")
else:
    updates = r.get("result", [])
    if not updates:
        print("\nGeen berichten gevonden.")
        print("→ Stuur /start naar jouw bot in Telegram en draai dit script opnieuw.")
    else:
        last = updates[-1]
        chat = last.get("message", {}).get("chat", {})
        real_chat_id = chat.get("id")
        naam = chat.get("first_name", "")
        print(f"\n✅ Jouw echte chat ID is: {real_chat_id} ({naam})")
        print(f"\nZet dit in je .env:")
        print(f"TELEGRAM_CHAT_ID={real_chat_id}")

        # Stuur testbericht met gevonden ID
        r2 = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": real_chat_id, "text": "✅ Verbinding werkt!"},
            timeout=10,
        ).json()
        if r2.get("ok"):
            print("\n✅ Testbericht verstuurd — check Telegram!")
        else:
            print(f"Fout bij sturen: {r2}")
