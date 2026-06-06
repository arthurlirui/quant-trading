"""
🔄 均值回归策略 — Mean Reversion
适用于: 现货 + 合约
原理: RSI 超买超卖 + 布林带回归，捕捉价格回归均值
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import BaseStrategy, Signal, MarketType


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略."""

    @property
    def name(self) -> str:
        return "均值回归"

    @property
    def description(self) -> str:
        return "RSI 超买超卖 + 布林带回归，低买高卖赚回归"

    @property
    def supported_markets(self) -> list[MarketType]:
        return ["spot", "futures"]

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "rsi_period": 14,             # RSI 周期
            "rsi_oversold": 30,            # 超卖阈值
            "rsi_overbought": 70,          # 超买阈值
            "bb_period": 20,               # 布林带周期
            "bb_std": 2.5,                 # 布林带标准差 (更宽, 避免假信号)
            "entry_threshold": 0.3,        # 入场置信度
            "take_profit_pct": 2.0,        # 止盈
            "stop_loss_pct": 1.5,          # 止损
            "max_holding_bars": 48,        # 最大持仓K线数
            "min_deviation_reentry": 0.5,  # 重新入场最小偏离
            "futures_leverage": 2,         # 合约杠杆
        }

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        self._prices: list[float] = []
        self._holding_bars: int = 0

    def reset(self):
        super().reset()
        self._prices.clear()
        self._holding_bars = 0

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        price = kline["close"]
        self._prices.append(price)
        if len(self._prices) > 500:
            self._prices = self._prices[-300:]

        # 数据预热
        bb_period = int(self.params["bb_period"])
        if len(self._prices) < max(bb_period, self.params["rsi_period"]) + 5:
            return Signal("hold", 0.0, price, "预热中")

        # 持仓管理
        if self.position.active:
            self._holding_bars += 1
            exit_signal = self._check_exit(price)
            if exit_signal.action != "hold":
                return exit_signal

        # 计算 RSI
        rsi = self._compute_rsi()

        # 计算布林带
        price_arr = np.array(self._prices[-bb_period:])
        sma = np.mean(price_arr)
        std = np.std(price_arr) + 1e-8
        upper_band = sma + self.params["bb_std"] * std
        lower_band = sma - self.params["bb_std"] * std

        # Z-Score (价格偏离)
        zscore = (price - sma) / std

        # 信号逻辑
        signal_value = 0.0
        action: str = "hold"
        reason = ""

        # 超卖 + 跌破下轨 → 做多
        if rsi <= self.params["rsi_oversold"] and price <= lower_band:
            # 偏离强度
            deviation = (lower_band - price) / lower_band * 100
            signal_value = min(abs(zscore) / 3.0, 1.0)
            if signal_value >= self.params["entry_threshold"]:
                action = "buy"
                reason = f"超卖回归: RSI={rsi:.1f}, 偏离${price:.0f} (Z={zscore:.2f})"

        # 超买 + 突破上轨 → 做空 (合约) / 平多 (现货)
        elif rsi >= self.params["rsi_overbought"] and price >= upper_band:
            deviation = (price - upper_band) / upper_band * 100
            signal_value = min(abs(zscore) / 3.0, 1.0)
            if signal_value >= self.params["entry_threshold"]:
                if self._market_type == "futures":
                    action = "sell"
                    reason = f"超买回归: RSI={rsi:.1f}, 偏离${price:.0f} (Z={zscore:.2f})"
                else:
                    action = "close_long"
                    reason = f"超买离场: RSI={rsi:.1f}, 上轨突破"

        if action in ("buy", "sell"):
            tp_price = price * (1 + self.params["take_profit_pct"] / 100) if action == "buy" else \
                       price * (1 - self.params["take_profit_pct"] / 100)
            sl_price = price * (1 - self.params["stop_loss_pct"] / 100) if action == "buy" else \
                       price * (1 + self.params["stop_loss_pct"] / 100)

            return Signal(
                action=action,
                strength=signal_value,
                price=price,
                reason=reason,
                sl_price=sl_price,
                tp_price=tp_price,
            )

        return Signal("hold", 0.0, price,
                      f"RSI={rsi:.1f}, Z={zscore:.2f}")

    def _compute_rsi(self) -> float:
        """计算 RSI."""
        period = int(self.params["rsi_period"])
        prices = self._prices[-(period + 1):]
        if len(prices) < period + 1:
            return 50.0

        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change >= 0:
                gains.append(change)
            else:
                losses.append(abs(change))

        avg_gain = np.mean(gains) if gains else 0
        avg_loss = np.mean(losses) if losses else 1e-8

        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _check_exit(self, price: float) -> Signal:
        """检查是否需要退出."""
        entry = self.position.entry_price

        if self.position.side == "long":
            pnl_pct = (price - entry) / entry * 100
            if pnl_pct <= -self.params["stop_loss_pct"]:
                return Signal("close_long", 1.0, price, f"止损: {pnl_pct:.2f}%")
            if pnl_pct >= self.params["take_profit_pct"]:
                return Signal("close_long", 1.0, price, f"止盈: {pnl_pct:.2f}%")

        elif self.position.side == "short":
            pnl_pct = (entry - price) / entry * 100
            if pnl_pct <= -self.params["stop_loss_pct"]:
                return Signal("close_short", 1.0, price, f"止损: {pnl_pct:.2f}%")
            if pnl_pct >= self.params["take_profit_pct"]:
                return Signal("close_short", 1.0, price, f"止盈: {pnl_pct:.2f}%")

        # 最大持仓时间
        if self._holding_bars >= self.params["max_holding_bars"]:
            side = "close_long" if self.position.side == "long" else "close_short"
            return Signal(side, 0.5, price, f"超时平仓: {self._holding_bars}根K线")

        return Signal("hold", 0.0, price, "持仓中")

    def update_position(self, action: str, price: float, time: int, qty: float, pnl: float = 0.0):
        super().update_position(action, price, time, qty, pnl)
        if action in ("buy", "sell"):
            self._holding_bars = 0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["mean_reversion"] = {
            "holding_bars": self._holding_bars,
        }
        return d
