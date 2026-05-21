from __future__ import annotations
"""
Monster Crypto Bot — de meest geavanceerde trading bot die je ooit gezien hebt.

Gebruik:
    python bot.py                    # Paper trading (veilig!)
    python bot.py --live             # Echt geld (voorzichtig!)
    python bot.py --backtest         # Backtesting
    python bot.py --train            # Modellen trainen
    python bot.py --symbol ETH/USDT  # Ander symbool

BELANGRIJK: Start ALTIJD met paper trading eerst!
"""
import os
import sys
import time
import argparse
import threading
from datetime import datetime

import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from data.fetcher import DataFetcher
from data.features import add_all_features, get_feature_columns
from data.orderbook import OrderBookAnalyzer
from data.sentiment import SentimentAnalyzer
from strategies.signals import SignalCombiner
from strategies.anomaly import AnomalyDetector, AnomalyType
from strategies.regime import RegimeDetector, Regime
from strategies.momentum_rotation import MomentumRotation
from data.funding_rate import FundingRateAnalyzer
from monitoring.report import ReportGenerator
from agent.lstm_predictor import LSTMPredictor
from risk.manager import RiskManager
from monitoring.logger import BotLogger
from monitoring.telegram_bot import TelegramBot
from analytics.setup_classifier import SetupClassifier
from risk.meta_controller import MetaController
from execution.microstructure import MicrostructureFilter
from strategies.stat_arb import StatArbAnalyzer

console = Console()


