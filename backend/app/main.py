"""Quant Trading System — FastAPI Application."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import settings
from app.db import create_tables, get_db, async_session_factory
from app.models import Strategy, Kline, Trade, BacktestRun, Position
from app.core.strategy import VolumeSurgeStrategy
from app.core.exchange import connector
from app.core.backtest import BacktestEngine

logger = logging.getLogger(__name__)

# ── Active strategies ──
_active_strategies: dict[str, VolumeSurgeStrategy] = {}
_ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Quant Trading System starting...")
    await create_tables()
    yield
    await connector.stop()
    for s in _active_strategies.values():
        s.reset()
    logger.info("System stopped.")


app = FastAPI(title="Quant Trading API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ── Binance market data handler ─────────────────────────────────

async def on_kline(data: dict):
    """Handle incoming kline from Binance — feed active strategies."""
    symbol = data["symbol"]
    msg = json.dumps({"type": "kline", "data": data})
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead

    # Feed active strategies
    if symbol in _active_strategies:
        strategy = _active_strategies[symbol]
        signal = strategy.on_kline(data)
        if signal.action != "hold":
            signal_msg = json.dumps({
                "type": "signal", "data": {
                    "symbol": symbol,
                    "action": signal.action,
                    "strength": signal.strength,
                    "price": signal.price,
                    "reason": signal.reason,
                }
            })
            for ws in _ws_clients:
                try:
                    await ws.send_text(signal_msg)
                except Exception:
                    pass


async def on_ticker(data: dict):
    msg = json.dumps({"type": "ticker", "data": data})
    for ws in list(_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _ws_clients.discard(ws)


connector.on("kline", on_kline)
connector.on("ticker", on_ticker)


# ── Status ──────────────────────────────────────────────────────

@app.get("/api/v1/status")
async def status():
    return {
        "status": "running",
        "env": settings.app_env,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "active_strategies": list(_active_strategies.keys()),
        "ws_clients": len(_ws_clients),
        "testnet": settings.binance_testnet,
    }


# ── Market ──────────────────────────────────────────────────────

@app.get("/api/v1/market/ticker/{symbol}")
async def get_ticker(symbol: str):
    data = await connector.get_ticker(symbol.upper())
    return data or {"error": "not found"}


@app.get("/api/v1/market/klines/{symbol}")
async def get_klines(symbol: str, interval: str = "1m", limit: int = 100):
    return await connector.get_klines(symbol.upper(), interval, limit)


@app.get("/api/v1/market/info")
async def get_exchange_info():
    return await connector.get_exchange_info()


# ── Strategies ──────────────────────────────────────────────────

@app.get("/api/v1/strategies")
async def list_strategies():
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).order_by(Strategy.updated_at.desc()))
        return result.scalars().all()


@app.post("/api/v1/strategies")
async def create_strategy(data: dict):
    async with async_session_factory() as db:
        strategy = Strategy(
            name=data.get("name", "Volume Surge"),
            symbol=data.get("symbol", "BTCUSDT"),
            timeframe=data.get("timeframe", "1m"),
            params=json.dumps(data.get("params", {})),
        )
        db.add(strategy)
        await db.commit()
        await db.refresh(strategy)
        return strategy


@app.get("/api/v1/strategies/{sid}")
async def get_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")
        return s


@app.put("/api/v1/strategies/{sid}")
async def update_strategy(sid: str, data: dict):
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")
        for k, v in data.items():
            if hasattr(s, k) and k not in ("id", "created_at"):
                if k == "params" and isinstance(v, dict):
                    v = json.dumps(v)
                setattr(s, k, v)
        await db.commit()
        await db.refresh(s)
        return s


@app.delete("/api/v1/strategies/{sid}")
async def delete_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")
        await db.delete(s)
        await db.commit()
    _active_strategies.pop(sid, None)
    return {"ok": True}


@app.post("/api/v1/strategies/{sid}/start")
async def start_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")

    params = json.loads(s.params) if isinstance(s.params, str) else s.params
    strategy = VolumeSurgeStrategy(params)
    _active_strategies[s.symbol] = strategy

    # Start Binance connector if not running
    await connector.start([s.symbol])

    s.status = "running"
    async with async_session_factory() as db:
        await db.merge(s)
        await db.commit()

    return {"ok": True, "symbol": s.symbol}


@app.post("/api/v1/strategies/{sid}/stop")
async def stop_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(Strategy).where(Strategy.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")

    _active_strategies.pop(s.symbol, None)
    s.status = "stopped"
    await db.merge(s)
    await db.commit()

    return {"ok": True}


# ── Backtest ───────────────────────────────────────────────────

backtest_results: dict[str, dict] = {}


@app.post("/api/v1/backtest/run")
async def run_backtest(data: dict):
    symbol = data.get("symbol", "BTCUSDT")
    params = data.get("params", {})
    lookback = int(data.get("lookback_hours", 24))

    # Fetch klines
    klines = await connector.get_klines(symbol, "1m", limit=lookback * 60)
    if len(klines) < 50:
        # Use synthetic data if Binance unavailable
        klines = _generate_synthetic_klines(symbol, lookback * 60)

    # Run backtest
    strategy = VolumeSurgeStrategy(params)
    engine = BacktestEngine(
        initial_capital=data.get("initial_capital", 10000),
        commission=data.get("commission", 0.001),
    )
    result = await engine.run(strategy, klines, symbol)

    # Save
    import uuid
    bt_id = str(uuid.uuid4())
    backtest_results[bt_id] = {
        "id": bt_id,
        **{
            k: v for k, v in result.__dict__.items()
            if not k.startswith("_")
        },
    }

    return {"id": bt_id, "summary": {
        "total_return_pct": round(result.total_return_pct, 2),
        "sharpe": round(result.sharpe_ratio, 2),
        "max_drawdown": round(result.max_drawdown, 2),
        "win_rate": round(result.win_rate, 2),
        "total_trades": result.total_trades,
        "profit_factor": round(result.profit_factor, 2),
    }}


@app.get("/api/v1/backtest/{bid}")
async def get_backtest(bid: str):
    bt = backtest_results.get(bid)
    if not bt:
        raise HTTPException(404, "Backtest not found")
    return bt


def _generate_synthetic_klines(symbol: str, n: int) -> list[dict]:
    """生成模拟K线用于回测."""
    import random
    import time
    rng = random.Random(42)
    price = 50000.0
    base_time = int(time.time() * 1000) - n * 60000
    klines = []
    for i in range(n):
        change = rng.gauss(0, 0.002)
        vol_surge = 1.0
        if rng.random() < 0.05:  # 5% 成交量突增
            vol_surge = 3.0 + rng.random() * 5
            change += rng.gauss(0.005 if rng.random() > 0.5 else -0.005, 0.003)
        price *= (1 + change)
        volume = rng.uniform(50, 200) * vol_surge
        klines.append({
            "open_time": base_time + i * 60000,
            "open": price * (1 - rng.uniform(0, 0.001)),
            "high": price * (1 + rng.uniform(0, 0.003)),
            "low": price * (1 - rng.uniform(0, 0.003)),
            "close": price,
            "volume": volume,
        })
    return klines


# ── Trades ──────────────────────────────────────────────────────

@app.get("/api/v1/trades")
async def list_trades():
    async with async_session_factory() as db:
        result = await db.execute(select(Trade).order_by(Trade.created_at.desc()).limit(100))
        return result.scalars().all()


@app.get("/api/v1/positions")
async def get_positions():
    async with async_session_factory() as db:
        result = await db.execute(select(Position))
        return result.scalars().all()


# ── WebSocket ───────────────────────────────────────────────────

@app.websocket("/api/v1/ws/market/{symbol}")
async def ws_market(ws: WebSocket, symbol: str):
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("[WS] Client connected for %s", symbol)
    try:
        # Start connector if not running
        await connector.start([symbol.upper()])
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "quant-trading"}
