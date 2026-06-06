"""
⚡ 交易执行器 — Spot + Futures Order Execution

封装 Binance 的现货和合约下单接口。
支持: 市价单、限价单、止损单、止盈单、双向持仓管理。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

import httpx

from app.config import settings
from .types import (
    Order, OrderSide, OrderType, OrderStatus, MarketType,
    Position, AccountInfo, ExecutionResult,
)

logger = logging.getLogger(__name__)


class TradeExecutor:
    """
    交易执行器 — 统一现货/合约下单接口。

    测试网模式: 所有订单为模拟 (simulate=True)。
    实盘模式: 直接发往 Binance REST API。
    """

    def __init__(self):
        self._session: httpx.AsyncClient | None = None
        self._orders: dict[str, Order] = {}          # order_id -> Order
        self._positions: dict[str, Position] = {}     # symbol -> Position
        self._simulate = settings.binance_testnet
        self._api_key = settings.binance_api_key
        self._secret_key = settings.binance_secret_key

        # REST endpoints
        if settings.binance_testnet:
            self._spot_base = "https://testnet.binance.vision"
            self._futures_base = "https://testnet.binancefuture.com"
        else:
            self._spot_base = "https://api.binance.com"
            self._futures_base = "https://fapi.binance.com"

    async def start(self):
        """初始化 HTTP 会话."""
        if not self._session:
            self._session = httpx.AsyncClient(timeout=30)

    async def stop(self):
        """关闭 HTTP 会话."""
        if self._session:
            await self._session.aclose()
            self._session = None

    # ── 下单核心 ────────────────────────────────────────────────

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: float = 0.0,
        market_type: MarketType = "spot",
        stop_price: float | None = None,
        reduce_only: bool = False,
        leverage: int = 1,
        strategy_id: str = "",
    ) -> ExecutionResult:
        """创建订单."""
        order_id = str(uuid.uuid4())
        created_at = int(time.time() * 1000)

        order = Order(
            id=order_id,
            strategy_id=strategy_id,
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            market_type=market_type,
            price=price,
            quantity=quantity,
            stop_price=stop_price,
            reduce_only=reduce_only,
            leverage=leverage,
            status="pending",
            created_at=created_at,
            updated_at=created_at,
        )

        if self._simulate:
            return await self._simulate_order(order)
        else:
            return await self._place_real_order(order)

    async def _simulate_order(self, order: Order) -> ExecutionResult:
        """模拟下单 (测试网/回测)."""
        await asyncio.sleep(0.05)  # 模拟网络延迟

        # 模拟成交
        fill_price = order.price if order.order_type == "limit" and order.price > 0 else \
                     await self._simulate_market_price(order.symbol)

        order.status = "filled"
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        order.updated_at = int(time.time() * 1000)
        order.exchange_order_id = f"sim_{order.id[:8]}"

        # 更新持仓
        self._update_position(order)

        self._orders[order.id] = order
        logger.info("[Sim] Order filled: %s %s %s @ %.2f (qty=%.4f)",
                     order.symbol, order.side, order.order_type, fill_price, order.quantity)

        return ExecutionResult(
            success=True,
            order=order,
            exchange_response={"simulated": True, "fill_price": fill_price},
        )

    async def _place_real_order(self, order: Order) -> ExecutionResult:
        """真实下单 (Binance API)."""
        if not self._session or not self._api_key:
            return ExecutionResult(success=False, error="API key not configured", order=order)

        try:
            base = self._futures_base if order.market_type == "futures" else self._spot_base
            endpoint = "/fapi/v1/order" if order.market_type == "futures" else "/api/v3/order"

            params: dict[str, Any] = {
                "symbol": order.symbol,
                "side": order.side.upper(),
                "type": order.order_type.upper(),
                "quantity": order.quantity,
                "timestamp": int(time.time() * 1000),
            }

            if order.order_type == "limit":
                params["price"] = order.price
                params["timeInForce"] = "GTC"
            if order.stop_price:
                params["stopPrice"] = order.stop_price
            if order.reduce_only:
                params["reduceOnly"] = "true"

            # Sign
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            signature = hmac.new(
                self._secret_key.encode(),
                query.encode(),
                hashlib.sha256,
            ).hexdigest()
            params["signature"] = signature

            resp = await self._session.post(
                f"{base}{endpoint}",
                params=params,
                headers={"X-MBX-APIKEY": self._api_key},
            )
            data = resp.json()

            if resp.status_code != 200:
                return ExecutionResult(
                    success=False,
                    error=f"Binance error: {data.get('msg', 'unknown')}",
                    order=order,
                    exchange_response=data,
                )

            # Update order with exchange response
            order.status = data.get("status", "open").lower()
            order.exchange_order_id = data.get("orderId", "")
            order.filled_quantity = float(data.get("executedQty", 0))
            order.avg_fill_price = float(data.get("avgPrice", 0)) or float(data.get("price", 0))
            order.updated_at = int(time.time() * 1000)
            self._orders[order.id] = order

            if order.filled_quantity > 0:
                self._update_position(order)

            return ExecutionResult(success=True, order=order, exchange_response=data)

        except Exception as e:
            logger.error("[Binance] Order error: %s", e)
            return ExecutionResult(success=False, error=str(e), order=order)

    # ── 订单管理 ────────────────────────────────────────────────

    async def cancel_order(self, order_id: str) -> ExecutionResult:
        """撤销订单."""
        order = self._orders.get(order_id)
        if not order:
            return ExecutionResult(success=False, error="Order not found")

        if self._simulate:
            order.status = "cancelled"
            order.updated_at = int(time.time() * 1000)
            return ExecutionResult(success=True, order=order)

        # Real cancel
        try:
            base = self._futures_base if order.market_type == "futures" else self._spot_base
            endpoint = "/fapi/v1/order" if order.market_type == "futures" else "/api/v3/order"
            params = {
                "symbol": order.symbol,
                "orderId": order.exchange_order_id,
                "timestamp": int(time.time() * 1000),
            }
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            signature = hmac.new(self._secret_key.encode(), query.encode(), hashlib.sha256).hexdigest()
            params["signature"] = signature

            resp = await self._session.delete(
                f"{base}{endpoint}", params=params,
                headers={"X-MBX-APIKEY": self._api_key},
            )
            if resp.status_code == 200:
                order.status = "cancelled"
                return ExecutionResult(success=True, order=order)
            else:
                return ExecutionResult(success=False, error=resp.text, order=order)
        except Exception as e:
            return ExecutionResult(success=False, error=str(e), order=order)

    def get_order(self, order_id: str) -> Order | None:
        """获取订单."""
        return self._orders.get(order_id)

    def get_orders(self, strategy_id: str | None = None) -> list[Order]:
        """获取订单列表."""
        if strategy_id:
            return [o for o in self._orders.values() if o.strategy_id == strategy_id]
        return list(self._orders.values())

    # ── 持仓管理 ────────────────────────────────────────────────

    def _update_position(self, order: Order):
        """根据成交订单更新持仓."""
        sym = order.symbol

        pos = self._positions.get(sym)
        if not pos:
            pos = Position(
                symbol=sym,
                market_type=order.market_type,
                leverage=order.leverage,
                created_at=order.created_at,
            )
            self._positions[sym] = pos

        is_buy = order.side == "buy"
        fill_qty = order.quantity if not order.reduce_only else -order.quantity

        # 简单模式: 直接更新
        if fill_qty > 0:
            pos.side = "long"
            # 加权平均入场价
            old_value = pos.entry_price * pos.quantity
            new_value = order.avg_fill_price * fill_qty
            total_qty = pos.quantity + fill_qty
            pos.entry_price = (old_value + new_value) / total_qty if total_qty > 0 else order.avg_fill_price
            pos.quantity = total_qty
        elif fill_qty < 0:
            # 平仓/减仓
            reduce_qty = abs(fill_qty)
            if reduce_qty >= pos.quantity:
                # 全部平仓
                pnl = (order.avg_fill_price - pos.entry_price) * pos.quantity * \
                      (-1 if pos.side == "short" else 1)
                pos.realized_pnl += pnl
                pos.quantity = 0
                pos.entry_price = 0
            else:
                # 部分平仓
                pnl = (order.avg_fill_price - pos.entry_price) * reduce_qty * \
                      (-1 if pos.side == "short" else 1)
                pos.realized_pnl += pnl
                pos.quantity -= reduce_qty

        pos.updated_at = int(time.time() * 1000)

    def get_position(self, symbol: str) -> Position | None:
        """获取持仓."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[Position]:
        """获取所有持仓."""
        return [p for p in self._positions.values() if p.quantity > 0]

    # ── 账户 ────────────────────────────────────────────────────

    async def get_account(self, market_type: MarketType = "spot") -> AccountInfo:
        """获取账户信息."""
        if self._simulate or not self._api_key:
            # 模拟账户
            positions = self.get_all_positions()
            total_value = 10000.0  # 模拟余额
            return AccountInfo(
                total_equity=total_value,
                wallet_balance=total_value,
                available_balance=total_value,
                can_trade=True,
                positions=positions,
                market_type=market_type,
            )

        try:
            base = self._futures_base if market_type == "futures" else self._spot_base
            endpoint = "/fapi/v2/account" if market_type == "futures" else "/api/v3/account"
            params = {"timestamp": int(time.time() * 1000)}
            query = f"timestamp={params['timestamp']}"
            signature = hmac.new(
                self._secret_key.encode(), query.encode(), hashlib.sha256,
            ).hexdigest()
            params["signature"] = signature

            resp = await self._session.get(
                f"{base}{endpoint}", params=params,
                headers={"X-MBX-APIKEY": self._api_key},
            )
            data = resp.json()

            if market_type == "futures":
                positions = [
                    Position(
                        symbol=p["symbol"],
                        side="long" if float(p["positionAmt"]) > 0 else "short",
                        quantity=abs(float(p["positionAmt"])),
                        entry_price=float(p.get("entryPrice", 0)),
                        mark_price=float(p.get("markPrice", 0)),
                        liquidation_price=float(p.get("liquidationPrice", 0)),
                        leverage=int(p.get("leverage", 1)),
                        unrealized_pnl=float(p.get("unRealizedProfit", 0)),
                    )
                    for p in data.get("positions", [])
                    if abs(float(p["positionAmt"])) > 0
                ]
                return AccountInfo(
                    total_equity=float(data.get("totalWalletBalance", 0)),
                    wallet_balance=float(data.get("totalWalletBalance", 0)),
                    unrealized_pnl=float(data.get("totalUnrealizedProfit", 0)),
                    available_balance=float(data.get("availableBalance", 0)),
                    positions=positions,
                    can_trade=True,
                    market_type="futures",
                )
            else:
                balances = [
                    {"asset": b["asset"], "free": float(b["free"]), "locked": float(b["locked"])}
                    for b in data.get("balances", [])
                    if float(b["free"]) > 0 or float(b["locked"]) > 0
                ]
                return AccountInfo(
                    total_equity=0,
                    can_trade=data.get("canTrade", False),
                    market_type="spot",
                )

        except Exception as e:
            logger.error("[Binance] Account error: %s", e)
            return AccountInfo(error=str(e))

    # ── 模拟价格 ────────────────────────────────────────────────

    async def _simulate_market_price(self, symbol: str) -> float:
        """模拟获取市场价 (供模拟成交使用)."""
        try:
            if self._session:
                base = "https://testnet.binance.vision" if self._simulate else "https://api.binance.com"
                resp = await self._session.get(
                    f"{base}/api/v3/ticker/price",
                    params={"symbol": symbol},
                )
                if resp.status_code == 200:
                    return float(resp.json()["price"])
        except Exception:
            pass
        return 50000.0  # fallback

    # ── 高级交易方法 ──────────────────────────────────────────────

    async def execute_signal(
        self,
        signal_action: str,
        symbol: str,
        price: float,
        quantity_pct: float = 1.0,
        sl_price: float | None = None,
        tp_price: float | None = None,
        market_type: MarketType = "spot",
        leverage: int = 1,
        strategy_id: str = "",
    ) -> ExecutionResult:
        """根据交易信号执行下单."""
        if signal_action in ("buy",):
            return await self.create_order(
                symbol=symbol, side="buy", order_type="market",
                quantity=quantity_pct, market_type=market_type,
                leverage=leverage, strategy_id=strategy_id,
                stop_price=None, reduce_only=False,
            )
        elif signal_action in ("sell",):
            return await self.create_order(
                symbol=symbol, side="sell", order_type="market",
                quantity=quantity_pct, market_type=market_type,
                leverage=leverage, strategy_id=strategy_id,
                stop_price=None, reduce_only=False,
            )
        elif signal_action in ("close_long",):
            return await self.create_order(
                symbol=symbol, side="sell", order_type="market",
                quantity=quantity_pct, market_type=market_type,
                leverage=leverage, strategy_id=strategy_id,
                reduce_only=True,
            )
        elif signal_action in ("close_short",):
            return await self.create_order(
                symbol=symbol, side="buy", order_type="market",
                quantity=quantity_pct, market_type=market_type,
                leverage=leverage, strategy_id=strategy_id,
                reduce_only=True,
            )
        return ExecutionResult(success=False, error=f"Unknown action: {signal_action}")


# Singleton
executor = TradeExecutor()
