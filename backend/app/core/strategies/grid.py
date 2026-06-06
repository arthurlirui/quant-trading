"""
🧩 网格交易策略 — Grid Trading
适用于: 现货 + 合约
原理: 在价格区间内分层挂单，低买高卖，震荡市专用
"""
from __future__ import annotations

import math
from typing import Any

from .base import BaseStrategy, Signal, MarketType


class GridTradingStrategy(BaseStrategy):
    """网格交易策略."""

    @property
    def name(self) -> str:
        return "网格交易"

    @property
    def description(self) -> str:
        return "在价格区间内分层挂单，捕捉震荡行情波动"

    @property
    def supported_markets(self) -> list[MarketType]:
        return ["spot", "futures"]

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "grid_lower": 0.0,          # 网格下界 (0=自动)
            "grid_upper": 0.0,          # 网格上界 (0=自动)
            "grid_levels": 10,           # 网格层数
            "grid_spread_pct": 0.5,      # 网格间距百分比 (%)
            "position_per_grid": 0.1,    # 每格仓位比例
            "take_profit_pct": 0.8,      # 每格止盈百分比
            "stop_loss_pct": 2.0,        # 全局止损
            "auto_range": True,          # 自动计算网格范围
            "lookback_bars": 100,        # 自动范围参考K线数
        }

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        self._prices: list[float] = []
        self._grid_orders: list[dict] = []  # 当前网格挂单
        self._grid_positions: list[dict] = []  # 已成交网格仓位
        self._base_price: float = 0.0
        self._grid_built: bool = False

    def reset(self):
        super().reset()
        self._prices.clear()
        self._grid_orders.clear()
        self._grid_positions.clear()
        self._grid_built = False

    def _build_grid(self, current_price: float):
        """构建网格."""
        gl = self.params["grid_lower"]
        gu = self.params["grid_upper"]
        levels = int(self.params["grid_levels"])
        spread = self.params["grid_spread_pct"] / 100

        if self.params["auto_range"] or (gl == 0 and gu == 0):
            # 基于当前价 ± 范围
            half_range = spread * levels / 2
            gl = current_price * (1 - half_range)
            gu = current_price * (1 + half_range)

        step = (gu - gl) / levels
        self._grid_orders = []
        for i in range(levels):
            price = gl + step * i
            self._grid_orders.append({
                "level": i,
                "buy_price": round(price, 2),
                "sell_price": round(price * (1 + self.params["take_profit_pct"] / 100), 2),
                "filled": False,
                "bought_price": 0.0,
            })
        self._base_price = current_price
        self._grid_built = True

    def on_kline(self, kline: dict[str, Any]) -> Signal:
        price = kline["close"]
        self._prices.append(price)
        if len(self._prices) > 500:
            self._prices = self._prices[-300:]

        # 数据预热
        if len(self._prices) < int(self.params["lookback_bars"]):
            return Signal("hold", 0.0, price, "预热中")

        # 首次构建网格
        if not self._grid_built:
            self._build_grid(price)
            return Signal("hold", 0.0, price,
                          f"网格已构建: {self.params['grid_levels']}层, 间距{self.params['grid_spread_pct']}%")

        # 检查每个网格层
        for order in self._grid_orders:
            if not order["filled"]:
                # 价格跌到买入价 → 买入
                if price <= order["buy_price"]:
                    order["filled"] = True
                    order["bought_price"] = price
                    self._grid_positions.append(order)

                    qty_pct = self.params["position_per_grid"]
                    tp_price = order["sell_price"]
                    return Signal("buy", 0.7, price,
                                  f"网格买入 Lv{order['level']}: ${price:.2f}",
                                  order_type="limit",
                                  tp_price=tp_price,
                                  quantity_pct=qty_pct)
            else:
                # 已买入 → 检查止盈
                if price >= order["sell_price"]:
                    order["filled"] = False
                    qty_pct = self.params["position_per_grid"]
                    return Signal("sell", 0.7, price,
                                  f"网格卖出 Lv{order['level']}: ${price:.2f} (+{self.params['take_profit_pct']}%)",
                                  order_type="limit",
                                  quantity_pct=qty_pct)

        # 全局止损检查
        if self.position.active:
            pnl_pct = (price - self.position.entry_price) / self.position.entry_price * 100
            if self.position.side == "long" and pnl_pct <= -self.params["stop_loss_pct"]:
                return Signal("close_long", 1.0, price,
                              f"网格止损: {pnl_pct:.2f}%")
            elif self.position.side == "short" and pnl_pct >= self.params["stop_loss_pct"]:
                return Signal("close_short", 1.0, price,
                              f"网格止损: {pnl_pct:.2f}%")

        return Signal("hold", 0.0, price, "等待网格触发")

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["grid"] = {
            "levels": len(self._grid_orders),
            "filled": sum(1 for o in self._grid_orders if o["filled"]),
            "base_price": self._base_price,
            "built": self._grid_built,
        }
        return d
