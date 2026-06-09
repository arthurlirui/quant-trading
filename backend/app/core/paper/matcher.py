"""Paper trading match engine (market orders only for Phase 1)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.paper.account import PaperAccount, PaperPositionRuntime

logger = logging.getLogger(__name__)


@dataclass
class PaperTradeRuntime:
    """Single executed trade (not persisted yet)."""
    symbol: str
    side: str
    action: str
    price: float
    quantity: float
    notional: float
    fee: float
    pnl: float | None = None
    slippage_bps: float = 5.0
    signal_strength: float | None = None
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PaperExecutionResult:
    success: bool
    trade: PaperTradeRuntime | None = None
    position_after: PaperPositionRuntime | None = None
    cash_after: float = 0.0
    realized_pnl_delta: float = 0.0
    error: str | None = None


class PaperMatcher:
    """Matches paper orders against real market prices from connector.

    Phase 1: market orders only with fixed bps slippage.
    """

    def __init__(self, connector: Any):
        self.connector = connector

    async def _get_mark_price(self, symbol: str, fallback: float) -> float:
        try:
            ticker = await self.connector.get_ticker(symbol, market="spot")
            if ticker and "price" in ticker:
                return float(ticker["price"])
        except Exception:
            logger.warning("Failed to fetch ticker for %s, using fallback %.2f", symbol, fallback)
        return fallback

    async def execute_market_order(
        self,
        account: PaperAccount,
        symbol: str,
        side: str,  # buy | sell
        action: str,  # buy|sell|close_long|close_short
        quantity_pct: float | None,
        explicit_quantity: float | None,
        signal_price: float,
        signal_strength: float | None = None,
    ) -> PaperExecutionResult:
        mark_price = await self._get_mark_price(symbol, signal_price)

        # Apply slippage
        slippage_frac = account.slippage_bps / 10000.0
        if side == "buy":
            fill_price = mark_price * (1 + slippage_frac)
        else:
            fill_price = mark_price * (1 - slippage_frac)

        is_close = action in ("close_long", "close_short")

        if is_close:
            return self._close_position(account, symbol, action, fill_price, signal_strength)
        else:
            return await self._open_position(
                account, symbol, side, action, fill_price,
                quantity_pct, explicit_quantity, signal_strength,
            )

    def _close_position(
        self,
        account: PaperAccount,
        symbol: str,
        action: str,
        fill_price: float,
        signal_strength: float | None,
    ) -> PaperExecutionResult:
        pos = account.positions.get(symbol)
        if not pos or pos.quantity == 0:
            return PaperExecutionResult(False, error="no position to close")

        qty = pos.quantity
        close_value = qty * fill_price
        fee = close_value * account.fee_rate

        # PnL calculation
        if pos.side == "long":
            pnl = (fill_price - pos.avg_entry_price) * qty
        else:
            pnl = (pos.avg_entry_price - fill_price) * qty
        pnl_net = pnl - fee

        # Update account
        account.cash += close_value - fee
        account.realized_pnl += pnl_net
        account.closed_trades_count += 1
        if pnl_net > 0:
            account.win_count += 1

        # Close position side (if qty fully closed)
        # For phase 1: we always close full position
        del account.positions[symbol]

        trade = PaperTradeRuntime(
            symbol=symbol,
            side="sell" if pos.side == "long" else "buy",
            action=action,
            price=fill_price,
            quantity=qty,
            notional=close_value,
            fee=fee,
            pnl=round(pnl_net, 4),
            slippage_bps=account.slippage_bps,
            signal_strength=signal_strength,
        )

        return PaperExecutionResult(
            success=True,
            trade=trade,
            position_after=None,
            cash_after=account.cash,
            realized_pnl_delta=pnl_net,
        )

    async def _open_position(
        self,
        account: PaperAccount,
        symbol: str,
        side: str,
        action: str,
        fill_price: float,
        quantity_pct: float | None,
        explicit_quantity: float | None,
        signal_strength: float | None,
    ) -> PaperExecutionResult:
        # Calculate notional
        total_cash = account.cash
        if explicit_quantity is not None and explicit_quantity > 0:
            notional = explicit_quantity * fill_price
        elif quantity_pct is not None:
            notional = total_cash * min(quantity_pct, 0.99)
        else:
            notional = total_cash * 0.5  # default 50%

        if not account.can_afford(notional):
            return PaperExecutionResult(False, error="insufficient funds")
        if notional <= 0 or fill_price <= 0:
            return PaperExecutionResult(False, error="invalid order size")

        qty = notional / fill_price
        fee = round(notional * account.fee_rate, 4)
        total_cost = round(notional + fee, 4)

        # Deduct cash
        account.cash -= total_cost

        # Update or create position
        pos = account.positions.get(symbol)
        if pos and pos.side == "long" and side == "buy":
            # Increase (FIFO avg)
            total_qty = pos.quantity + qty
            total_cost_basis = pos.avg_entry_price * pos.quantity + fill_price * qty
            pos.quantity = total_qty
            pos.avg_entry_price = total_cost_basis / total_qty
            pos.updated_at = datetime.now(timezone.utc)
        else:
            account.positions[symbol] = PaperPositionRuntime(
                symbol=symbol,
                side="long",
                quantity=qty,
                avg_entry_price=fill_price,
                opened_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

        trade = PaperTradeRuntime(
            symbol=symbol,
            side=side,
            action=action,
            price=fill_price,
            quantity=qty,
            notional=notional,
            fee=fee,
            pnl=None,
            slippage_bps=account.slippage_bps,
            signal_strength=signal_strength,
        )

        return PaperExecutionResult(
            success=True,
            trade=trade,
            position_after=account.positions.get(symbol),
            cash_after=account.cash,
        )
