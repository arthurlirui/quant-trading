# Paper Trading 模块 — 设计稿

> **状态**：草案 v1，等待 review。
> **依赖**：`PAPER_TRADING_TASK.md` 任务书。
> **目标分支**：`feat/paper-trading`。

---

## 1. 整体思路

Paper trading 是一个**独立模块** `app/core/paper/`，与现有 `app/core/trading/executor.py`（实盘 executor）平行。
通过策略启动时的 `mode` 字段路由：

```
                 ┌──────────────────┐
strategy.signal ─┤  signal handler  ├─ mode=live  ─► executor.execute_signal()
                 │   (main.py)      │
                 └──────────────────┘
                          │
                          └────────── mode=paper ─► paper_manager.execute_signal()
                                                     │
                                                     ▼
                                              PaperAccount.matcher
                                                     │
                                                     ▼
                                          PaperTrade + PaperPosition + 权益快照
```

**关键不变量**：
- `BINANCE_TESTNET` 语义不动（继续是 executor.simulate 的开关）
- paper trading 完全用真实 mainnet 行情（已有 `connector` 是 mainnet）
- 一个策略 = 一个 mode = 一个账户绑定（强一致）

---

## 2. 数据模型

新增 4 张表（SQLAlchemy declarative，复用 `app.db.Base`）。

### 2.1 `paper_accounts`

```python
class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: str = Column(String, primary_key=True)          # uuid4
    name: str = Column(String, nullable=False)          # 用户友好名称
    initial_capital: float = Column(Float, nullable=False)
    current_cash: float = Column(Float, nullable=False) # 可用现金 (quote 币)
    quote_asset: str = Column(String, default="USDT")
    fee_rate: float = Column(Float, default=0.001)      # 0.1%
    slippage_bps: float = Column(Float, default=5.0)    # 0.05%
    status: str = Column(String, default="active")      # active|stopped|liquidated
    created_at: datetime
    updated_at: datetime
```

### 2.2 `paper_trades`

```python
class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: int = Column(Integer, primary_key=True, autoincrement=True)
    paper_account_id: str = Column(String, ForeignKey, index=True)
    strategy_id: str = Column(String, index=True)
    symbol: str
    side: str                                            # buy | sell
    action: str                                          # buy|sell|close_long|close_short
    price: float                                         # 实际成交价 (含滑点)
    quantity: float                                      # base 币数量
    notional: float                                      # = price * quantity
    fee: float
    pnl: float | None                                    # 平仓时填
    slippage_bps: float
    signal_strength: float | None
    executed_at: datetime
```

### 2.3 `paper_positions`

```python
class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: int = Column(Integer, primary_key=True, autoincrement=True)
    paper_account_id: str = Column(String, ForeignKey, index=True)
    symbol: str = Column(String, index=True)
    side: str                                            # long | short
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0
    opened_at: datetime
    updated_at: datetime
    # 当前价 / 未实现 PnL 不存库, 取查询时算
    # UNIQUE(paper_account_id, symbol, side)
```

> **注**：Phase 1 现货，所以 side 只用 `long`。`short` 留给 Phase 2 futures。

### 2.4 `paper_equity_snapshots`

```python
class PaperEquitySnapshot(Base):
    __tablename__ = "paper_equity_snapshots"
    id: int = Column(Integer, primary_key=True, autoincrement=True)
    paper_account_id: str = Column(String, ForeignKey, index=True)
    timestamp: datetime = Column(DateTime, index=True)
    equity: float                                        # = cash + positions_value
    cash: float
    positions_value: float                               # mark-to-market
    realized_pnl: float                                  # 累计已实现
    unrealized_pnl: float                                # 当前未实现
```

### 2.5 复用现有

- `strategies` 表新增列：`mode: str` 默认 `"live"`（`live | paper`），`paper_account_id: str | None`
- 通过 `db.merge` 在 start 时设置

---

## 3. 模块结构

```
backend/app/core/paper/
  __init__.py             # 导出 manager 单例
  account.py              # PaperAccount runtime 对象 (区别于 ORM)
  matcher.py              # PaperMatcher: 撮合引擎
  manager.py              # PaperAccountManager: 多账户调度
  metrics.py              # 权益/PnL/Sharpe/MaxDD 计算
  events.py               # 事件总线 (供 WS 推送)
```

---

