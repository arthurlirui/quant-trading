"""Paper trade execution record."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_account_id: Mapped[str] = mapped_column(String(36), ForeignKey("paper_accounts.id"), index=True)
    strategy_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(8))                # buy | sell
    action: Mapped[str] = mapped_column(String(20))             # buy|sell|close_long|close_short
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)              # price * quantity
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[float] = mapped_column(Float, default=0.0)
    signal_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True,
    )

    __table_args__ = (
        Index("ix_paper_trades_account_executed", "paper_account_id", "executed_at"),
    )
