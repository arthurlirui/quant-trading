"""Pydantic Settings."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "production"] = "development"
    secret_key: str = "change-me"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./quant_trading.db"
    cors_origins: list[str] = ["*"]

    # Binance
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = True       # Use testnet by default for safety

    # Trading
    default_symbol: str = "BTCUSDT"
    default_timeframe: str = "1m"
    max_position_size: float = 1.0
    max_leverage: int = 1

    # Reconnect
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 60.0
    reconnect_backoff: float = 2.0
    health_check_interval: int = 30

    # Backtest
    backtest_initial_capital: float = 10000.0
    backtest_commission: float = 0.001

    # Strategy defaults
    default_lookback: int = 20
    default_entry_threshold: float = 2.0
    default_exit_threshold: float = 0.5
    default_stop_loss_pct: float = 2.0
    default_take_profit_pct: float = 5.0

    # Paper trading
    paper_default_capital: float = 10000.0
    paper_default_fee_rate: float = 0.001
    paper_default_slippage_bps: float = 5.0
    paper_equity_snapshot_interval: int = 60


settings = Settings()