## 4. 运行时对象设计

### 4.1 `account.py`

```python
@dataclass
class PaperPositionRuntime:
    symbol: str
    side: str                # long | short
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0
    opened_at: datetime
    updated_at: datetime

    def unrealized_pnl(self, mark_price: float) -> float:
        if self.side == "long":
            return (mark_price - self.avg_entry_price) * self.quantity
        return (self.avg_entry_price - mark_price) * self.quantity

@dataclass
class PaperAccount:
    id: str
    name: str
    cash: float
    initial_capital: float
    fee_rate: float
    slippage_bps: float
    positions: dict[str, PaperPositionRuntime]   # key = symbol, 现货只一条 (long)
    realized_pnl: float = 0.0
    closed_trades_count: int = 0
    win_count: int = 0

    def equity(self, mark_prices: dict[str, float]) -> float:
        pos_val = sum(
            p.quantity * mark_prices.get(p.symbol, p.avg_entry_price)
            for p in self.positions.values()
        )
        return self.cash + pos_val - sum(p.quantity * p.avg_entry_price for p in self.positions.values())

    def can_afford(self, notional: float) -> bool:
        return self.cash >= notional

    def to_dict(self) -> dict:
        return { ... }
```

### 4.2 `matcher.py`

```python
@dataclass
class PaperTradeRuntime:
    symbol: str; side: str; action: str
    price: float; quantity: float; notional: float
    fee: float; pnl: float | None
    slippage_bps: float; signal_strength: float | None
    executed_at: datetime

@dataclass
class PaperExecutionResult:
    success: bool
    trade: PaperTradeRuntime | None
    position_after: PaperPositionRuntime | None
    cash_after: float
    realized_pnl_delta: float
    error: str | None = None

class PaperMatcher:
    def __init__(self, connector):
        self.connector = connector

    async def execute_market_order(
        self, account: PaperAccount,
        symbol: str, side: str, action: str,
        quantity_pct: float | None, explicit_quantity: float | None,
        signal_price: float,
    ) -> PaperExecutionResult:
        # 1) 取 ticker（优先 realtime，fallback signal_price）
        ticker = await self.connector.get_ticker(symbol)
        mark_price = float(ticker.get("price", signal_price))

        # 2) 滑点
        slippage = mark_price * (account.slippage_bps / 10000)
        fill_price = mark_price + slippage if side == "buy" else mark_price - slippage

        # 3) 计算数量
        fee_rate = account.fee_rate
        is_close = action in ("close_long", "close_short")

        if is_close:
            pos = account.positions.get(symbol)
            if not pos or pos.quantity == 0:
                return PaperExecutionResult(False, error="no position to close")
            qty = pos.quantity
            # Clear position
            close_value = qty * fill_price
            fee = close_value * fee_rate
            # PnL
            if pos.side == "long":
                pnl = (fill_price - pos.avg_entry_price) * qty
            else:
                pnl = (pos.avg_entry_price - fill_price) * qty
            pnl_net = pnl - fee
            account.cash += qty * fill_price - fee
            account.realized_pnl += pnl_net
            account.closed_trades_count += 1
            if pnl_net > 0: account.win_count += 1
            del account.positions[symbol]
            return PaperExecutionResult(success=True, trade=..., position_after=None, ...)

        else:
            # Open trade
            total_cash = account.cash
            if quantity_pct:
                notional = total_cash * quantity_pct
            else:
                notional = total_cash * 0.5  # default 50%
            qty = notional / fill_price
            if not account.can_afford(notional):
                return PaperExecutionResult(False, error="insufficient funds")
            fee = notional * fee_rate
            account.cash -= (notional + fee)
            # Update position (increase or create)
            pos = account.positions.get(symbol)
            if pos and pos.side == side:
                # Increase: avg entry
                total_cost = pos.avg_entry_price * pos.quantity + fill_price * qty
                pos.quantity += qty
                pos.avg_entry_price = total_cost / pos.quantity
            else:
                account.positions[symbol] = PaperPositionRuntime(
                    symbol=symbol, side="long", quantity=qty,
                    avg_entry_price=fill_price, opened_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            return PaperExecutionResult(success=True, trade=..., position_after=..., ...)
```

### 4.3 `manager.py`

