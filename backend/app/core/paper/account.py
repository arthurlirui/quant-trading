"""Paper trading runtime account & position objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PaperPositionRuntime:
    """In-memory position for one symbol."""
    symbol: str
    side: str  # long | short
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0
    opened_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        if self.opened_at is None:
            self.opened_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = self.opened_at

    def unrealized_pnl(self, mark_price: float) -> float:
        if self.quantity == 0:
            return 0.0
        if self.side == "long":
            return (mark_price - self.avg_entry_price) * self.quantity
        return (self.avg_entry_price - mark_price) * self.quantity

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "avg_entry_price": self.avg_entry_price,
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": 0.0,  # filled by caller with mark prices
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
        }


@dataclass
class PaperAccount:
    """In-memory paper trading account (distinct from ORM model)."""
    id: str
    name: str
    cash: float
    initial_capital: float
    fee_rate: float
    slippage_bps: float
    status: str = "active"
    positions: dict[str, PaperPositionRuntime] = field(default_factory=dict)  # symbol -> pos
    realized_pnl: float = 0.0
    closed_trades_count: int = 0
    win_count: int = 0

    def equity(self, mark_prices: dict[str, float]) -> float:
        pos_val = sum(
            p.quantity * mark_prices.get(p.symbol, p.avg_entry_price)
            for p in self.positions.values()
        )
        if not self.positions:
            return self.cash
        # cost basis = sum(qty * entry) for all open positions
        cost_basis = sum(p.quantity * p.avg_entry_price for p in self.positions.values())
        return self.cash + (pos_val - cost_basis) + self.realized_pnl

    def positions_value(self, mark_prices: dict[str, float]) -> float:
        return sum(
            p.quantity * mark_prices.get(p.symbol, p.avg_entry_price)
            for p in self.positions.values()
        )

    def can_afford(self, notional: float) -> bool:
        return self.cash >= notional * 1.001  # slight buffer for fee

    @property
    def win_rate(self) -> float:
        if self.closed_trades_count == 0:
            return 0.0
        return self.win_count / self.closed_trades_count

    def to_dict(self, mark_prices: dict[str, float] | None = None) -> dict[str, Any]:
        mp = mark_prices or {}
        upnl = sum(p.unrealized_pnl(mp.get(p.symbol, p.avg_entry_price))
                    for p in self.positions.values())
        return {
            "id": self.id,
            "name": self.name,
            "cash": round(self.cash, 4),
            "initial_capital": self.initial_capital,
            "equity": round(self.equity(mp), 4),
            "fee_rate": self.fee_rate,
            "slippage_bps": self.slippage_bps,
            "status": self.status,
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(upnl, 4),
            "open_positions": len(self.positions),
            "closed_trades": self.closed_trades_count,
            "win_rate": round(self.win_rate, 4),
            "positions": {s: p.to_dict() for s, p in self.positions.items()},
        }
