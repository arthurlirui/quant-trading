"""Kline (candlestick) ORM model."""
from __future__ import annotations

from sqlalchemy import BigInteger, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Kline(Base):
    __tablename__ = "klines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(5), nullable=False)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    close_time: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("idx_kline_symbol_interval_time", "symbol", "interval", "open_time", unique=True),
    )