```python
class PaperAccountManager:
    def __init__(self, session_factory, connector):
        self._sessions = session_factory
        self._matcher = PaperMatcher(connector)
        self._accounts: dict[str, PaperAccount] = {}
        self._lock = asyncio.Lock()
        self._snapshot_task: asyncio.Task | None = None

    async def start(self):
        await self._load_all()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    async def stop(self):
        if self._snapshot_task:
            self._snapshot_task.cancel()

    async def create_account(self, name: str, initial_capital: float = 10000.0,
                             fee_rate: float = 0.001, slippage_bps: float = 5.0) -> PaperAccount:
        acc_id = str(uuid4())
        account = PaperAccount(id=acc_id, name=name, cash=initial_capital,
                               initial_capital=initial_capital, fee_rate=fee_rate,
                               slippage_bps=slippage_bps)
        self._accounts[acc_id] = account
        await self._persist_account(account)
        return account

    async def execute_signal(self, account_id: str, strategy_id: str,
                             signal_action: str, symbol: str, price: float,
                             quantity_pct: float) -> PaperExecutionResult:
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                return PaperExecutionResult(False, error="account not found")
            result = await self._matcher.execute_market_order(
                account, symbol=symbol,
                side=("buy" if signal_action in ("buy", "close_short") else "sell"),
                action=signal_action,
                quantity_pct=quantity_pct, explicit_quantity=None, signal_price=price,
            )
            if result.success:
                await self._persist_trade(account_id, strategy_id, result)
                await self._save_account(account)
                paper_events.emit("trade_filled", {"account_id": account_id, ...})
            return result

    # ... 辅助方法: _load_all, _persist_account, _persist_trade, _snapshot_loop, _get_mark_prices
```

### 4.4 `metrics.py`

```python
def calc_sharpe(snapshots: list[dict], periods_per_year: int = 525600) -> float:
    if len(snapshots) < 2: return 0.0
    returns = [
        (s["equity"] / snapshots[i-1]["equity"]) - 1
        for i, s in enumerate(snapshots) if s["equity"] > 0 and snapshots[i-1]["equity"] > 0
    ]
    if not returns: return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r)**2 for r in returns) / len(returns)
    if var_r == 0: return 0.0
    std_r = var_r**0.5
    return (mean_r / std_r) * (periods_per_year**0.5) if std_r > 0 else 0.0

def calc_max_drawdown(snapshots: list[dict]) -> float:
    if not snapshots: return 0.0
    peak = snapshots[0]["equity"]; mdd = 0.0
    for s in snapshots:
        eq = s["equity"]
        if eq > peak: peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > mdd: mdd = dd
    return mdd

def calc_win_rate(trades: list[dict]) -> tuple[float, int, int]:
    wins = sum(1 for t in trades if t["pnl"] and t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] and t["pnl"] <= 0)
    total = wins + losses
    return (wins / total if total > 0 else 0.0, wins, losses)

def calc_profit_factor(trades: list[dict]) -> float:
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] and t["pnl"] > 0)
    gross_loss = sum(abs(t["pnl"]) for t in trades if t["pnl"] and t["pnl"] < 0)
    return gross_win / gross_loss if gross_loss > 0 else 0.0
```

### 4.5 `events.py`

```python
class _PaperEventBus:
    def __init__(self):
        self._listeners: list[Callable] = []
    def on(self, cb):
        self._listeners.append(cb)
    def emit(self, kind: str, payload: dict):
        for cb in self._listeners:
            try: cb(kind, payload)
            except: ...

paper_events = _PaperEventBus()
```

`main.py` WS handler 在 loop 末尾注册 listener，事件广播到 `_ws_clients`。

---

## 5. REST API 设计

### 5.1 Paper accounts

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/api/v1/paper/accounts` | `{name, initial_capital?, fee_rate?, slippage_bps?}` | account |
| GET | `/api/v1/paper/accounts` | - | account[] |
| GET | `/api/v1/paper/accounts/{id}` | - | account detail (含 equity) |
| DELETE | `/api/v1/paper/accounts/{id}` | - | ok |
| POST | `/api/v1/paper/accounts/{id}/reset` | `{initial_capital?}` | account (重置到初始) |

### 5.2 Paper trades / positions / equity

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/v1/paper/accounts/{id}/trades` | trade[] (最新 N 条, 按时间 desc) |
| GET | `/api/v1/paper/accounts/{id}/positions` | position[] (当前 open) |
| GET | `/api/v1/paper/accounts/{id}/equity` | snapshot[] (时间序列) |
| GET | `/api/v1/paper/accounts/{id}/metrics` | {total_pnl, sharpe, max_dd, win_rate, ...} |

