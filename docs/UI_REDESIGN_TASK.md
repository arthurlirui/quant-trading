# 前端 UI 升级 + 策略命令行监控 — 设计任务书

> 工作在 `feat/paper-trading` 分支上。范围：升级整个显示界面 + 新增 CLI 工具。

---

## 🎯 业务目标

### Part A — 前端显示界面整体设计与定期数据更新

当前前端（http://localhost:5190）已有功能：
- 现货/合约切换 + 交易对搜索
- TradingView 风格 K 线图（lightweight-charts v5）
- 合约信息卡（mark/funding/OI）
- 策略卡 + 参数编辑器 + 异步启停
- 交易明细表（带策略/模式过滤）
- 市场总览页（spot/futures, top 60, 收藏）

**痛点和需要升级的方向**：

1. **数据更新策略混乱**：
   - K 线现货走 WebSocket，合约走 5 秒轮询
   - Ticker 每 4 秒轮询
   - 合约信息卡每 5 秒轮询
   - 交易明细每 5 秒轮询
   - 没有统一的 polling/SWR 抽象，各组件自己 setInterval，浪费请求、难维护

2. **TradingView 主图缺少**：
   - 多周期切换（1m/5m/15m/1h/4h/1d）
   - 指标叠加（MA / EMA / RSI / MACD）
   - 鼠标悬停的 OHLCV tooltip
   - 全屏 / 工具栏
   - 自动滚动到最新一根

3. **整体 UI 结构**：
   - 顶栏可以精简，把状态信息放到底部 status bar
   - 增加深色/浅色主题切换（可选）
   - 响应式：在窄屏（< 1280px）布局应该堆叠

4. **数据更新需要可控**：
   - 用户应该能切换"实时 / 每 5s / 每 30s / 暂停"
   - 暂停时显示「数据已暂停」徽标
   - WebSocket 断线时自动重连（带退避）

### Part B — CLI 工具：策略状态终端监控

新建一个独立的 Python CLI（放在 `backend/cli/` 或 `tools/`），通过后端 API 实时显示所有策略状态。**重点是用颜色清晰区分决策**。

**功能要求**：

