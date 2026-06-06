"""
🚀 动量突破策略 — Momentum Breakout
适用于: 现货 + 合约 (合约更佳)
原理: 布林带突破 + 成交量确认，捕捉趋势启动
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import BaseStrategy, Signal, MarketType


class MomentumBreakoutStrategy(BaseStrategy):
    """动量突破策略."""

    @property
    def name(self) -> str:
        return "动量突破"

    @property
    def description(self) -> str:
        return "布林带突破 + 成交量确认，捕捉趋势启动瞬间"

    @property
    def supported_markets(self) -> list[MarketType]:
        return ["spot", "futures"]

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "bb_period": 20,              # 布林带周期
            "bb_std": 2.0,                # 布林带标准差
            "volume_multiplier": 1.8,     # 成交量倍数阈值
            "lookback_volume": 20,        # 成交量参考周期
            "take_profit_pct": 3.0,       # 止盈
            "stop_loss_pct": 1.5,         # 止损
            "trailing_stop_pct": 1.0,     # 追踪止损
            "use_trailing_stop": True,    # 启用追踪止损
            "min_breakout_candles": 1,    # 确认突破的K线数
            "futures_leverage": 3,        # 合约杠杆 (仅合约)
        }

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        self._prices: list[float] = []
        self._volumes: list[float] = []
        self._highest_since_entry: float = 0.0
        self._lowest_since_entry: float = float("inf")
        self._breakout_count: int = 0

    def reset(self):
        super().reset()
        self._prices.clear()
        self._volumes.clear()
        self._highest_since_entry = 0.0
        self._lowest_since_entry = float("inf")
        self._breakout_count = 0

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        price = kline["close"]
        volume = kline["volume"]

        self._prices.append(price)
        self._volumes.append(volume)
        if len(self._prices) > 500:
            self._prices = self._prices[-300:]
            self._volumes = self._volumes[-300:]

        # 数据预热
        bb_period = int(self.params["bb_period"])
        if len(self._prices) < bb_period + 5:
            base_signal = Signal("hold", 0.0, price, "预热中")

        # 已有持仓 → 管理出场
        if self.position.active:
            signal = self._manage_exit(price)
            if signal.action != "hold":
                return signal

        # 计算布林带
        if len(self._prices) < bb_period + 1:
            return Signal("hold", 0.0, price, "数据不足")

        price_arr = np.array(self._prices[-bb_period:])
        sma = np.mean(price_arr)
        std = np.std(price_arr) + 1e-8
        upper_band = sma + self.params["bb_std"] * std
        lower_band = sma - self.params["bb_std"] * std

        # 计算成交量基准
        vol_arr = np.array(self._volumes[-self.params["lookback_volume"]:])
        vol_sma = np.mean(vol_arr) + 1e-8
        vol_ratio = volume / vol_sma

        # 价格在布林带内的位置 (0~1)
        bandwidth = upper_band - lower_band
        bb_position = (price - lower_band) / bandwidth if bandwidth > 0 else 0.5

        # 突破检测
        is_breakout_up = price > upper_band
        is_breakout_down = price < lower_band
        is_volume_surge = vol_ratio >= self.params["volume_multiplier"]

        # 信号强度 (基于突破幅度 + 成交量)
        breakout_strength = 0.0
        action: str = "hold"
        reason = ""

        if is_breakout_up and is_volume_surge:
            self._breakout_count += 1
            breakout_pct = (price - upper_band) / upper_band * 100
            strength = min(abs(breakout_pct) / 2.0, 1.0)
            action = "buy"
            reason = f"多头突破: ${price:.0f} (幅度{breakout_pct:.2f}%, 量比{vol_ratio:.1f}x)"
            breakout_strength = strength
        elif is_breakout_down and is_volume_surge:
            self._breakout_count += 1
            breakout_pct = (price - lower_band) / lower_band * 100
            strength = min(abs(breakout_pct) / 2.0, 1.0)
            # 合约市场可以做空，现货市场用close
            if self._market_type == "futures":
                action = "sell"
                reason = f"空头突破: ${price:.0f} (幅度{breakout_pct:.2f}%, 量比{vol_ratio:.1f}x)"
            else:
                action = "close_long"
                reason = f"下行突破: ${price:.0f}, 离场"
            breakout_strength = strength
        else:
            # 信号衰减
            if self._breakout_count > 0:
                self._breakout_count = max(0, self._breakout_count - 1)

        if action != "hold" and self._breakout_count >= self.params["min_breakout_candles"]:
            tp_price = price * (1 + self.params["take_profit_pct"] / 100) if action == "buy" else \
                       price * (1 - self.params["take_profit_pct"] / 100)
            sl_price = price * (1 - self.params["stop_loss_pct"] / 100) if action == "buy" else \
                       price * (1 + self.params["stop_loss_pct"] / 100)

            return Signal(
                action=action,
                strength=breakout_strength,
                price=price,
                reason=reason,
                sl_price=sl_price,
                tp_price=tp_price,
            )

        return Signal("hold", 0.0, price, f"BB位置: {bb_position:.0%}")

    def _manage_exit(self, price: float) -> Signal:
        """管理持仓退出."""
        entry = self.position.entry_price
        pnl_pct = (price - entry) / entry * 100

        if self.position.side == "long":
            self._highest_since_entry = max(self._highest_since_entry, price)

            # 止损
            if pnl_pct <= -self.params["stop_loss_pct"]:
                return Signal("close_long", 1.0, price, f"止损: {pnl_pct:.2f}%")
            # 止盈
            if pnl_pct >= self.params["take_profit_pct"]:
                return Signal("close_long", 1.0, price, f"止盈: {pnl_pct:.2f}%")
            # 追踪止损
            if self.params["use_trailing_stop"]:
                trail_pct = (self._highest_since_entry - price) / self._highest_since_entry * 100
                if trail_pct >= self.params["trailing_stop_pct"]:
                    return Signal("close_long", 0.8, price,
                                  f"追踪止损: 高位回撤{trail_pct:.2f}%")

        elif self.position.side == "short":
            self._lowest_since_entry = min(self._lowest_since_entry, price)
            pnl_short = (entry - price) / entry * 100

            if pnl_short <= -self.params["stop_loss_pct"]:
                return Signal("close_short", 1.0, price, f"止损: {pnl_short:.2f}%")
            if pnl_short >= self.params["take_profit_pct"]:
                return Signal("close_short", 1.0, price, f"止盈: {pnl_short:.2f}%")
            if self.params["use_trailing_stop"]:
                trail_pct = (price - self._lowest_since_entry) / self._lowest_since_entry * 100
                if trail_pct >= self.params["trailing_stop_pct"]:
                    return Signal("close_short", 0.8, price,
                                  f"追踪止损: 低位反弹{trail_pct:.2f}%")

        return Signal("hold", 0.0, price, "持仓中")

    def update_position(self, action: str, price: float, time: int, qty: float, pnl: float = 0.0):
        super().update_position(action, price, time, qty, pnl)
        if action in ("buy", "sell"):
            self._highest_since_entry = price
            self._lowest_since_entry = price
        elif action in ("close_long", "close_short"):
            self._breakout_count = 0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["breakout"] = {
            "breakout_count": self._breakout_count,
            "highest_since_entry": self._highest_since_entry,
            "lowest_since_entry": self._lowest_since_entry if self._lowest_since_entry != float("inf") else 0,
        }
        return d