class MonsterBot:
    def __init__(self, config: Config):
        self.config = config
        self.logger = BotLogger()
        self.telegram = TelegramBot(config.telegram_token, config.telegram_chat_id)
        self._should_stop = False

        # Data & exchange
        self.fetcher = DataFetcher(config.exchange_id, config.api_key, config.api_secret)

        # Analyse modules
        self.order_book = OrderBookAnalyzer(self.fetcher.exchange)
        self.sentiment = SentimentAnalyzer()
        self.anomaly = AnomalyDetector()
        self.regime_detector = RegimeDetector()
        self.momentum_rotation = MomentumRotation()
        self.funding_analyzer = FundingRateAnalyzer()
        self.reporter = ReportGenerator(self.logger, self.telegram, config.initial_capital)
        self.signal_combiner = SignalCombiner(
            rl_weight=config.rl_weight,
            lstm_weight=config.lstm_weight,
        )

        # AI modellen
        self.lstm = LSTMPredictor(config.lstm_path)
        self.rl_model = self._load_rl_model()

        # Risico
        self.setup_classifier = SetupClassifier(str(self.logger.log_dir / "trades.json"))
        self.meta = MetaController(str(self.logger.log_dir / "trades.json"))
        from strategies.market_structure import MarketStructureStrategy as _MS
        self._ms4h = _MS()
        self.microstructure = MicrostructureFilter()
        self.stat_arb = StatArbAnalyzer()
        self._stat_arb_signals: dict = {}
        self.risk = RiskManager(
            max_drawdown_stop=config.max_drawdown_stop,
            max_position_pct=config.max_position_pct,
            min_confidence=config.min_confidence,
            kelly_fraction=config.kelly_fraction,
            atr_sl_mult=config.atr_sl_multiplier,
            atr_tp_mult=config.atr_tp_multiplier,
            trailing_pct=config.trailing_stop_pct,
        )

        # Trading engine
        if config.paper_trading:
            from execution.paper_engine import PaperEngine
            self.engine = PaperEngine(config.initial_capital, self.risk, fee_rate=config.trading_fee)
            _engine_state = self.logger.log_dir / "engine_state.json"
            self.engine.load_state(_engine_state)
        else:
            from execution.live_engine import LiveEngine
            self.engine = LiveEngine(
                config.exchange_id, config.api_key, config.api_secret,
                self.risk, config.initial_capital,
            )

        # Persistente state paden
        self._weights_path   = self.logger.log_dir / "weights_state.json"
        self._bot_state_path = self.logger.log_dir / "bot_state.json"
        self._load_weights()

        # Auto-hertrainer
        self._start_auto_retrain()

        # Telegram commando's registreren
        self._register_telegram_commands()

        # Status
        self._cycle = 0
        self._last_sentiment = {"score": 0.0, "signal": 0, "label": "Neutraal"}
        self._last_ob: dict[str, dict] = {}
        self._last_regime: dict[str, object] = {}
        self._last_signal_details: dict[str, list] = {}
        self._last_no_trade_reasons: dict[str, str] = {}
        self._equity_curve: list[float] = [config.initial_capital]
        self._last_summary_day = -1
        self._last_trade_time: float = time.time()
        self._last_drawdown_alert: float = 0.0  # laatste drawdown niveau waarvoor alert verstuurd
        self._last_heartbeat_hour: int = -1
        self._rolling_wr_paused: bool = False   # auto-pause bij rolling WR < 30%
        self._rolling_wr_warned: bool = False   # éénmalige waarschuwing bij WR < 35%
        self._manual_paused: bool = False       # handmatige pauze via /pauze commando
        # (symbol → (unix_time, direction)) — cooldown na stop-loss
        self._last_sl_hit: dict[str, tuple[float, int]] = {}
        # Regime hysteresis — telt opeenvolgende andersluidende detecties per symbool
        self._regime_change_count: dict[str, int] = {}
        # Circuit breaker — dagelijks verliesplafond
        self._circuit_breaker_until: float = 0.0
        self._daily_start_value: float = config.initial_capital
        self._last_daily_reset: int = -1
        # Daily SL teller — pauze als ≥3 stop-losses op één dag
        self._daily_sl_count: int = 0
        self._daily_sl_pause_until: float = 0.0
        # Persistente bot-state herstellen (SL cooldowns, circuit breaker, equity curve)
        self._load_bot_state()
        self._restore_equity_curve()

        self._start_daily_summary_thread()
        self._start_heartbeat_thread()
        self.reporter.start_weekly_scheduler(self._equity_curve)

        mode = "PAPER TRADING" if config.paper_trading else "LIVE TRADING"
        self.logger.info(f"Monster Bot gestart | {mode} | {config.symbols}")
        self.telegram.startup_message(mode, config.symbols, config.initial_capital)
        self.telegram.start_polling()

        console.print(Panel.fit(
            f"[bold green]Monster Bot gestart[/bold green]\n"
            f"Symbolen: [cyan]{', '.join(config.symbols)}[/cyan]\n"
            f"Modus: [{'yellow' if config.paper_trading else 'red'}]"
            f"{'PAPER' if config.paper_trading else 'LIVE'} TRADING[/]\n"
            f"RL Model: [{'green]geladen' if self.rl_model else 'yellow]niet gevonden'}[/]\n"
            f"LSTM: [{'green]geladen' if self.lstm.model else 'yellow]niet getraind'}[/]",
            title="Monster Bot",
            border_style="green",
        ))

    # ── Dagelijkse samenvatting ────────────────────────────────────
    def _start_daily_summary_thread(self):
        def _loop():
            import time as _time
            while True:
                _time.sleep(60)
                now = datetime.now()
                if now.hour == 8 and now.minute == 0 and now.day != self._last_summary_day:
                    self._last_summary_day = now.day
                    summary = self.logger.get_trade_summary()
                    self.telegram.daily_summary(summary)
                    self.telegram.send_equity_chart(
                        self._equity_curve, self.config.initial_capital
                    )
        threading.Thread(target=_loop, daemon=True).start()

    # ── Heartbeat thread (elke 2 uur) ─────────────────────────────
    def _start_heartbeat_thread(self):
        def _loop():
            import time as _time
            while True:
                _time.sleep(60)
                now = datetime.now()
                # Stuur elke even uur (0, 2, 4, ... 22)
                current_hour = now.hour
                if current_hour % 2 == 0 and now.minute == 0 and current_hour != self._last_heartbeat_hour:
                    self._last_heartbeat_hour = current_hour
                    try:
                        symbols = self.config.symbols if self.config.multi_asset else [self.config.symbol]
                        prices = {}
                        for s in symbols:
                            try:
                                prices[s] = self.fetcher.fetch_current_price(s)
                            except Exception:
                                pass
                        status = self.engine.get_status(prices) if hasattr(self.engine, "get_status") else {}
                        regime_str = ", ".join(
                            f"{s}:{r.regime.value}" for s, r in self._last_regime.items()
                        ) or "onbekend"
                        last_trade_h = (time.time() - self._last_trade_time) / 3600
                        self.telegram.heartbeat({
                            "total_value": status.get("total_value", 0),
                            "pnl_pct": status.get("pnl_pct", 0),
                            "drawdown": status.get("drawdown", 0),
                            "open_positions": status.get("open_positions", 0),
                            "regime": regime_str,
                            "last_trade_hours": last_trade_h,
                        })
                        # Rolling WR info meesturen bij heartbeat
                        try:
                            rolling = self.logger.get_rolling_stats(n=20)
                            if rolling["n"] >= 5:
                                self.telegram.send(
                                    f"📊 <b>Rolling WR</b> (laatste {rolling['n']} trades): "
                                    f"<b>{rolling['win_rate']:.1%}</b> | "
                                    f"PF: {rolling['profit_factor']:.2f} | "
                                    f"Gem: {rolling['avg_pnl']:+.2%}"
                                    + (" | ⚠️ GEPAUZEERD" if self._rolling_wr_paused else "")
                                )
                        except Exception:
                            pass
                        # Inactiviteitsalert bij heartbeat: >= 12 uur geen trade
                        if last_trade_h >= 12:
                            self.telegram.inactivity_alert(last_trade_h, self._last_no_trade_reasons)
                    except Exception:
                        pass
        threading.Thread(target=_loop, daemon=True).start()

    # ── Telegram commando's ────────────────────────────────────────
    def _register_telegram_commands(self):
        self.telegram.register("bal", self._cmd_bal)
        self.telegram.register("stats", self._cmd_stats)
        self.telegram.register("posities", self._cmd_posities)
        self.telegram.register("regime", self._cmd_regime)
        self.telegram.register("signalen", self._cmd_signalen)
        self.telegram.register("health", self._cmd_health)
        self.telegram.register("log", self._cmd_log)
        self.telegram.register("stop", self._cmd_stop)
        self.telegram.register("trades", self._cmd_trades)
        self.telegram.register("rolling", self._cmd_rolling)
        self.telegram.register("equity", self._cmd_equity)
        self.telegram.register("pauze", self._cmd_pauze)
        self.telegram.register("hervat", self._cmd_hervat)
        self.telegram.register("config", self._cmd_config)
        self.telegram.register("status", self._cmd_status)
        self.telegram.register("check", self._cmd_check)
        self.telegram.register("week", self._cmd_week)
        self.telegram.register("fix", self._cmd_fix)
        self.telegram.register("analyse", self._cmd_analyse)
        self.telegram.register("roadmap", self._cmd_roadmap)

    def _cmd_bal(self) -> str:
        try:
            prices = {s: self.fetcher.fetch_current_price(s) for s in self.config.symbols}
            status = self.engine.get_status(prices)
            pnl = status["pnl_pct"]
            sign = "+" if pnl >= 0 else ""
            regime_info = ""
            if self._last_regime:
                r = list(self._last_regime.values())[0]
                regime_info = f"\nRegime: <b>{r.regime.value}</b>"
            return (
                f"💰 <b>Portfolio</b>\n\n"
                f"Totaal: <b>${status['total_value']:,.2f}</b>\n"
                f"PnL: <b>{sign}{pnl:.2%}</b>\n"
                f"Drawdown: {status['drawdown']:.1%}\n"
                f"Vrij kapitaal: ${status['free_capital']:,.2f}\n"
                f"Open posities: {status['open_positions']}"
                f"{regime_info}\n"
                f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
            )
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_stats(self) -> str:
        try:
            summary = self.logger.get_trade_summary()
            if summary.get("closed_trades", 0) == 0:
                return "📊 <b>Statistieken</b>\n\nNog geen gesloten trades."
            return (
                f"📊 <b>Statistieken</b>\n\n"
                f"Totaal trades: {summary['closed_trades']}\n"
                f"Win rate: <b>{summary['win_rate']:.1%}</b>\n"
                f"Gem. PnL: {summary['avg_pnl']:+.2%}\n"
                f"Beste trade: <b>{summary['best_trade']:+.2%}</b> 🏆\n"
                f"Slechtste: <b>{summary['worst_trade']:+.2%}</b> 💀\n"
                f"Totaal PnL: <b>{summary['total_pnl']:+.2%}</b>"
            )
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_posities(self) -> str:
        try:
            prices = {s: self.fetcher.fetch_current_price(s) for s in self.config.symbols}
            positions = self.engine.positions  # PaperEngine.positions direct
            if not positions:
                return "📋 <b>Open posities</b>\n\nGeen open posities."
            lines = ["📋 <b>Open posities</b>\n"]
            for sym, pos in positions.items():
                price = prices.get(sym, pos.entry_price)
                if pos.direction == 1:
                    pnl = (price - pos.entry_price) / pos.entry_price
                    dir_label = "▲ LONG"
                else:
                    pnl = (pos.entry_price - price) / pos.entry_price
                    dir_label = "▼ SHORT"
                sign = "+" if pnl >= 0 else ""
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f"{emoji} <b>{sym}</b> — {dir_label}\n"
                    f"  Instap: ${pos.entry_price:,.4f}\n"
                    f"  Nu: ${price:,.4f}\n"
                    f"  PnL: <b>{sign}{pnl:.2%}</b>\n"
                    f"  SL: ${pos.stop_loss:,.4f}\n"
                    f"  TP: ${pos.take_profit:,.4f}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_stop(self) -> str:
        self._should_stop = True
        return "🛑 <b>Bot wordt gestopt...</b>\nActieve posities blijven open op de exchange."

    def _cmd_regime(self) -> str:
        if not self._last_regime:
            return "🌍 <b>Marktregime</b>\n\nNog geen regime data — bot is aan het opstarten."
        regime_labels = {
            "bull_trend": "📈 Bull Trend",
            "bear_trend": "📉 Bear Trend",
            "ranging": "↔️ Ranging",
            "high_vol": "🌪 Hoge Volatiliteit",
            "accumulation": "🏗 Accumulatie",
        }
        lines = ["🌍 <b>Marktregime</b>\n"]
        for sym, reg in self._last_regime.items():
            label = regime_labels.get(reg.regime.value, reg.regime.value)
            lines.append(
                f"<b>{sym}</b>\n"
                f"  {label}\n"
                f"  Kracht: {reg.strength:.0%}\n"
                f"  {reg.description}"
            )
        lines.append(f"\n<i>{datetime.now().strftime('%H:%M:%S')}</i>")
        return "\n".join(lines)

    def _cmd_signalen(self) -> str:
        if not self._last_signal_details:
            return "📡 <b>Signalen</b>\n\nNog geen signaaldata — wacht op eerste analyse cyclus."
        lines = ["📡 <b>Laatste signalen per strategie</b>\n"]
        for sym, details in self._last_signal_details.items():
            lines.append(f"<b>{sym}</b>")
            if not details:
                lines.append("  Geen signalen")
                continue
            for d in sorted(details, key=lambda x: abs(x.get("bijdrage", 0)), reverse=True)[:8]:
                actie = d.get("actie", 0)
                bijdrage = d.get("bijdrage", 0)
                richting = "▲" if actie == 1 else ("▼" if actie == -1 else "—")
                sign = "+" if bijdrage >= 0 else ""
                lines.append(f"  {richting} {d.get('naam', '?')}: {sign}{bijdrage:.3f}")
        lines.append(f"\n<i>{datetime.now().strftime('%H:%M:%S')}</i>")
        return "\n".join(lines)

    def _cmd_health(self) -> str:
        lines = ["🖥 <b>Systeem status</b>\n"]
        # CPU temperatuur (Raspberry Pi)
        try:
            temp_raw = open("/sys/class/thermal/thermal_zone0/temp").read().strip()
            temp_c = int(temp_raw) / 1000
            temp_emoji = "🔥" if temp_c > 75 else ("🌡" if temp_c > 60 else "✅")
            lines.append(f"CPU temp: {temp_emoji} <b>{temp_c:.1f}°C</b>")
        except Exception:
            lines.append("CPU temp: niet beschikbaar")
        # RAM gebruik
        try:
            mem = open("/proc/meminfo").read()
            total = int([l for l in mem.split("\n") if "MemTotal" in l][0].split()[1])
            avail = int([l for l in mem.split("\n") if "MemAvailable" in l][0].split()[1])
            used_pct = (total - avail) / total
            ram_emoji = "🔴" if used_pct > 0.85 else ("🟡" if used_pct > 0.70 else "✅")
            lines.append(f"RAM: {ram_emoji} <b>{used_pct:.0%}</b> gebruikt ({avail//1024} MB vrij)")
        except Exception:
            lines.append("RAM: niet beschikbaar")
        # Schijfruimte
        try:
            import shutil
            disk = shutil.disk_usage("/")
            disk_pct = disk.used / disk.total
            disk_emoji = "🔴" if disk_pct > 0.90 else ("🟡" if disk_pct > 0.75 else "✅")
            lines.append(f"Schijf: {disk_emoji} <b>{disk_pct:.0%}</b> gebruikt ({disk.free // (1024**3):.1f} GB vrij)")
        except Exception:
            lines.append("Schijf: niet beschikbaar")
        # Uptime
        try:
            uptime_s = float(open("/proc/uptime").read().split()[0])
            uptime_h = uptime_s / 3600
            lines.append(f"Uptime: ⏱ <b>{uptime_h:.1f} uur</b>")
        except Exception:
            pass
        # Bot info
        lines.append(f"\nBot cyclus: #{self._cycle}")
        lines.append(f"<i>{datetime.now().strftime('%H:%M:%S')}</i>")
        return "\n".join(lines)

    def _cmd_log(self) -> str:
        try:
            log_file = self.logger.log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
            if not log_file.exists():
                return "📋 <b>Log</b>\n\nGeen logbestand voor vandaag."
            lines_all = log_file.read_text(encoding="utf-8").splitlines()
            errors = [l for l in lines_all if "| ERROR |" in l or "| WARNING |" in l]
            if not errors:
                return "📋 <b>Log</b>\n\n✅ Geen fouten of waarschuwingen vandaag."
            last_5 = errors[-5:]
            result = "📋 <b>Laatste meldingen</b>\n\n"
            for line in last_5:
                # Verwijder timestamp prefix voor leesbaarheid
                parts = line.split(" | ", 2)
                level = parts[1] if len(parts) > 1 else ""
                msg = parts[2][:120] if len(parts) > 2 else line[:120]
                emoji = "🚨" if "ERROR" in level else "⚠️"
                result += f"{emoji} <code>{msg}</code>\n\n"
            return result.strip()
        except Exception as e:
            return f"❌ Fout bij lezen log: {e}"

    def _cmd_trades(self) -> str:
        try:
            closed = [
                t for t in self.logger.trades
                if t.get("type") in ("sell", "cover") and "pnl_pct" in t
            ]
            if not closed:
                return "📜 <b>Laatste trades</b>\n\nNog geen gesloten trades."
            recent = closed[-8:]
            lines = [f"📜 <b>Laatste {len(recent)} gesloten trades</b>\n"]
            for t in reversed(recent):
                pnl = t.get("pnl_pct", 0)
                emoji = "✅" if pnl > 0 else "❌"
                sym = t.get("symbol", "?")
                direction = "LONG" if t.get("direction", 1) == 1 else "SHORT"
                ts = t.get("timestamp", "")[:16]
                reason = t.get("exit_reason", t.get("type", "?"))
                lines.append(
                    f"{emoji} <b>{sym}</b> {direction} | <b>{pnl:+.2%}</b>\n"
                    f"  {ts} — {reason}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_rolling(self) -> str:
        try:
            r20 = self.logger.get_rolling_stats(n=20)
            r10 = self.logger.get_rolling_stats(n=10)
            if r20["n"] == 0:
                return "📊 <b>Rolling stats</b>\n\nNog geen gesloten trades."
            paused = self._rolling_wr_paused or self._manual_paused
            pause_label = " ⚠️ GEPAUZEERD" if paused else " ✅ actief"
            wr_emoji = "🟢" if r20["win_rate"] >= 0.45 else ("🟡" if r20["win_rate"] >= 0.35 else "🔴")
            return (
                f"📊 <b>Rolling statistieken</b>{pause_label}\n\n"
                f"<b>Laatste 20 trades:</b>\n"
                f"  WR: {wr_emoji} <b>{r20['win_rate']:.1%}</b> | PF: <b>{r20['profit_factor']:.2f}</b> | Gem: {r20['avg_pnl']:+.2%}\n\n"
                f"<b>Laatste 10 trades:</b>\n"
                f"  WR: <b>{r10['win_rate']:.1%}</b> | PF: <b>{r10['profit_factor']:.2f}</b> | Gem: {r10['avg_pnl']:+.2%}\n\n"
                f"<i>Auto-pauze: WR &lt; 30% over laatste 15 trades</i>\n"
                f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
            )
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_equity(self) -> str:
        try:
            self.telegram.send_equity_chart(self._equity_curve, self.config.initial_capital)
            return f"📈 Equity curve verstuurd ({len(self._equity_curve)} datapunten)"
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_pauze(self) -> str:
        self._manual_paused = True
        return (
            "⏸ <b>Bot gepauzeerd</b>\n\n"
            "Nieuwe entries worden geblokkeerd.\n"
            "Open posities blijven actief (SL/TP werken gewoon).\n\n"
            "Gebruik /hervat om trading te hervatten."
        )

    def _cmd_hervat(self) -> str:
        self._manual_paused = False
        self._rolling_wr_paused = False
        return "▶️ <b>Trading hervat</b>\n\nBot accepteert weer nieuwe entries."

    def _cmd_config(self) -> str:
        c = self.config
        return (
            f"⚙️ <b>Huidige configuratie</b>\n\n"
            f"<b>Entry filters:</b>\n"
            f"  MIN_CONFIDENCE: <b>{c.min_confidence}</b>\n"
            f"  KELLY_FRACTION: <b>{c.kelly_fraction}</b>\n\n"
            f"<b>Risk/Reward:</b>\n"
            f"  ATR_SL_MULT: <b>{c.atr_sl_multiplier}</b>\n"
            f"  ATR_TP_MULT: <b>{c.atr_tp_multiplier}</b>\n"
            f"  TRAILING_STOP: <b>{c.trailing_stop_pct:.0%}</b>\n"
            f"  MAX_DRAWDOWN: <b>{c.max_drawdown_stop:.0%}</b>\n\n"
            f"<b>AI gewichten:</b>\n"
            f"  RL_WEIGHT: <b>{c.rl_weight}</b>\n"
            f"  LSTM_WEIGHT: <b>{c.lstm_weight}</b>\n\n"
            f"<b>Symbolen:</b> {', '.join(c.symbols)}\n"
            f"<b>Modus:</b> {'PAPER' if c.paper_trading else '⚠️ LIVE'}\n"
            f"<b>Startkapitaal:</b> ${c.initial_capital:,.0f}"
        )

    def _cmd_status(self) -> str:
        try:
            now = time.time()
            lines = [f"🤖 <b>Bot status</b>\n"]

            # Trading staat
            if self._manual_paused:
                lines.append("Trading: ⏸ <b>HANDMATIG GEPAUZEERD</b>")
            elif self._rolling_wr_paused:
                lines.append("Trading: ⚠️ <b>AUTO-GEPAUZEERD</b> (rolling WR &lt; 30%)")
            elif self._circuit_breaker_until > now:
                minuten = int((self._circuit_breaker_until - now) / 60)
                lines.append(f"Trading: 🔴 <b>CIRCUIT BREAKER</b> — nog {minuten} min geblokkeerd")
            elif self._daily_sl_pause_until > now:
                lines.append("Trading: 🔴 <b>DAGELIJKS SL LIMIET</b> — pauze tot dagswitch")
            else:
                lines.append("Trading: ✅ <b>ACTIEF</b>")

            # Cyclus en uptime
            lines.append(f"Cyclus: #{self._cycle}")
            idle_min = int((now - self._last_trade_time) / 60)
            if idle_min < 60:
                lines.append(f"Laatste trade: {idle_min} min geleden")
            else:
                lines.append(f"Laatste trade: {idle_min // 60}u {idle_min % 60}m geleden")

            # Daily SL teller
            lines.append(f"Daily SL teller: {self._daily_sl_count}/3")

            # Rolling WR
            r15 = self.logger.get_rolling_stats(n=15)
            if r15["n"] >= 5:
                wr_emoji = "🟢" if r15["win_rate"] >= 0.45 else ("🟡" if r15["win_rate"] >= 0.35 else "🔴")
                lines.append(f"Rolling WR (15): {wr_emoji} {r15['win_rate']:.1%}")

            # Portfolio
            prices = {s: self.fetcher.fetch_current_price(s) for s in self.config.symbols}
            status = self.engine.get_status(prices)
            pnl = status["pnl_pct"]
            sign = "+" if pnl >= 0 else ""
            lines.append(f"\nPortfolio: ${status['total_value']:,.2f} ({sign}{pnl:.2%})")
            lines.append(f"Drawdown: {status['drawdown']:.1%} | Open: {status['open_positions']}")
            lines.append(f"\n<i>{datetime.now().strftime('%H:%M:%S')}</i>")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_check(self) -> str:
        try:
            import re, subprocess
            self.telegram.send("🔍 <b>Check gestart...</b>\nEven geduld (~10 sec)")
            result = subprocess.run(
                ["venv/bin/python", "tools/check_report.py"],
                capture_output=True, text=True, timeout=60,
                cwd="/home/pi/crypto_bot"
            )
            output = result.stdout + (result.stderr if result.returncode != 0 else "")
            # Strip ANSI/Rich kleurcodes
            output = re.sub(r"\x1b\[[0-9;]*m", "", output)
            output = re.sub(r"\[/?[a-z_ ]+\]", "", output)
            output = re.sub(r"[─━╌]+", "─" * 30, output)
            # Stuur in brokken van max 3800 tekens (Telegram limiet = 4096)
            chunks = [output[i:i+3800] for i in range(0, len(output), 3800)]
            for i, chunk in enumerate(chunks[:6]):  # max 6 berichten
                if i == 0:
                    self.telegram.send(f"📋 <b>Check rapport</b>\n\n<pre>{chunk}</pre>")
                else:
                    self.telegram.send(f"<pre>{chunk}</pre>")
            return ""  # al verstuurd via send()
        except subprocess.TimeoutExpired:
            return "❌ Check duurde te lang (timeout 60s)"
        except Exception as e:
            return f"❌ Check mislukt: {e}"

    def _cmd_week(self) -> str:
        try:
            from collections import defaultdict
            from datetime import timedelta
            closed = [t for t in self.logger.trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
            if not closed:
                return "📅 <b>Weekoverzicht</b>\n\nNog geen gesloten trades."
            now = datetime.now()
            week_ago = now - timedelta(days=7)
            two_weeks_ago = now - timedelta(days=14)

            def wk(trades_list, from_dt, to_dt):
                w = [t for t in trades_list if t.get("timestamp") and from_dt <= datetime.fromisoformat(str(t["timestamp"])[:19]) < to_dt]
                if not w: return None
                pnls = [t["pnl_pct"] for t in w]
                wins = [p for p in pnls if p > 0]
                return {"n": len(w), "wr": len(wins)/len(pnls), "pnl": sum(pnls), "avg": sum(pnls)/len(pnls)}

            tw = wk(closed, week_ago, now)
            lw = wk(closed, two_weeks_ago, week_ago)

            lines = ["📅 <b>Weekoverzicht</b>\n"]
            if tw:
                trend = "🟢" if (lw and tw["wr"] > lw["wr"]) else ("🔴" if (lw and tw["wr"] < lw["wr"]) else "➡️")
                lines.append(f"<b>Deze week</b> {trend}")
                lines.append(f"  Trades: {tw['n']} | WR: <b>{tw['wr']:.1%}</b> | PnL: {tw['pnl']:+.2%}")
            else:
                lines.append("<b>Deze week:</b> geen trades")
            if lw:
                lines.append(f"\n<b>Vorige week</b>")
                lines.append(f"  Trades: {lw['n']} | WR: <b>{lw['wr']:.1%}</b> | PnL: {lw['pnl']:+.2%}")

            by_sym = defaultdict(list)
            for t in closed:
                by_sym[t.get("symbol", "?")].append(t["pnl_pct"])
            lines.append("\n<b>Per symbool (alles)</b>")
            for sym, pnls in sorted(by_sym.items()):
                wins = [p for p in pnls if p > 0]
                wr = len(wins)/len(pnls)
                emoji = "🟢" if wr >= 0.5 else ("🟡" if wr >= 0.4 else "🔴")
                lines.append(f"  {emoji} {sym}: WR {wr:.0%} | {len(pnls)} trades | {sum(pnls):+.2%}")

            lines.append(f"\n<b>Roadmap:</b> Week 1 t/m 27 mei — wachten op 62 closed trades (nu: {len(closed)})")
            lines.append(f"<i>{datetime.now().strftime('%H:%M:%S')}</i>")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_fix(self) -> str:
        try:
            import subprocess, re
            self.telegram.send("🔧 <b>Fix analyse gestart...</b>")
            result = subprocess.run(
                ["venv/bin/python", "tools/auto_optimizer.py"],
                capture_output=True, text=True, timeout=30,
                cwd="/home/pi/crypto_bot"
            )
            output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout).strip()
            if not output or "Geen problemen" in output:
                return "✅ <b>Fix</b>\n\nGeen problemen gevonden — bot presteert normaal."
            return f"🔧 <b>Fix analyse</b>\n\n<pre>{output[:3000]}</pre>"
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_analyse(self) -> str:
        try:
            import subprocess, re
            closed = [t for t in self.logger.trades if t.get("type") in ("sell", "cover")]
            if len(closed) < 20:
                return f"🔬 <b>Analyse</b>\n\nTe weinig data: {len(closed)} trades (minimum 20)."
            self.telegram.send("🔬 <b>Analyse gestart...</b> Dit duurt even (~30 sec)")
            result = subprocess.run(
                ["venv/bin/python", "-c", """
import json, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

with open('logs/trades.json') as f:
    trades = json.load(f)
closed = [t for t in trades if t.get('type') in ('sell','cover')]
pnls = [t.get('pnl_pct',0) for t in closed]
wins = [p for p in pnls if p > 0]
wr = len(wins)/len(pnls)

hour_data = defaultdict(list)
for t in closed:
    ts = t.get('close_time') or t.get('timestamp','')
    try:
        h = datetime.fromisoformat(str(ts)[:19]).hour
        hour_data[h].append(t.get('pnl_pct',0))
    except: pass

best_h = max(hour_data, key=lambda h: len([p for p in hour_data[h] if p>0])/len(hour_data[h]) if hour_data[h] else 0)
worst_h = min(hour_data, key=lambda h: len([p for p in hour_data[h] if p>0])/len(hour_data[h]) if hour_data[h] else 1)
best_wr = len([p for p in hour_data[best_h] if p>0])/len(hour_data[best_h]) if hour_data[best_h] else 0
worst_wr = len([p for p in hour_data[worst_h] if p>0])/len(hour_data[worst_h]) if hour_data[worst_h] else 0

after_loss = []
for i in range(1, len(closed)):
    if closed[i-1].get('pnl_pct',0) < 0:
        after_loss.append(closed[i].get('pnl_pct',0))
wr_al = len([p for p in after_loss if p>0])/len(after_loss) if after_loss else 0

print(f'WR={wr:.1%} trades={len(closed)}')
print(f'beste_uur={best_h}u WR={best_wr:.0%}')
print(f'slechtste_uur={worst_h}u WR={worst_wr:.0%}')
print(f'na_verlies_wr={wr_al:.0%} n={len(after_loss)}')
"""],
                capture_output=True, text=True, timeout=30,
                cwd="/home/pi/crypto_bot"
            )
            lines = result.stdout.strip().splitlines()
            data = {}
            for line in lines:
                for part in line.split():
                    if "=" in part:
                        k, v = part.split("=", 1)
                        data[k] = v
            return (
                f"🔬 <b>Patroonanalyse</b>\n\n"
                f"Win Rate: <b>{data.get('WR','?')}</b> ({data.get('trades','?')} trades)\n"
                f"Beste uur: <b>{data.get('beste_uur','?')}</b> (WR {data.get('beste_uur_WR', data.get('WR','?'))})\n"
                f"Slechtste uur: <b>{data.get('slechtste_uur','?')}</b> (WR {data.get('slechtste_uur_WR', '?')})\n"
                f"Na verlies WR: <b>{data.get('na_verlies_wr','?')}</b> ({data.get('n','?')} trades)\n\n"
                f"<i>Volledige analyse: typ /check of open dashboard</i>"
            )
        except Exception as e:
            return f"❌ Fout: {e}"

    def _cmd_roadmap(self) -> str:
        try:
            closed = [t for t in self.logger.trades if t.get("type") in ("sell", "cover")]
            n = len(closed)
            pnls = [t.get("pnl_pct", 0) for t in closed]
            wins = [p for p in pnls if p > 0]
            wr = len(wins)/len(pnls) if pnls else 0
            wr_emoji = "🟢" if wr >= 0.50 else ("🟡" if wr >= 0.40 else "🔴")
            week1_done = n >= 62
            w1 = "✅" if week1_done else "🔄"
            return (
                f"🗺 <b>Roadmap status</b>\n\n"
                f"{w1} <b>Week 1 — t/m 27 mei</b>\n"
                f"  Trades: {n}/62 ({max(0,62-n)} nog nodig)\n"
                f"  WR: {wr_emoji} {wr:.1%} (doel: richting 50%)\n"
                f"  Status: {'KLAAR — klaar voor week 2' if week1_done else 'bezig — niets aanpassen'}\n\n"
                f"⏳ <b>Week 2 — ~27 mei</b>\n"
                f"  Correlatie-filter bouwen\n"
                f"  BTC/ETH/SOL max 1 positie als >90% gecorreleerd\n\n"
                f"⏳ <b>Week 3 — ~3 juni</b>\n"
                f"  LSTM per symbool (alleen als 50+ trades)\n"
                f"  Nu: {n} trades — {'✅ genoeg' if n >= 50 else f'nog {50-n} nodig'}\n\n"
                f"📋 <b>Backlog</b>\n"
                f"  • Ranging WR verbeteren (nu ~32%)\n"
                f"  • TP1 reach rate verhogen\n"
                f"  • Slechte uren blokkeren (02u/12u/23u UTC)\n\n"
                f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
            )
        except Exception as e:
            return f"❌ Fout: {e}"

    # ── Adaptieve gewichten persistentie ──────────────────────────
    def _load_weights(self):
        try:
            if self._weights_path.exists():
                import json as _json
                data = _json.loads(self._weights_path.read_text(encoding="utf-8"))
                self.signal_combiner.weight_tracker.load(data)
                total = sum(len(v) for v in data.values())
                self.logger.info(f"Adaptieve gewichten hersteld — {total} samples geladen")
        except Exception:
            pass

    def _save_weights(self):
        try:
            import json as _json
            data = self.signal_combiner.weight_tracker.save()
            self._weights_path.write_text(
                _json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _load_bot_state(self):
        """Herstel SL-cooldowns, circuit breaker en dagelijkse verliesgrens na herstart."""
        try:
            import json as _json
            if self._bot_state_path.exists():
                data = _json.loads(self._bot_state_path.read_text(encoding="utf-8"))
                for sym, info in data.get("last_sl_hit", {}).items():
                    self._last_sl_hit[sym] = (float(info[0]), int(info[1]))
                self._circuit_breaker_until = float(data.get("circuit_breaker_until", 0.0))
                self._daily_start_value = float(data.get("daily_start_value", self.config.initial_capital))
                self._last_daily_reset = int(data.get("last_daily_reset", -1))
                self._daily_sl_count = int(data.get("daily_sl_count", 0))
                self._daily_sl_pause_until = float(data.get("daily_sl_pause_until", 0.0))
                n_sl = len(self._last_sl_hit)
                cb_active = self._circuit_breaker_until > time.time()
                self.logger.info(
                    f"Bot state hersteld — {n_sl} SL cooldowns | "
                    f"Circuit breaker: {'actief' if cb_active else 'inactief'} | "
                    f"Daily SL vandaag: {self._daily_sl_count}/3"
                )
        except Exception:
            pass

    def _save_bot_state(self):
        """Sla alle leer-relevante runtime-state op zodat herstart naadloos doorgaat."""
        try:
            import json as _json
            data = {
                "last_sl_hit": {sym: list(info) for sym, info in self._last_sl_hit.items()},
                "circuit_breaker_until": self._circuit_breaker_until,
                "daily_start_value": self._daily_start_value,
                "last_daily_reset": self._last_daily_reset,
                "daily_sl_count": self._daily_sl_count,
                "daily_sl_pause_until": self._daily_sl_pause_until,
                "saved_at": datetime.now().isoformat(),
            }
            self._bot_state_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _restore_equity_curve(self):
        """Laad de equity curve uit performance.json zodat de grafiek klopt na herstart."""
        try:
            if self.logger.perf_file.exists():
                import json as _json
                data = _json.loads(self.logger.perf_file.read_text(encoding="utf-8"))
                if data:
                    self._equity_curve = [
                        d.get("total_value", self.config.initial_capital)
                        for d in data[-5000:]
                    ]
                    self.logger.info(f"Equity curve hersteld — {len(self._equity_curve)} punten")
        except Exception:
            pass

    # ── RL model laden ─────────────────────────────────────────────
    def _load_rl_model(self):
        try:
            from stable_baselines3 import PPO
            from pathlib import Path
            p = Path(self.config.model_path)
            if p.with_suffix(".zip").exists():
                return PPO.load(str(p))
        except Exception:
            pass
        return None

    def _get_rl_action(self, df, feature_cols: list) -> tuple[int, float]:
        if self.rl_model is None:
            return 0, 0.0
        try:
            import torch as _torch
            from agent.environment import CryptoTradingEnv
            env = CryptoTradingEnv(df, feature_cols, window_size=20)
            env.reset()
            env.current_step = len(df) - 1
            obs = env._get_observation()
            action, _ = self.rl_model.predict(obs, deterministic=True)
            # Werkelijke actie-probabiliteit ophalen uit policy (geen hardcoded 0.65)
            try:
                obs_t, _ = self.rl_model.policy.obs_to_tensor(obs.reshape(1, -1))
                with _torch.no_grad():
                    dist = self.rl_model.policy.get_distribution(obs_t)
                    probs = dist.distribution.probs.cpu().numpy()[0]
                rl_confidence = float(probs[int(action)])
            except Exception:
                rl_confidence = 0.55  # fallback als policy-probabilities niet beschikbaar
            # 4-actie systeem: 0=wacht, 1=long, 2=short, 3=sluit positie
            return {0: 0, 1: 1, 2: -1, 3: 0}.get(int(action), 0), rl_confidence
        except Exception:
            return 0, 0.0

    # ── Auto-hertraining ───────────────────────────────────────────
    def _start_auto_retrain(self):
        from agent.trainer import ModelTrainer
        trainer = ModelTrainer(self.config, self.fetcher, self.logger)
        trainer.start_auto_retrain(self.lstm, self.config.retrain_interval_hours)

    # ── Hoofd loop ─────────────────────────────────────────────────
    def run(self):
        console.print(f"\n[bold]Bot actief - analyse elke {self.config.interval_seconds}s[/bold]")
        console.print("[dim]Ctrl+C om te stoppen[/dim]\n")

        while not self._should_stop:
            try:
                self._cycle += 1
                self._tick()
                time.sleep(self.config.interval_seconds)
            except KeyboardInterrupt:
                console.print("\n[yellow]Bot gestopt door gebruiker.[/yellow]")
                summary = self.logger.get_trade_summary()
                self.telegram.daily_summary(summary)
                break
            except Exception as e:
                self.logger.log_error("Hoofd loop", e)
                self.telegram.error_alert(str(e))
                time.sleep(15)

        if self._should_stop:
            console.print("\n[yellow]Bot gestopt via Telegram /stop commando.[/yellow]")
            summary = self.logger.get_trade_summary()
            self.telegram.daily_summary(summary)

    def _tick(self):
        symbols = self.config.symbols if self.config.multi_asset else [self.config.symbol]
        current_prices: dict[str, float] = {}

        # ── 1. SL/TP check voor alle open posities ─────────────────
        for symbol in symbols:
            try:
                current_prices[symbol] = self.fetcher.fetch_current_price(symbol)
            except Exception:
                pass

        if hasattr(self.engine, "check_stops"):
            closed = self.engine.check_stops(current_prices)
            for trade in closed:
                self.logger.log_trade(trade)
                if trade.get("reason") == "STOP-LOSS":
                    self._last_sl_hit[trade["symbol"]] = (
                        time.time(), trade.get("direction", 0)
                    )
                    self._daily_sl_count += 1
                    if self._daily_sl_count >= 3:
                        self._daily_sl_pause_until = time.time() + 86400  # tot morgen reset
                        self.logger.warning(
                            f"Daily SL limiet bereikt ({self._daily_sl_count} stops vandaag) — geen nieuwe entries tot dagswitch"
                        )
                        self.telegram.send(
                            f"⚠️ <b>Daily SL limiet</b>\n{self._daily_sl_count} stop-losses vandaag.\n"
                            f"Geen nieuwe trades tot morgen (bestaande posities blijven open)."
                        )
                # Adaptieve gewichten bijwerken — gebruik last_signals (alle strategieën)
                # of fallback naar entry_reasons (top-6) voor oude trades
                pnl = trade.get("pnl_pct", 0)
                if pnl != 0:
                    entry_sigs = trade.get("last_signals")
                    if not entry_sigs:
                        entry_sigs = {
                            r["naam"]: r["actie"]
                            for r in trade.get("entry_reasons", [])
                            if r.get("actie", 0) != 0
                        }
                    if entry_sigs:
                        self.signal_combiner.update_weights(entry_sigs, pnl)
                self.telegram.trade_alert(
                    trade["symbol"], "SELL (auto)", trade["price"],
                    trade.get("pnl_pct"), None
                )

        # ── Rolling win rate check na gesloten trades ──────────────
        if closed:
            rolling = self.logger.get_rolling_stats(n=20)
            wr15 = self.logger.get_rolling_stats(n=15)
            # Vroege waarschuwing bij WR < 35% (vóór de 30% pauze)
            if rolling["n"] >= 10 and rolling["win_rate"] < 0.35 and not self._rolling_wr_warned and not self._rolling_wr_paused:
                self._rolling_wr_warned = True
                self.logger.warning(f"Rolling WR waarschuwing: {rolling['win_rate']:.1%} (laatste {rolling['n']} trades)")
                self.telegram.send(
                    f"🔔 <b>Rolling WR Waarschuwing</b>\n"
                    f"Win rate laatste {rolling['n']} trades: <b>{rolling['win_rate']:.1%}</b>\n"
                    f"Drempel 35% bereikt — let op. Pauze treedt in bij &lt;30%."
                )
            elif rolling["win_rate"] >= 0.40 and self._rolling_wr_warned:
                self._rolling_wr_warned = False  # reset zodra WR voldoende hersteld
            if wr15["is_paused"] and not self._rolling_wr_paused:
                self._rolling_wr_paused = True
                self.logger.warning(
                    f"Rolling WR auto-pause: {wr15['win_rate']:.1%} over laatste {wr15['n']} trades"
                )
                self.telegram.send(
                    f"⚠️ <b>Rolling WR Auto-Pause</b>\n"
                    f"Win rate laatste {wr15['n']} trades: <b>{wr15['win_rate']:.1%}</b> (onder 30%)\n"
                    f"Nieuwe entries gepauzeerd tot WR herstelt boven 35%."
                )
            elif rolling["win_rate"] >= 0.35 and self._rolling_wr_paused:
                self._rolling_wr_paused = False
                self.logger.info(f"Rolling WR hersteld: {rolling['win_rate']:.1%} — entries hervat")
                self.telegram.send(
                    f"✅ <b>Rolling WR Hersteld</b>\n"
                    f"Win rate laatste {rolling['n']} trades: <b>{rolling['win_rate']:.1%}</b>\n"
                    f"Bot hervat normale trading."
                )

        # ── 1b. Circuit breaker — dagelijks verliesplafond ─────────
        now = datetime.now()
        if now.day != self._last_daily_reset:
            self._last_daily_reset = now.day
            self._daily_sl_count = 0      # reset SL teller bij nieuwe dag
            self._daily_sl_pause_until = 0.0
            if hasattr(self.engine, "get_status"):
                self._daily_start_value = self.engine.get_status(current_prices).get(
                    "total_value", self._daily_start_value
                )
        if time.time() < self._circuit_breaker_until:
            self._print_dashboard(current_prices)
            self._write_state(current_prices)
            return  # Bot pauzeert — circuit breaker actief

        # ── Rolling WR auto-pause + handmatige pauze ─────────────────
        if self._rolling_wr_paused or self._manual_paused:
            self._print_dashboard(current_prices)
            self._write_state(current_prices)
            return

        # ── Daily SL limiet — geen nieuwe entries na 3 stops vandaag ─
        _daily_sl_paused = self._daily_sl_count >= 3
        if _daily_sl_paused:
            # Toon in dashboard maar blokkeer entries; bestaande posities SL/TP-checks
            # lopen gewoon door (check_stops hierboven is al uitgevoerd)
            self._print_dashboard(current_prices)
            self._write_state(current_prices)
            return

        # ── Drawdown alert (8% drempel, max 1x per niveau) ─────────
        if hasattr(self.engine, "get_status") and current_prices:
            try:
                _dd = self.engine.get_status(current_prices).get("drawdown", 0)
                _tv = self.engine.get_status(current_prices).get("total_value", 0)
                if _dd >= 0.08 and _dd > self._last_drawdown_alert + 0.02:
                    self._last_drawdown_alert = _dd
                    self.telegram.drawdown_alert(_dd, _tv)
                elif _dd < 0.05:
                    self._last_drawdown_alert = 0.0  # Reset als drawdown herstelt
            except Exception:
                pass

        if hasattr(self.engine, "get_status") and self._daily_start_value > 0:
            current_total = self.engine.get_status(current_prices).get("total_value", 0)
            daily_pnl = (current_total - self._daily_start_value) / self._daily_start_value
            if daily_pnl < -0.05:  # Meer dan 5% dagverlies → 24u pauze
                self._circuit_breaker_until = time.time() + 86400
                self.logger.warning(f"Circuit breaker: {daily_pnl:.1%} dagverlies — 24u pauze")
                self.telegram.send(
                    f"🔴 <b>Circuit Breaker</b>\nDagverlies: <b>{daily_pnl:.1%}</b>\n"
                    f"Bot pauzeert 24 uur."
                )
                self._print_dashboard(current_prices)
                self._write_state(current_prices)
                return

        # ── 2. Sentiment (elke 10 cycli = ~10 min) ─────────────────
        if self._cycle % 10 == 1:
            try:
                self._last_sentiment = self.sentiment.combined_sentiment()
            except Exception:
                pass

        # ── 3. Momentum rotatie (elke 30 cycli = ~30 min) ──────────
        # Bouwt een ranglijst van best presterende munten
        _momentum_best: str | None = None
        if self._cycle % 30 == 1 and len(symbols) > 1:
            try:
                sym_dfs = {}
                for sym in symbols:
                    df = self.fetcher.fetch_ohlcv(sym, self.config.timeframe, limit=200)
                    from data.features import add_all_features
                    sym_dfs[sym] = add_all_features(df)
                rotation = self.momentum_rotation.analyze(sym_dfs)
                _momentum_best = rotation.best_symbol if rotation.should_rotate else None
            except Exception:
                pass
        else:
            _momentum_best = getattr(self, "_cached_momentum_best", None)
        self._cached_momentum_best = _momentum_best

        # ── 4. Stat Arb — update prijsgeschiedenis + bereken z-scores ─
        for symbol in symbols:
            try:
                df_sa = self.fetcher.fetch_ohlcv(symbol, self.config.timeframe, limit=100)
                if df_sa is not None and len(df_sa) > 0:
                    self.stat_arb.update(symbol, df_sa["close"])
            except Exception:
                pass
        self._stat_arb_signals = self.stat_arb.compute_signals()

        # ── 5. Per symbool analyseren ──────────────────────────────
        for symbol in symbols:
            try:
                self._analyze_symbol(symbol, current_prices.get(symbol),
                                     momentum_boost=(symbol == _momentum_best))
            except Exception as e:
                self.logger.log_error(f"Analyse {symbol}", e)

        # ── 4. Dashboard + state opslaan voor web-dashboard ──────────
        self._print_dashboard(current_prices)
        self._write_state(current_prices)
        self._save_weights()
        self._save_bot_state()

    def _analyze_symbol(self, symbol: str, cached_price: float | None,
                        momentum_boost: bool = False):
        # ── 1h data ophalen ────────────────────────────────────────
        df = self.fetcher.fetch_ohlcv(symbol, self.config.timeframe, limit=1000)
        df = add_all_features(df)
        if len(df) < 50:
            return  # Te weinig data na feature berekening (bijv. door cache-conflict)
        feature_cols = get_feature_columns(df)
        current_price = float(df["close"].iloc[-1])
        atr = float(df.get("atr_14", df["close"] * 0.02).iloc[-1])
        # Regime detectie hier — sl_mult gebruikt in atr voor bredere stops bij HIGH_VOL

        # ── 15m micro-trend (entry timing) ────────────────────────
        tf_15m = 0
        try:
            df_15m = self.fetcher.fetch_ohlcv(symbol, "15m", limit=200)
            df_15m = add_all_features(df_15m)
            ema9_15m  = df_15m["ema_9"].iloc[-1]
            ema21_15m = df_15m["ema_21"].iloc[-1]
            rsi_15m   = df_15m.get("rsi_14", df_15m["close"]).iloc[-1]
            # Bullish micro: EMA9 > EMA21 + RSI niet overbought
            # Bearish micro: EMA9 < EMA21 + RSI niet oversold
            if ema9_15m > ema21_15m and rsi_15m < 70:
                tf_15m = 1
            elif ema9_15m < ema21_15m and rsi_15m > 30:
                tf_15m = -1
        except Exception:
            pass

        # ── 4h data voor trend filter (multi-timeframe) ────────────
        try:
            df_4h = self.fetcher.fetch_ohlcv(symbol, "4h", limit=500)
            df_4h = add_all_features(df_4h)
            # EMA21/50 op 4h is stabieler dan EMA9/21 — minder vals signalen in zijwaartse markt
            tf_trend = 1 if df_4h["ema_21"].iloc[-1] > df_4h["ema_50"].iloc[-1] else -1
        except Exception:
            tf_trend = 0  # Geen filter als 4h data niet beschikbaar

        # ── 4h BOS — vroeg reversal signaal ───────────────────────
        tf_bos_bullish = False
        tf_bos_bearish = False
        try:
            _ms4h_sig = self._ms4h.signal(df_4h)
            if _ms4h_sig.action == 1 and _ms4h_sig.confidence >= 0.85:
                tf_bos_bullish = True
            elif _ms4h_sig.action == -1 and _ms4h_sig.confidence >= 0.85:
                tf_bos_bearish = True
        except Exception:
            pass

        # ── 1D macro trend filter (derde timeframe) ────────────────
        trend_1d = 0
        try:
            df_1d = self.fetcher.fetch_ohlcv(symbol, "1d", limit=60)
            df_1d = add_all_features(df_1d)
            trend_1d = 1 if df_1d["close"].iloc[-1] > df_1d["ema_50"].iloc[-1] else -1
        except Exception:
            pass

        # ── Marktregime detectie met hysteresis ──────────────────────
        # Gemini: regimes mogen niet elke minuut flikkerden. Pas wisselen na
        # 3 opeenvolgende detecties van het nieuwe regime — voorkomt vals signaal.
        raw_regime = self.regime_detector.detect(df)
        prev_regime = self._last_regime.get(symbol)

        if prev_regime is None or raw_regime.regime == prev_regime.regime:
            regime = raw_regime
            self._regime_change_count[symbol] = 0
        else:
            count = self._regime_change_count.get(symbol, 0) + 1
            self._regime_change_count[symbol] = count
            if count >= 3:
                regime = raw_regime
                self._regime_change_count[symbol] = 0
            else:
                regime = prev_regime  # Stabiel houden — nog niet bevestigd

        self._last_regime[symbol] = regime

        # ── Volatility filter — geen entries bij extreme ATR ──────
        if "atr_14" in df.columns and len(df) >= 20:
            avg_atr = df["atr_14"].iloc[-20:].mean()
            if atr > avg_atr * 2.0:
                return  # ATR > 2× gemiddelde = te chaotisch voor entry

        # ── Anomalie check ─────────────────────────────────────────
        anomaly = self.anomaly.detect(df)
        if anomaly.type != AnomalyType.NORMAL:
            self.logger.log_anomaly(symbol, anomaly.type, anomaly.details)
            if anomaly.severity > 0.6:
                self.telegram.anomaly_alert(symbol, anomaly.type, anomaly.details)
            if not anomaly.should_trade:
                return

        # ── Regime-exit: sluit positie als die tegen huidig regime ingaat ──
        # Short in bull_trend/accumulation → sluit. Long in bear_trend → sluit.
        existing = self.engine.positions.get(symbol)
        if existing:
            regime_val = regime.regime.value
            should_exit = (
                (existing.direction == -1 and regime_val in ("bull_trend", "accumulation")) or
                (existing.direction == 1 and regime_val == "bear_trend")
            )
            if should_exit and (time.time() - getattr(existing, "opened_at", 0)) < 7200:
                should_exit = False  # Min. 2u holdtijd — voorkomt flip door ruis
            if should_exit:
                result = self.engine.sell(symbol, current_price, "regime_exit")
                if result:
                    pnl = result.get("pnl_pct", 0)
                    self.logger.log_trade(result)
                    entry_sigs = {
                        r["naam"]: r["actie"]
                        for r in result.get("entry_reasons", [])
                        if r.get("actie", 0) != 0
                    }
                    if entry_sigs and pnl != 0:
                        self.signal_combiner.update_weights(entry_sigs, pnl)
                    total = self.engine.get_status({symbol: current_price})["total_value"]
                    self._equity_curve.append(total)
                    self._equity_curve = self._equity_curve[-5000:]
                    self._last_trade_time = time.time()
                    self.telegram.trade_alert(symbol, "REGIME-EXIT", current_price, pnl, total)
                    color = "green" if pnl >= 0 else "red"
                    console.print(f"[bold {color}]REGIME-EXIT {symbol}[/bold {color}] "
                                  f"@ {current_price:,.4f} | {regime_val} | PnL: {pnl:+.2%}")

        # ── Signalen verzamelen ────────────────────────────────────
        rl_action, rl_conf = self._get_rl_action(df, feature_cols)
        lstm_action, lstm_conf = self.lstm.predict(df, feature_cols)

        ob = self._last_ob.get(symbol, {})
        if self._cycle % 5 == 1:
            try:
                ob = self.order_book.analyze(symbol)
                self._last_ob[symbol] = ob
            except Exception:
                pass

        # Regime aanpassing — gebruik berekende multipliers vanuit RegimeDetector
        regime_mult = regime.position_mult

        # StatArb ophalen vóór combine() zodat het de score beïnvloedt
        sa = self._stat_arb_signals.get(symbol)
        _stat_arb_active = regime.regime.value in ("ranging", "accumulation", "high_vol")

        signal = self.signal_combiner.combine(
            df,
            rl_action=rl_action, rl_confidence=rl_conf,
            lstm_action=lstm_action, lstm_confidence=lstm_conf,
            sentiment_score=self._last_sentiment.get("score", 0.0),
            ob_signal=ob.get("signal", 0), ob_confidence=ob.get("confidence", 0.0),
            regime_mult=regime_mult,
            regime=regime.regime.value,
            stat_arb_action=sa.action if sa else 0,
            stat_arb_confidence=sa.confidence if sa else 0.0,
            stat_arb_reason=sa.reason if sa else "",
        )

        action = signal["actie"]
        confidence = signal["confidence"]

        # ── No-trade reden bijhouden voor inactiviteitsmelding ────────
        _ntr = ""
        if action == 0:
            _score = signal.get("score", 0)
            _thr = signal.get("threshold_used", 0.20)
            _regime_nl = {
                "bull_trend": "bull trend",
                "bear_trend": "bear trend",
                "ranging": "ranging — strikte drempel",
                "high_vol": "hoge volatiliteit",
                "accumulation": "accumulatie",
            }.get(regime.regime.value, regime.regime.value)
            _ntr = f"Score {_score:+.3f} vs drempel {_thr:.2f} ({_regime_nl})"

        # StatArb is nu geïntegreerd in combine() — alleen het hard veto blijft hier.
        # Hard veto: StatArb conf > 0.65 en tegengestelde richting → trade blokkeren.
        if _stat_arb_active and sa and sa.action != 0 and action != 0:
            if sa.action != action and sa.confidence > 0.65:
                action = 0
                _ntr = f"StatArb veto — sterke divergentie ({sa.reason})"

        # ── 15m micro-trend modifier ───────────────────────────────
        # Niet blokkeren — alleen bijsturen. 15m-bevestiging → +5% confidence.
        # 15m tegengesteld → −5% confidence (zachte penalty, geen veto).
        if tf_15m != 0 and action != 0:
            if tf_15m == action:
                confidence = min(1.0, confidence + 0.05)
            else:
                confidence = max(0.0, confidence - 0.05)

        # ── Multi-timeframe filter (slim) ──────────────────────────
        # Trendstrategieën moeten 4h trend volgen.
        # Mean-reversion mag TEGEN 4h ingaan als 2+ MR-strategieën het eens zijn
        # en geen enkele trendstrategie het ook eens is (dan is het geen MR setup).
        # In accumulation/ranging: sla de MTF-filter over — 1h-signaal is leidend.
        # Ratio: accumulation = mogelijke bodem, ranging = mean reversion fase.
        # De confluence-filter bewaakt de kwaliteit al.
        if tf_trend != 0 and action != 0 and action != tf_trend and regime.regime.value not in ("accumulation", "ranging"):
            _mr = {"Bollinger", "RSI", "Wyckoff", "Grid"}
            _tr = {"EMA_Cross", "Breakout", "MACD", "MarketStructure", "Ichimoku"}
            mr_agree = sum(1 for d in signal.get("details", [])
                           if d.get("naam") in _mr and d.get("actie") == action)
            tr_agree = sum(1 for d in signal.get("details", [])
                           if d.get("naam") in _tr and d.get("actie") == action)
            if not (mr_agree >= 2 and tr_agree == 0):
                action = 0
                _ntr = f"4h trend {'bullish' if tf_trend == 1 else 'bearish'} — 1h signaal gaat andere kant op"

        # ── Filter 1: Regime richting ──────────────────────────────
        # Geen shorts in bull trend, geen longs in bear trend
        if action == -1 and regime.regime.value == "bull_trend":
            action = 0
            _ntr = "Short geblokkeerd — markt is in bull_trend"
        elif action == 1 and regime.regime.value == "bear_trend":
            action = 0
            _ntr = "Long geblokkeerd — markt is in bear_trend"

        # ── Filter 1b: 1D macro filter ─────────────────────────────
        # Blokkeer longs alleen als ZOWEL 1D als 4h bearish zijn.
        # Alleen 1D bearish is niet genoeg — 4h kan herstellen terwijl 1D nog daalt.
        if trend_1d == -1 and tf_trend == -1 and action == 1 and not tf_bos_bullish:
            action = 0
            _ntr = "Long geblokkeerd — 1D én 4h beide bearish"

        # ── Filter 1c: Macro bias in ranging ──────────────────────
        # In ranging regime bepaalt de 1D trend de toegestane richting.
        # Shorts in bullish macro = tegen de stroom in → WR 29-30% (BTC/ETH data).
        # SOL bewijs: zodra bull_trend actief, WR sprong naar 44%.
        if regime.regime.value == "ranging":
            if trend_1d == 1 and action == -1 and not tf_bos_bearish:
                action = 0
                _ntr = "Short geblokkeerd in ranging — 1D macro is bullish"
            elif trend_1d == -1 and action == 1 and not tf_bos_bullish:
                action = 0
                _ntr = "Long geblokkeerd in ranging — 1D macro is bearish"

        # ── Filter 2: Stop-loss cooldown (4 uur) ──────────────────
        # Na een SL: geen herinstap in dezelfde richting voor 4 uur
        if action != 0:
            sl_info = self._last_sl_hit.get(symbol)
            if sl_info:
                sl_time, sl_dir = sl_info
                if time.time() - sl_time < 14400 and action == sl_dir:
                    action = 0
                    _ntr = f"SL cooldown — nog {(14400 - (time.time() - sl_time)) / 3600:.1f}u wachten"

        # ── Filter 3: BOS veto ─────────────────────────────────────
        # Niet shorten als MarketStructure Bullish BOS bevestigt (en vice versa)
        if action != 0:
            for d in signal.get("details", []):
                if d.get("naam") == "MarketStructure" and d.get("confidence", 0) >= 0.70:
                    ms_action = d.get("actie", 0)
                    if ms_action != 0 and ms_action != action:
                        action = 0
                        _ntr = "BOS veto — MarketStructure blokkeert richting"
                        break

        # ── Filter 4: Minimale technische confluence ───────────────
        # Minstens N technische strategieën (excl RL/LSTM/Sentiment/OB) moeten
        # het eens zijn met de uiteindelijke actie — voorkomt RL-dominantie.
        # Shorts vereisen altijd 3 — WR 33% bewees dat 2 te weinig is (SL bounce-risico).
        # Longs: 2 in zwakke regimes (accumulation/ranging/bear_trend), anders 3.
        if action != 0:
            _tech = {"EMA_Cross","Bollinger","RSI","MACD","Breakout",
                     "SMC","SR","Ichimoku","Wyckoff","VolumeProfile",
                     "MarketStructure","Grid"}
            agreeing = sum(
                1 for d in signal.get("details", [])
                if d.get("naam") in _tech and d.get("actie") == action
            )
            if action == -1:
                _min_agreeing = 2 if regime.regime.value in ("accumulation", "ranging") else 3
            else:
                _min_agreeing = 2 if regime.regime.value in ("accumulation", "ranging", "bear_trend") else 3
            if agreeing < _min_agreeing:
                action = 0
                _ntr = f"Confluence te laag — {agreeing}/{_min_agreeing} technische strategieën eens"

        # ── Filter 5: RSI extremen — niet shorten bij oversold, niet longen bij overbought ──
        # Drempel 72 (was 65) — 65 blokkeerde ook A+-setups in sterke trends
        # In sterke bear_trend (≥85%) kan RSI weken lang onder 35 blijven → verlaag drempel naar 28
        if action != 0 and "rsi_14" in df.columns:
            rsi_now = float(df["rsi_14"].iloc[-1])
            _strong_bear = regime.regime.value == "bear_trend" and regime.strength >= 0.85
            _rsi_short_block = 28 if _strong_bear else 35
            if action == -1 and rsi_now < _rsi_short_block:
                action = 0
                _ntr = f"RSI oversold ({rsi_now:.0f}) — geen shorts, bounce verwacht"
            elif action == 1 and rsi_now > 72:
                action = 0
                _ntr = f"RSI overbought ({rsi_now:.0f}) — geen longs, pullback verwacht"

        # ── Filter 5b: Lokaal extreme — geen shorts vlak bij dieptepunt, geen longs bij hoogtepunt ──
        # Rationale: in bear_trend shortte de bot op lokale lows → bounce sloeg SL weg (May 1 incident).
        # Was 2.5%/20 kaarsen — te breed: blokkeerde 60-70% van setups in normale markt.
        # Nu 1.5%/10 kaarsen normaal. In sterke bear (≥85%): 0.5% — short op bounce van low is valide entry.
        if action != 0 and len(df) >= 10:
            local_high = float(df["high"].iloc[-10:].max())
            local_low  = float(df["low"].iloc[-10:].min())
            _local_pct = 0.0 if (regime.regime.value == "bear_trend" and regime.strength >= 0.95) else (0.005 if _strong_bear else 0.015)
            if action == -1 and current_price < local_low * (1 + _local_pct):
                action = 0
                _ntr = f"Short geblokkeerd — prijs {current_price:.2f} binnen {_local_pct:.1%} van lokaal dieptepunt {local_low:.2f}"
            elif action == 1 and current_price > local_high * 0.985:
                action = 0
                _ntr = f"Long geblokkeerd — prijs {current_price:.2f} binnen 1.5% van lokaal hoogtepunt {local_high:.2f}"

        # ── Filter 6: Volume bevestiging — trades alleen bij actieve markt ──
        # Was 0.7 → 0.5 (weekend). In sterke bear_trend (≥85%): 0.30 — volume daalt na dump.
        # Gebruik gemiddelde van laatste 3 voltooide kaarsen (niet huidige) — voorkomt nul-volume
        # bij begin nieuwe uurkaars (minutenlang geen volume in de huidige kaars).
        if action != 0 and "volume_ratio" in df.columns:
            vol_ratio_now = float(df["volume_ratio"].iloc[-4:-1].mean()) if len(df) >= 4 else float(df["volume_ratio"].iloc[-1])
            _vol_min = 0.30 if _strong_bear else 0.50
            if vol_ratio_now < _vol_min:
                action = 0
                _ntr = f"Volume te laag ({vol_ratio_now:.2f}x gemiddeld)"

        # ── Filter 7: Consecutive loss protection ──────────────────
        # Na 3 opeenvolgende verliezen: hogere confidence drempel
        if action != 0:
            recent_closed = [
                t for t in self.logger.trades[-8:]
                if t.get("type") in ("sell", "cover") and "pnl_pct" in t
            ]
            last_3 = recent_closed[-3:] if len(recent_closed) >= 3 else []
            if len(last_3) == 3 and all(t["pnl_pct"] < 0 for t in last_3):
                if confidence < self.risk.min_confidence + 0.10:
                    action = 0
                    _ntr = "Verliesstreak bescherming — 3 verliesgevende trades op rij"

        # ── Filter 8: Global Noise Index ───────────────────────────
        # Bij 2+ ruis-indicatoren actief → markt te onduidelijk → geen trade.
        # ADX < 15 is NORMAAL in ranging/accumulation — sla ADX-check daar over.
        if action != 0:
            noise_score = 0
            _regime_val_f8 = regime.regime.value
            if "adx_14" in df.columns and float(df["adx_14"].iloc[-1]) < 15:
                if _regime_val_f8 not in ("ranging", "accumulation"):
                    noise_score += 1  # Lage ADX = geen trendsterkte (niet relevant in ranging)
            if "volume_ratio" in df.columns:
                _vol_f8 = float(df["volume_ratio"].iloc[-4:-1].mean()) if len(df) >= 4 else float(df["volume_ratio"].iloc[-1])
                if _vol_f8 < 0.40:
                    noise_score += 1  # Laag volume — gemiddelde 3 afgeronde kaarsen (was iloc[-1] = onafgemaakte kaars)
            if "bb_width" in df.columns and len(df) >= 50:
                bb_w = float(df["bb_width"].iloc[-1])
                hist_bb = float(df["bb_width"].rolling(50).mean().iloc[-1])
                if bb_w < hist_bb * 0.20:
                    noise_score += 1  # Alleen echte extreme squeeze (was 0.30 — blokkeerde BTC continu)
            if noise_score >= 2:
                action = 0
                _ntr = f"Markt te noisy ({noise_score}/3) — volume/BB squeeze"

        prices = {symbol: current_price}

        # ── Sla signaaldetails op voor dashboard ───────────────────
        self._last_signal_details[symbol] = signal.get("details", [])

        # ── Funding rate versterkt/verzwakt signaal ────────────────
        try:
            funding = self.funding_analyzer.analyze(symbol)
            if funding.action == action and funding.confidence > 0.5:
                confidence = min(confidence * 1.05, 1.0)  # was 1.2 — lagging indicator
            elif funding.action != 0 and funding.action != action:
                confidence *= 0.95  # was 0.8 — minder hard straffen
        except Exception:
            pass

        # ── Momentum rotatie boost: best presterende munt +15% conf ──
        if momentum_boost:
            confidence = min(confidence * 1.15, 1.0)

        # ── Entry reasons: top signalen gesorteerd op bijdrage ────────
        entry_reasons = [
            {"naam": d["naam"], "reden": d.get("reden", ""), "bijdrage": round(d.get("bijdrage", 0), 4), "actie": d.get("actie", 0)}
            for d in sorted(signal.get("details", []), key=lambda x: abs(x.get("bijdrage", 0)), reverse=True)
            if d.get("actie", 0) != 0
        ][:6]

        # ── Correlatie-filter — max posities in dezelfde richting ──
        # Max 2 in alle regimes — 3 gecoreleerde stops tegelijk te groot verlies (zie May 1 incident).
        if action != 0 and hasattr(self.engine, "positions"):
            same_dir = sum(
                1 for pos in self.engine.positions.values()
                if pos.direction == action
            )
            corr_limit = 2
            if same_dir >= corr_limit:
                _ntr = f"Al {same_dir} {'long' if action == 1 else 'short'} posities open (correlatie-limiet {corr_limit})"
                action = 0

        # ── Regime-specifieke SL/TP ratio's ────────────────────────
        # Verschillende R:R per marktomstandigheid — niet één maat voor alles.
        # high_vol: breed SL zodat we niet uitgestopt worden door ruis.
        # ranging: smal SL + smal TP want mean-reversion doelen zijn dichtbij.
        _REGIME_SL_TP = {
            "bull_trend":   (2.0, 5.0),
            "bear_trend":   (2.5, 5.0),   # Was 2.0 — te strak voor shorts; bounces van 2-3% stopten valide setups
            "ranging":      (1.5, 2.5),   # Was 2.0 → TP1-formule (1.5×sl=2.25ATR) > TP2 (2.0ATR) → altijd cap → 0.6R. Fix: TP2=2.5 zodat TP1=2.25<TP2=2.5, geen cap, proper 1.5R
            "high_vol":     (3.0, 6.0),
            "accumulation": (1.8, 3.5),
        }
        sl_mult_r, tp_mult_r = _REGIME_SL_TP.get(regime.regime.value, (2.0, 4.0))

        # ── Confidence cap — voorkomt onrealistische posities ───────
        # Confidence > 0.75 is statistisch onwaarschijnlijk in 1h crypto.
        # Een A+ setup met conf=0.955 leidde tot een $111 positie (May 4 incident).
        confidence = min(confidence, 0.75)

        # ── Setup kwaliteit: A+/A/B/C scoring via SetupClassifier ───
        vol_ratio_cur = float(df["volume_ratio"].iloc[-1]) if "volume_ratio" in df.columns else 1.0
        clf = self.setup_classifier.classify(
            signal=signal,
            action=action,
            confidence=confidence,
            regime_value=regime.regime.value,
            regime_strength=regime.strength,
            vol_ratio=vol_ratio_cur,
        )
        setup_grade  = clf["grade"]
        position_pct = clf["position_pct"]
        agreeing_count = clf["agreeing_count"]
        quality_pts  = clf["quality_pts"]

        # C-setup met negatieve bewezen edge → sla over
        if clf["skip"]:
            self._last_no_trade_reasons[symbol] = f"Setup grade C met negatieve edge — overgeslagen"
            return

        # Negatieve edge score bij bestaande positie → geen pyramid bijkopen
        if clf.get("edge_score", 0) < 0 and symbol in self.engine.positions:
            self._last_no_trade_reasons[symbol] = f"Negatieve edge ({clf['edge_score']:+.3f}) — geen pyramid"
            return

        # Conservative profiel: alleen A+ en A setups toelaten
        if self.config.only_a_setups and setup_grade not in ("A+", "A"):
            self._last_no_trade_reasons[symbol] = f"Setup grade {setup_grade} — alleen A+/A toegestaan (conservatief profiel)"
            return

        # ── Meta throttle: schaal positie op basis van recente prestaties ─
        throttle = self.meta.get_throttle()
        position_pct = round(position_pct * throttle, 4)

        # Attributie-data die bij elke entry gelogd wordt
        _attribution = {
            "regime": regime.regime.value,
            "regime_strength": round(regime.strength, 2),
            "setup_grade": setup_grade,
            "agreeing_strategies": agreeing_count,
            "quality_score": quality_pts,
            "edge_score": clf["edge_score"],
        }

        # ── Microstructure check — blokkeer bij te grote spread ──────
        ms_ok, current_price = self.microstructure.check_entry(
            current_price, atr, action, ob
        )
        if not ms_ok:
            self._last_no_trade_reasons[symbol] = "Spread te groot — microstructure check gefaald"
            return

        # ── Trade uitvoeren (long én short) ───────────────────────
        # Extra logging-data voor analyse: score, margin, LSTM confidence
        _sig_score = signal.get("score", 0)
        _sig_thresh = signal.get("threshold_used", 0.13)
        _lstm_det = next((d for d in signal.get("details", []) if d.get("naam") == "LSTM"), {})
        _extra_log = {
            "score": round(_sig_score, 4),
            "score_margin": round(abs(_sig_score) - _sig_thresh, 4),
            "lstm_conf": round(_lstm_det.get("confidence", 0.0), 3),
            "lstm_actie": _lstm_det.get("actie", 0),
            "num_agreeing": agreeing_count,
        }

        if action == 0:
            self._last_no_trade_reasons[symbol] = _ntr or "Score onder drempel"
        if action == 1:
            result = self.engine.buy(symbol, current_price, atr, confidence, prices,
                                     entry_reasons=entry_reasons, position_pct=position_pct,
                                     sl_mult=sl_mult_r, tp_mult=tp_mult_r,
                                     regime=regime.regime.value, setup_grade=setup_grade)
            if result:
                self._last_no_trade_reasons.pop(symbol, None)
                self.logger.log_trade({**result, "symbol": symbol, **_attribution,
                                       "last_signals": signal.get("last_signals", {}),
                                       **_extra_log})
                total = self.engine.get_status(prices)["total_value"]
                self._equity_curve.append(total)
                self._equity_curve = self._equity_curve[-5000:]
                self._last_trade_time = time.time()
                self.telegram.trade_alert(symbol, "LONG", current_price, portfolio_value=total)
                edge_str = f" Edge:{clf['edge_score']:+.3f}" if clf["edge_score"] != 0 else ""
                console.print(f"[bold green]^ LONG {symbol}[/bold green] @ {current_price:,.4f} "
                               f"| Regime: {regime.regime.value} [{setup_grade}]{edge_str} "
                               f"| SL={result['stop_loss']:,.4f} TP={result['take_profit']:,.4f}")

        elif action == -1:
            existing_pos = self.engine.positions.get(symbol)
            if existing_pos and existing_pos.direction == 1:
                # Long positie open — sluit alleen als verlies klein is (<0.3%)
                # Grote verliezen laat de stop-loss afhandelen, niet een signaalwissel
                pnl_check = (current_price - existing_pos.entry_price) / existing_pos.entry_price
                if pnl_check > -0.003:
                    result = self.engine.sell(symbol, current_price, "omgekeerd_signaal")
                    if result:
                        pnl = result.get("pnl_pct", 0)
                        self.logger.log_trade(result)
                        self.signal_combiner.update_weights(signal.get("last_signals", {}), pnl)
                        total = self.engine.get_status(prices)["total_value"]
                        self._equity_curve.append(total)
                        self._equity_curve = self._equity_curve[-5000:]
                        self.telegram.trade_alert(symbol, "SELL", current_price, pnl, total)
                        color = "green" if pnl >= 0 else "red"
                        console.print(f"[bold {color}]v SELL {symbol}[/bold {color}] @ {current_price:,.4f} PnL: {pnl:+.2%}")
            else:
                # Geen long open — open short (engine.short() weigert als short al bestaat)
                result = self.engine.short(symbol, current_price, atr, confidence, prices,
                                           entry_reasons=entry_reasons, position_pct=position_pct,
                                           sl_mult=sl_mult_r, tp_mult=tp_mult_r,
                                           regime=regime.regime.value, setup_grade=setup_grade)
                if result:
                    self._last_no_trade_reasons.pop(symbol, None)
                    self.logger.log_trade({**result, "symbol": symbol, **_attribution,
                                           "last_signals": signal.get("last_signals", {}),
                                           **_extra_log})
                    total = self.engine.get_status(prices)["total_value"]
                    self._equity_curve.append(total)
                    self._equity_curve = self._equity_curve[-5000:]
                    self._last_trade_time = time.time()
                    self.telegram.trade_alert(symbol, "SHORT", current_price, portfolio_value=total)
                    edge_str = f" Edge:{clf['edge_score']:+.3f}" if clf["edge_score"] != 0 else ""
                    console.print(f"[bold magenta]v SHORT {symbol}[/bold magenta] @ {current_price:,.4f} "
                                  f"| Regime: {regime.regime.value} [{setup_grade}]{edge_str} "
                                  f"| SL={result['stop_loss']:,.4f} TP={result['take_profit']:,.4f}")

    # ── Dashboard ──────────────────────────────────────────────────
    def _print_dashboard(self, prices: dict):
        console.rule(f"[dim]Cyclus #{self._cycle} — {datetime.now().strftime('%H:%M:%S')}[/dim]")

        # Portfolio status
        if hasattr(self.engine, "get_status"):
            status = self.engine.get_status(prices)
            pnl = status["pnl_pct"]
            pnl_color = "green" if pnl >= 0 else "red"
            summary = self.logger.get_trade_summary()

            portfolio_text = Text()
            portfolio_text.append(f"Portfolio: ", style="bold")
            portfolio_text.append(f"${status['total_value']:,.2f}  ", style="bold white")
            portfolio_text.append(f"PnL: ", style="bold")
            portfolio_text.append(f"{pnl:+.2%}  ", style=f"bold {pnl_color}")
            portfolio_text.append(f"DD: {status['drawdown']:.1%}  ", style="yellow")
            portfolio_text.append(f"Posities: {status['open_positions']}  ", style="cyan")
            portfolio_text.append(f"Trades: {status['total_trades']}  ", style="dim")
            wr_final   = summary.get("win_rate", 0)               # per finale exit
            wr_partial = summary.get("win_rate_with_partials", wr_final)  # incl. partial TPs
            wr_color   = "green" if wr_final >= 0.40 else ("yellow" if wr_final >= 0.32 else "red")
            portfolio_text.append(f"WR: {wr_final:.1%}", style=wr_color)
            portfolio_text.append(f"({wr_partial:.1%}+TP)", style="dim")
            console.print(portfolio_text)

            # Meta throttle indicator
            meta = self.meta.get_state()
            if meta["throttle"] < 1.0:
                throttle_color = "red" if meta["throttle"] <= 0.25 else ("yellow" if meta["throttle"] <= 0.50 else "dark_orange")
                console.print(f"[{throttle_color}]⚠ Throttle: {meta['throttle']:.0%} — {meta['reason']}[/{throttle_color}]")

            # Daily SL teller
            if self._daily_sl_count > 0:
                sl_color = "red" if self._daily_sl_count >= 3 else ("yellow" if self._daily_sl_count >= 2 else "dim")
                sl_status = "GEPAUZEERD — geen nieuwe entries vandaag" if self._daily_sl_count >= 3 else f"{self._daily_sl_count}/3 stops"
                console.print(f"[{sl_color}]⛔ Daily SL: {sl_status}[/{sl_color}]")

        # Sentiment
        sent = self._last_sentiment
        sent_color = "green" if sent.get("score", 0) > 0.1 else ("red" if sent.get("score", 0) < -0.1 else "yellow")
        console.print(
            f"Sentiment: [{sent_color}]{sent.get('label', 'Neutraal')}[/{sent_color}] "
            f"({sent.get('score', 0):+.2f}) | "
            f"F&G: {sent.get('fear_greed', 0):+.2f} | "
            f"Nieuws: {sent.get('news', 0):+.2f}"
        )

        # Regime per symbool
        for sym, reg in self._last_regime.items():
            regime_colors = {
                "bull_trend": "green", "bear_trend": "red",
                "ranging": "yellow", "high_vol": "magenta", "accumulation": "cyan",
            }
            rc = regime_colors.get(reg.regime.value, "white")
            console.print(
                f"[{sym}] Regime: [{rc}]{reg.regime.value}[/{rc}] "
                f"| Kracht: {reg.strength:.0%} | {reg.description}"
            )
        console.print()

    # ── Web dashboard state schrijven ──────────────────────────────
    def _write_state(self, prices: dict):
        try:
            status = self.engine.get_status(prices) if hasattr(self.engine, "get_status") else {}
            positions_out = {}
            for sym, pos in getattr(self.engine, "positions", {}).items():
                cur = prices.get(sym, pos.entry_price)
                if pos.direction == 1:
                    pnl_pct = (cur - pos.entry_price) / pos.entry_price
                    pnl_dollar = (cur - pos.entry_price) * pos.size
                else:
                    pnl_pct = (pos.entry_price - cur) / pos.entry_price
                    pnl_dollar = (pos.entry_price - cur) * pos.size
                positions_out[sym] = {
                    "direction": pos.direction,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "take_profit_2": pos.take_profit_2,
                    "capital_invested": pos.capital_invested,
                    "partial_closed": pos.partial_closed,
                    "pyramid_count": pos.pyramid_count,
                    "current_price": cur,
                    "pnl_pct": pnl_pct,
                    "pnl_dollar": pnl_dollar,
                    "entry_reasons": pos.entry_reasons,
                }
            regimes_out = {}
            for sym, reg in self._last_regime.items():
                regimes_out[sym] = {
                    "regime": reg.regime.value,
                    "strength": reg.strength,
                    "description": reg.description,
                }
            meta_state  = self.meta.get_state()
            state = {
                "running": True,
                "cycle": self._cycle,
                "last_update": datetime.now().isoformat(),
                "prices": prices,
                "portfolio": status,
                "positions": positions_out,
                "regimes": regimes_out,
                "sentiment": self._last_sentiment,
                "summary": self.logger.get_trade_summary(),
                "current_signals": self._last_signal_details,
                "no_trade_reasons": self._last_no_trade_reasons,
                "strategy_stats": self.signal_combiner.get_strategy_stats(),
                "profile": self.config.profile,
                "meta": {
                    "throttle":        meta_state.get("throttle", 1.0),
                    "reason":          meta_state.get("reason", ""),
                    "win_rate_5d":     meta_state.get("recent_win_rate_5d", 0),
                    "streak":          meta_state.get("streak", 0),
                    "session":         meta_state.get("session", ""),
                    "is_weekend":      meta_state.get("is_weekend", False),
                    "hour_multiplier": meta_state.get("hour_multiplier", 1.0),
                },
            }
            state_file = self.logger.log_dir / "state.json"
            state_file.write_text(
                __import__("json").dumps(state, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            # Engine state opslaan zodat herstart posities + balans behoudt
            if hasattr(self.engine, "save_state"):
                self.engine.save_state(self.logger.log_dir / "engine_state.json")
            # Equity curve opslaan voor dashboard grafiek
            self.logger.log_performance({
                "total_value": status.get("total_value", self.config.initial_capital),
                "pnl_pct": status.get("pnl_pct", 0),
                "drawdown": status.get("drawdown", 0),
            })
        except Exception:
            pass

    # ── Backtest mode ──────────────────────────────────────────────
    def run_backtest(self):
        from backtesting.engine import BacktestEngine

        console.print("[bold]Backtest starten...[/bold]")
        bt = BacktestEngine(self.config.initial_capital)
        df = self.fetcher.fetch_historical(
            self.config.symbol, self.config.timeframe,
            days=self.config.backtest_lookback_days
        )
        df = add_all_features(df)
        feature_cols = get_feature_columns(df)

        def signal_fn(slice_df):
            regime_val = "ranging"
            try:
                regime_val = self.regime_detector.detect(slice_df).regime.value
            except Exception:
                pass
            return self.signal_combiner.combine(slice_df, regime=regime_val)

        result = bt.run(df, signal_fn)
        console.print(str(result))

    # ── Train mode ─────────────────────────────────────────────────
    def run_training(self):
        from agent.trainer import ModelTrainer
        trainer = ModelTrainer(self.config, self.fetcher, self.logger)
        console.print("[bold]LSTM trainen...[/bold]")
        acc = trainer.train_lstm(self.lstm)
        console.print(f"[green]LSTM klaar - accuraatheid: {acc:.1%}[/green]")
        console.print("[bold]RL model trainen...[/bold]")
        trainer.train_rl()
        console.print("[green]Training klaar![/green]")


# ── Entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monster Crypto Bot")
    parser.add_argument("--symbol",     default=None)
    parser.add_argument("--timeframe",  default=None)
    parser.add_argument("--capital",    type=float, default=None)
    parser.add_argument("--live",       action="store_true")
    parser.add_argument("--backtest",   action="store_true")
    parser.add_argument("--train",      action="store_true")
    parser.add_argument("--interval",   type=int, default=None)
    parser.add_argument("--api-key",    default=None)
    parser.add_argument("--api-secret", default=None)
    args = parser.parse_args()

    config = Config.from_env()

    # CLI argumenten overschrijven .env
    if args.symbol:
        config.symbol = args.symbol
        config.symbols = [args.symbol]
    if args.timeframe:
        config.timeframe = args.timeframe
    if args.capital:
        config.initial_capital = args.capital
    if args.live:
        config.paper_trading = False
    if args.interval:
        config.interval_seconds = args.interval
    if args.api_key:
        config.api_key = args.api_key
    if args.api_secret:
        config.api_secret = args.api_secret

    bot = MonsterBot(config)

    if args.backtest:
        bot.run_backtest()
    elif args.train:
        bot.run_training()
        # Watchdog-herstart triggeren: verwijder stop-vlag zodat start_bot.sh de bot opnieuw opstart
        import pathlib
        pathlib.Path("/tmp/bot_stop").unlink(missing_ok=True)
    else:
        bot.run()
