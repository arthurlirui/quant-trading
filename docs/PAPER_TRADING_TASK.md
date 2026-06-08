# 虚拟持仓（Paper Trading）模块 — 设计任务书

> 目标：在 quant-trading 系统中新增独立的 paper trading 模块，使用真实 Binance 行情对多个策略进行实盘验证，**0 资金风险**。

---

## 🎯 业务目标

1. **真实行情**：直接从 Binance 主网拉 ticker / kline / orderbook（已通过只读 API key 验证）。
2. **模拟撮合**：本地撮合引擎，按真实价格执行，但不发往交易所。
3. **多策略隔离**：每个策略实例拥有独立虚拟账户（独立现金、持仓、PnL、订单簿）。
4. **可观察**：每个虚拟账户的权益曲线、成交记录、回撤、夏普可以实时查看。
5. **与现有真实交易解耦**：paper trading 应该是一个独立模式（`mode=paper|live`），不依赖 `BINANCE_TESTNET` 开关。

---

## 📐 现状分析

- 已有 `backend/app/core/trading/executor.py` 模拟撮合逻辑，但**只在 testnet=true 时启用**，且不支持多账户。
- 已有 `Position` ORM 模型，但没有"虚拟账户"维度（缺现金、初始资金、权益、账户 id）。
- 策略层 (`core/strategies/`) 已有多种策略 (volume_surge / grid / momentum / mean_reversion / macd_rsi)。
- 行情通过 `core/exchange.py` 的 `BinanceConnector` 拉取（WebSocket + REST）。
- API 在 `main.py` 中以 `/api/v1/*` 暴露。
- 前端 Vite (port 5190)，后端 FastAPI (port 8003)。

---

## 🏗️ 架构设计要求

### 1. 新增模块 `core/paper/`

建议结构（你可以根据情况调整）：

```
backend/app/core/paper/
  __init__.py
  account.py          # PaperAccount: 单个虚拟账户
  matcher.py          # 撮合引擎：按真实行情/盘口模拟成交（市价/限价/止损）
  manager.py          # PaperAccountManager: 管理多个账户、与策略绑定
  metrics.py          # 权益曲线、Sharpe、回撤、胜率等指标计算
  events.py           # 账户事件（成交/平仓/爆仓/止损触发等）用于 WS 推送
```

### 2. 新增 ORM 模型

```python
# models/paper_account.py
class PaperAccount:
    id, name, strategy_id (nullable, 一对一或一对多), 
    initial_capital, current_cash, quote_asset (默认 USDT),
    created_at, updated_at, status (active | stopped | liquidated)

# models/paper_trade.py     —— 虚拟成交记录
class PaperTrade:
    id, paper_account_id, strategy_id, symbol, side, price, quantity, 
    fee, pnl, slippage, order_type, signal_strength, executed_at

# models/paper_position.py
class PaperPosition:
    id, paper_account_id, symbol, side (long/short),
    quantity, avg_entry_price, current_price, unrealized_pnl, realized_pnl,
    opened_at, updated_at

# models/paper_equity_snapshot.py   —— 用于画权益曲线
class PaperEquitySnapshot:
    id, paper_account_id, timestamp, equity, cash, positions_value, 
    realized_pnl, unrealized_pnl
```

### 3. 撮合引擎要点

- **市价单**：用最近一次 ticker 价 + 可配置 slippage（默认 0.05%）撮合
- **限价单**：维护订单簿，当真实行情穿越限价时触发成交
- **止损/止盈**：实时监听行情，触发后转市价成交
- **手续费**：默认 0.1%（Binance spot maker/taker，可在账户配置）
- **滑点模型**：可选固定 bps 或基于盘口深度
- **保证金/杠杆**：先支持现货（不需要保证金）；合约阶段可以是 Phase 2

### 4. 多策略隔离

- 每个策略 instance 在启动时可以**选择绑定**：
  - `mode=live` → 真实下单（原 executor）
  - `mode=paper` → 走 paper trading manager
- Manager 支持：
  - 创建账户 `POST /api/v1/paper/accounts {name, initial_capital, fee_rate, slippage_bps}`
  - 绑定策略到账户
  - 一个策略 ↔ 一个账户（强约束），便于隔离

### 5. 接口（REST）

最少需要：

