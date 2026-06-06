"""
🔤 交易类型定义 — Trading Types
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from datetime import datetime, timezone

MarketType = Literal["spot", "futures"]
OrderSide = Literal["buy", "sell"]
OrderStatus = Literal["pending", "open", "filled", "partially_filled", "cancelled", "rejected", "expired"]
OrderType = Literal["market", "limit", "stop_market", "stop_limit", "take_profit"]


@dataclass
class Order:
    """订单数据结构."""
    id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: OrderSide = "buy"
    order_type: OrderType = "market"
    market_type: MarketType = "spot"
    price: float = 0.0
    quantity: float = 0.0
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    status: OrderStatus = "pending"
    stop_price: float | None = None
    sl_price: float | None = None    # 止损价
    tp_price: float | None = None    # 止盈价
    leverage: int = 1
    reduce_only: bool = False
    error: str = ""
    created_at: int = 0
    updated_at: int = 0
    exchange_order_id: str = ""

    @property
    def is_open(self) -> bool:
        return self.status in ("pending", "open", "partially_filled")

    @property
    def is_closed(self) -> bool:
        return self.status in ("filled", "cancelled", "rejected", "expired")


@dataclass
class Position:
    """持仓数据结构."""
    symbol: str = ""
    side: Literal["long", "short"] = "long"
    market_type: MarketType = "spot"
    quantity: float = 0.0
    entry_price: float = 0.0
    mark_price: float = 0.0
    liquidation_price: float = 0.0
    leverage: int = 1
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    margin: float = 0.0
    created_at: int = 0
    updated_at: int = 0


@dataclass
class AccountInfo:
    """账户信息."""
    total_equity: float = 0.0
    wallet_balance: float = 0.0
    unrealized_pnl: float = 0.0
    margin_ratio: float = 0.0
    available_balance: float = 0.0
    positions: list[Position] = field(default_factory=list)
    can_trade: bool = False
    market_type: MarketType = "spot"


@dataclass
class ExecutionResult:
    """执行结果."""
    success: bool = False
    order: Order | None = None
    error: str = ""
    exchange_response: dict[str, Any] = field(default_factory=dict)

    def __bool__(self):
        return self.success
