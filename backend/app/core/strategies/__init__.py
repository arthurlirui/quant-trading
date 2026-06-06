"""
🧩 策略注册表 — 所有策略的注册和工厂
"""
from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, PositionInfo, MarketType
from .grid import GridTradingStrategy
from .momentum import MomentumBreakoutStrategy
from .mean_reversion import MeanReversionStrategy
from .macd_rsi import MACDComboStrategy
from .volume_surge import VolumeSurgeStrategy

# 策略注册表: name -> class
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "volume_surge": VolumeSurgeStrategy,
    "grid": GridTradingStrategy,
    "momentum": MomentumBreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
    "macd_rsi": MACDComboStrategy,
}

# 策略元数据索引
STRATEGY_META: dict[str, dict[str, Any]] = {
    name: {
        "id": name,
        "name": cls(None if hasattr(cls, 'strategy_id') else "dummy").name,
        "description": cls(None if hasattr(cls, 'strategy_id') else "dummy").description,
        "supported_markets": cls(None if hasattr(cls, 'strategy_id') else "dummy").supported_markets,
        "default_params": cls(None if hasattr(cls, 'strategy_id') else "dummy").default_params,
    }
    for name, cls in STRATEGY_REGISTRY.items()
}


def create_strategy(strategy_type: str, strategy_id: str,
                    params: dict[str, Any] | None = None,
                    market_type: MarketType = "spot") -> BaseStrategy | None:
    """创建策略实例."""
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if not cls:
        return None
    instance = cls(strategy_id, params)
    instance.set_market_type(market_type)
    return instance


def get_strategy_meta() -> dict[str, dict[str, Any]]:
    """获取所有策略的元数据."""
    return STRATEGY_META


__all__ = [
    "BaseStrategy", "Signal", "PositionInfo", "MarketType",
    "STRATEGY_REGISTRY", "STRATEGY_META",
    "create_strategy", "get_strategy_meta",
    "VolumeSurgeStrategy", "GridTradingStrategy",
    "MomentumBreakoutStrategy", "MeanReversionStrategy",
    "MACDComboStrategy",
]