### 5.3 Strategy binding

| Method | Path | Body | Notes |
|--------|------|------|-------|
| POST | `/api/v1/strategies/{sid}/bind-paper-account` | `{paper_account_id}` | 设置 strategy.mode=paper + paper_account_id |

---

## 6. 对 main.py 的修改

### 6.1 startup 变化

```python
@app.on_event("startup")
async def startup():
    ...
    paper_manager = PaperAccountManager(async_session_factory, connector)
    await paper_manager.start()         # 加载账户 + 启动快照循环
```

### 6.2 signal handler 变化

在 `on_kline` 中现在的 `executor.execute_signal(...)` 附近加分支：

```python
# 查询策略 mode
strategy_config = strategies.get()      # 在 _active_strategies 层维护
mode = strategy_config.mode             # "live" | "paper"

if mode == "live":
    result = await executor.execute_signal(...)
    ...  # 现有逻辑不变
elif mode == "paper":
    account_id = strategy_config.paper_account_id
    result = await paper_manager.execute_signal(
        account_id=account_id, strategy_id=db_id,
        signal_action=signal.action, symbol=symbol,
        price=signal.price, quantity_pct=signal.quantity_pct,
    )
    if result.success:
        # 更新策略仓位
        if result.position_after:
            strategy.update_position(signal.action, result.position_after.avg_entry_price,
                                     data.get("open_time", 0), result.position_after.quantity,
                                     pnl=result.trade.pnl if result.trade else 0.0)
        else:
            strategy.update_position("close", 0, 0, 0, pnl=result.realized_pnl_delta)
        logger.info("[Paper] %s %s %s @ %.2f ✅", symbol, signal.action, mrkt, signal.price)
```

---

## 7. 配置

```python
# app/config.py 新增
paper_default_capital: float = 10000.0
paper_default_fee_rate: float = 0.001
paper_default_slippage_bps: float = 5.0
paper_equity_snapshot_interval: int = 60  # 秒
```

---

## 8. 测试

### Phase 1 测试覆盖

1. **`tests/test_paper_matcher.py`**
   - 市价开仓 → 验证扣款、产生 trade、更新 position
   - 市价平仓 → 验证 PnL、现金恢复、position 消失
   - 资金不足 → 验证失败返回
   - 多次加仓 → 验证 avg_entry 加权平均
   - 滑点 + 手续费 → 验证数字正确

2. **`tests/test_paper_manager.py`**
   - 创建多个账户 → 隔离性：一个账户的交易不影响另一个
   - 重置 → 回到初始

3. **`tests/test_paper_metrics.py`**
   - 输入已知快照序列 → 验证 Sharpe / MDD 正确

---

## 9. 实现顺序 (4 ~ 6 个 commit)

| # | Commit | 内容 |
|---|--------|------|
| 1 | feat(models): add PaperAccount/PaperTrade/PaperPosition/PaperEquitySnapshot ORM | 4 模型 + 建表 + strategy 表加 mode/paper_account_id 列 |
| 2 | feat(core): PaperAccount + PaperMatcher + PaperAccountManager | account.py / matcher.py / manager.py / events.py / metrics.py |
| 3 | feat(api): paper REST endpoints | 所有 API routes + 信号路由改造 |
| 4 | feat(tools): example paper trading quickstart | `tools/paper_demo.py` 演示流程 + test 文件 (3 个) |
| 5 | docs: paper trading usage doc | `docs/PAPER_TRADING.md` API 文档 + 示例 |

---

## 10. 验收检查清单

- [ ] 创建 2 个虚拟账户，各自 10000 USDT / 5000 USDT
- [ ] 同一策略绑定到账户 1（mode=paper），不影响真实账户
- [ ] 两个不同策略各自绑到不同账户，互不串
- [ ] 成交价 = 行情价 ± 滑点（可配）
- [ ] 手动计算 2~3 笔交易的 PnL = 系统输出
- [ ] 重启后账户/持仓/交易/权益快照恢复
- [ ] 所有现有功能（回测 / 实盘 executor）仍可用
- [ ] 测试通过
