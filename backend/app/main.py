"""Quant Trading System — FastAPI Application."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text as sa_text

from app.config import settings
from app.db import create_tables, get_db, async_session_factory
from app.models import Strategy as StrategyModel, Kline, Trade, BacktestRun, Position, Order
from app.core.exchange import connector
from app.core.backtest import BacktestEngine
from app.core.strategies import (
    BaseStrategy, Signal, MarketType,
    create_strategy as factory_create_strategy, get_strategy_meta,
    VolumeSurgeStrategy, GridTradingStrategy,
    MomentumBreakoutStrategy, MeanReversionStrategy,
    MACDComboStrategy,
)
from app.core.trading import executor, risk_manager
from app.core.paper import PaperAccountManager, paper_events

logger = logging.getLogger(__name__)

# Paper manager (initialized in lifespan)
paper_manager: PaperAccountManager | None = None

# ── Global state ──
_active_strategies: dict[str, BaseStrategy] = {}     # db_id -> strategy instance
_active_symbol_map: dict[str, set[str]] = {}         # symbol -> set of db_ids
_ws_clients: set[WebSocket] = set()

# Track which symbols the connector is subscribed to
_connector_symbols: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global paper_manager
    logger.info("Quant Trading System v0.2.0 starting...")
    await create_tables()
    await executor.start()
    # 启动行情 connector 默认订阅, REST sessions 始终可用
    await connector.start([settings.default_symbol])
    _connector_symbols.add(settings.default_symbol.upper())
    # Paper trading manager
    paper_manager = PaperAccountManager(async_session_factory, connector)
    await paper_manager.start()
    # Forward paper events to WS clients
    def _on_paper_event(kind: str, payload: dict):
        msg = json.dumps({"type": f"paper_{kind}", "data": payload})
        for ws in list(_ws_clients):
            try:
                asyncio.create_task(ws.send_text(msg))
            except Exception:
                pass
    paper_events.on(_on_paper_event)
    logger.info("System ready.")
    yield
    if paper_manager:
        await paper_manager.stop()
    await connector.stop()
    await executor.stop()
    for s in _active_strategies.values():
        s.reset()
    logger.info("System stopped.")


app = FastAPI(title="Quant Trading API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ── Market data handler ─────────────────────────────────────────

async def on_kline(data: dict):
    symbol = data["symbol"]
    # Broadcast to WS clients
    msg = json.dumps({"type": "kline", "data": data})
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)

    # Feed all active strategies on this symbol
    if symbol in _active_symbol_map:
        for db_id in list(_active_symbol_map[symbol]):
            strategy = _active_strategies.get(db_id)
            if strategy:
                signal = strategy.on_kline(data)
                strategy.log_signal(signal, data)
                # Broadcast non-hold signals
                if signal.action != "hold":
                    signal_msg = json.dumps({
                        "type": "signal", "data": {
                            "strategy_id": db_id,
                            "strategy_name": strategy.name,
                            "symbol": symbol,
                            "action": signal.action,
                            "strength": signal.strength,
                            "price": signal.price,
                            "reason": signal.reason,
                            "sl_price": signal.sl_price,
                            "tp_price": signal.tp_price,
                        }
                    })
                    for ws in _ws_clients:
                        try:
                            await ws.send_text(signal_msg)
                        except Exception:
                            pass

                    # Execute signal via trading executor OR paper manager
                    if signal.action in ("buy", "sell", "close_long", "close_short"):
                        pos = strategy.position
                        mrkt = strategy._market_type
                        lvg = strategy.params.get("futures_leverage", 1)

                        # Determine routing mode: paper if strategy.mode=='paper' and account bound
                        strategy_mode = getattr(strategy, "_mode", "live")
                        paper_acc_id = getattr(strategy, "_paper_account_id", None)

                        if strategy_mode == "paper" and paper_acc_id and paper_manager:
                            # Paper route
                            paper_result = await paper_manager.execute_signal(
                                account_id=paper_acc_id,
                                strategy_id=db_id,
                                signal_action=signal.action,
                                symbol=symbol,
                                price=signal.price,
                                quantity_pct=signal.quantity_pct or 0.5,
                                signal_strength=getattr(signal, "strength", None),
                            )
                            if paper_result.success and paper_result.trade:
                                t = paper_result.trade
                                if paper_result.position_after:
                                    strategy.update_position(
                                        signal.action, t.price, data.get("open_time", 0),
                                        t.quantity, pnl=t.pnl or 0.0,
                                    )
                                else:
                                    strategy.update_position(
                                        signal.action, t.price, data.get("open_time", 0),
                                        0.0, pnl=paper_result.realized_pnl_delta,
                                    )
                                _save_trade_to_db(
                                    strategy_id=db_id, symbol=symbol, side=t.side,
                                    price=t.price, quantity=t.quantity, pnl=t.pnl,
                                    signal_strength=getattr(signal, "strength", None),
                                    action=signal.action, mode="paper",
                                )
                                logger.info("[Paper] %s %s @ %.2f ✅ (acc=%s)",
                                            symbol, signal.action, t.price, paper_acc_id[:8])
                            elif not paper_result.success:
                                logger.warning("[Paper] %s %s ❌ %s",
                                               symbol, signal.action, paper_result.error)
                            continue  # skip live executor branch

                        # Live route (default)
                        result = await executor.execute_signal(
                            signal_action=signal.action,
                            symbol=symbol,
                            price=signal.price,
                            quantity_pct=signal.quantity_pct,
                            market_type=mrkt,
                            leverage=lvg,
                            strategy_id=db_id,
                        )
                        if result.success and result.order:
                            strategy.update_position(
                                signal.action,
                                result.order.avg_fill_price,
                                data.get("open_time", 0),
                                result.order.filled_quantity,
                                pnl=result.order.pnl or 0.0,
                            )
                            risk_manager.record_trade_pnl(result.order.pnl or 0.0)
                            _save_order_to_db(result.order)
                            # 同步落库 Trade 表 (交易明细)
                            mode = "sim" if settings.binance_testnet else "live"
                            _save_trade_to_db(
                                strategy_id=db_id,
                                symbol=symbol,
                                side=result.order.side,
                                price=result.order.avg_fill_price,
                                quantity=result.order.filled_quantity,
                                pnl=result.order.pnl,
                                signal_strength=getattr(signal, "strength", None),
                                action=signal.action,
                                mode=mode,
                            )
                            logger.info("[Exec] %s %s %s @ %.2f ✅",
                                        symbol, signal.action, mrkt, signal.price)


async def on_ticker(data: dict):
    msg = json.dumps({"type": "ticker", "data": data})
    for ws in list(_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _ws_clients.discard(ws)


connector.on("kline", on_kline)
connector.on("ticker", on_ticker)


def _save_order_to_db(order):
    """异步保存订单到数据库 (fire & forget)."""
    async def _save():
        try:
            async with async_session_factory() as db:
                db.add(Order(
                    id=order.id,
                    strategy_id=order.strategy_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    market_type=order.market_type,
                    price=order.price,
                    quantity=order.quantity,
                    filled_quantity=order.filled_quantity,
                    avg_fill_price=order.avg_fill_price,
                    status=order.status,
                    sl_price=order.sl_price,
                    tp_price=order.tp_price,
                    leverage=order.leverage,
                    reduce_only=order.reduce_only,
                    pnl=order.pnl if hasattr(order, 'pnl') else None,
                    error=order.error,
                    exchange_order_id=order.exchange_order_id,
                ))
                await db.commit()
        except Exception as e:
            logger.error("Save order error: %s", e)
    asyncio.ensure_future(_save())


def _save_trade_to_db(*, strategy_id: str, symbol: str, side: str, price: float,
                        quantity: float, pnl: float | None,
                        signal_strength: float | None,
                        action: str, mode: str = "live"):
    """保存 Trade 记录 (fire & forget). action=buy|sell|close_long|close_short."""
    # side normalized: "buy" / "sell" 不动; close_long/short 映射到 sell/buy
    db_side = side
    is_close = action in ("close_long", "close_short")
    if action == "close_long":
        db_side = "sell"
    elif action == "close_short":
        db_side = "buy"
    status = "closed" if is_close else "open"

    async def _save():
        try:
            async with async_session_factory() as db:
                db.add(Trade(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side=db_side,
                    price=price,
                    quantity=quantity,
                    pnl=pnl,
                    status=status,
                    signal_strength=signal_strength,
                    backtest_id=f"mode:{mode}",  # 没有专门字段, 复用 backtest_id 存 mode
                    close_time=datetime.now(timezone.utc) if is_close else None,
                ))
                await db.commit()
        except Exception as e:
            logger.error("Save trade error: %s", e)
    asyncio.ensure_future(_save())


# ── Helpers ──────────────────────────────────────────────────────

async def _ensure_symbols(symbols: list[str]):
    """确保连接器订阅了这些交易对."""
    new = [s.upper() for s in symbols if s.upper() not in _connector_symbols]
    if new:
        await connector.start(new)
        _connector_symbols.update(new)


# ═══════════════════════════════════════════════════════════════════
# REST API
# ═══════════════════════════════════════════════════════════════════

# ── Status ──────────────────────────────────────────────────────

@app.get("/api/v1/status")
async def get_status():
    return {
        "version": "0.2.0",
        "status": "running",
        "env": settings.app_env,
        "testnet": settings.binance_testnet,
        "active_strategies": len(_active_strategies),
        "ws_clients": len(_ws_clients),
        "open_positions": len(executor.get_all_positions()),
    }


# ── Strategy Types ──────────────────────────────────────────────

@app.get("/api/v1/strategies/types")
async def list_strategy_types():
    """列出所有可用的策略类型及元数据."""
    return list(get_strategy_meta().values())


# ── Strategies ──────────────────────────────────────────────────

@app.get("/api/v1/strategies")
async def list_strategies():
    """列出所有策略 (DB 中的)."""
    async with async_session_factory() as db:
        result = await db.execute(
            select(StrategyModel).order_by(StrategyModel.updated_at.desc())
        )
        strategies = result.scalars().all()
        enriched = []
        for s in strategies:
            d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
            d["running"] = s.id in _active_strategies
            d["strategy_type"] = getattr(s, "strategy_type", "volume_surge")
            if s.id in _active_strategies:
                d["live_state"] = _active_strategies[s.id].to_dict()
            enriched.append(d)
        return enriched


@app.post("/api/v1/strategies")
async def create_strategy(data: dict):
    """创建新策略 (支持选择策略类型)."""
    strategy_type = data.get("strategy_type", "volume_surge")
    market_type = data.get("market_type", "spot")
    symbol = data.get("symbol", "BTCUSDT").upper()
    params = data.get("params", {})

    # Validate strategy type
    meta = get_strategy_meta()
    if strategy_type not in meta:
        raise HTTPException(400, f"Unknown strategy type: {strategy_type}. Available: {list(meta.keys())}")
    if market_type not in meta[strategy_type]["supported_markets"]:
        raise HTTPException(400, f"Market '{market_type}' not supported by '{strategy_type}'")

    async with async_session_factory() as db:
        strategy = StrategyModel(
            name=data.get("name", meta[strategy_type]["name"]),
            symbol=symbol,
            timeframe=data.get("timeframe", "1m"),
            params=json.dumps(params),
            status="stopped",
        )
        db.add(strategy)
        await db.commit()
        await db.refresh(strategy)

    return {
        "id": strategy.id,
        "name": strategy.name,
        "strategy_type": strategy_type,
        "symbol": strategy.symbol,
        "timeframe": strategy.timeframe,
        "market_type": market_type,
        "params": params,
        "status": strategy.status,
    }


@app.get("/api/v1/strategies/{sid}")
async def get_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")
        return s


@app.put("/api/v1/strategies/{sid}")
async def update_strategy(sid: str, data: dict):
    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
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
        # Update running strategy params
        if sid in _active_strategies and "params" in data:
            _active_strategies[sid].update_params(
                data["params"] if isinstance(data["params"], dict) else json.loads(data["params"])
            )
        return s


@app.delete("/api/v1/strategies/{sid}")
async def delete_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")

        # Stop if running
        if sid in _active_strategies:
            sym = s.symbol
            _active_strategies.pop(sid, None)
            if sym in _active_symbol_map:
                _active_symbol_map[sym].discard(sid)

        await db.delete(s)
        await db.commit()
    return {"ok": True}


@app.post("/api/v1/strategies/{sid}/start")
async def start_strategy(sid: str, data: dict | None = None):
    """启动策略.

    Body (可选):
        market_type: "spot" | "futures"
    """
    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")

    market_type = (data or {}).get("market_type", "spot")
    mode = (data or {}).get("mode", getattr(s, "mode", None) or "live")
    paper_account_id = (data or {}).get("paper_account_id", getattr(s, "paper_account_id", None))
    strategy_type = getattr(s, "strategy_type", "volume_surge")

    # Validate paper mode
    if mode == "paper":
        if not paper_account_id:
            raise HTTPException(400, "mode=paper requires paper_account_id")
        if not paper_manager or not (await paper_manager.get_account(paper_account_id)):
            raise HTTPException(404, f"paper account {paper_account_id} not found")

    # Parse params from DB
    params = {}
    if s.params:
        try:
            params = json.loads(s.params) if isinstance(s.params, str) else s.params
        except (json.JSONDecodeError, TypeError):
            params = {}

    # Create strategy instance
    strategy = factory_create_strategy(strategy_type, sid, params, market_type)
    if not strategy:
        raise HTTPException(400, f"Failed to create strategy of type '{strategy_type}'")

    # Attach mode info
    strategy._mode = mode  # type: ignore[attr-defined]
    strategy._paper_account_id = paper_account_id  # type: ignore[attr-defined]

    _active_strategies[sid] = strategy
    if s.symbol not in _active_symbol_map:
        _active_symbol_map[s.symbol] = set()
    _active_symbol_map[s.symbol].add(sid)

    # Ensure connector is subscribed
    await _ensure_symbols([s.symbol])

    s.status = "running"
    s.mode = mode
    s.paper_account_id = paper_account_id
    async with async_session_factory() as db:
        await db.merge(s)
        await db.commit()

    return {"ok": True, "symbol": s.symbol, "strategy_id": sid,
            "strategy_type": strategy_type, "market_type": market_type,
            "mode": mode, "paper_account_id": paper_account_id}


@app.post("/api/v1/strategies/{sid}/stop")
async def stop_strategy(sid: str):
    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")

    if sid in _active_strategies:
        _active_strategies.pop(sid, None)
        if s.symbol in _active_symbol_map:
            _active_symbol_map[s.symbol].discard(sid)

    s.status = "stopped"
    async with async_session_factory() as db:
        await db.merge(s)
        await db.commit()

    return {"ok": True}


# ── Strategy State (Real-time) ──────────────────────────────────

@app.get("/api/v1/strategies/{sid}/state")
async def get_strategy_state(sid: str):
    """获取策略实时状态."""
    strategy = _active_strategies.get(sid)
    if not strategy:
        raise HTTPException(404, "Strategy not running")

    state = strategy.to_dict()
    # Add executor positions for this strategy
    positions = executor.get_all_positions()
    if positions:
        state["executor_positions"] = [
            {"symbol": p.symbol, "side": p.side, "quantity": p.quantity,
             "entry_price": p.entry_price, "unrealized_pnl": p.unrealized_pnl,
             "realized_pnl": p.realized_pnl}
            for p in positions
        ]
    return state


# ── Market ──────────────────────────────────────────────────────

@app.get("/api/v1/market/ticker/{symbol}")
async def get_ticker(symbol: str, market: str = Query("spot", regex="^(spot|futures)$")):
    data = await connector.get_ticker(symbol.upper(), market=market)
    return data or {"error": "not found"}


@app.get("/api/v1/market/klines/{symbol}")
async def get_klines(symbol: str, interval: str = "1m", limit: int = 100,
                      market: str = Query("spot", regex="^(spot|futures)$")):
    return await connector.get_klines(symbol.upper(), interval, limit, market=market)


@app.get("/api/v1/market/info")
async def get_exchange_info(market: str = Query("spot", regex="^(spot|futures)$")):
    return await connector.get_exchange_info(market=market)


# ── Futures-only endpoints ──────────────────────────────────────

@app.get("/api/v1/market/futures/mark-price/{symbol}")
async def get_mark_price(symbol: str):
    """获取合约标记价格 + 资金费率."""
    data = await connector.get_mark_price(symbol.upper())
    return data or {"error": "not found"}


@app.get("/api/v1/market/futures/open-interest/{symbol}")
async def get_open_interest(symbol: str):
    """获取合约未平仓位."""
    data = await connector.get_open_interest(symbol.upper())
    return data or {"error": "not found"}


@app.get("/api/v1/market/futures/depth/{symbol}")
async def get_futures_depth(symbol: str, limit: int = 10):
    """获取合约盘口."""
    data = await connector.get_futures_order_book(symbol.upper(), limit)
    return data or {"error": "not found"}


@app.get("/api/v1/market/futures/funding-rates")
async def get_funding_rates(symbol: str = "", limit: int = 100):
    """获取历史资金费率."""
    return await connector.get_funding_rates(symbol.upper() if symbol else "", limit)


@app.get("/api/v1/market/summary/{symbol}")
async def get_market_summary(symbol: str):
    """合并某个交易对的现货 + 合约概览 (一次拉取)."""
    sym = symbol.upper()
    import asyncio
    spot_ticker, futures_ticker, mark, oi = await asyncio.gather(
        connector.get_ticker(sym, market="spot"),
        connector.get_ticker(sym, market="futures"),
        connector.get_mark_price(sym),
        connector.get_open_interest(sym),
        return_exceptions=True,
    )
    def safe(x):
        return x if not isinstance(x, BaseException) and x else None
    return {
        "symbol": sym,
        "spot": safe(spot_ticker),
        "futures": safe(futures_ticker),
        "futures_mark": safe(mark),
        "futures_open_interest": safe(oi),
    }


# ── Market Data Download ────────────────────────────────────────

@app.post("/api/v1/market/download")
async def download_market_data(data: dict):
    symbol = data.get("symbol", "BTCUSDT").upper()
    interval = data.get("interval", "1m")
    limit = min(int(data.get("limit", 500)), 1000)
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    klines = await connector.get_klines(symbol, interval, limit)
    if not klines:
        return {"error": "无法获取行情数据", "downloaded": 0}

    if start_time:
        klines = [k for k in klines if k["open_time"] >= start_time]
    if end_time:
        klines = [k for k in klines if k["open_time"] <= end_time]

    saved = 0
    skipped = 0
    async with async_session_factory() as db:
        for k in klines:
            try:
                existing = await db.execute(
                    select(Kline).where(
                        Kline.symbol == symbol, Kline.interval == interval,
                        Kline.open_time == k["open_time"],
                    )
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    continue
                db.add(Kline(
                    symbol=symbol, interval=interval,
                    open_time=k["open_time"],
                    open=k["open"], high=k["high"], low=k["low"],
                    close=k["close"], volume=k["volume"],
                    close_time=k.get("close_time", k["open_time"] + 60000),
                ))
                saved += 1
            except Exception as e:
                logger.warning("Skip kline: %s", e)
                skipped += 1
        await db.commit()

    return {
        "symbol": symbol, "interval": interval,
        "downloaded": saved, "skipped": skipped,
        "range": {
            "from": klines[0]["open_time"], "to": klines[-1]["open_time"],
            "count": len(klines),
        } if klines else None,
    }


@app.get("/api/v1/market/data")
async def query_market_data(
    symbol: str = "BTCUSDT", interval: str = "1m",
    limit: int = 200, offset: int = 0,
    start_time: int | None = None, end_time: int | None = None,
):
    async with async_session_factory() as db:
        query = select(Kline).where(
            Kline.symbol == symbol.upper(), Kline.interval == interval,
        ).order_by(Kline.open_time.desc())

        if start_time:
            query = query.where(Kline.open_time >= start_time)
        if end_time:
            query = query.where(Kline.open_time <= end_time)

        total = await db.execute(
            select(Kline.id).where(
                Kline.symbol == symbol.upper(), Kline.interval == interval,
            )
        )
        total_count = len(total.all())

        result = await db.execute(query.offset(offset).limit(limit))
        rows = result.scalars().all()

        return {
            "symbol": symbol.upper(), "interval": interval,
            "total": total_count, "offset": offset, "limit": limit,
            "data": [{
                "open_time": r.open_time, "open": r.open, "high": r.high,
                "low": r.low, "close": r.close, "volume": r.volume,
                "close_time": r.close_time,
            } for r in rows],
        }


@app.get("/api/v1/market/data/stats")
async def market_data_stats():
    async with async_session_factory() as db:
        raw = await db.execute(sa_text("""
            SELECT symbol, interval, COUNT(*) as count,
                   MIN(open_time) as earliest, MAX(open_time) as latest
            FROM klines GROUP BY symbol, interval ORDER BY symbol, interval
        """))
        return [{
            "symbol": r[0], "interval": r[1], "count": r[2],
            "earliest": r[3], "latest": r[4],
        } for r in raw]


# ── Orders ──────────────────────────────────────────────────────

@app.post("/api/v1/orders")
async def create_order(data: dict):
    """手动创建订单."""
    symbol = data.get("symbol", "BTCUSDT").upper()
    side = data.get("side", "buy")
    order_type = data.get("order_type", "market")
    quantity = float(data.get("quantity", 0.01))
    price = float(data.get("price", 0))
    market_type = data.get("market_type", "spot")
    leverage = int(data.get("leverage", 1))
    strategy_id = data.get("strategy_id", "")

    result = await executor.create_order(
        symbol=symbol, side=side, order_type=order_type,
        quantity=quantity, price=price,
        market_type=market_type, leverage=leverage,
        strategy_id=strategy_id,
    )

    if result.success and result.order:
        _save_order_to_db(result.order)

    return {
        "success": result.success,
        "order": result.order.__dict__ if result.order else None,
        "error": result.error,
    }


@app.get("/api/v1/orders")
async def list_orders(strategy_id: str | None = None):
    """列出订单."""
    return executor.get_orders(strategy_id)


@app.delete("/api/v1/orders/{oid}")
async def cancel_order(oid: str):
    result = await executor.cancel_order(oid)
    return {"success": result.success, "error": result.error}


# ── Positions ──────────────────────────────────────────────────

@app.get("/api/v1/positions")
async def get_positions():
    """获取当前持仓 (来自交易执行器)."""
    positions = executor.get_all_positions()
    return [{
        "symbol": p.symbol, "side": p.side,
        "quantity": p.quantity, "entry_price": p.entry_price,
        "mark_price": p.mark_price,
        "unrealized_pnl": p.unrealized_pnl,
        "realized_pnl": p.realized_pnl,
        "leverage": p.leverage,
        "market_type": p.market_type,
    } for p in positions]


# ── Account ────────────────────────────────────────────────────

@app.get("/api/v1/account")
async def get_account(market_type: str = "spot"):
    """获取账户信息."""
    info = await executor.get_account(market_type)
    return {
        "total_equity": info.total_equity,
        "wallet_balance": info.wallet_balance,
        "available_balance": info.available_balance,
        "unrealized_pnl": info.unrealized_pnl,
        "margin_ratio": info.margin_ratio,
        "can_trade": info.can_trade,
        "market_type": info.market_type,
        "positions_count": len(info.positions),
    }


# ── Risk ────────────────────────────────────────────────────────

@app.get("/api/v1/risk")
async def get_risk():
    """获取风控状态."""
    return risk_manager.to_dict()


@app.put("/api/v1/risk/config")
async def update_risk_config(data: dict):
    """更新风控参数."""
    for k, v in data.items():
        if hasattr(risk_manager, k):
            setattr(risk_manager, k, v)
    return risk_manager.to_dict()


# ── Trades (legacy) ─────────────────────────────────────────────

@app.get("/api/v1/trades")
async def list_trades(
    strategy_id: str | None = None,
    symbol: str | None = None,
    mode: str | None = Query(None, regex="^(sim|live)$"),
    limit: int = Query(200, ge=1, le=1000),
):
    """列出交易记录, 可按 strategy_id / symbol / mode 过滤."""
    async with async_session_factory() as db:
        q = select(Trade).order_by(Trade.created_at.desc())
        if strategy_id:
            q = q.where(Trade.strategy_id == strategy_id)
        if symbol:
            q = q.where(Trade.symbol == symbol.upper())
        if mode:
            q = q.where(Trade.backtest_id == f"mode:{mode}")
        q = q.limit(limit)
        result = await db.execute(q)
        rows = result.scalars().all()
        return [
            {
                "id": t.id,
                "strategy_id": t.strategy_id,
                "symbol": t.symbol,
                "side": t.side,
                "price": t.price,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "status": t.status,
                "signal_strength": t.signal_strength,
                "mode": (t.backtest_id or "").replace("mode:", "") if t.backtest_id and t.backtest_id.startswith("mode:") else None,
                "open_time": t.open_time.isoformat() if t.open_time else None,
                "close_time": t.close_time.isoformat() if t.close_time else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ]


# ── Backtest ────────────────────────────────────────────────────

backtest_results_cache: dict[str, dict] = {}


@app.post("/api/v1/backtest/run")
async def run_backtest(data: dict):
    """运行回测 (支持选择策略类型)."""
    strategy_type = data.get("strategy_type", "volume_surge")
    market_type = data.get("market_type", "spot")
    symbol = data.get("symbol", "BTCUSDT")
    params = data.get("params", {})
    lookback = int(data.get("lookback_hours", 24))

    # Fetch klines
    klines = await connector.get_klines(symbol, "1m", limit=lookback * 60)
    if len(klines) < 50:
        klines = _generate_synthetic_klines(symbol, lookback * 60)

    # Create strategy for backtest
    bt_strategy = factory_create_strategy(strategy_type, "bt", params, market_type)
    if not bt_strategy:
        raise HTTPException(400, f"Unknown strategy type: {strategy_type}")

    engine = BacktestEngine(
        initial_capital=data.get("initial_capital", 10000),
        commission=data.get("commission", 0.001),
    )
    result = await engine.run(bt_strategy, klines, symbol)

    bt_id = str(uuid.uuid4())
    backtest_results_cache[bt_id] = {
        "id": bt_id, "strategy_type": strategy_type,
        "symbol": symbol, "market_type": market_type,
        **{k: v for k, v in result.__dict__.items() if not k.startswith("_")},
    }

    return {"id": bt_id, "strategy_type": strategy_type, "summary": {
        "total_return_pct": round(result.total_return_pct, 2),
        "sharpe": round(result.sharpe_ratio, 2),
        "max_drawdown": round(result.max_drawdown, 2),
        "win_rate": round(result.win_rate, 2),
        "total_trades": result.total_trades,
        "profit_factor": round(result.profit_factor, 2),
    }}


@app.get("/api/v1/backtest/{bid}")
async def get_backtest(bid: str):
    bt = backtest_results_cache.get(bid)
    if not bt:
        raise HTTPException(404, "Backtest not found")
    return bt


def _generate_synthetic_klines(symbol: str, n: int) -> list[dict]:
    import random
    import time
    rng = random.Random(42)
    price = 50000.0
    base_time = int(time.time() * 1000) - n * 60000
    klines = []
    for i in range(n):
        change = rng.gauss(0, 0.002)
        vol_surge = 1.0
        if rng.random() < 0.05:
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


# ── WebSocket ───────────────────────────────────────────────────

@app.websocket("/api/v1/ws/market/{symbol}")
async def ws_market(ws: WebSocket, symbol: str):
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("[WS] Client connected for %s", symbol)
    try:
        await _ensure_symbols([symbol.upper()])
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


@app.websocket("/api/v1/ws/signals")
async def ws_signals(ws: WebSocket):
    """WebSocket 推送所有交易信号."""
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("[WS] Signal client connected")
    try:
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
    return {"status": "ok", "service": "quant-trading", "version": "0.2.0"}



# ── Paper Trading ──────────────────────────────────────────────────

@app.post("/api/v1/paper/accounts")
async def create_paper_account(data: dict):
    """Create a new paper trading account."""
    if not paper_manager:
        raise HTTPException(503, "paper trading not initialized")
    account = await paper_manager.create_account(
        name=data.get("name", "Paper Account"),
        initial_capital=data.get("initial_capital", settings.paper_default_capital),
        fee_rate=data.get("fee_rate", settings.paper_default_fee_rate),
        slippage_bps=data.get("slippage_bps", settings.paper_default_slippage_bps),
    )
    return account.to_dict({})


@app.get("/api/v1/paper/accounts")
async def list_paper_accounts():
    """List all paper trading accounts."""
    if not paper_manager:
        return []
    accounts = await paper_manager.list_accounts()
    all_symbols = set()
    for acc in paper_manager._accounts.values():
        all_symbols.update(acc.positions.keys())
    mark_prices = await paper_manager._get_mark_prices(list(all_symbols))
    return [a.to_dict(mark_prices) for a in accounts]


@app.get("/api/v1/paper/accounts/{account_id}")
async def get_paper_account(account_id: str):
    """Get paper account detail (with equity & PnL)."""
    if not paper_manager:
        raise HTTPException(503, "paper trading not initialized")
    account = await paper_manager.get_account(account_id)
    if not account:
        raise HTTPException(404, "account not found")
    mark_prices = await paper_manager._get_mark_prices(list(account.positions.keys()))
    return account.to_dict(mark_prices)


@app.delete("/api/v1/paper/accounts/{account_id}")
async def delete_paper_account(account_id: str):
    if not paper_manager:
        raise HTTPException(503, "paper trading not initialized")
    ok = await paper_manager.delete_account(account_id)
    if not ok:
        raise HTTPException(404, "account not found")
    return {"ok": True}


@app.post("/api/v1/paper/accounts/{account_id}/reset")
async def reset_paper_account(account_id: str, data: dict | None = None):
    if not paper_manager:
        raise HTTPException(503, "paper trading not initialized")
    capital = data.get("initial_capital") if data else None
    account = await paper_manager.reset_account(account_id, capital)
    if not account:
        raise HTTPException(404, "account not found")
    return account.to_dict({})


@app.get("/api/v1/paper/accounts/{account_id}/trades")
async def get_paper_trades(account_id: str, limit: int = Query(50, ge=1, le=500)):
    if not paper_manager:
        return []
    return await paper_manager.get_trades(account_id, limit)


@app.get("/api/v1/paper/accounts/{account_id}/positions")
async def get_paper_positions(account_id: str):
    if not paper_manager:
        return []
    return await paper_manager.get_positions(account_id)


@app.get("/api/v1/paper/accounts/{account_id}/equity")
async def get_paper_equity(account_id: str, limit: int = Query(5000, ge=1, le=100000)):
    if not paper_manager:
        return []
    return await paper_manager.get_equity_snapshots(account_id, limit)


@app.get("/api/v1/paper/accounts/{account_id}/metrics")
async def get_paper_metrics(account_id: str):
    if not paper_manager:
        return {}
    return await paper_manager.get_metrics(account_id)


@app.post("/api/v1/strategies/{sid}/bind-paper-account")
async def bind_paper_account(sid: str, data: dict):
    """Bind a strategy to a paper trading account."""
    paper_account_id = data.get("paper_account_id")
    if not paper_account_id:
        raise HTTPException(400, "paper_account_id required")
    if not paper_manager:
        raise HTTPException(503, "paper trading not initialized")
    account = await paper_manager.get_account(paper_account_id)
    if not account:
        raise HTTPException(404, f"paper account {paper_account_id} not found")

    async with async_session_factory() as db:
        result = await db.execute(select(StrategyModel).where(StrategyModel.id == sid))
        s = result.scalar_one_or_none()
        if not s:
            raise HTTPException(404, "Strategy not found")
        s.mode = "paper"
        s.paper_account_id = paper_account_id
        await db.commit()

    if sid in _active_strategies:
        _active_strategies[sid]._mode = "paper"  # type: ignore[attr-defined]
        _active_strategies[sid]._paper_account_id = paper_account_id  # type: ignore[attr-defined]

    return {"ok": True, "strategy_id": sid, "mode": "paper", "paper_account_id": paper_account_id}