```
POST   /api/v1/paper/accounts                  # 创建虚拟账户
GET    /api/v1/paper/accounts                  # 列出所有
GET    /api/v1/paper/accounts/{id}             # 详情（含权益、PnL）
DELETE /api/v1/paper/accounts/{id}             # 删除/停用
POST   /api/v1/paper/accounts/{id}/reset       # 重置回初始资金

GET    /api/v1/paper/accounts/{id}/trades      # 成交历史
GET    /api/v1/paper/accounts/{id}/positions   # 当前持仓
GET    /api/v1/paper/accounts/{id}/equity      # 权益曲线（time series）
GET    /api/v1/paper/accounts/{id}/metrics     # Sharpe / 回撤 / 胜率 / PnL

POST   /api/v1/strategies/{sid}/bind-paper-account
       Body: {paper_account_id}                # 绑定策略
```

### 6. WebSocket 推送

扩展现有 `/ws`（或新开 `/ws/paper/{account_id}`），实时推送：
- `paper_trade_filled` 事件
- `paper_position_update` 事件
- `paper_equity_update` 事件（节流，比如每 5 秒一次）

### 7. 配置

在 `app/config.py` 中加：

```python
paper_default_capital: float = 10000.0
paper_default_fee_rate: float = 0.001       # 0.1%
paper_default_slippage_bps: float = 5       # 0.05%
paper_equity_snapshot_interval: int = 60    # 秒
```

---

## ✅ 验收标准

1. **能创建 N 个虚拟账户**，各自独立资金/持仓/历史
2. **同一策略可以一键 paper trade**，不影响真实账户
3. **可同时跑多个策略**（绑到不同账户），互不串
4. **真实行情驱动**：成交价跟当时市价匹配（带可配滑点）
5. **指标正确**：手动算几个交易后核对 PnL / 回撤 / Sharpe 与系统计算一致
6. **重启不丢数据**：账户、持仓、成交、权益快照全部入库
7. **前端 dashboard 至少有一个 paper accounts 列表页**（可选 Phase 2，最低先有 REST）

---

## 🛠️ 实现建议

### Phase 1（核心）
- [ ] 4 个新 ORM 模型 + alembic / create_tables 迁移
- [ ] `PaperAccount` 类（持仓管理、现金管理、PnL 计算）
- [ ] `PaperMatcher`（市价 + 限价，使用 `core/exchange.py` 的 ticker 价格）
- [ ] `PaperAccountManager`（多账户 + 策略绑定，单例）
- [ ] REST endpoints
- [ ] 修改 `main.py`：策略启动时按 `mode` 路由到 paper 或 live
- [ ] 后台权益快照任务（每 60s 一次）
- [ ] 单元测试覆盖核心撮合 + PnL 计算

### Phase 2（增强）
- [ ] 止损/止盈订单类型
- [ ] 前端 dashboard：账户列表、权益曲线、成交记录表格
- [ ] WebSocket 实时推送
- [ ] 合约 / 杠杆支持
- [ ] CSV 导出 / 报表

---

## 📦 输出要求

1. **代码**：在 `feat/paper-trading` 分支上提交，commit 信息清晰，按逻辑分多次 commit
2. **测试**：`backend/tests/test_paper_*.py` 至少覆盖撮合、PnL、多账户隔离
3. **文档**：`docs/PAPER_TRADING.md` 说明用法、API、示例
4. **示例**：一个 quickstart 脚本，演示"创建账户 → 启动策略 → 看 PnL"
5. **不要破坏现有功能**：所有现存测试 / 回测引擎 / 实盘 executor 必须仍可用

---

## ⚠️ 注意事项

1. **不要修改 `BINANCE_TESTNET` 的语义**——这是真实交易开关，paper trading 应该有独立开关。
2. **不要往 `executor.py` 里硬塞**——新建独立模块。
3. **行情来源**：复用 `core/exchange.py:connector`，不要重新写 Binance client。
4. **数据库**：sqlite (`quant_trading.db`)，使用现有 `app.db.async_session_factory`。
5. **设计先行**：开始编码前，先在 `docs/PAPER_TRADING_DESIGN.md` 输出你的设计稿（数据模型 + 类图 + 时序图描述），让用户 review 后再实现。

---

## 🚦 启动后第一步

1. 阅读现有代码（重点：`core/trading/executor.py`, `core/strategies/base.py`, `models/`, `main.py` 中策略生命周期相关部分）
2. 在 `docs/PAPER_TRADING_DESIGN.md` 写出设计稿
3. 等待用户 review 通过后再开始编码

完成每个 Phase 后告知用户进度，并展示关键改动 diff / 测试结果。
