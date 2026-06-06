"""
📈 Volume Surge Detector — 量价突变检测策略

三因子模型:
  Signal = α · price_zscore + β · volume_zscore + γ · volume_delta_zscore

检测逻辑:
  当成交量突然放大(超过均值n个标准差),配合价格位置,
  判断是上涨启动还是下跌启动,产生交易信号。

参数:
  lookback: Z-Score 计算窗口
  entry_threshold: 入场阈值
  exit_threshold: 出场阈值
  stop_loss_pct: 止损百分比
  take_profit_pct: 止盈百分比
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """交易信号."""
    action: str          # buy | sell | close_buy | close_sell | hold
    strength: float      # 信号强度 0-1
    price: float
    reason: str = ""


@dataclass
class PositionState:
    """当前持仓状态."""
    active: bool = False
    side: str = ""        # buy | sell
    entry_price: float = 0.0
    entry_time: int = 0
    quantity: float = 0.0
    trades: int = 0
    win_trades: int = 0


class VolumeSurgeStrategy:
    """量价突变检测策略 — 核心引擎."""

    def __init__(self, params: dict[str, Any] | None = None):
        p = params or {}
        self.lookback = int(p.get("lookback", 20))
        self.entry_threshold = float(p.get("entry_threshold", 2.0))
        self.exit_threshold = float(p.get("exit_threshold", 0.5))
        self.stop_loss_pct = float(p.get("stop_loss_pct", 2.0))
        self.take_profit_pct = float(p.get("take_profit_pct", 5.0))
        self.volume_surge_min = float(p.get("volume_surge_min", 1.5))

        # Alpha weights
        self.price_weight = float(p.get("price_weight", 0.3))
        self.volume_weight = float(p.get("volume_weight", 0.4))
        self.volume_delta_weight = float(p.get("volume_delta_weight", 0.3))

        # Internal state
        self._prices: list[float] = []
        self._volumes: list[float] = []
        self.position = PositionState()
        self._signal_log: list[dict] = []

    def reset(self):
        """重置策略状态."""
        self._prices.clear()
        self._volumes.clear()
        self.position = PositionState()
        self._signal_log.clear()

    def update_params(self, params: dict[str, Any]):
        """动态更新参数."""
        for k, v in params.items():
            if hasattr(self, k):
                setattr(self, k, v)

    @property
    def params(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "volume_surge_min": self.volume_surge_min,
            "price_weight": self.price_weight,
            "volume_weight": self.volume_weight,
            "volume_delta_weight": self.volume_delta_weight,
        }

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        """
        处理新 K 线 → 产生信号.

        kline: {open, high, low, close, volume, open_time}
        """
        self._prices.append(kline["close"])
        self._volumes.append(kline["volume"])

        # 保留足够数据
        if len(self._prices) < self.lookback + 1:
            return Signal("hold", 0.0, kline["close"], "预热中")

        # 只保留 lookback * 2 的数据
        if len(self._prices) > self.lookback * 3:
            self._prices = self._prices[-self.lookback * 2:]
            self._volumes = self._volumes[-self.lookback * 2:]

        # 计算因子
        signal = self._compute_signal(kline)

        # 管理持仓
        if self.position.active:
            signal = self._manage_position(kline, signal)

        # 记录信号
        self._signal_log.append({
            "time": kline["open_time"],
            "price": kline["close"],
            "volume": kline["volume"],
            "action": signal.action,
            "strength": signal.strength,
            "reason": signal.reason,
        })
        if len(self._signal_log) > 1000:
            self._signal_log = self._signal_log[-500:]

        return signal

    def _compute_signal(self, kline: dict) -> Signal:
        """计算三因子模型信号."""
        price_arr = np.array(self._prices)
        vol_arr = np.array(self._volumes)

        # Price Z-Score
        price_sma = np.mean(price_arr[-self.lookback:])
        price_std = np.std(price_arr[-self.lookback:]) + 1e-8
        price_z = (kline["close"] - price_sma) / price_std

        # Volume Z-Score
        vol_sma = np.mean(vol_arr[-self.lookback:])
        vol_std = np.std(vol_arr[-self.lookback:]) + 1e-8
        vol_z = (kline["volume"] - vol_sma) / vol_std

        # Volume Delta (导数 — 相对变化)
        if len(vol_arr) >= 2:
            vol_delta = (kline["volume"] - vol_arr[-2]) / (vol_arr[-2] + 1e-8)
        else:
            vol_delta = 0.0

        # Volume surge check
        vol_ratio = kline["volume"] / (vol_sma + 1e-8)
        is_surge = vol_ratio >= self.volume_surge_min

        # Combined signal
        signal_value = (
            self.price_weight * price_z
            + self.volume_weight * vol_z
            + self.volume_delta_weight * vol_delta * 10  # scale
        )

        strength = min(abs(signal_value) / self.entry_threshold, 1.0)

        # 入场逻辑: 成交量放大 + 信号强度超过阈值
        if not self.position.active:
            if is_surge and signal_value >= self.entry_threshold:
                return Signal("buy", strength, kline["close"],
                              f"量价突涨: vol_ratio={vol_ratio:.2f}, signal={signal_value:.2f}")
            elif is_surge and signal_value <= -self.entry_threshold:
                return Signal("sell", strength, kline["close"],
                              f"量价突跌: vol_ratio={vol_ratio:.2f}, signal={signal_value:.2f}")

        return Signal("hold", strength, kline["close"], "")

    def _manage_position(self, kline: dict, current_signal: Signal) -> Signal:
        """管理已有持仓: 止盈止损 + 信号反转出场."""
        price = kline["close"]
        entry = self.position.entry_price

        if self.position.side == "buy":
            pnl_pct = (price - entry) / entry * 100
            # 止损
            if pnl_pct <= -self.stop_loss_pct:
                return Signal("close_buy", 1.0, price, f"止损: {pnl_pct:.2f}%")
            # 止盈
            if pnl_pct >= self.take_profit_pct:
                return Signal("close_buy", 1.0, price, f"止盈: {pnl_pct:.2f}%")
            # 信号反转
            if current_signal.action == "sell" or current_signal.strength < self.exit_threshold:
                return Signal("close_buy", 0.5, price, "信号减弱出场")

        elif self.position.side == "sell":
            pnl_pct = (entry - price) / entry * 100
            if pnl_pct <= -self.stop_loss_pct:
                return Signal("close_sell", 1.0, price, f"止损: {pnl_pct:.2f}%")
            if pnl_pct >= self.take_profit_pct:
                return Signal("close_sell", 1.0, price, f"止盈: {pnl_pct:.2f}%")
            if current_signal.action == "buy" or current_signal.strength < self.exit_threshold:
                return Signal("close_sell", 0.5, price, "信号减弱出场")

        return Signal("hold", current_signal.strength, price, "持仓中")

    def update_position(self, action: str, price: float, time: int, qty: float):
        """更新持仓状态 (由交易执行器调用)."""
        if action in ("buy", "sell"):
            self.position.active = True
            self.position.side = action
            self.position.entry_price = price
            self.position.entry_time = time
            self.position.quantity = qty
            self.position.trades += 1
        elif action in ("close_buy", "close_sell"):
            self.position.active = False
            self.position.quantity = 0.0

    @property
    def signal_log(self) -> list[dict]:
        return self._signal_log[-100:]
