"""
🔌 Binance Connector — 实时行情连接管理器 (Spot + Futures)

支持:
  - 现货/合约 WebSocket 实时行情 (ticker + kline)
  - 现货/合约 REST API
  - 自动断线重连 (指数退避)
  - 健康检查
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── 公共 REST (不需要 key) ──────────────────────────────────────

class _PublicAPI:
    def __init__(self, base_spot: str, base_futures: str):
        self._spot_base = base_spot
        self._futures_base = base_futures

    async def _fetch(self, url: str) -> dict | list | None:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning("[Binance-Public] %s → %s", url.split("?")[0], e)
            return None


class _SpotConnector:
    """现货 REST + WebSocket."""

    def __init__(self, base: str, ws_base: str):
        self._base = base
        self._ws_base = ws_base
        self._session: httpx.AsyncClient | None = None
        self._running = False
        self._reconnect_delay = settings.reconnect_min_delay
        self._listeners: dict[str, list[Callable]] = {
            "kline": [], "ticker": [], "trade": [], "error": [],
        }
        self._tasks: list[Any] = []
        self._subscribed_symbols: set[str] = set()

    async def start(self, symbols: list[str]):
        self._session = httpx.AsyncClient(timeout=30)
        self._running = True
        new = [s.upper() for s in symbols if s.upper() not in self._subscribed_symbols]
        if new:
            self._subscribed_symbols.update(new)
            self._tasks.append(asyncio.create_task(self._run_connection(new)))
            logger.info("[Spot] Connector subscribed: %s", new)

    async def stop(self):
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._session:
            await self._session.aclose()

    # ── REST ────────────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str = "1m",
                         limit: int = 100) -> list[dict]:
        if not self._session:
            return []
        try:
            r = await self._session.get(f"{self._base}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit})
            r.raise_for_status()
            return [{"open_time": k[0],"open":float(k[1]),"high":float(k[2]),
                      "low":float(k[3]),"close":float(k[4]),"volume":float(k[5]),
                      "close_time":k[6]} for k in r.json()]
        except Exception as e:
            logger.error("[Spot] klines error: %s", e)
            return []

    async def get_ticker(self, symbol: str) -> dict | None:
        if not self._session:
            return None
        try:
            r = await self._session.get(f"{self._base}/api/v3/ticker/24hr",
                params={"symbol": symbol})
            r.raise_for_status()
            d = r.json()
            return {"symbol":d["symbol"],"price":float(d["lastPrice"]),
                    "change":float(d["priceChange"]),"change_pct":float(d["priceChangePercent"]),
                    "high":float(d["highPrice"]),"low":float(d["lowPrice"]),
                    "volume":float(d["volume"])}
        except Exception as e:
            logger.error("[Spot] ticker error: %s", e)
            return None

    async def get_exchange_info(self) -> list[dict]:
        if not self._session:
            return []
        try:
            r = await self._session.get(f"{self._base}/api/v3/exchangeInfo")
            r.raise_for_status()
            data = r.json()
            return [{"symbol":s["symbol"],"status":s["status"],
                      "base_asset":s["baseAsset"],"quote_asset":s["quoteAsset"]}
                    for s in data.get("symbols",[]) if s["status"] == "TRADING"]
        except Exception as e:
            logger.error("[Spot] exchangeInfo error: %s", e)
            return []

    # ── Websocket ───────────────────────────────────────────────

    async def _run_connection(self, symbols: list[str]):
        import asyncio, websockets
        while self._running:
            try:
                streams = [f"{s.lower()}@kline_1m" for s in symbols]
                streams += [f"{s.lower()}@ticker" for s in symbols]
                url = f"{self._ws_base}/{'/'.join(streams)}"
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    self._reconnect_delay = settings.reconnect_min_delay
                    async for msg in ws:
                        await self._handle(json.loads(msg))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[Spot] WS lost: %s. reconnect in %.1fs", e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _handle(self, msg: dict):
        e = msg.get("e", "")
        if e == "kline":
            k = msg["k"]
            data = {"symbol":msg["s"],"open_time":k["t"],"open":float(k["o"]),
                    "high":float(k["h"]),"low":float(k["l"]), "close":float(k["c"]),
                    "volume":float(k["v"]), "close_time":k["T"],"is_final":k["x"]}
            await self._emit("kline", data)
        elif e == "24hrTicker":
            data = {"symbol":msg["s"],"price":float(msg["c"]),"change":float(msg["p"]),
                    "change_pct":float(msg["P"]),"high":float(msg["h"]),"low":float(msg["l"]),
                    "volume":float(msg["v"]),"quote_volume":float(msg["q"])}
            await self._emit("ticker", data)
        elif e == "trade":
            data = {"symbol":msg["s"],"price":float(msg["p"]),"quantity":float(msg["q"]),
                    "time":msg["T"],"is_buyer_maker":msg["m"]}
            await self._emit("trade", data)

    async def _emit(self, event: str, data: Any):
        for cb in self._listeners.get(event, []):
            try:
                if asyncio.iscoroutinefunction(cb): await cb(data)
                else: cb(data)
            except Exception as e:
                logger.error("[Spot] listener: %s", e)

    def on(self, event: str, cb: Callable):
        if event in self._listeners:
            self._listeners[event].append(cb)

    def off(self, event: str, cb: Callable):
        if event in self._listeners:
            self._listeners[event] = [c for c in self._listeners[event] if c != cb]


class _FuturesConnector:
    """合约 REST (无 WebSocket 订阅 — 复用现货 WS 的价格近似, 但 REST 独立)."""

    def __init__(self, base: str):
        self._base = base
        self._session: httpx.AsyncClient | None = None

    async def start(self):
        self._session = httpx.AsyncClient(timeout=30)

    async def stop(self):
        if self._session:
            await self._session.aclose()

    # ── Klines (U 本位合约 klines 接口与现货不同) ──────────────

    async def get_klines(self, symbol: str, interval: str = "1m",
                         limit: int = 100) -> list[dict]:
        if not self._session:
            return []
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit})
            r.raise_for_status()
            return [{"open_time": k[0],"open":float(k[1]),"high":float(k[2]),
                      "low":float(k[3]),"close":float(k[4]),"volume":float(k[5]),
                      "close_time":k[6]} for k in r.json()]
        except Exception as e:
            logger.error("[Futures] klines error: %s", e)
            return []

    async def get_ticker(self, symbol: str) -> dict | None:
        if not self._session:
            return None
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/ticker/24hr",
                params={"symbol": symbol})
            r.raise_for_status()
            d = r.json()
            return {"symbol":d["symbol"],"price":float(d["lastPrice"]),
                    "change":float(d["priceChange"]),"change_pct":float(d["priceChangePercent"]),
                    "high":float(d["highPrice"]),"low":float(d["lowPrice"]),
                    "volume":float(d["volume"]),"quote_volume":float(d["quoteVolume"])}
        except Exception as e:
            logger.error("[Futures] ticker error: %s", e)
            return None

    async def get_exchange_info(self) -> list[dict]:
        if not self._session:
            return []
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/exchangeInfo")
            r.raise_for_status()
            data = r.json()
            return [{"symbol":s["symbol"],"status":s["status"],
                      "base_asset":s["baseAsset"],"quote_asset":s["quoteAsset"],
                      "contract_type":s.get("contractType","")}
                    for s in data.get("symbols",[]) if s["status"] == "TRADING"]
        except Exception as e:
            logger.error("[Futures] exchangeInfo error: %s", e)
            return []

    # ── 合约特有 ────────────────────────────────────────────────

    async def get_mark_price(self, symbol: str) -> dict | None:
        if not self._session:
            return None
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/premiumIndex",
                params={"symbol": symbol})
            r.raise_for_status()
            d = r.json()
            return {"symbol":d["symbol"],"mark_price":float(d["markPrice"]),
                    "index_price":float(d["indexPrice"]),
                    "funding_rate":float(d.get("lastFundingRate", 0)),
                    "next_funding_time":d.get("nextFundingTime", 0)}
        except Exception as e:
            logger.error("[Futures] markPrice error: %s", e)
            return None

    async def get_open_interest(self, symbol: str) -> dict | None:
        if not self._session:
            return None
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/openInterest",
                params={"symbol": symbol})
            r.raise_for_status()
            d = r.json()
            return {"symbol":d["symbol"],"open_interest":float(d["openInterest"])}
        except Exception as e:
            logger.error("[Futures] OI error: %s", e)
            return None

    async def get_order_book(self, symbol: str, limit: int = 10) -> dict | None:
        if not self._session:
            return None
        try:
            r = await self._session.get(f"{self._base}/fapi/v1/depth",
                params={"symbol": symbol, "limit": limit})
            r.raise_for_status()
            d = r.json()
            return {"symbol":symbol,"bids":d["bids"],"asks":d["asks"]}
        except Exception as e:
            logger.error("[Futures] depth error: %s", e)
            return None

    async def get_funding_rates(self, symbol: str = "", limit: int = 100) -> list[dict]:
        """Funding rate history."""
        if not self._session:
            return []
        try:
            params = {"limit": limit}
            if symbol: params["symbol"] = symbol
            r = await self._session.get(f"{self._base}/fapi/v1/fundingRate",
                params=params)
            r.raise_for_status()
            data = r.json()
            return [{"symbol":d["symbol"],"funding_rate":float(d["fundingRate"]),
                      "funding_time":d["fundingTime"]} for d in data]
        except Exception as e:
            logger.error("[Futures] fundingRate error: %s", e)
            return []


# ── 统一入口 ────────────────────────────────────────────────────

class BinanceConnector:
    """统一行情入口: .spot / .futures 分别访问."""

    def __init__(self):
        if settings.binance_testnet:
            self._ws_spot = "wss://testnet.binance.vision/ws"
            self._rest_spot = "https://testnet.binance.vision"
            self._rest_futures = "https://testnet.binancefuture.com"
        else:
            self._ws_spot = "wss://stream.binance.com:9443/ws"
            self._rest_spot = "https://api.binance.com"
            self._rest_futures = "https://fapi.binance.com"

        self.spot = _SpotConnector(self._rest_spot, self._ws_spot)
        self.futures = _FuturesConnector(self._rest_futures)

        # 兼容旧代码: 默认指向 spot
        self._listeners = self.spot._listeners
        self._session = None

    async def start(self, symbols: list[str] | None = None):
        syms = symbols or [settings.default_symbol]
        await self.spot.start(syms)
        await self.futures.start()
        logger.info("[Connector] Spot+Future ready: %s", syms)

    async def stop(self):
        await self.spot.stop()
        await self.futures.stop()

    # ── 兼容旧接口 ──────────────────────────────────────────────

    async def get_klines(self, symbol: str, interval: str = "1m",
                         limit: int = 100, market: str = "spot") -> list[dict]:
        c = self.spot if market == "spot" else self.futures
        return await c.get_klines(symbol, interval, limit)

    async def get_ticker(self, symbol: str, market: str = "spot") -> dict | None:
        c = self.spot if market == "spot" else self.futures
        return await c.get_ticker(symbol)

    async def get_exchange_info(self, market: str = "spot") -> list[dict]:
        c = self.spot if market == "spot" else self.futures
        return await c.get_exchange_info()

    # ── Event listener 转发 (只转发现货, 合约走 REST) ──────────

    def on(self, event: str, cb: Callable):
        self.spot.on(event, cb)

    def off(self, event: str, cb: Callable):
        self.spot.off(event, cb)

    # ── 合约专属的便捷方法 ─────────────────────────────────────

    async def get_mark_price(self, symbol: str) -> dict | None:
        return await self.futures.get_mark_price(symbol)

    async def get_open_interest(self, symbol: str) -> dict | None:
        return await self.futures.get_open_interest(symbol)

    async def get_futures_order_book(self, symbol: str, limit: int = 10) -> dict | None:
        return await self.futures.get_order_book(symbol, limit)

    async def get_funding_rates(self, symbol: str = "", limit: int = 100) -> list[dict]:
        return await self.futures.get_funding_rates(symbol, limit)

    # ── 用于测试 ────────────────────────────────────────────────

    async def get_account(self) -> dict:
        """保留兼容: 走旧有逻辑."""
        from binance.client import Client
        try:
            c = Client(settings.binance_api_key, settings.binance_secret_key,
                       testnet=settings.binance_testnet)
            acc = c.get_account()
            nonzero = [b for b in acc.get("balances", [])
                       if float(b["free"]) > 0 or float(b["locked"]) > 0]
            return {"balances": nonzero, "can_trade": acc.get("canTrade", False)}
        except Exception as e:
            logger.error("[Connector] account error: %s", e)
            return {"error": str(e)}


# Singleton
connector = BinanceConnector()