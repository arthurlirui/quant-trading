"""Paper trading account ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    current_cash: Mapped[float] = mapped_column(Float, nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(10), default="USDT")
    fee_rate: Mapped[float] = mapped_column(Float, default=0.001)
    slippage_bps: Mapped[float] = mapped_column(Float, default=5.0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|stopped|liquidated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
