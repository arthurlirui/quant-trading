"""Tests for PaperAccountManager."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.paper.manager import PaperAccountManager


def _mock_session_factory():
    """Mock async_sessionmaker that returns context-manager mock sessions."""
    sf = MagicMock()
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.merge = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)
    # context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    sf.return_value = ctx
    return sf


@pytest.mark.asyncio
async def test_create_account_starts_with_correct_capital():
    sf = _mock_session_factory()
    manager = PaperAccountManager(sf, AsyncMock())
    acc = await manager.create_account("test", 5000.0, 0.002, 10.0)
    assert acc.name == "test"
    assert acc.initial_capital == 5000.0
    assert acc.cash == 5000.0
    assert acc.fee_rate == 0.002
    assert acc.slippage_bps == 10.0
    assert acc.id is not None
    assert acc.id in manager._accounts


@pytest.mark.asyncio
async def test_multi_account_isolation():
    sf = _mock_session_factory()
    manager = PaperAccountManager(sf, AsyncMock())
    a1 = await manager.create_account("A", 10000.0)
    a2 = await manager.create_account("B", 5000.0)
    assert a1.cash == 10000.0
    assert a2.cash == 5000.0
    assert a1.id != a2.id


@pytest.mark.asyncio
async def test_reset_account():
    sf = _mock_session_factory()
    manager = PaperAccountManager(sf, AsyncMock())
    acc = await manager.create_account("resetme", 10000.0)
    acc.cash = 2000.0
    acc.realized_pnl = -8000.0
    restored = await manager.reset_account(acc.id)
    assert restored is not None
    assert restored.cash == 10000.0
    assert restored.realized_pnl == 0.0
    assert len(restored.positions) == 0