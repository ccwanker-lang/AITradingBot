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
from strategies.scalping import ScalpingStrategy
from strategies.regime import RegimeDetector, Regime
from strategies.momentum_rotation import MomentumRotation
from data.funding_rate import FundingRateAnalyzer
from monitoring.report import ReportGenerator
from agent.lstm_predictor import LSTMPredictor
from risk.manager import RiskManager
from monitoring.logger import BotLogger
from monitoring.telegram_bot import TelegramBot

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
        self.scalper = ScalpingStrategy()
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
            self.engine = PaperEngine(config.initial_capital, self.risk)
        else:
            from execution.live_engine import LiveEngine
            self.engine = LiveEngine(
                config.exchange_id, config.api_key, config.api_secret,
                self.risk, config.initial_capital,
            )

        # Auto-hertrainer
        self._start_auto_retrain()

        # Telegram commando's registreren
        self._register_telegram_commands()

        # Status
        self._cycle = 0
        self._last_sentiment = {"score": 0.0, "signal": 0, "label": "Neutraal"}
        self._last_ob: dict[str, dict] = {}
        self._last_regime: dict[str, object] = {}
        self._equity_curve: list[float] = [config.initial_capital]
        self._last_summary_day = -1
        self._start_daily_summary_thread()
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

    # ── Telegram commando's ────────────────────────────────────────
    def _register_telegram_commands(self):
        self.telegram.register("bal", self._cmd_bal)
        self.telegram.register("stats", self._cmd_stats)
        self.telegram.register("posities", self._cmd_posities)
        self.telegram.register("stop", self._cmd_stop)

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
            positions = self.engine.portfolio.state.positions
            if not positions:
                return "📋 <b>Open posities</b>\n\nGeen open posities."
            lines = ["📋 <b>Open posities</b>\n"]
            for sym, pos in positions.items():
                price = prices.get(sym, pos.entry_price)
                pnl = (price - pos.entry_price) / pos.entry_price
                sign = "+" if pnl >= 0 else ""
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f"{emoji} <b>{sym}</b>\n"
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
            from agent.environment import CryptoTradingEnv
            env = CryptoTradingEnv(df, feature_cols, window_size=20)
            env.reset()
            env.current_step = len(df) - 1
            obs = env._get_observation()
            action, _ = self.rl_model.predict(obs, deterministic=True)
            return {0: 0, 1: 1, 2: -1}.get(int(action), 0), 0.65
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
                self.telegram.trade_alert(
                    trade["symbol"], "SELL (auto)", trade["price"],
                    trade.get("pnl_pct"), None
                )

        # ── 2. Sentiment (elke 10 cycli = ~10 min) ─────────────────
        if self._cycle % 10 == 1:
            try:
                self._last_sentiment = self.sentiment.combined_sentiment()
            except Exception:
                pass

        # ── 3. Per symbool analyseren ──────────────────────────────
        for symbol in symbols:
            try:
                self._analyze_symbol(symbol, current_prices.get(symbol))
            except Exception as e:
                self.logger.log_error(f"Analyse {symbol}", e)

        # ── 4. Dashboard + state opslaan voor web-dashboard ──────────
        self._print_dashboard(current_prices)
        self._write_state(current_prices)

    def _analyze_symbol(self, symbol: str, cached_price: float | None):
        # ── 1h data ophalen ────────────────────────────────────────
        df = self.fetcher.fetch_ohlcv(symbol, self.config.timeframe, limit=400)
        df = add_all_features(df)
        feature_cols = get_feature_columns(df)
        current_price = float(df["close"].iloc[-1])
        atr = float(df.get("atr_14", df["close"] * 0.02).iloc[-1])

        # ── 4h data voor trend filter (multi-timeframe) ────────────
        try:
            df_4h = self.fetcher.fetch_ohlcv(symbol, "4h", limit=100)
            df_4h = add_all_features(df_4h)
            tf_trend = 1 if df_4h["ema_9"].iloc[-1] > df_4h["ema_21"].iloc[-1] else -1
        except Exception:
            tf_trend = 0  # Geen filter als 4h data niet beschikbaar

        # ── Marktregime detectie ───────────────────────────────────
        regime = self.regime_detector.detect(df)
        self._last_regime[symbol] = regime

        # ── Anomalie check ─────────────────────────────────────────
        anomaly = self.anomaly.detect(df)
        if anomaly.type != AnomalyType.NORMAL:
            self.logger.log_anomaly(symbol, anomaly.type, anomaly.details)
            if anomaly.severity > 0.6:
                self.telegram.anomaly_alert(symbol, anomaly.type, anomaly.details)
            if not anomaly.should_trade:
                return

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

        # Regime aanpassing: bear trend = minder kopen
        regime_mult = 1.0
        if regime.regime == Regime.BEAR_TREND:
            regime_mult = 0.5
        elif regime.regime == Regime.HIGH_VOL:
            regime_mult = 0.4
        elif regime.regime == Regime.BULL_TREND:
            regime_mult = 1.2

        signal = self.signal_combiner.combine(
            df,
            rl_action=rl_action, rl_confidence=rl_conf,
            lstm_action=lstm_action, lstm_confidence=lstm_conf,
            sentiment_score=self._last_sentiment.get("score", 0.0),
            ob_signal=ob.get("signal", 0), ob_confidence=ob.get("confidence", 0.0),
            regime_mult=regime_mult,
        )

        # ── Multi-timeframe filter ─────────────────────────────────
        # Alleen kopen als 4h ook bullish, alleen verkopen als 4h bearish
        action = signal["actie"]
        if tf_trend != 0 and action != 0 and action != tf_trend:
            action = 0  # 1h en 4h zijn het niet eens — wachten

        confidence = signal["confidence"]
        prices = {symbol: current_price}

        # ── Funding rate versterkt/verzwakt signaal ────────────────
        try:
            funding = self.funding_analyzer.analyze(symbol)
            if funding.action == action and funding.confidence > 0.5:
                confidence = min(confidence * 1.2, 1.0)
            elif funding.action != 0 and funding.action != action:
                confidence *= 0.8
        except Exception:
            pass

        # ── Trade uitvoeren (long én short) ───────────────────────
        if action == 1:
            result = self.engine.buy(symbol, current_price, atr, confidence, prices)
            if result:
                self.logger.log_trade({**result, "symbol": symbol})
                total = self.engine.get_status(prices)["total_value"]
                self._equity_curve.append(total)
                self.telegram.trade_alert(symbol, "LONG", current_price, portfolio_value=total)
                console.print(f"[bold green]^ LONG {symbol}[/bold green] @ {current_price:,.4f} "
                               f"| Regime: {regime.regime.value} "
                               f"| SL={result['stop_loss']:,.4f} TP={result['take_profit']:,.4f}")

        elif action == -1:
            # Sluit open long first, dan open short
            long_pos = self.engine.positions.get(symbol)
            if long_pos and long_pos.direction == 1:
                result = self.engine.sell(symbol, current_price, "omgekeerd_signaal")
                if result:
                    pnl = result.get("pnl_pct", 0)
                    self.logger.log_trade(result)
                    self.signal_combiner.update_weights(signal.get("last_signals", {}), pnl)
                    total = self.engine.get_status(prices)["total_value"]
                    self._equity_curve.append(total)
                    self.telegram.trade_alert(symbol, "SELL", current_price, pnl, total)
                    color = "green" if pnl >= 0 else "red"
                    console.print(f"[bold {color}]v SELL {symbol}[/bold {color}] @ {current_price:,.4f} PnL: {pnl:+.2%}")
            else:
                # Open short positie
                result = self.engine.short(symbol, current_price, atr, confidence, prices)
                if result:
                    self.logger.log_trade({**result, "symbol": symbol})
                    total = self.engine.get_status(prices)["total_value"]
                    self._equity_curve.append(total)
                    self.telegram.trade_alert(symbol, "SHORT", current_price, portfolio_value=total)
                    console.print(f"[bold magenta]v SHORT {symbol}[/bold magenta] @ {current_price:,.4f} "
                                  f"| Regime: {regime.regime.value} "
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
            portfolio_text.append(f"Win%: {summary.get('win_rate', 0):.1%}", style="green")
            console.print(portfolio_text)

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
                positions_out[sym] = {
                    "direction": pos.direction,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": pos.take_profit,
                    "current_price": prices.get(sym, pos.entry_price),
                    "pnl_pct": (
                        (prices.get(sym, pos.entry_price) - pos.entry_price) / pos.entry_price
                        if pos.direction == 1
                        else (pos.entry_price - prices.get(sym, pos.entry_price)) / pos.entry_price
                    ),
                }
            regimes_out = {}
            for sym, reg in self._last_regime.items():
                regimes_out[sym] = {
                    "regime": reg.regime.value,
                    "strength": reg.strength,
                    "description": reg.description,
                }
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
            }
            state_file = self.logger.log_dir / "state.json"
            state_file.write_text(
                __import__("json").dumps(state, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
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
            return self.signal_combiner.combine(slice_df)

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
    else:
        bot.run()
