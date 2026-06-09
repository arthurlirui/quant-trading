"""Paper trading performance metrics."""
from __future__ import annotations

from typing import Any


def calc_sharpe(snapshots: list[dict], periods_per_year: int = 525600) -> float:
    """Annualized Sharpe ratio from equity snapshot time series (minute-level default)."""
    if len(snapshots) < 2:
        return 0.0
    returns = []
    for i in range(1, len(snapshots)):
        prev_eq = snapshots[i - 1].get("equity", 0)
        cur_eq = snapshots[i].get("equity", 0)
        if prev_eq > 0:
            returns.append((cur_eq / prev_eq) - 1)
    if not returns:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / n
    if var_r == 0:
        return 0.0
    std_r = var_r ** 0.5
    return (mean_r / std_r) * (periods_per_year ** 0.5) if std_r > 0 else 0.0


def calc_max_drawdown(snapshots: list[dict]) -> dict:
    """Maximum drawdown and its duration info."""
    if not snapshots:
        return {"max_drawdown_pct": 0.0, "drawdown_start": None, "drawdown_end": None}
    peak = snapshots[0].get("equity", 0)
    mdd = 0.0
    peak_idx = 0
    mdd_start_idx = 0
    mdd_end_idx = 0
    current_dd_start = 0

    for i, s in enumerate(snapshots):
        eq = s.get("equity", 0)
        if eq > peak:
            peak = eq
            peak_idx = i
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd
            mdd_start_idx = current_dd_start if current_dd_start > 0 else peak_idx
            mdd_end_idx = i
        # track start
        if dd > 0.01 and current_dd_start == 0:
            current_dd_start = i
        elif dd <= 0.01:
            current_dd_start = 0

    return {
        "max_drawdown_pct": round(mdd * 100, 2),
        "drawdown_start": snapshots[mdd_start_idx]["timestamp"] if mdd > 0 else None,
        "drawdown_end": snapshots[mdd_end_idx]["timestamp"] if mdd > 0 else None,
    }


def calc_win_rate(trades: list[dict]) -> tuple[float, int, int]:
    """(rate, wins, losses)"""
    wins = sum(1 for t in trades if t.get("pnl") and t["pnl"] > 0)
    losses = sum(1 for t in trades if t.get("pnl") and t["pnl"] <= 0)
    total = wins + losses
    return (wins / total if total > 0 else 0.0, wins, losses)


def calc_profit_factor(trades: list[dict]) -> float:
    gross_win = sum(t["pnl"] for t in trades if t.get("pnl") and t["pnl"] > 0)
    gross_loss = sum(abs(t["pnl"]) for t in trades if t.get("pnl") and t["pnl"] < 0)
    return round(gross_win / gross_loss, 4) if gross_loss > 0 else 0.0


def calc_avg_pnl(trades: list[dict]) -> dict:
    wins = [t["pnl"] for t in trades if t.get("pnl") and t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t.get("pnl") and t["pnl"] < 0]
    return {
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "total_trades": len(trades),
    }


def build_metrics(account: dict, snapshots: list[dict], trades: list[dict]) -> dict:
    """Compute full metrics from account/snapshots/trade dicts."""
    mdd_info = calc_max_drawdown(snapshots)
    win_rate, wins, losses = calc_win_rate(trades)
    return {
        "total_pnl": round(account.get("realized_pnl", 0) + account.get("unrealized_pnl", 0), 4),
        "realized_pnl": round(account.get("realized_pnl", 0), 4),
        "unrealized_pnl": round(account.get("unrealized_pnl", 0), 4),
        "equity": round(account.get("equity", 0), 4),
        "cash": round(account.get("cash", 0), 4),
        "return_pct": round(
            (account.get("equity", 0) - account.get("initial_capital", 0))
            / max(account.get("initial_capital", 1), 1) * 100, 2,
        ),
        "sharpe": round(calc_sharpe(snapshots), 4),
        "max_drawdown_pct": mdd_info["max_drawdown_pct"],
        "win_rate": round(win_rate, 4),
        "wins": wins,
        "losses": losses,
        "profit_factor": round(calc_profit_factor(trades), 4),
        **calc_avg_pnl(trades),
    }
