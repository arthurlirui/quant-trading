"""Strategy ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), default="BTCUSDT")
    timeframe: Mapped[str] = mapped_column(String(5), default="1m")
    params: Mapped[str] = mapped_column(Text, default="{}", comment="JSON config")
    status: Mapped[str] = mapped_column(String(20), default="stopped")
    strategy_type: Mapped[str] = mapped_column(String(50), default="volume_surge")
    mode: Mapped[str] = mapped_column(String(10), default="live")        # live | paper
    paper_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
    )
