"""
🔙 Backtest Engine — 事件驱动回测引擎

支持:
  - 多周期回测
  - 手续费模拟
  - 滑点模拟
  - 策略参数优化
  - 详细绩效报告
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.strategy import VolumeSurgeStrategy, Signal
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    strategy_id: str = ""
    symbol: str = ""
    start_time: int = 0
    end_time: int = 0
    total_return: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    final_capital: float = 0.0
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BacktestEngine:
    """事件驱动回测引擎."""

    def __init__(self, initial_capital: float | None = None,
                 commission: float | None = None):
        self.initial_capital = initial_capital or settings.backtest_initial_capital
        self.commission = commission or settings.backtest_commission

    async def run(self, strategy: VolumeSurgeStrategy, klines: list[dict],
                  symbol: str = "BTCUSDT") -> BacktestResult:
        """运行回测.

        Args:
            strategy: 策略实例(已配置参数)
            klines: K线数据 [{open_time, open, high, low, close, volume}, ...]
            symbol: 交易对

        Returns:
            BacktestResult: 回测结果
        """
        if len(klines) < 50:
            return BacktestResult(errors=["数据不足 (最少 50 根 K线)"])

        strategy.reset()
        result = BacktestResult(
            strategy_id=strategy.__class__.__name__,
            symbol=symbol,
            start_time=klines[0]["open_time"],
            end_time=klines[-1]["open_time"],
        )

        capital = self.initial_capital
        position = 0.0  # 持仓数量
        position_side = ""  # buy | sell
        entry_price = 0.0
        equity_curve = [capital]
        trades: list[dict] = []

        for i, kline in enumerate(klines):
            signal = strategy.on_kline(kline)

            # 执行交易
            capital, position, position_side, entry_price, trade = self._execute(
                capital, position, position_side, entry_price,
                signal, kline, i, strategy,
            )
            if trade:
                trades.append(trade)

            # 更新持仓市值
            if position > 0 and position_side == "buy":
                equity = capital + position * kline["close"]
            elif position > 0 and position_side == "sell":
                equity = capital + position * (2 * entry_price - kline["close"])
            else:
                equity = capital
            equity_curve.append(equity)

        # 计算绩效指标
        result = self._compute_metrics(result, trades, equity_curve, capital)
        result.trades = trades
        result.equity_curve = equity_curve
        return result

    def _execute(self, capital: float, position: float, position_side: str,
                 entry_price: float, signal: Signal, kline: dict,
                 idx: int, strategy: VolumeSurgeStrategy) -> tuple[float, float, str, float, dict | None]:
        """执行单笔交易."""
        price = kline["close"]
        trade = None

        if signal.action == "buy" and position == 0:
            qty = capital * 0.95 / price
            cost = qty * price * (1 + self.commission)
            if cost <= capital:
                position = qty
                position_side = "buy"
                entry_price = price
                capital -= cost
                strategy.update_position("buy", price, kline["open_time"], qty)
                trade = {
                    "time": kline["open_time"], "side": "buy",
                    "price": price, "quantity": qty, "cost": cost,
                    "reason": signal.reason,
                }

        elif signal.action == "sell" and position == 0:
            # 做空
            qty = capital * 0.95 / price
            position = qty
            position_side = "sell"
            entry_price = price
            capital += qty * price * (1 - self.commission)
            strategy.update_position("sell", price, kline["open_time"], qty)
            trade = {
                "time": kline["open_time"], "side": "sell",
                "price": price, "quantity": qty,
                "reason": signal.reason,
            }

        elif signal.action == "close_buy" and position > 0:
            revenue = position * price * (1 - self.commission)
            pnl = revenue - (position * entry_price * (1 + self.commission))
            trade = {
                "time": kline["open_time"], "side": "close_buy",
                "price": price, "quantity": position,
                "pnl": round(pnl, 2), "pnl_pct": round(pnl / capital * 100, 2),
                "reason": signal.reason, "entry_price": entry_price,
            }
            capital += revenue
            position = 0
            position_side = ""
            entry_price = 0
            strategy.update_position("close_buy", price, kline["open_time"], 0)
            strategy.position.win_trades += 1 if pnl > 0 else 0

        elif signal.action == "close_sell" and position > 0:
            cost = position * price * (1 + self.commission)
            pnl = (position * entry_price) - cost
            trade = {
                "time": kline["open_time"], "side": "close_sell",
                "price": price, "quantity": position,
                "pnl": round(pnl, 2), "pnl_pct": round(pnl / capital * 100, 2),
                "reason": signal.reason, "entry_price": entry_price,
            }
            capital -= cost
            position = 0
            position_side = ""
            entry_price = 0
            strategy.update_position("close_sell", price, kline["open_time"], 0)
            strategy.position.win_trades += 1 if pnl > 0 else 0

        return capital, position, position_side, entry_price, trade

    def _compute_metrics(self, result: BacktestResult, trades: list[dict],
                         equity_curve: list[float], final_capital: float) -> BacktestResult:
        """计算绩效指标."""
        result.total_trades = len([t for t in trades if t["side"] in ("close_buy", "close_sell")])
        result.final_capital = final_capital
        result.net_profit = final_capital - self.initial_capital
        result.total_return = result.net_profit
        result.total_return_pct = (final_capital / self.initial_capital - 1) * 100

        closed = [t for t in trades if "pnl" in t]
        result.winning_trades = len([t for t in closed if t.get("pnl", 0) > 0])
        result.losing_trades = len([t for t in closed if t.get("pnl", 0) <= 0])
        result.win_rate = (result.winning_trades / max(result.total_trades, 1)) * 100

        if closed:
            pnls = [t["pnl"] for t in closed]
            result.gross_profit = sum(p for p in pnls if p > 0)
            result.gross_loss = abs(sum(p for p in pnls if p < 0))
            result.profit_factor = result.gross_profit / max(result.gross_loss, 1e-8)

            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            result.avg_win = np.mean(wins) if wins else 0
            result.avg_loss = abs(np.mean(losses)) if losses else 0

        # Sharpe Ratio (年化)
        if len(equity_curve) > 1:
            returns = np.diff(np.log(np.array(equity_curve) + 1e-8))
            if np.std(returns) > 0:
                result.sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(365 * 24 * 60))

        # Max Drawdown
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown = max_dd

        return result
