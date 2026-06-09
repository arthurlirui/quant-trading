"""Tests for paper trading metrics."""
import pytest
from app.core.paper.metrics import (
    calc_sharpe, calc_max_drawdown, calc_win_rate,
    calc_profit_factor, calc_avg_pnl, build_metrics,
)


def test_sharpe_no_snapshots():
    assert calc_sharpe([]) == 0.0
    assert calc_sharpe([{"equity": 1000}]) == 0.0


def test_sharpe_constant_equity():
    s = [{"equity": 1000} for _ in range(10)]
    assert calc_sharpe(s, 1) == 0.0


def test_sharpe_positive():
    # Use varying returns (so variance > 0) but mostly positive
    import random
    random.seed(42)
    s = []
    eq = 1000.0
    for _ in range(200):
        eq *= 1 + (random.gauss(0.001, 0.0005))  # mean 0.1%/period, std 0.05%
        s.append({"equity": eq})
    sharpe = calc_sharpe(s, 525600)
    assert sharpe > 0


def test_max_drawdown_no_snapshots():
    assert calc_max_drawdown([])["max_drawdown_pct"] == 0.0


def test_max_drawdown_simple():
    s = [
        {"equity": 100, "timestamp": "t1"},
        {"equity": 120, "timestamp": "t2"},
        {"equity": 90, "timestamp": "t3"},
        {"equity": 100, "timestamp": "t4"},
    ]
    dd = calc_max_drawdown(s)
    assert dd["max_drawdown_pct"] == pytest.approx(25.0, abs=0.1)


def test_win_rate_empty():
    rate, wins, losses = calc_win_rate([])
    assert rate == 0.0
    assert wins == 0
    assert losses == 0


def test_win_rate_mixed():
    trades = [{"pnl": 50}, {"pnl": -30}, {"pnl": 20}, {"pnl": -10}, {"pnl": 5}]
    rate, wins, losses = calc_win_rate(trades)
    assert wins == 3
    assert losses == 2
    assert rate == 3 / 5


def test_profit_factor():
    trades = [{"pnl": 100}, {"pnl": -40}, {"pnl": 60}, {"pnl": -10}]
    pf = calc_profit_factor(trades)
    assert pf == pytest.approx((100 + 60) / (40 + 10), rel=0.01)


def test_avg_pnl():
    trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 30}, {"pnl": -20}]
    avg = calc_avg_pnl(trades)
    assert avg["avg_win"] == (100 + 30) / 2
    assert avg["avg_loss"] == (-50 + -20) / 2
    assert avg["total_trades"] == 4


def test_build_metrics_empty():
    acc = {"realized_pnl": 0, "unrealized_pnl": 0, "equity": 1000, "cash": 1000, "initial_capital": 1000}
    m = build_metrics(acc, [], [])
    assert m["sharpe"] == 0.0
    assert m["win_rate"] == 0.0
    assert m["return_pct"] == 0.0