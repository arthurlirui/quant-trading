"""
🛡️ 风险管理器 — Risk Manager

功能:
  - 仓位规模计算 (固定比例/Kelly公式)
  - 最大回撤控制
  - 每日亏损限制
  - 最大持仓数量限制
  - 杠杆管理
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .types import MarketType, Position

logger = logging.getLogger(__name__)

# 24小时窗口 (毫秒)
DAY_MS = 86400_000


class RiskManager:
    """
    风险管理器 — 风控逻辑中心。

    支持全局风控和策略级风控:
    - 全局: 总仓位限制, 日亏损限制, 最大回撤
    - 策略级: 单策略仓位, 杠杆, 止损限制
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}

        # 全局风控
        self.max_position_value = float(cfg.get("max_position_value", 5000))     # 最大持仓总价值
        self.max_daily_loss = float(cfg.get("max_daily_loss", 500))               # 日最大亏损
        self.max_drawdown_pct = float(cfg.get("max_drawdown_pct", 15.0))          # 最大回撤 %
        self.max_positions = int(cfg.get("max_positions", 5))                     # 最大持仓数
        self.max_leverage = int(cfg.get("max_leverage", 5))                      # 最大杠杆

        # 策略级
        self.max_position_per_strategy = float(cfg.get("max_position_per_strategy", 0.3))  # 单策略占用比例
        self.default_stop_loss_pct = float(cfg.get("default_stop_loss_pct", 2.0))

        # 运行时状态
        self._daily_pnl: list[tuple[int, float]] = []      # (timestamp_ms, pnl)
        self._peak_equity: float = 10000.0
        self._current_equity: float = 10000.0
        self._initial_equity: float = 10000.0

    def update_equity(self, equity: float):
        """更新当前权益."""
        self._current_equity = equity
        self._peak_equity = max(self._peak_equity, equity)

    def record_trade_pnl(self, pnl: float):
        """记录交易盈亏."""
        now = int(time.time() * 1000)
        self._daily_pnl.append((now, pnl))
        # 清理 24h 之前的数据
        cutoff = now - DAY_MS
        self._daily_pnl = [(t, p) for t, p in self._daily_pnl if t > cutoff]

    # ── 检查方法 ────────────────────────────────────────────────

    def can_open_position(self, position_value: float, positions_count: int,
                          market_type: MarketType = "spot") -> tuple[bool, str]:
        """检查是否可以开新仓."""
        # 持仓数量限制
        if positions_count >= self.max_positions:
            return False, f"达到最大持仓数限制 ({self.max_positions})"

        # 仓位价值限制
        if position_value > self.max_position_value:
            return False, f"仓位价值 ${position_value:.0f} 超过限制 ${self.max_position_value:.0f}"

        # 回撤检查
        if self._peak_equity > 0:
            dd_pct = (self._peak_equity - self._current_equity) / self._peak_equity * 100
            if dd_pct >= self.max_drawdown_pct:
                return False, f"回撤 {dd_pct:.1f}% 超过限制 {self.max_drawdown_pct}%"

        # 日亏损检查
        daily_loss = sum(p for _, p in self._daily_pnl if p < 0)
        if abs(daily_loss) >= self.max_daily_loss:
            return False, f"日亏损 ${abs(daily_loss):.0f} 超过限制 ${self.max_daily_loss:.0f}"

        return True, "ok"

    def can_increase_position(self, current_qty: float, add_qty: float,
                              price: float) -> tuple[bool, str]:
        """检查是否可以加仓."""
        new_value = (current_qty + add_qty) * price
        if new_value > self.max_position_value:
            return False, f"加仓后价值 ${new_value:.0f} 超过限制"
        return True, "ok"

    def get_position_size(self, capital: float, price: float,
                          risk_pct: float = 0.02,
                          stop_loss_pct: float = 2.0,
                          market_type: MarketType = "spot",
                          leverage: int = 1) -> float:
        """
        计算仓位规模 (固定比例风险模型).

        Kelly 风格: position_size = capital * risk_pct / stop_loss_pct
        """
        # 基础仓位 = 资金 * 风险比例 / 止损百分比
        base_qty = (capital * risk_pct) / (stop_loss_pct / 100) / price

        # 杠杆调整 (合约)
        if market_type == "futures" and leverage > 1:
            base_qty = base_qty * leverage

        # 不超过最大仓位
        max_qty = self.max_position_value / price
        return min(base_qty, max_qty)

    def get_allowed_leverage(self, market_type: MarketType,
                             requested: int = 1) -> int:
        """获取允许的杠杆倍数."""
        if market_type == "spot":
            return 1
        return min(requested, self.max_leverage)

    def check_stop_loss(self, entry_price: float, current_price: float,
                        side: str, stop_loss_pct: float | None = None) -> bool:
        """检查是否触发止损."""
        sl_pct = stop_loss_pct or self.default_stop_loss_pct
        if side == "long":
            return (entry_price - current_price) / entry_price * 100 >= sl_pct
        else:
            return (current_price - entry_price) / entry_price * 100 >= sl_pct

    def get_risk_summary(self) -> dict:
        """获取风控摘要."""
        daily_pnl = sum(p for _, p in self._daily_pnl)
        daily_loss = sum(p for _, p in self._daily_pnl if p < 0)
        dd_pct = ((self._peak_equity - self._current_equity) / max(self._peak_equity, 1)) * 100

        return {
            "equity": {
                "current": round(self._current_equity, 2),
                "peak": round(self._peak_equity, 2),
                "initial": round(self._initial_equity, 2),
                "drawdown_pct": round(dd_pct, 2),
            },
            "daily": {
                "pnl": round(daily_pnl, 2),
                "loss": round(daily_loss, 2),
                "trades": len(self._daily_pnl),
            },
            "limits": {
                "max_positions": self.max_positions,
                "max_position_value": self.max_position_value,
                "max_daily_loss": self.max_daily_loss,
                "max_drawdown_pct": self.max_drawdown_pct,
                "max_leverage": self.max_leverage,
            },
            "can_trade": self._check_can_trade(),
        }

    def _check_can_trade(self) -> bool:
        """综合检查是否可以继续交易."""
        if self._peak_equity <= 0:
            return False
        dd_pct = (self._peak_equity - self._current_equity) / self._peak_equity * 100
        if dd_pct >= self.max_drawdown_pct:
            return False
        daily_loss = sum(p for _, p in self._daily_pnl if p < 0)
        if abs(daily_loss) >= self.max_daily_loss:
            return False
        return True

    def to_dict(self) -> dict:
        return self.get_risk_summary()


# 全局实例
risk_manager = RiskManager()
