# 📈 量化交易系统 — 架构设计

> **Archy** 设计 | **Managy** 接口设计 | **Cody** 实现 | 2026-06-02

---

## 1. 系统概述

高性能量化交易系统，基于 Binance 实时行情，运行多因子策略，支持回测与实盘。

### 核心能力

```
📊 Binance 行情 → 🧮 策略引擎 → ⚡ 交易执行 → 📈 实时监控
                    ↕
              🔄 回测引擎
```

---

## 2. 技术栈

| 层 | 技术 | 用途 |
|-----|------|------|
| **前端图表** | Lightweight Charts (TradingView) | K线/成交量可视化 |
| **前端 UI** | React + TypeScript + TailwindCSS | 仪表盘/控制面板 |
| **后端 API** | Python FastAPI + WebSocket | 行情推送/交易管理 |
| **行情引擎** | python-binance WebSocket | 实时行情流 |
| **数据库** | SQLite (dev) / PostgreSQL + TimescaleDB (prod) | 行情/交易/回测数据 |
| **回测引擎** | 自定义事件驱动 | 策略回测验证 |
| **策略** | 量价突变检测 (Volume Surge) | 自定义因子模型 |
| **消息队列** | asyncio.Queue | 内部事件总线 |
| **重连** | 指数退避 + 健康检查 | 自动断线重连 |

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                          │
│  ┌──────────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ K线/成交量图表     │  │ 持仓/盈亏面板 │  │ 策略控制台         │  │
│  │ (TradingView)    │  │              │  │ 参数/启动/停止     │  │
│  └────────┬─────────┘  └──────┬───────┘  └────────┬──────────┘  │
└───────────┼───────────────────┼────────────────────┼─────────────┘
            │                   │                    │
            ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                     API Gateway (FastAPI + WS)                     │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │REST CRUD│ │WS /kline  │ │WS /ticker │ │WS /trade │ │WS /log │ │
│  │ 策略/配置│ │K线数据    │ │实时报价   │ │成交数据   │ │系统日志 │ │
│  └─────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘ │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Trading Engine                             │
│  ┌────────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────────┐ │
│  │ Binance    │ │ 事件驱动总线   │ │ 策略引擎  │ │ 回测引擎       │ │
│  │ WebSocket  │ │ (asyncio)    │ │ 多因子    │ │ (事件驱动)     │ │
│  │ 连接管理器  │ │              │ │ 调度器    │ │               │ │
│  │ (自动重连)  │ │              │ │          │ │               │ │
│  └─────┬──────┘ └──────┬───────┘ └─────┬────┘ └───────┬───────┘ │
└────────┼───────────────┼───────────────┼──────────────┼──────────┘
         │               │               │              │
         ▼               ▼               ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Data Layer                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ SQLite/PG    │  │ Redis Cache  │  │ CSV/Parquet (回测数据)    │ │
│  │ 行情/交易/回测│  │ 高频数据缓存  │  │ 历史数据存储               │ │
│  └─────────────┘  └──────────────┘  └──────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 策略设计 — Volume Surge Detector

### 4.1 核心逻辑

**三因子模型**: `price × volume × volume_derivative`

```
Signal = α · price_zscore + β · volume_zscore + γ · volume_delta_zscore
```

| 因子 | 含义 | 计算 |
|------|------|------|
| **价格 Z-Score** | 当前价格偏离均值的程度 | `(price - SMA(price, n)) / std(price, n)` |
| **成交量 Z-Score** | 当前成交量是否异常 | `(volume - SMA(volume, n)) / std(volume, n)` |
| **成交量导数** | 成交量变化速度 | `volume - volume[-1]` (归一化) |

### 4.2 交易逻辑

```
当 Signal > threshold_up   → 做多 (突发放量上涨)
当 Signal < threshold_down → 做空 (突发放量下跌)
持续持仓直到信号反转或止损
```

### 4.3 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| lookback_period | 20 | Z-Score 计算窗口 |
| entry_threshold | 2.0 | 入场信号阈值 |
| exit_threshold | 0.5 | 出场信号阈值 |
| stop_loss_pct | 2.0% | 止损 |
| take_profit_pct | 5.0% | 止盈 |
| position_size | 0.1 | 仓位比例 |
| volume_surge_min | 1.5 | 最小成交量倍数 |

---

## 5. API 接口设计 (Managy)

### 5.1 REST API

```
# 系统
GET    /api/v1/status                    系统状态

# 行情
GET    /api/v1/market/ticker/:symbol     当前报价
GET    /api/v1/market/klines/:symbol     K线历史
GET    /api/v1/market/info               交易对信息

# 策略
GET    /api/v1/strategies                策略列表
POST   /api/v1/strategies                创建策略
GET    /api/v1/strategies/:id            策略详情
PUT    /api/v1/strategies/:id            更新策略参数
DELETE /api/v1/strategies/:id            删除策略
POST   /api/v1/strategies/:id/start      启动策略
POST   /api/v1/strategies/:id/stop       停止策略

# 回测
POST   /api/v1/backtest/run              运行回测
GET    /api/v1/backtest/:id              回测结果
GET    /api/v1/backtest/:id/trades       回测交易明细

# 交易
GET    /api/v1/trades                    历史交易
GET    /api/v1/positions                 当前持仓
GET    /api/v1/account                   账户信息

# 日志
GET    /api/v1/logs                      系统日志
```

### 5.2 WebSocket

```
WS /api/v1/ws/market/:symbol    实时行情推送 (ticker + kline)
WS /api/v1/ws/signals            实时交易信号推送
WS /api/v1/ws/trades             实时成交推送
WS /api/v1/ws/logs               实时系统日志
```

---

## 6. 数据模型

```python
# 策略配置
class Strategy(Base):
    id, name, symbol, timeframe, params(JSON), status, created_at

# K线数据
class Kline(Base):
    symbol, interval, open_time, open, high, low, close, volume, close_time

# 交易记录
class Trade(Base):
    id, strategy_id, symbol, side(buy/sell), price, quantity,
    pnl, status(open/closed), open_time, close_time

# 回测运行
class BacktestRun(Base):
    id, strategy_id, symbol, start_time, end_time, params,
    total_return, sharpe, max_drawdown, win_rate, total_trades

# 持仓
class Position(Base):
    id, strategy_id, symbol, side, quantity, entry_price,
    current_price, unrealized_pnl, created_at
```

---

## 7. 连接管理 (鲁棒性)

```
┌──────────────┐    失败     ┌────────────────┐
│  Binance WS   │──────────→ │  重连管理器     │
│   (主要连接)   │            │                 │
│              │←──────────│  指数退避: 1s→2s→4s→8s...→60s max
└──────────────┘  恢复连接   └────────────────┘
                                    │
                                    ▼
                              ┌──────────────┐
                              │  健康检查       │
                              │  每 30s ping   │
                              │  超时 5s 重启   │
                              └──────────────┘
```

---

## 8. 执行计划

| Phase | 内容 | 角色 |
|-------|------|------|
| P1 | 架构设计 + 接口规范 | 🏛️ **Archy** + 📋 **Managy** |
| P2 | 数据库 + 数据模型 | 🛠️ **Cody** |
| P3 | Binance 连接管理器 (自动重连) | 🛠️ **Cody** |
| P4 | Volume Surge 策略引擎 | 🛠️ **Cody** |
| P5 | 回测引擎 | 🛠️ **Cody** |
| P6 | REST API + WebSocket | 🛠️ **Cody** |
| P7 | 前端 (图表/控制台/仪表盘) | 🦕 **Frontend** |
| P8 | 集成测试 + 部署 | 🧪 **Testy** |
