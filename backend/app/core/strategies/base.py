"""
📐 策略基类 — 所有策略的抽象接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


MarketType = Literal["spot", "futures"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
TimeFrame = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


@dataclass
class Signal:
    """交易信号."""
    action: Literal["buy", "sell", "close_long", "close_short", "hold"]
    strength: float          # 0.0 ~ 1.0
    price: float
    reason: str = ""
    order_type: OrderType = "market"
    sl_price: float | None = None   # 止损价
    tp_price: float | None = None   # 止盈价
    quantity_pct: float = 1.0       # 仓位比例 0.0~1.0


@dataclass
class PositionInfo:
    """策略内部持仓状态."""
    active: bool = False
    side: str = ""           # long | short
    entry_price: float = 0.0
    entry_time: int = 0
    quantity: float = 0.0
    trades: int = 0
    win_trades: int = 0

    @property
    def win_rate(self) -> float:
        if self.trades == 0:
            return 0.0
        return self.win_trades / self.trades * 100


class BaseStrategy(ABC):
    """所有策略的抽象基类."""

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        self.strategy_id = strategy_id
        self.params: dict[str, Any] = self.default_params
        if params:
            self.params.update(params)
        self.position = PositionInfo()
        self._signal_log: list[dict] = []
        self._market_type: MarketType = "spot"

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称."""
        ...

    @property
    @abstractmethod
    def default_params(self) -> dict[str, Any]:
        """默认参数."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述."""
        ...

    @property
    @abstractmethod
    def supported_markets(self) -> list[MarketType]:
        """支持的市场类型."""
        ...

    @abstractmethod
    def on_kline(self, kline: dict[str, Any]) -> Signal:
        """处理新 K 线，返回交易信号."""
        ...

    def set_market_type(self, market_type: MarketType):
        """设置交易市场类型."""
        self._market_type = market_type

    def reset(self):
        """重置策略状态."""
        self.position = PositionInfo()
        self._signal_log.clear()

    def update_params(self, params: dict[str, Any]):
        """动态更新参数."""
        for k, v in params.items():
            if k in self.default_params:
                self.params[k] = v

    def log_signal(self, signal: Signal, kline: dict):
        """记录信号."""
        self._signal_log.append({
            "time": kline.get("open_time", 0),
            "price": kline.get("close", signal.price),
            "volume": kline.get("volume", 0),
            "action": signal.action,
            "strength": signal.strength,
            "reason": signal.reason,
            "sl_price": signal.sl_price,
            "tp_price": signal.tp_price,
        })
        if len(self._signal_log) > 1000:
            self._signal_log = self._signal_log[-500:]

    def update_position(self, action: str, price: float, time: int, qty: float, pnl: float = 0.0):
        """更新持仓状态."""
        if action in ("buy", "sell"):
            side_map = {"buy": "long", "sell": "short"}
            self.position.active = True
            self.position.side = side_map.get(action, action)
            self.position.entry_price = price
            self.position.entry_time = time
            self.position.quantity = qty
            self.position.trades += 1
        elif action in ("close_long", "close_short", "close_buy", "close_sell"):
            if pnl > 0:
                self.position.win_trades += 1
            self.position.active = False
            self.position.quantity = 0.0

    @property
    def signal_log(self) -> list[dict]:
        return self._signal_log[-100:]

    @property
    def signal_count(self) -> int:
        return len(self._signal_log)

    def to_dict(self) -> dict:
        """序列化策略状态."""
        return {
            "id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "market_type": self._market_type,
            "supported_markets": self.supported_markets,
            "params": self.params,
            "position": {
                "active": self.position.active,
                "side": self.position.side,
                "entry_price": self.position.entry_price,
                "quantity": self.position.quantity,
                "trades": self.position.trades,
                "win_trades": self.position.win_trades,
                "win_rate": round(self.position.win_rate, 1),
            },
            "signal_count": self.signal_count,
        }
