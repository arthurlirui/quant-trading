# 📈 Quant Trading System

> 基于 Binance 实时行情的量化交易系统 · Volume Surge 多因子策略

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-00a393?logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev)
[![Lightweight Charts](https://img.shields.io/badge/Lightweight%20Charts-5.x-FF4500)](https://github.com/tradingview/lightweight-charts)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ 功能

| 功能 | 描述 |
|------|------|
| 📊 **实时行情** | Binance WebSocket 推送，自动断线重连（指数退避） |
| 🧮 **策略引擎** | 三因子 Volume Surge 策略（价格 + 成交量 + 成交量变化率） |
| 🔙 **回测引擎** | 事件驱动回测，支持手续费、滑点、绩效指标 |
| 📈 **前端仪表盘** | K 线图 + 成交量柱状图 + 信号日志 |
| 🔌 **REST API** | 完整的策略 / 行情 / 交易 / 回测管理接口 |
| 🔐 **测试网优先** | 默认连接 Binance 测试网，安全无风险 |

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────────────┐
│                    React Dashboard                     │
│  ┌──────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ K 线/成交量图  │  │ 策略面板  │  │ 实时信号日志    │  │
│  └──────┬───────┘  └────┬─────┘  └───────┬────────┘  │
└─────────┼───────────────┼────────────────┼────────────┘
          │               │                │
          ▼               ▼                ▼
┌──────────────────────────────────────────────────────┐
│              FastAPI + WebSocket (Backend)             │
│  ┌────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐ │
│  │ REST   │  │ WS 行情   │  │ 策略    │  │ 回测引擎   │ │
│  │ API    │  │ 推送      │  │ 调度器  │  │           │ │
│  └────────┘  └────┬─────┘  └────┬───┘  └─────┬─────┘ │
└───────────────────┼──────────────┼────────────┼───────┘
                    │              │            │
                    ▼              ▼            ▼
┌──────────────────────────────────────────────────────┐
│              Binance (Testnet / Mainnet)               │
│         WebSocket 实时流 + REST 行情/交易 API           │
└──────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 前置条件

- Python 3.12+
- Node.js 20+
- Binance 测试网账户（可选，默认可用）

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 启动开发服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API 文档自动生成：http://localhost:8000/docs

### 前端

```bash
cd frontend
npm install
npm run dev
```

默认访问：http://localhost:5173

---

## 📡 API 一览

### REST

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/status` | 系统状态 |
| `GET` | `/api/v1/market/ticker/{symbol}` | 实时报价 |
| `GET` | `/api/v1/market/klines/{symbol}` | K 线历史 |
| `GET` | `/api/v1/strategies` | 策略列表 |
| `POST` | `/api/v1/strategies` | 创建策略 |
| `POST` | `/api/v1/strategies/{id}/start` | 启动策略 |
| `POST` | `/api/v1/strategies/{id}/stop` | 停止策略 |
| `POST` | `/api/v1/backtest/run` | 运行回测 |
| `GET` | `/api/v1/trades` | 交易记录 |
| `GET` | `/api/v1/positions` | 当前持仓 |

### WebSocket

| 路径 | 说明 |
|------|------|
| `/api/v1/ws/market/{symbol}` | 实时 K 线 + ticker 推送 |
| `/api/v1/ws/signals` | 实时交易信号（开发中） |

---

## 🧠 策略：Volume Surge Detector

三因子模型：

```
Signal = α · price_zscore + β · volume_zscore + γ · volume_delta_zscore
```

| 因子 | 含义 |
|------|------|
| **价格 Z-Score** | 当前价格偏离均值的标准差倍数 |
| **成交量 Z-Score** | 当前成交量的异常程度 |
| **成交量变化率** | 成交量相比上一周期的变化速度 |

当 Signal 超过阈值时产生交易信号：
- `Signal > +threshold` → **做多**（量价齐升）
- `Signal < -threshold` → **做空**（放量下跌）
- 持仓后按止盈 / 止损 / 信号反转自动退出

默认参数：

| 参数 | 默认值 |
|------|--------|
| lookback | 20 |
| 入场阈值 | 2.0σ |
| 出场阈值 | 0.5σ |
| 止损 | 2% |
| 止盈 | 5% |

---

## 🧪 回测示例

```bash
curl -X POST http://localhost:8000/api/v1/backtest/run \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTCUSDT",
    "lookback_hours": 24,
    "initial_capital": 10000
  }'
```

返回示例：

```json
{
  "summary": {
    "total_return_pct": 3.21,
    "sharpe": 1.45,
    "max_drawdown": 1.23,
    "win_rate": 62.5,
    "total_trades": 16,
    "profit_factor": 2.31
  }
}
```

---

## ⚙️ 配置

所有配置通过环境变量或 `.env` 文件管理：

```env
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./quant_trading.db
BINANCE_TESTNET=true
BINANCE_API_KEY=your_key
BINANCE_SECRET_KEY=your_secret
```

> ⚠️ API Key 仅用于实盘交易和账户查询。默认测试网模式无需填写。

---

## 📁 项目结构

```
quant-trading/
├── backend/
│   ├── app/
│   │   ├── api/              # API 路由
│   │   ├── core/             # 核心引擎
│   │   │   ├── strategy.py   # 策略逻辑
│   │   │   ├── exchange.py   # Binance 连接
│   │   │   └── backtest.py   # 回测引擎
│   │   ├── models/           # SQLAlchemy 模型
│   │   ├── config.py         # 配置管理
│   │   ├── db.py             # 数据库
│   │   └── main.py           # 入口
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── components/       # React 组件
│   │   │   ├── Chart/        # 图表组件
│   │   │   └── Trading/      # 交易面板
│   │   ├── types/            # TypeScript 类型
│   │   └── App.tsx           # 主界面
│   ├── package.json
│   └── vite.config.ts
├── ARCHITECTURE.md           # 详细架构文档
└── README.md
```

---

## 🗺️ 路线图

- [x] 架构设计 & API 规范
- [x] 数据库 & 数据模型
- [x] Binance WebSocket 连接管理器
- [x] Volume Surge 策略引擎
- [x] 回测引擎
- [x] REST API & WebSocket
- [x] 前端仪表盘
- [ ] 单元测试 & 集成测试
- [ ] PostgreSQL + TimescaleDB 支持
- [ ] Docker 部署
- [ ] 多策略并行运行
- [ ] Telegram / 飞书通知
- [ ] 实盘交易执行

---

## 📄 License

MIT
