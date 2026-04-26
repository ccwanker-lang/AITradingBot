"""
Wekelijks rapport — genereert een uitgebreide performance samenvatting.
Stuurt grafiek + statistieken via Telegram elke zondag.
"""
import io
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


class ReportGenerator:
    def __init__(self, logger, telegram, initial_capital: float):
        self.logger = logger
        self.telegram = telegram
        self.initial_capital = initial_capital

    def generate_and_send(self, equity_curve: list[float]):
        summary = self.logger.get_trade_summary()
        self._send_text_report(summary)
        self._send_chart(equity_curve, summary)

    def _send_text_report(self, summary: dict):
        closed = summary.get("closed_trades", 0)
        if closed == 0:
            self.telegram.send("📊 <b>Weekrapport</b>\n\nNog geen gesloten trades deze week.")
            return

        win_rate = summary.get("win_rate", 0)
        avg_pnl  = summary.get("avg_pnl", 0)
        total    = summary.get("total_pnl", 0)
        best     = summary.get("best_trade", 0)
        worst    = summary.get("worst_trade", 0)

        grade = "S" if total > 0.10 else "A" if total > 0.05 else "B" if total > 0 else "C"
        emoji = "🏆" if grade == "S" else "✅" if grade in ("A","B") else "⚠️"

        self.telegram.send(
            f"📊 <b>Weekrapport — Cijfer: {grade} {emoji}</b>\n\n"
            f"Gesloten trades: {closed}\n"
            f"Win rate: <b>{win_rate:.1%}</b>\n"
            f"Gem. PnL per trade: {avg_pnl:+.2%}\n"
            f"Totaal PnL: <b>{total:+.2%}</b>\n"
            f"Beste trade: <b>{best:+.2%}</b> 🚀\n"
            f"Slechtste trade: <b>{worst:+.2%}</b> 💀\n\n"
            f"<i>{datetime.now().strftime('%d %b %Y')}</i>"
        )

    def _send_chart(self, equity_curve: list[float], summary: dict):
        if len(equity_curve) < 2:
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.gridspec as gridspec
            import numpy as np

            pnl = [(v - self.initial_capital) / self.initial_capital * 100
                   for v in equity_curve]
            color = "green" if pnl[-1] >= 0 else "red"

            fig = plt.figure(figsize=(12, 8), facecolor="#1a1a2e")
            gs  = gridspec.GridSpec(2, 2, figure=fig)

            # Equity curve
            ax1 = fig.add_subplot(gs[0, :])
            ax1.set_facecolor("#16213e")
            ax1.plot(pnl, color=color, linewidth=2)
            ax1.fill_between(range(len(pnl)), pnl, 0, alpha=0.2, color=color)
            ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
            ax1.set_title("📈 Portfolio PnL (%)", color="white", fontsize=13)
            ax1.tick_params(colors="white")
            ax1.grid(True, alpha=0.2)

            # Win/Loss pie
            ax2 = fig.add_subplot(gs[1, 0])
            ax2.set_facecolor("#16213e")
            wr = summary.get("win_rate", 0)
            ax2.pie([wr, 1-wr], labels=["Wins", "Losses"],
                    colors=["#00ff88", "#ff4444"],
                    autopct="%1.0f%%", textprops={"color": "white"})
            ax2.set_title("Win Rate", color="white")

            # Stats
            ax3 = fig.add_subplot(gs[1, 1])
            ax3.set_facecolor("#16213e")
            ax3.axis("off")
            stats = [
                f"Trades: {summary.get('closed_trades', 0)}",
                f"Gem PnL: {summary.get('avg_pnl', 0):+.2%}",
                f"Beste:   {summary.get('best_trade', 0):+.2%}",
                f"Slechtste: {summary.get('worst_trade', 0):+.2%}",
                f"Totaal:  {summary.get('total_pnl', 0):+.2%}",
            ]
            ax3.text(0.1, 0.5, "\n".join(stats), transform=ax3.transAxes,
                     color="white", fontsize=11, verticalalignment="center",
                     fontfamily="monospace")
            ax3.set_title("Statistieken", color="white")

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor())
            buf.seek(0)
            plt.close()

            import requests
            requests.post(
                f"{self.telegram.base_url}/sendPhoto",
                data={"chat_id": self.telegram.chat_id},
                files={"photo": ("weekrapport.png", buf, "image/png")},
                timeout=15,
            )
        except Exception as e:
            self.logger.log_error("Weekrapport grafiek", e)

    def start_weekly_scheduler(self, equity_curve_ref: list):
        """Stuurt elke zondag om 09:00 een rapport."""
        def _loop():
            while True:
                time.sleep(3600)
                now = datetime.now()
                if now.weekday() == 6 and now.hour == 9 and now.minute < 5:
                    self.generate_and_send(equity_curve_ref)
        threading.Thread(target=_loop, daemon=True).start()
