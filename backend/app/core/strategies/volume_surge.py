"""
📈 Volume Surge Detector — 量价突变检测策略

三因子模型:
  Signal = α · price_zscore + β · volume_zscore + γ · volume_delta_zscore

适用于: 现货 + 合约
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .base import BaseStrategy, Signal, MarketType

logger = logging.getLogger(__name__)


class VolumeSurgeStrategy(BaseStrategy):
    """量价突变检测策略."""

    @property
    def name(self) -> str:
        return "量价突变"

    @property
    def description(self) -> str:
        return "三因子量价突变检测 (价格Z-Score + 成交量Z-Score + 成交量导数)"

    @property
    def supported_markets(self) -> list[MarketType]:
        return ["spot", "futures"]

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "lookback": 20,
            "entry_threshold": 2.0,
            "exit_threshold": 0.5,
            "stop_loss_pct": 2.0,
            "take_profit_pct": 5.0,
            "volume_surge_min": 1.5,
            "price_weight": 0.3,
            "volume_weight": 0.4,
            "volume_delta_weight": 0.3,
            "futures_leverage": 2,
        }

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        self._prices: list[float] = []
        self._volumes: list[float] = []

    def reset(self):
        super().reset()
        self._prices.clear()
        self._volumes.clear()

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        self._prices.append(kline["close"])
        self._volumes.append(kline["volume"])

        lookback = int(self.params["lookback"])

        if len(self._prices) < lookback + 1:
            return Signal("hold", 0.0, kline["close"], "预热中")

        if len(self._prices) > lookback * 3:
            self._prices = self._prices[-lookback * 2:]
            self._volumes = self._volumes[-lookback * 2:]

        # 已有持仓 -> 检查出场
        if self.position.active:
            exit_signal = self._check_exit(kline)
            if exit_signal.action != "hold":
                return exit_signal

        signal = self._compute_signal(kline)
        return signal

    def _compute_signal(self, kline: dict) -> Signal:
        lookback = int(self.params["lookback"])
        price_arr = np.array(self._prices)
        vol_arr = np.array(self._volumes)

        price_sma = np.mean(price_arr[-lookback:])
        price_std = np.std(price_arr[-lookback:]) + 1e-8
        price_z = (kline["close"] - price_sma) / price_std

        vol_sma = np.mean(vol_arr[-lookback:])
        vol_std = np.std(vol_arr[-lookback:]) + 1e-8
        vol_z = (kline["volume"] - vol_sma) / vol_std

        if len(vol_arr) >= 2:
            vol_delta = (kline["volume"] - vol_arr[-2]) / (vol_arr[-2] + 1e-8)
        else:
            vol_delta = 0.0

        vol_ratio = kline["volume"] / (vol_sma + 1e-8)
        is_surge = vol_ratio >= self.params["volume_surge_min"]

        signal_value = (
            self.params["price_weight"] * price_z
            + self.params["volume_weight"] * vol_z
            + self.params["volume_delta_weight"] * vol_delta * 10
        )

        strength = min(abs(signal_value) / self.params["entry_threshold"], 1.0)

        if not self.position.active:
            if is_surge and signal_value >= self.params["entry_threshold"]:
                tp = kline["close"] * (1 + self.params["take_profit_pct"] / 100)
                sl = kline["close"] * (1 - self.params["stop_loss_pct"] / 100)
                return Signal("buy", strength, kline["close"],
                              f"量价突涨: vol_ratio={vol_ratio:.2f}, signal={signal_value:.2f}",
                              sl_price=sl, tp_price=tp)

            elif is_surge and signal_value <= -self.params["entry_threshold"]:
                if self._market_type == "futures":
                    tp = kline["close"] * (1 - self.params["take_profit_pct"] / 100)
                    sl = kline["close"] * (1 + self.params["stop_loss_pct"] / 100)
                    return Signal("sell", strength, kline["close"],
                                  f"量价突跌: vol_ratio={vol_ratio:.2f}, signal={signal_value:.2f}",
                                  sl_price=sl, tp_price=tp)
                else:
                    return Signal("close_long", strength, kline["close"],
                                  f"量价突跌, 离场: signal={signal_value:.2f}")

        return Signal("hold", strength, kline["close"], "")

    def _check_exit(self, kline: dict) -> Signal:
        price = kline["close"]
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

        return Signal("hold", 0.0, price, "持仓中")

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["volume_surge"] = {
            "data_points": len(self._prices),
            "price_sma": round(np.mean(self._prices[-20:]), 2) if len(self._prices) >= 20 else 0,
        }
        return d
