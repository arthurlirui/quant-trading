"""Tests for PaperMatcher."""
from __future__ import annotations
import pytest
from app.core.paper.account import PaperAccount
from app.core.paper.matcher import PaperMatcher
from unittest.mock import AsyncMock


@pytest.fixture
def account():
    return PaperAccount(id="t1", name="test", cash=10000.0, initial_capital=10000.0,
                        fee_rate=0.001, slippage_bps=5.0)


@pytest.fixture
def matcher():
    m = PaperMatcher.__new__(PaperMatcher)
    m.connector = AsyncMock()
    m.connector.get_ticker = AsyncMock(return_value={"price": "50000.0"})
    return m


@pytest.mark.asyncio
async def test_open_long(matcher, account):
    result = await matcher.execute_market_order(
        account, "BTCUSDT", "buy", "buy", 0.5, None, 50000.0, signal_strength=0.8)
    assert result.success
    assert result.trade is not None
    assert result.trade.side == "buy"
    assert result.trade.action == "buy"
    assert result.trade.quantity > 0
    assert result.trade.quantity < 1.0
    assert result.trade.price > 50000  # slippage added for buy
    assert result.trade.fee > 0
    assert result.trade.pnl is None  # open trade
    assert result.position_after is not None
    assert result.position_after.quantity > 0
    assert result.position_after.side == "long"
    assert account.cash < 10000  # cash deducted
    expected_cost = result.trade.notional + result.trade.fee
    assert abs(account.cash - (10000 - expected_cost)) < 0.01


@pytest.mark.asyncio
async def test_close_long(matcher, account):
    await matcher.execute_market_order(account, "BTCUSDT", "buy", "buy", 0.5, None, 50000.0)
    assert "BTCUSDT" in account.positions
    m2 = PaperMatcher.__new__(PaperMatcher)
    m2.connector = AsyncMock()
    m2.connector.get_ticker = AsyncMock(return_value={"price": "51000.0"})
    result = await m2.execute_market_order(
        account, "BTCUSDT", "sell", "close_long", None, None, 51000.0, signal_strength=0.9)
    assert result.success
    assert result.trade.pnl is not None
    assert result.trade.pnl > 0
    assert result.position_after is None
    assert "BTCUSDT" not in account.positions
    assert account.closed_trades_count == 1
    assert account.win_count == 1


@pytest.mark.asyncio
async def test_insufficient_funds(matcher, account):
    account.cash = 0.0  # nothing left; notional will be 0 → fail on invalid order size
    result = await matcher.execute_market_order(
        account, "BTCUSDT", "buy", "buy", 0.9, None, 60000.0)
    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
async def test_close_no_position(matcher, account):
    result = await matcher.execute_market_order(
        account, "BTCUSDT", "sell", "close_long", None, None, 50000.0)
    assert not result.success
    assert "no position" in (result.error or "")


@pytest.mark.asyncio
async def test_multiple_adds_fifo_avg(matcher, account):
    await matcher.execute_market_order(
        account, "BTCUSDT", "buy", "buy", 0.25, None, 50000.0)
    q1 = account.positions["BTCUSDT"].quantity
    e1 = account.positions["BTCUSDT"].avg_entry_price
    m2 = PaperMatcher.__new__(PaperMatcher)
    m2.connector = AsyncMock()
    m2.connector.get_ticker = AsyncMock(return_value={"price": "55000.0"})
    await m2.execute_market_order(
        account, "BTCUSDT", "buy", "buy", 0.25, None, 55000.0)
    q2 = account.positions["BTCUSDT"].quantity
    e2 = account.positions["BTCUSDT"].avg_entry_price
    assert q2 > q1
    assert e1 < e2 < 55000