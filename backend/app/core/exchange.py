"""
🔌 Binance Connector — 实时行情连接管理器

特性:
  - WebSocket 实时行情 (ticker + kline)
  - 自动断线重连 (指数退避)
  - 健康检查 (ping/pong)
  - 多交易对支持
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from typing import Any, Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class BinanceConnector:
    """Binance WebSocket + REST 连接管理器."""

    def __init__(self):
        self._ws: Any = None
        self._running = False
        self._reconnect_delay = settings.reconnect_min_delay
        self._listeners: dict[str, list[Callable]] = {
            "kline": [],
            "ticker": [],
            "trade": [],
            "error": [],
        }
        self._tasks: list[asyncio.Task] = []
        self._session: httpx.AsyncClient | None = None

        # For testnet
        if settings.binance_testnet:
            self._ws_base = "wss://testnet.binance.vision/ws"
            self._rest_base = "https://testnet.binance.vision"
        else:
            self._ws_base = "wss://stream.binance.com:9443/ws"
            self._rest_base = "https://api.binance.com"

    def on(self, event: str, callback: Callable):
        """注册事件监听器."""
        if event in self._listeners:
            self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable):
        """移除事件监听器."""
        if event in self._listeners:
            self._listeners[event] = [c for c in self._listeners[event] if c != callback]

    async def start(self, symbols: list[str] | None = None):
        """启动连接."""
        if self._running:
            return
        self._running = True
        self._session = httpx.AsyncClient(timeout=30)
        syms = symbols or [settings.default_symbol]
        self._tasks.append(asyncio.create_task(self._run_connection(syms)))
        logger.info("[Binance] Connector started for %s", syms)

    async def stop(self):
        """停止连接."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.aclose()
        logger.info("[Binance] Connector stopped")

    async def _run_connection(self, symbols: list[str]):
        """运行连接循环 — 自动重连."""
        while self._running:
            try:
                streams = []
                for s in symbols:
                    sym_lower = s.lower()
                    streams.extend([
                        f"{sym_lower}@kline_1m",
                        f"{sym_lower}@ticker",
                        f"{sym_lower}@trade",
                    ])
                stream_path = "/".join(streams)
                url = f"{self._ws_base}/{stream_path}"

                import websockets
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._reconnect_delay = settings.reconnect_min_delay
                    logger.info("[Binance] WebSocket connected ✅")

                    async for message in ws:
                        await self._handle_message(json.loads(message))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[Binance] Connection lost: %s. Reconnecting in %.1fs...",
                               e, self._reconnect_delay)
                self._emit("error", {"error": str(e), "reconnect_delay": self._reconnect_delay})
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * settings.reconnect_backoff,
                    settings.reconnect_max_delay,
                )

    async def _handle_message(self, msg: dict):
        """处理 WebSocket 消息."""
        e_type = msg.get("e", "")
        if e_type == "kline":
            k = msg["k"]
            data = {
                "symbol": msg["s"],
                "open_time": k["t"],
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "close_time": k["T"],
                "is_final": k["x"],
            }
            await self._emit_async("kline", data)
        elif e_type == "24hrTicker":
            data = {
                "symbol": msg["s"],
                "price": float(msg["c"]),
                "change": float(msg["p"]),
                "change_pct": float(msg["P"]),
                "high": float(msg["h"]),
                "low": float(msg["l"]),
                "volume": float(msg["v"]),
                "quote_volume": float(msg["q"]),
            }
            await self._emit_async("ticker", data)
        elif e_type == "trade":
            data = {
                "symbol": msg["s"],
                "price": float(msg["p"]),
                "quantity": float(msg["q"]),
                "time": msg["T"],
                "is_buyer_maker": msg["m"],
            }
            await self._emit_async("trade", data)

    async def _emit_async(self, event: str, data: Any):
        """异步通知所有监听器."""
        for cb in self._listeners.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(data)
                else:
                    cb(data)
            except Exception as e:
                logger.error("[Binance] Listener error: %s", e)

    def _emit(self, event: str, data: Any):
        """同步通知."""
        for cb in self._listeners.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.error("[Binance] Listener error: %s", e)

    # ── REST API ────────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str = "1m",
                         limit: int = 100) -> list[dict]:
        """获取历史K线."""
        if not self._session:
            return []
        try:
            resp = await self._session.get(
                f"{self._rest_base}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            resp.raise_for_status()
            raw = resp.json()
            return [
                {
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": k[6],
                }
                for k in raw
            ]
        except Exception as e:
            logger.error("[Binance] REST error: %s", e)
            return []

    async def get_ticker(self, symbol: str) -> dict | None:
        """获取当前报价."""
        if not self._session:
            return None
        try:
            resp = await self._session.get(
                f"{self._rest_base}/api/v3/ticker/24hr",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            d = resp.json()
            return {
                "symbol": d["symbol"],
                "price": float(d["lastPrice"]),
                "change": float(d["priceChange"]),
                "change_pct": float(d["priceChangePercent"]),
                "high": float(d["highPrice"]),
                "low": float(d["lowPrice"]),
                "volume": float(d["volume"]),
            }
        except Exception as e:
            logger.error("[Binance] Ticker error: %s", e)
            return None

    async def get_exchange_info(self) -> list[dict]:
        """获取交易对信息."""
        if not self._session:
            return []
        try:
            resp = await self._session.get(f"{self._rest_base}/api/v3/exchangeInfo")
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "symbol": s["symbol"],
                    "status": s["status"],
                    "base_asset": s["baseAsset"],
                    "quote_asset": s["quoteAsset"],
                    "min_qty": float(next(f["minQty"] for f in s["filters"] if f["filterType"] == "LOT_SIZE")),
                    "step_size": float(next(f["stepSize"] for f in s["filters"] if f["filterType"] == "LOT_SIZE")),
                }
                for s in data.get("symbols", [])
            ]
        except Exception as e:
            logger.error("[Binance] Exchange info error: %s", e)
            return []

    async def get_account(self) -> dict:
        """获取账户信息 (需要 API Key)."""
        if not self._session or not settings.binance_api_key:
            return {"status": "no_api_key"}
        try:
            ts = int(time.time() * 1000)
            query = f"timestamp={ts}"
            signature = hmac.new(
                settings.binance_secret_key.encode(),
                query.encode(),
                hashlib.sha256,
            ).hexdigest()
            resp = await self._session.get(
                f"{self._rest_base}/api/v3/account?{query}&signature={signature}",
                headers={"X-MBX-APIKEY": settings.binance_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "balances": [
                    {"asset": b["asset"], "free": float(b["free"]), "locked": float(b["locked"])}
                    for b in data.get("balances", [])
                    if float(b["free"]) > 0 or float(b["locked"]) > 0
                ],
                "can_trade": data.get("canTrade", False),
            }
        except Exception as e:
            logger.error("[Binance] Account error: %s", e)
            return {"error": str(e)}


# Singleton
connector = BinanceConnector()
