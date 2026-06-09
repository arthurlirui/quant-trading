"""PaperAccountManager: multi-account lifecycle + strategy binding."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.paper.account import PaperAccount, PaperPositionRuntime
from app.core.paper.events import paper_events
from app.core.paper.matcher import PaperMatcher, PaperExecutionResult
from app.core.paper.metrics import build_metrics
from app.models.paper_account import PaperAccount as PaperAccountModel
from app.models.paper_trade import PaperTrade as PaperTradeModel
from app.models.paper_position import PaperPosition as PaperPositionModel
from app.models.paper_equity_snapshot import PaperEquitySnapshot

logger = logging.getLogger(__name__)


class PaperAccountManager:
    """Manages all paper trading accounts, strategies binding, and snapshot loop."""

    def __init__(self, session_factory, connector):
        self._session_factory = session_factory
        self._matcher = PaperMatcher(connector)
        self._accounts: dict[str, PaperAccount] = {}
        self._lock = asyncio.Lock()
        self._snapshot_task: asyncio.Task | None = None
        self._stopped = False

    async def start(self):
        await self._load_all()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        logger.info("PaperAccountManager started (%d accounts)", len(self._accounts))

    async def stop(self):
        self._stopped = True
        if self._snapshot_task:
            self._snapshot_task.cancel()
            try:
                await self._snapshot_task
            except asyncio.CancelledError:
                pass
        logger.info("PaperAccountManager stopped")

    # ── Account CRUD ────────────────────────────────────────────

    async def create_account(
        self, name: str, initial_capital: float = 10000.0,
        fee_rate: float = 0.001, slippage_bps: float = 5.0,
    ) -> PaperAccount:
        acc_id = str(uuid4())
        account = PaperAccount(
            id=acc_id, name=name, cash=initial_capital,
            initial_capital=initial_capital, fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )
        self._accounts[acc_id] = account
        await self._persist_account(account)
        paper_events.emit("account_created", {"account_id": acc_id, "name": name})
        logger.info("Created paper account '%s' (id=%s) capital=%.0f", name, acc_id, initial_capital)
        return account

    async def get_account(self, account_id: str) -> PaperAccount | None:
        return self._accounts.get(account_id)

    async def list_accounts(self) -> list[PaperAccount]:
        return list(self._accounts.values())

    async def reset_account(
        self, account_id: str, initial_capital: float | None = None,
    ) -> PaperAccount | None:
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return None
            ic = initial_capital if initial_capital is not None else account.initial_capital
            account.cash = ic
            account.initial_capital = ic
            account.positions.clear()
            account.realized_pnl = 0.0
            account.closed_trades_count = 0
            account.win_count = 0
            account.status = "active"
            # DB updates
            async with self._session_factory() as db:
                model = await db.get(PaperAccountModel, account_id)
                if model:
                    model.current_cash = ic
                    model.initial_capital = ic
                    model.status = "active"
                    model.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                # clear positions & trades
                await db.execute(
                    PaperPositionModel.__table__.delete().where(
                        PaperPositionModel.paper_account_id == account_id
                    )
                )
                await db.commit()
            return account

    async def delete_account(self, account_id: str) -> bool:
        async with self._lock:
            self._accounts.pop(account_id, None)
            async with self._session_factory() as db:
                model = await db.get(PaperAccountModel, account_id)
                if model:
                    await db.delete(model)
                    await db.commit()
                    return True
            return False

    # ── Execution ────────────────────────────────────────────────

    async def execute_signal(
        self, account_id: str, strategy_id: str,
        signal_action: str, symbol: str, price: float,
        quantity_pct: float, signal_strength: float | None = None,
    ) -> PaperExecutionResult:
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return PaperExecutionResult(False, error=f"account {account_id} not found")

            side = "buy" if signal_action in ("buy", "close_short") else "sell"

            result = await self._matcher.execute_market_order(
                account=account, symbol=symbol, side=side, action=signal_action,
                quantity_pct=quantity_pct, explicit_quantity=None,
                signal_price=price, signal_strength=signal_strength,
            )
            if result.success:
                await self._persist_trade(account_id, strategy_id, result)
                await self._persist_position(account_id, result)
                await self._update_account_db(account)
                paper_events.emit("trade_filled", {
                    "account_id": account_id,
                    "symbol": symbol,
                    "action": signal_action,
                    "price": result.trade.price if result.trade else None,
                    "pnl": result.realized_pnl_delta,
                })
            return result

    # ── Persistence ──────────────────────────────────────────────

    async def _load_all(self):
        async with self._session_factory() as db:
            models = (await db.execute(select(PaperAccountModel))).scalars().all()
            for m in models:
                acc = PaperAccount(
                    id=m.id, name=m.name, cash=m.current_cash,
                    initial_capital=m.initial_capital, fee_rate=m.fee_rate,
                    slippage_bps=m.slippage_bps, status=m.status,
                )
                # Load positions
                pos_models = (await db.execute(
                    select(PaperPositionModel).where(PaperPositionModel.paper_account_id == m.id)
                )).scalars().all()
                for p in pos_models:
                    acc.positions[p.symbol] = PaperPositionRuntime(
                        symbol=p.symbol, side=p.side, quantity=p.quantity,
                        avg_entry_price=p.avg_entry_price, realized_pnl=p.realized_pnl,
                        opened_at=p.opened_at, updated_at=p.updated_at,
                    )
                self._accounts[m.id] = acc

    async def _persist_account(self, account: PaperAccount):
        async with self._session_factory() as db:
            db.add(PaperAccountModel(
                id=account.id, name=account.name,
                initial_capital=account.initial_capital,
                current_cash=account.cash,
                fee_rate=account.fee_rate,
                slippage_bps=account.slippage_bps,
                status=account.status,
            ))
            await db.commit()

    async def _update_account_db(self, account: PaperAccount):
        async with self._session_factory() as db:
            model = await db.get(PaperAccountModel, account.id)
            if model:
                model.current_cash = account.cash
                model.updated_at = datetime.now(timezone.utc)
                await db.commit()

    async def _persist_trade(self, account_id: str, strategy_id: str, result: PaperExecutionResult):
        if not result.trade:
            return
        t = result.trade
        async with self._session_factory() as db:
            db.add(PaperTradeModel(
                paper_account_id=account_id,
                strategy_id=strategy_id,
                symbol=t.symbol, side=t.side, action=t.action,
                price=t.price, quantity=t.quantity,
                notional=t.notional, fee=t.fee, pnl=t.pnl,
                slippage_bps=t.slippage_bps,
                signal_strength=t.signal_strength,
                executed_at=t.executed_at,
            ))
            await db.commit()

    async def _persist_position(self, account_id: str, result: PaperExecutionResult):
        pos = result.position_after
        if not pos:
            # Position closed — delete from DB
            async with self._session_factory() as db:
                await db.execute(
                    PaperPositionModel.__table__.delete().where(
                        PaperPositionModel.paper_account_id == account_id
                    )
                )
                await db.commit()
            return
        async with self._session_factory() as db:
            existing = (await db.execute(
                select(PaperPositionModel).where(
                    PaperPositionModel.paper_account_id == account_id,
                    PaperPositionModel.symbol == pos.symbol,
                )
            )).scalar_one_or_none()
            if existing:
                existing.quantity = pos.quantity
                existing.avg_entry_price = pos.avg_entry_price
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db.add(PaperPositionModel(
                    paper_account_id=account_id,
                    symbol=pos.symbol, side=pos.side,
                    quantity=pos.quantity, avg_entry_price=pos.avg_entry_price,
                    realized_pnl=pos.realized_pnl,
                    opened_at=pos.opened_at,
                ))
            await db.commit()

    async def _save_snapshot(self, account_id: str):
        account = self._accounts.get(account_id)
        if not account:
            return
        # Get mark prices for all symbols
        mark_prices = await self._get_mark_prices(list(account.positions.keys()))
        snap = {
            "equity": round(account.equity(mark_prices), 4),
            "cash": account.cash,
            "positions_value": account.positions_value(mark_prices),
            "realized_pnl": account.realized_pnl,
            "unrealized_pnl": sum(
                p.unrealized_pnl(mark_prices.get(p.symbol, p.avg_entry_price))
                for p in account.positions.values()
            ),
        }
        async with self._session_factory() as db:
            db.add(PaperEquitySnapshot(
                paper_account_id=account_id, timestamp=datetime.now(timezone.utc),
                equity=snap["equity"], cash=snap["cash"],
                positions_value=snap["positions_value"],
                realized_pnl=snap["realized_pnl"],
                unrealized_pnl=round(snap["unrealized_pnl"], 4),
            ))
            await db.commit()

    async def _snapshot_loop(self):
        from app.config import settings

        interval = settings.paper_equity_snapshot_interval
        while not self._stopped:
            await asyncio.sleep(interval)
            for acc_id in list(self._accounts.keys()):
                try:
                    await self._save_snapshot(acc_id)
                except Exception as e:
                    logger.warning("Snapshot error for %s: %s", acc_id, e)
            if self._accounts:
                paper_events.emit("equity_snapshot", {
                    "accounts_count": len(self._accounts),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    async def _get_mark_prices(self, symbols: list[str]) -> dict[str, float]:
        prices: dict[str, float] = {}
        for sym in symbols:
            try:
                ticker = await self._matcher.connector.get_ticker(sym, market="spot")
                if ticker:
                    prices[sym] = float(ticker["price"])
            except Exception:
                pass
        return prices

    # ── Query helpers ─────────────────────────────────────────────

    async def get_trades(self, account_id: str, limit: int = 50) -> list[dict]:
        async with self._session_factory() as db:
            rows = (await db.execute(
                select(PaperTradeModel)
                .where(PaperTradeModel.paper_account_id == account_id)
                .order_by(PaperTradeModel.executed_at.desc())
                .limit(limit)
            )).scalars().all()
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in rows
            ]

    async def get_positions(self, account_id: str) -> list[dict]:
        async with self._session_factory() as db:
            rows = (await db.execute(
                select(PaperPositionModel)
                .where(PaperPositionModel.paper_account_id == account_id)
            )).scalars().all()
            account = self._accounts.get(account_id)
            mark_prices = await self._get_mark_prices([r.symbol for r in rows])
            result = []
            for r in rows:
                d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
                d["unrealized_pnl"] = round(
                    (1 if r.side == "long" else -1)
                    * (mark_prices.get(r.symbol, r.avg_entry_price) - r.avg_entry_price)
                    * r.quantity if r.side == "long" else
                    (r.avg_entry_price - mark_prices.get(r.symbol, r.avg_entry_price))
                    * r.quantity,
                    4,
                )
                d.pop("id", None)
                result.append(d)
            return result

    async def get_equity_snapshots(self, account_id: str, limit: int = 5000) -> list[dict]:
        async with self._session_factory() as db:
            rows = (await db.execute(
                select(PaperEquitySnapshot)
                .where(PaperEquitySnapshot.paper_account_id == account_id)
                .order_by(PaperEquitySnapshot.timestamp.asc())
                .limit(limit)
            )).scalars().all()
            return [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "equity": r.equity,
                    "cash": r.cash,
                    "positions_value": r.positions_value,
                    "realized_pnl": r.realized_pnl,
                    "unrealized_pnl": r.unrealized_pnl,
                }
                for r in rows
            ]

    async def get_metrics(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            return {}
        trades = await self.get_trades(account_id, limit=9999)
        snapshots = await self.get_equity_snapshots(account_id)
        account_dict = account.to_dict(await self._get_mark_prices(list(account.positions.keys())))
        return build_metrics(account_dict, snapshots, trades)
