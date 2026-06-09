#!/usr/bin/env python3
"""
Paper Trading Quickstart Demo.

Shows: create accounts → bind strategy → check state → start (paper mode)

Usage:
  python tools/paper_demo.py [--api http://localhost:8003]
"""
from __future__ import annotations

import sys
import httpx


def main(api: str = "http://localhost:8003"):
    client = httpx.Client(base_url=api, timeout=5)

    print("=" * 60)
    print("📊 Paper Trading Demo")
    print("=" * 60)

    # 1. Create two accounts
    a1 = client.post("/api/v1/paper/accounts", json={
        "name": "BTC Momentum Paper",
        "initial_capital": 10000,
    }).raise_for_status().json()
    a2 = client.post("/api/v1/paper/accounts", json={
        "name": "ETH Grid Paper",
        "initial_capital": 5000,
    }).raise_for_status().json()
    print(f"\n✅ Account 1: {a1['name']} [{a1['id'][:8]}] equity={a1['equity']}")
    print(f"✅ Account 2: {a2['name']} [{a2['id'][:8]}] equity={a2['equity']}")

    # 2. List strategies
    strategies = client.get("/api/v1/strategies").raise_for_status().json()
    sid = None
    if strategies:
        sid = strategies[0]["id"]
        print(f"\n🔗 Binding strategy '{strategies[0]['name']}' → Account 1...")
        r = client.post(f"/api/v1/strategies/{sid}/bind-paper-account",
                        json={"paper_account_id": a1["id"]}).raise_for_status().json()
        print(f"   Mode: {r['mode']}, PaperAccount: {r['paper_account_id'][:8]}")
    else:
        print("\n⚠️  No strategies in DB. Create one via POST /api/v1/strategies first.")

    # 3. Fetch account detail
    acc = client.get(f"/api/v1/paper/accounts/{a1['id']}").raise_for_status().json()
    print(f"\n💰 Account 1 detail:")
    print(f"   Cash: {acc['cash']:.2f} USDT")
    print(f"   Equity: {acc['equity']:.2f} USDT")
    print(f"   Open Positions: {acc['open_positions']}")
    print(f"   Realized PnL: {acc['realized_pnl']:.4f}")

    # 4. Metrics
    metrics = client.get(f"/api/v1/paper/accounts/{a1['id']}/metrics").raise_for_status().json()
    print(f"\n📈 Metrics (no trades yet):")
    print(f"   Total PnL: {metrics['total_pnl']}")
    print(f"   Return: {metrics['return_pct']}%")
    print(f"   Sharpe: {metrics['sharpe']}")
    print(f"   MaxDD: {metrics['max_drawdown_pct']}%")
    print(f"   Win rate: {metrics['win_rate']}")

    # 5. Start strategy in paper mode
    if sid:
        print(f"\n▶️  Starting strategy {sid[:8]} in paper mode...")
        r = client.post(f"/api/v1/strategies/{sid}/start", json={
            "mode": "paper",
            "paper_account_id": a1["id"],
        }).raise_for_status().json()
        print(f"   {r}")

    print("\n" + "=" * 60)
    print("✅ Demo complete. Wait for signals, then check:")
    print(f"   GET /api/v1/paper/accounts/{a1['id'][:8]}.../trades")
    print(f"   GET /api/v1/paper/accounts/{a1['id'][:8]}.../metrics")
    print("=" * 60)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8003"
    main(url)