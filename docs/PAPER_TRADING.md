# Paper Trading 用户文档

> **零资金风险** — 用真实 Binance 行情对策略做实盘验证。

---

## 🎯 什么是 Paper Trading

Paper Trading（纸面交易/模拟交易）是一种交易系统中的特殊模式：

- **行情真实**：撮合价格来自 Binance mainnet 的最新 ticker（已配置只读 API key）
- **资金虚拟**：你设定的初始资金不是真钱，盈亏只在数据库里
- **行为真实**：策略产生的信号会和真实交易一样被"成交"，但订单不发往交易所
- **多策略隔离**：每个策略实例绑定到一个独立的虚拟账户，资金/持仓/盈亏完全隔离

适用场景：
- 实盘上线前的策略验证
- 多策略并行对比
- 在不同参数下跑同一策略
- 验证策略代码改动是否会"翻车"

---

## 🏗️ 架构总览

```
                ┌─────────────────┐
strategy.signal ┤ signal handler  ├─── mode=live  ──► executor.execute_signal()  (真实下单)
                │   (main.py)     │
                └─────────────────┘
                         │
                         └────────── mode=paper ──► paper_manager.execute_signal()
                                                     │
                                                     ▼
                                              PaperMatcher (用真实行情撮合)
                                                     │
                                                     ▼
                                          PaperTrade + PaperPosition + 权益快照
```

**关键点**：
- `BINANCE_TESTNET` 开关**只影响真实 executor 的 simulate 模式**，与 paper trading 无关
- Paper trading **始终使用 mainnet 行情**
- 策略表新增 `mode` 和 `paper_account_id` 列，启动时决定路由方向

---

## 📦 模块组成

```
backend/app/core/paper/
  ├─ account.py      # PaperAccount 运行时对象, 持仓 PaperPositionRuntime
  ├─ matcher.py      # PaperMatcher: 市价单 + 固定 bps 滑点撮合
  ├─ manager.py      # PaperAccountManager: CRUD + 60s 权益快照后台任务
  ├─ metrics.py      # Sharpe / 最大回撤 / 胜率 / 盈亏比 等
  └─ events.py       # 进程内事件总线 (用于 WS 推送)

backend/app/models/
  ├─ paper_account.py
  ├─ paper_trade.py
  ├─ paper_position.py
  └─ paper_equity_snapshot.py
```

---

## 🚀 快速上手

### 0. 启动后端（确认服务在 :8003）

```bash
cd backend
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8003
```

### 1. 创建一个虚拟账户

```bash
curl -X POST http://localhost:8003/api/v1/paper/accounts \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "BTC 动量策略验证",
    "initial_capital": 10000,
    "fee_rate": 0.001,
    "slippage_bps": 5
  }'
```

返回：
```json
{
  "id": "ad98b876-962d-4bba-b688-eed49fd8e5b2",
  "name": "BTC 动量策略验证",
  "cash": 10000,
  "initial_capital": 10000,
  "equity": 10000
}
```

### 2. 绑定策略到账户

```bash
curl -X POST http://localhost:8003/api/v1/strategies/<STRATEGY_ID>/bind-paper-account \
  -H 'Content-Type: application/json' \
  -d '{"paper_account_id": "ad98b876-..."}'
```

### 3. 以 paper 模式启动策略

```bash
curl -X POST http://localhost:8003/api/v1/strategies/<STRATEGY_ID>/start \
  -H 'Content-Type: application/json' \
  -d '{
    "mode": "paper",
    "paper_account_id": "ad98b876-..."
  }'
```

### 4. 等几个 K 线，然后看结果

```bash
# 实时账户状态
curl http://localhost:8003/api/v1/paper/accounts/<ID>

# 最近成交
curl http://localhost:8003/api/v1/paper/accounts/<ID>/trades?limit=20

# 当前持仓
curl http://localhost:8003/api/v1/paper/accounts/<ID>/positions

# 权益曲线（每 60s 一个点）
curl http://localhost:8003/api/v1/paper/accounts/<ID>/equity

# 综合指标
curl http://localhost:8003/api/v1/paper/accounts/<ID>/metrics
```

### 5. 一键演示

```bash
./.venv/bin/python tools/paper_demo.py
```

---

## 📡 API 完整列表

### 账户管理

| Method | Path | Body | 说明 |
|--------|------|------|------|
| POST | /api/v1/paper/accounts | {name, initial_capital?, fee_rate?, slippage_bps?} | 创建账户 |
| GET | /api/v1/paper/accounts | - | 列出所有账户 |
| GET | /api/v1/paper/accounts/{id} | - | 单账户详情 |
| DELETE | /api/v1/paper/accounts/{id} | - | 删除账户 |
| POST | /api/v1/paper/accounts/{id}/reset | {initial_capital?} | 重置 |

### 数据查询

| Method | Path | Query | 说明 |
|--------|------|-------|------|
| GET | /api/v1/paper/accounts/{id}/trades | limit=50 | 成交记录 |
| GET | /api/v1/paper/accounts/{id}/positions | - | 当前持仓 |
| GET | /api/v1/paper/accounts/{id}/equity | limit=5000 | 权益时间序列 |
| GET | /api/v1/paper/accounts/{id}/metrics | - | 综合指标 |

### 策略绑定

| Method | Path | Body | 说明 |
|--------|------|------|------|
| POST | /api/v1/strategies/{sid}/bind-paper-account | {paper_account_id} | 绑定 |
| POST | /api/v1/strategies/{sid}/start | {mode?, paper_account_id?} | 启动 |

---

## 📊 指标说明

| 字段 | 说明 |
|------|------|
| total_pnl | 总盈亏 = 已实现 + 浮动 |
| realized_pnl | 已实现盈亏 |
| unrealized_pnl | 浮动盈亏 |
| equity | 当前权益 |
| return_pct | 收益率 % |
| sharpe | 年化夏普比率 |
| max_drawdown_pct | 最大回撤 % |
| win_rate | 胜率 |
| profit_factor | 盈亏比 |
| avg_win / avg_loss | 平均盈/亏 |

---

## ⚙️ 配置

```env
PAPER_DEFAULT_CAPITAL=10000.0
PAPER_DEFAULT_FEE_RATE=0.001
PAPER_DEFAULT_SLIPPAGE_BPS=5.0
PAPER_EQUITY_SNAPSHOT_INTERVAL=60
```

---

## 🧮 撮合模型（Phase 1）

1. 取价: connector.get_ticker(symbol)
2. 滑点: buy = mark*(1+bps/10000), sell = mark*(1-bps/10000)
3. 数量: 开仓 = cash*pct/fill, 平仓 = 全部持仓
4. 手续费: fee = notional * fee_rate
5. PnL: long close = (close - avg_entry) * qty - fee
6. 加仓: FIFO weighted avg entry price

---

## 🧪 测试

```bash
cd backend && ./.venv/bin/python -m pytest tests/test_paper_*.py -v
```

18 tests covering matcher (5), manager (3), metrics (10).

---

## 🚧 Phase 2 计划

- 限价单 + 止损止盈
- 合约 / 杠杆 / 做空
- 前端 Dashboard
- CSV 导出
- 盘口深度滑点
- 部分平仓
