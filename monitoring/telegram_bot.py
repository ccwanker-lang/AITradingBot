"""
Telegram bot — trade alerts + interactieve commando's.
Commando's: /bal /stats /posities /stop /help
"""
import time
import threading
import requests
from datetime import datetime


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._callbacks: dict[str, callable] = {}
        self._last_update_id = 0
        self._running = False
        self._stop_flag = threading.Event()
        self._register_defaults()

    # ── Registratie van commando callbacks ─────────────────────────
    def _register_defaults(self):
        self.register("help", self._cmd_help)

    def register(self, command: str, callback: callable):
        """Registreer een commando handler. callback() moet een string teruggeven."""
        self._callbacks[command.lower().lstrip("/")] = callback

    # ── Polling loop (draait in achtergrond thread) ────────────────
    def start_polling(self):
        if not self.enabled:
            return
        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()

    def stop_polling(self):
        self._running = False
        self._stop_flag.set()

    def _poll_loop(self):
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception:
                pass
            time.sleep(2)

    def _get_updates(self) -> list:
        try:
            r = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": 10},
                timeout=15,
            )
            data = r.json()
            updates = data.get("result", [])
            if updates:
                self._last_update_id = updates[-1]["update_id"]
            return updates
        except Exception:
            return []

    def _handle_update(self, update: dict):
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Alleen commando's van jouw eigen chat verwerken (veiligheid)
        if chat_id != self.chat_id:
            return
        if not text.startswith("/"):
            return

        command = text.split()[0].lower().lstrip("/").split("@")[0]
        callback = self._callbacks.get(command)
        if callback:
            try:
                response = callback()
                self._send_raw(response, chat_id)
            except Exception as e:
                self._send_raw(f"❌ Fout bij /{command}: {e}", chat_id)
        else:
            self._send_raw(f"❓ Onbekend commando: /{command}\n\nStuur /help voor overzicht.", chat_id)

    # ── Berichten versturen ────────────────────────────────────────
    def _send_raw(self, text: str, chat_id: str = None):
        if not self.enabled:
            return
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": chat_id or self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=5,
            )
        except Exception:
            pass

    def send(self, text: str):
        self._send_raw(text)

    # ── Trade alerts ───────────────────────────────────────────────
    def trade_alert(self, symbol: str, trade_type: str, price: float,
                    pnl_pct: float = None, portfolio_value: float = None):
        emoji = "🟢" if trade_type.upper() == "BUY" else "🔴"
        lines = [
            f"{emoji} <b>{trade_type.upper()} — {symbol}</b>",
            f"Prijs: <b>${price:,.4f}</b>",
        ]
        if pnl_pct is not None:
            sign = "+" if pnl_pct >= 0 else ""
            lines.append(f"PnL: <b>{sign}{pnl_pct:.2%}</b>")
        if portfolio_value is not None:
            lines.append(f"Portfolio: <b>${portfolio_value:,.2f}</b>")
        lines.append(f"<i>{datetime.now().strftime('%H:%M:%S')}</i>")
        self.send("\n".join(lines))

    def anomaly_alert(self, symbol: str, anomaly_type: str, details: str):
        self.send(
            f"⚠️ <b>ANOMALIE — {symbol}</b>\n"
            f"Type: <b>{anomaly_type}</b>\n"
            f"{details}"
        )

    def error_alert(self, error: str):
        self.send(f"🚨 <b>BOT FOUT</b>\n{error}")

    def startup_message(self, mode: str, symbols: list, capital: float):
        self.send(
            f"🤖 <b>Monster Bot gestart</b>\n"
            f"Modus: <b>{mode}</b>\n"
            f"Symbolen: {', '.join(symbols)}\n"
            f"Kapitaal: <b>${capital:,.2f}</b>\n\n"
            f"Commando's: /help"
        )

    def daily_summary(self, summary: dict):
        total_pnl = summary.get("total_pnl", 0)
        emoji = "📈" if total_pnl >= 0 else "📉"
        self.send(
            f"{emoji} <b>Dagelijkse samenvatting</b>\n"
            f"Trades: {summary.get('closed_trades', 0)}\n"
            f"Win rate: <b>{summary.get('win_rate', 0):.1%}</b>\n"
            f"Totaal PnL: <b>{total_pnl:+.2%}</b>\n"
            f"Beste: {summary.get('best_trade', 0):+.2%}\n"
            f"Slechtste: {summary.get('worst_trade', 0):+.2%}"
        )

    def send_equity_chart(self, equity_curve: list, initial_capital: float):
        """Stuur een equity curve grafiek als afbeelding."""
        if not self.enabled or len(equity_curve) < 2:
            return
        try:
            import io
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            pnl_pct = [(v - initial_capital) / initial_capital * 100 for v in equity_curve]
            color = "green" if pnl_pct[-1] >= 0 else "red"

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(pnl_pct, color=color, linewidth=1.5)
            ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
            ax.fill_between(range(len(pnl_pct)), pnl_pct, 0,
                            alpha=0.15, color=color)
            ax.set_title("📊 Portfolio PnL (%)", fontsize=14)
            ax.set_xlabel("Tijd (kaarsen)")
            ax.set_ylabel("PnL (%)")
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=100)
            buf.seek(0)
            plt.close()

            requests.post(
                f"{self.base_url}/sendPhoto",
                data={"chat_id": self.chat_id},
                files={"photo": ("equity.png", buf, "image/png")},
                timeout=15,
            )
        except Exception:
            pass

    # ── Standaard /help commando ───────────────────────────────────
    def _cmd_help(self) -> str:
        return (
            "🤖 <b>Monster Bot commando's</b>\n\n"
            "/bal — Portfolio waarde &amp; PnL\n"
            "/stats — Trade statistieken\n"
            "/posities — Open posities\n"
            "/stop — Bot veilig stoppen\n"
            "/help — Dit overzicht"
        )