- 命令：`python -m backend.cli.monitor`（或 `tools/strategy-monitor.py`）
- 全屏 TUI（推荐用 [rich](https://github.com/Textualize/rich) 或 [textual](https://github.com/Textualize/textual)）
- **每个策略一行 / 一个卡片**，显示：
  - 策略名 / symbol / market_type / 运行状态（绿/灰）
  - 当前价格 + 24h 涨跌（颜色：涨绿跌红）
  - 持仓信息：方向 / 入场价 / 数量 / 浮动 PnL（颜色按盈亏）
  - 信号统计：总信号数 / 最近一个信号 / 信号强度（颜色按强度）
  - 关键参数（lookback / entry_threshold 等）
  - 最近 5 个决策（DEC: BUY / SELL / HOLD / CLOSE_LONG ...），**每种决策不同颜色**：
    - `BUY` → 鲜绿 (bold)
    - `SELL` → 鲜红 (bold)
    - `CLOSE_LONG` → 黄色
    - `CLOSE_SHORT` → 橙色
    - `HOLD` → 暗灰
- 顶部有总览栏：总策略数 / 运行中 / 总信号 / 累计 PnL
- **刷新频率 1 秒**，画面更新平滑（不要每秒清屏全重绘 — 用 Live render）
- 支持按键：
  - `q` 退出
  - `r` 立即刷新
  - `p` 暂停/恢复
  - `↑/↓` 选择策略，按 `Enter` 展开详情
- 支持命令行参数：
  - `--api http://localhost:8003`（默认）
  - `--interval 1.0`（刷新间隔秒）
  - `--filter SYMBOL`（只看某交易对）

---

## 📐 当前代码现状（重要！先读这些）

```
backend/
  app/main.py                     # FastAPI routes
  app/core/exchange.py            # spot + futures connector
  app/core/strategies/__init__.py # factory + meta
  app/core/strategies/base.py     # BaseStrategy 接口

frontend/src/
  App.tsx                         # 主入口 + tab 路由
  lib/api.ts                      # 简单 API client (要扩展成有 polling/swr)
  types/index.ts                  # 类型定义
  components/
    Chart/{TradingChart,TickerBar}.tsx
    Market/{MarketSelector,FuturesInfoCard,MarketOverview}.tsx
    Trading/{StrategyPanel,StrategyParamsEditor,TradeHistory}.tsx
    Dashboard/{index,StrategyMonitor,DataDownloadPanel}.tsx
```

**后端可用的 API**（部分列举）：
- `GET /api/v1/status`
- `GET /api/v1/strategies`（含 `live_state`）
- `GET /api/v1/strategies/{sid}/state`
- `GET /api/v1/trades?strategy_id=&mode=&symbol=&limit=`
- `GET /api/v1/positions`
- `GET /api/v1/market/ticker/{symbol}?market=spot|futures`
- `GET /api/v1/market/klines/{symbol}?market=&interval=&limit=`
- `GET /api/v1/market/summary/{symbol}`
- `WS  /api/v1/ws/market/{symbol}`（推送 kline / ticker / signal）

---

## ✅ 验收标准

### Part A（前端）
- [ ] 抽出一个统一的 `useSWR / usePoll` hook，所有组件用它请求数据
- [ ] 全局有「刷新频率」控制器（1s/5s/30s/暂停），通过 React Context 共享
- [ ] WebSocket 断线自动重连 + 状态徽标
- [ ] TradingChart 加：周期切换、至少 1 个叠加指标（MA20）、OHLCV tooltip
- [ ] 响应式适配（窄屏堆叠）
- [ ] 所有数据流有 loading skeleton，不再出现「闪空」
- [ ] 跑 `npm run build` 必须能编译通过

### Part B（CLI）
- [ ] 单文件 `tools/strategy_monitor.py` 或 `backend/cli/monitor.py`
- [ ] 安装好 `rich` 依赖（写进 `requirements.txt`）
- [ ] 启动命令：`python tools/strategy_monitor.py`
- [ ] 至少能跑起来连后端，显示一张实时刷新的策略表
- [ ] 决策颜色区分清晰（BUY/SELL/CLOSE 等）
- [ ] 至少处理 q 键退出

---

## 🛠️ 实施建议

### Part A 先做基础设施
1. 写 `frontend/src/lib/hooks/useSWR.ts`（用原生 fetch + setInterval 实现轻量 SWR）
2. 写 `frontend/src/context/RefreshContext.tsx`（全局刷新频率 + 暂停）
3. 改造现有组件迁移到 hook，删掉重复 setInterval
4. 升级 TradingChart：用 lightweight-charts v5 已有的多 series 支持
5. 最后做响应式

### Part B 用 rich Live
```python
from rich.live import Live
from rich.table import Table
...
with Live(renderable, refresh_per_second=2) as live:
    while True:
        live.update(build_table(fetch_strategies()))
```

---

## 📦 输出要求

1. **代码**：在 `feat/paper-trading` 分支上分多个 commit 提交
2. **设计稿**：写一份 `docs/UI_REDESIGN.md` 简述新布局、hook 抽象、CLI 截图（用 ASCII 描述）
3. **不要破坏现有 paper-trading 任务**：之前我们另外有 `docs/PAPER_TRADING_TASK.md`，那是单独的任务，不要混

---

## 🚦 启动第一步

1. 阅读现有前端代码，重点：`App.tsx`、`Chart/TradingChart.tsx`、`lib/api.ts`、各组件的 setInterval 用法
2. 阅读 lightweight-charts v5 已有的 typings：`frontend/node_modules/lightweight-charts/dist/typings.d.ts`
3. 先在 `docs/UI_REDESIGN.md` 写**设计稿**（包含：新 hook 接口、组件改动列表、CLI ASCII 截图），让我 review
4. review 通过后再编码
