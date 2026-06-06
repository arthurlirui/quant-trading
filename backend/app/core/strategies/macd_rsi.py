"""
🎯 MACD + RSI 双指标策略 — MACD RSI Combo
适用于: 合约 (做空+做多) / 现货 (仅做多)
原理: MACD 金叉/死叉 + RSI 过滤，双指标确认降低假信号
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .base import BaseStrategy, Signal, MarketType


class MACDComboStrategy(BaseStrategy):
    """MACD + RSI 双指标组合策略."""

    @property
    def name(self) -> str:
        return "MACD+RSI 组合"

    @property
    def description(self) -> str:
        return "MACD 金叉死叉 + RSI 过滤，双指标确认降低假信号"

    @property
    def supported_markets(self) -> list[MarketType]:
        return ["spot", "futures"]

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "macd_fast": 12,              # MACD 快线周期
            "macd_slow": 26,              # MACD 慢线周期
            "macd_signal": 9,             # MACD 信号线周期
            "rsi_period": 14,             # RSI 周期
            "rsi_long_threshold": 50,     # 做多 RSI 过滤 (> 此值)
            "rsi_short_threshold": 50,    # 做空 RSI 过滤 (< 此值)
            "histogram_threshold": 0.0,   # 柱状图最小绝对值
            "take_profit_pct": 2.5,       # 止盈
            "stop_loss_pct": 1.5,         # 止损
            "trailing_stop_pct": 1.2,     # 追踪止损
            "use_trailing_stop": True,    # 启用追踪
            "max_holding_bars": 60,       # 最大持仓K线
            "futures_leverage": 3,        # 合约杠杆
        }

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        self._prices: list[float] = []
        self._holding_bars: int = 0
        self._prev_macd: float = 0.0
        self._prev_signal: float = 0.0
        self._prev_hist: float = 0.0

    def reset(self):
        super().reset()
        self._prices.clear()
        self._holding_bars = 0
        self._prev_macd = 0.0
        self._prev_signal = 0.0
        self._prev_hist = 0.0

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        price = kline["close"]
        self._prices.append(price)
        if len(self._prices) > 500:
            self._prices = self._prices[-300:]

        # 数据预热 (需要足够数据计算 MACD)
        slow = int(self.params["macd_slow"])
        if len(self._prices) < slow + self.params["macd_signal"] + 5:
            return Signal("hold", 0.0, price, "预热中")

        # 持仓管理
        if self.position.active:
            self._holding_bars += 1
            exit_signal = self._check_exit(price)
            if exit_signal.action != "hold":
                return exit_signal

        # 计算 MACD
        macd_line, signal_line, histogram = self._compute_macd()

        # 计算 RSI
        rsi = self._compute_rsi()

        # 检测交叉
        cross_up = self._prev_hist <= 0 and histogram > 0  # 金叉
        cross_down = self._prev_hist >= 0 and histogram < 0  # 死叉

        self._prev_macd = macd_line
        self._prev_signal = signal_line
        self._prev_hist = histogram

        # 信号逻辑
        action: str = "hold"
        strength = 0.0
        reason = ""

        # 金叉 + RSI 过滤 → 做多
        if cross_up and rsi > self.params["rsi_long_threshold"]:
            # 柱状图强度
            hist_strength = min(abs(histogram) / 10.0, 1.0)
            strength = max(hist_strength, 0.4)
            action = "buy"
            reason = f"MACD金叉+RSI{rsi:.1f}: MACD={macd_line:.2f}, HIST={histogram:.2f}"

        # 死叉 + RSI 过滤 → 做空 (合约) / 平多 (现货)
        elif cross_down and rsi < self.params["rsi_short_threshold"]:
            hist_strength = min(abs(histogram) / 10.0, 1.0)
            strength = max(hist_strength, 0.4)
            if self._market_type == "futures":
                action = "sell"
                reason = f"MACD死叉+RSI{rsi:.1f}: MACD={macd_line:.2f}, HIST={histogram:.2f}"
            else:
                action = "close_long"
                reason = f"MACD死叉离场: RSI={rsi:.1f}"

        # 无持仓时柱状图发散增强信号
        if not self.position.active and abs(histogram) > abs(self.params["histogram_threshold"]):
            strength = min(strength + 0.1, 1.0)

        if action in ("buy", "sell"):
            tp_price = price * (1 + self.params["take_profit_pct"] / 100) if action == "buy" else \
                       price * (1 - self.params["take_profit_pct"] / 100)
            sl_price = price * (1 - self.params["stop_loss_pct"] / 100) if action == "buy" else \
                       price * (1 + self.params["stop_loss_pct"] / 100)

            return Signal(
                action=action,
                strength=strength,
                price=price,
                reason=reason,
                sl_price=sl_price,
                tp_price=tp_price,
            )

        return Signal("hold", 0.0, price,
                      f"MACD={macd_line:.1f}, RSI={rsi:.1f}, HIST={histogram:.1f}")

    def _compute_macd(self) -> tuple[float, float, float]:
        """计算 MACD 指标."""
        fast = int(self.params["macd_fast"])
        slow = int(self.params["macd_slow"])
        signal = int(self.params["macd_signal"])

        prices = np.array(self._prices)

        # EMA 计算
        ema_fast = self._ema(prices, fast)
        ema_slow = self._ema(prices, slow)
        macd_line = ema_fast - ema_slow

        # 信号线 = MACD 的 EMA
        # 用最近 signal 个 MACD 值计算
        macd_values = []
        for i in range(len(prices)):
            ef = self._ema(prices[:i + 1], fast)
            es = self._ema(prices[:i + 1], slow)
            macd_values.append(ef - es)

        if len(macd_values) >= signal:
            signal_line = self._ema(np.array(macd_values), signal)
        else:
            signal_line = macd_line

        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _ema(self, data: np.ndarray, period: int) -> float:
        """计算 EMA 最后一个值."""
        if len(data) < period:
            return float(np.mean(data))
        multiplier = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        for i in range(period, len(data)):
            ema = (data[i] - ema) * multiplier + ema
        return ema

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
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _check_exit(self, price: float) -> Signal:
        """检查出场条件."""
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
        d["macd_rsi"] = {
            "holding_bars": self._holding_bars,
            "prev_macd": round(self._prev_macd, 2),
            "prev_hist": round(self._prev_hist, 2),
        }
        return d
