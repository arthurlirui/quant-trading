# UI Redesign — Design Review Draft

> 范围：`feat/paper-trading` 分支
> 关联任务书：`docs/UI_REDESIGN_TASK.md`
> 状态：**设计稿（待 review，未编码）**

本设计稿覆盖两部分：

- **Part A** — 前端整体显示界面升级 + 统一的数据更新抽象
- **Part B** — 策略状态终端监控 CLI（Python + rich）

---

## 0. 设计原则

1. **小步替换，不破坏现状** — 新 hook / Context 与旧 `useEffect+setInterval` 并存，组件逐个迁移；现有页面结构（trading / market / dashboard）保持不变。
2. **后端只读，不动 routes** — 全部基于现有 `/api/v1/*` 与 `/api/v1/ws/market/{symbol}`，不新增/重命名接口。
3. **可观测可控制** — 用户在任何页面都能看到「实时 / 5s / 30s / 暂停」当前是哪个状态，且 ws / poll 断连有视觉反馈。
4. **CLI 独立可跑** — `tools/strategy_monitor.py`，零侵入，单文件优先；依赖只加一个 `rich`。

---

# Part A — 前端

## A.1 当前问题速览

| 文件 | 现状 | 问题 |
|------|------|------|
| `App.tsx` | `setInterval` 5s 轮询合约 K 线 + ws 现货 K 线 | 重连/暂停无控制 |
| `Chart/TickerBar.tsx` | `setInterval 4s` | 自管周期 |
| `Market/FuturesInfoCard.tsx` | `setInterval 5s` | 自管周期 |
| `Market/MarketOverview.tsx` | `setInterval 6s` | 自管周期 |
| `Trading/TradeHistory.tsx` | `setInterval 5s` | 自管周期 |
| `Dashboard/StrategyMonitor.tsx` | `setInterval 3s` | 自管周期 |
| `Chart/TradingChart.tsx` | 单一 1m 周期 + 蜡烛 + 成交量 | 无周期切换、无指标、无 OHLCV tooltip |

→ 6 处各自的 `setInterval`，刷新策略无法统一调度，浪费请求且难以「暂停」。

## A.2 新增基础设施

### A.2.1 `frontend/src/context/RefreshContext.tsx`

全局刷新频率与暂停开关，通过 React Context 共享给所有 hook。

```ts
// 频率档位（毫秒）。null = 仅实时（ws），不主动轮询 HTTP
export type RefreshMode = 'realtime' | '5s' | '30s' | 'paused';

export interface RefreshContextValue {
  mode: RefreshMode;
  /** mode 转化成毫秒；paused / realtime 返回 null（HTTP poll 不跑） */
  intervalMs: number | null;
  /** 全局「暂停」便捷开关（不修改原 mode，便于一键恢复） */
  paused: boolean;
  setMode: (m: RefreshMode) => void;
  setPaused: (p: boolean) => void;
  /** 触发所有订阅 hook 立即重新拉取一次 */
  refreshNow: () => void;
  /** 单调递增的 tick；hook 把它列入 deps 实现「立即刷新」 */
  manualTick: number;
}

export const RefreshProvider: React.FC<{ children: React.ReactNode }>;
export function useRefresh(): RefreshContextValue;
```

UI 控件 `RefreshControl`（放在底部 status bar 中）：

```
[ 🟢 实时 ] [ 5s ] [ 30s ] [ ⏸ 暂停 ]   ↻ 立即刷新    ⏱ 上次更新 12:03:45
```

> 映射规则：`realtime` → null（HTTP 不主动 poll，由 ws 推；无 ws 的接口走默认 5s），`5s` → 5000，`30s` → 30000，`paused` → null + 全局 `paused=true`。
> 持久化：localStorage `qt.refresh.mode`。

### A.2.2 `frontend/src/lib/hooks/useSWR.ts`

轻量原生 SWR 风格 hook，**不引入 `swr` 包**（避免新依赖）。

```ts
export interface UseSWROptions<T> {
  /** 覆盖全局刷新频率；undefined = 跟随 RefreshContext */
  intervalMs?: number | null;
  /** 是否在 paused 时也跑（极少用，比如 status bar 自己） */
  ignorePause?: boolean;
  /** 自动跳过空 key */
  enabled?: boolean;
  /** 反序列化（默认 r => r.json()） */
  parser?: (r: Response) => Promise<T>;
  /** key 变化时是否清掉旧数据；默认 true */
  clearOnKeyChange?: boolean;
  /** 静默错误（不 setError，只 console.warn）；默认 false */
  silent?: boolean;
  /** realtime 模式下的兜底周期；默认 0 = 不兜底 */
  realtimeFallbackMs?: number;
}

export interface UseSWRResult<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;       // 仅首次或 key 变化时为 true
  fetching: boolean;      // 每次后台 revalidate 时为 true
  lastUpdated: number | null;
  refresh: () => Promise<void>;
}

export function useSWR<T>(
  key: string | null,
  options?: UseSWROptions<T>,
): UseSWRResult<T>;
```

实现要点：

- 内部用 `useEffect` + `setInterval` 管周期；订阅 `RefreshContext.intervalMs / paused / manualTick`。
- `key === null` 或 `enabled === false` 时不发请求。
- 用一个 module-scope `Map<string, { data, ts, inflight: Promise<T>|null }>` 做最朴素缓存：同 key 并发请求合并，组件卸载后保留 30s。
- `AbortController` 在 key 变化 / unmount 时取消未完成请求。
- 错误重试：连续失败用退避（1s → 2s → 4s → 8s 上限），成功后归零。

### A.2.3 `frontend/src/lib/hooks/useWebSocket.ts`

抽象现货 ws，自动重连 + 状态可观测。

```ts
export type WSStatus = 'connecting' | 'open' | 'closed' | 'error';

export interface UseWebSocketOptions {
  /** 连接 enabled，false 时不连 */
  enabled?: boolean;
  /** 是否在 RefreshContext.paused 时主动断开；默认 true */
  pauseOnPaused?: boolean;
  /** 收到一条消息回调（已 JSON.parse） */
  onMessage?: (data: unknown) => void;
  /** 退避策略：min/max ms，factor 倍率 */
  backoff?: { min: number; max: number; factor?: number };
}

export interface UseWebSocketResult {
  status: WSStatus;
  /** 当前连续重试次数 */
  retries: number;
  /** 上次成功连上时间戳 */
  lastConnectedAt: number | null;
  /** 主动重连（立刻断开后重新发起） */
  reconnect: () => void;
}

export function useWebSocket(
  url: string | null,
  options?: UseWebSocketOptions,
): UseWebSocketResult;
```

重连退避：默认 `min=1000, max=15000, factor=1.6`；成功连上后重置 `retries=0`；`url` 变化时关闭旧 ws 再建新连。

### A.2.4 `frontend/src/lib/hooks/useStrategies.ts`（领域 hook）

把 `/api/v1/strategies` + 每个 running 策略的 `state` 抽出来：

```ts
export interface UseStrategiesResult {
  strategies: Strategy[];
  states: Record<string, StrategyState>;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useStrategies(opts?: { intervalMs?: number }): UseStrategiesResult;
```

底层用 `useSWR`；states 用 `useEffect` 在 strategies 拉到后并发拉取（限制并发为 5），非 running 的从 `states` 里清掉。

## A.3 组件改造清单

| 组件 | 是否迁移到 useSWR | 移除内容 | 新增内容 |
|------|:---:|------|------|
| `App.tsx` | 是 | `useEffect` 内 5s `setInterval`；自管 ws；`status` 一次性 `fetch` | 用 `useSWR` 拉 `/status`、`/market/klines/{sym}`（合约 poll；现货 1m 走 ws，其它 interval 走 poll）；用 `useWebSocket` 接管现货 ws；新增 `interval` state 透传给 chart |
| `Chart/TickerBar.tsx` | 是 | `setInterval 4s` | `useSWR` 批量 4–8 symbol（沿用 `Promise.allSettled`） |
| `Chart/TradingChart.tsx` | 否（纯展示） | — | 见 §A.4 升级清单 |
| `Market/FuturesInfoCard.tsx` | 是 | `setInterval 5s` | `useSWR('/market/summary/' + sym)` |
| `Market/MarketOverview.tsx` | 是 | `setInterval 6s` | `useSWR` + 受全局频率控制；搜索输入 debounce 300ms |
| `Trading/TradeHistory.tsx` | 是 | `setInterval 5s` | `useSWR('/trades?...')`；过滤器变化时 `refresh()` |
| `Dashboard/StrategyMonitor.tsx` | 是 | 3s `setInterval` + 自管 `states` | 改用 `useStrategies()` |
| `Dashboard/DataDownloadPanel.tsx` | 否（命令式） | — | — |
| **新增** `components/StatusBar.tsx` | — | — | 底部条：ws 状态徽标、刷新档位、最后更新时间、版本号、测试网/主网 |
| **新增** `components/RefreshControl.tsx` | — | — | 频率切换 UI（嵌入 StatusBar 内） |
| **新增** `context/RefreshContext.tsx` | — | — | 见 §A.2.1 |
| **新增** `lib/hooks/useSWR.ts` / `useWebSocket.ts` / `useStrategies.ts` | — | — | 见 §A.2 |
| **新增** `lib/hooks/useResponsive.ts` | — | — | 监听 `matchMedia('(max-width: 1280px)')`，返回 `isNarrow` |

`App.tsx` 同步调整：

- 顶栏右侧的 ws 状态 + 测试网信息 → 挪到新 `StatusBar`。
- 顶栏只留 logo + `MarketSelector`；可选加主题切换占位（本期不实现）。
- 窄屏（`isNarrow=true`）时：把 sidebar 从右侧收起，改为顶栏下的折叠 tab：`图表 | 策略 | 信号`，单列展示。

## A.4 TradingChart 升级清单

文件：`frontend/src/components/Chart/TradingChart.tsx`

### A.4.1 新增 props

```ts
type Interval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

interface IndicatorConfig {
  ma?: number[];        // 例如 [20, 60] 画两条 MA
  ema?: number[];       // 例如 [50]
  rsi?: boolean;        // 在副图（pane=1）画 RSI(14)
  macd?: boolean;       // 在副图（pane=2）画 MACD(12,26,9)
}

interface Props {
  data: Kline[];
  trades?: TradeMarker[];
  height?: number;
  interval: Interval;
  onIntervalChange: (i: Interval) => void;
  indicators?: IndicatorConfig;
  onIndicatorsChange?: (next: IndicatorConfig) => void;
  /** 是否启用「自动滚到最新一根」；默认 true */
  followLatest?: boolean;
}
```

> 周期 state 放在 `App.tsx`，方便 `useSWR` 把 `interval` 拼进 key；现货 1m 仍走 ws，其它周期统一走 poll。

### A.4.2 工具栏（chart 顶部 overlay）

```
+-----------------------------------------------------------------+
|  [1m] [5m] [15m] [1h] [4h] [1d]    MA20  EMA50  RSI  MACD   [ ] |
+-----------------------------------------------------------------+
```

- 周期按钮：选中态高亮蓝色；点击 → `onIntervalChange`。
- 指标 chip：toggle；勾上即叠加，再次点击移除。
- 右上角 `[ ]`：全屏按钮（CSS：父容器 `position: fixed; inset: 0; z-index: 50`）。

### A.4.3 OHLCV tooltip（鼠标悬停）

利用 `chart.subscribeCrosshairMove(handler)`：从 `handler.seriesData.get(candleSeries)` 取 OHLC、`get(volumeSeries)` 取 volume。

显示位置：图表左上角浮窗，文本如下：

```
2025-06-08 14:30   O 67230.10  H 67250.50  L 67225.00  C 67248.20  V 12.85 BTC  +0.19%
```

实现方式：在 `TradingChart` 组件里用一个绝对定位的 `<div>` 跟随 `param.point`（屏幕坐标，px）做 left/top 偏移；离开图表区域时隐藏。

### A.4.4 指标实现

- **MA(n)** / **EMA(n)**：纯 JS 计算（k 线数组上 reduce），用 `chart.addSeries(LineSeries, { color, lineWidth: 1 })` 画在主 pane（paneIndex 默认 0）。
- **RSI(14)**：另一 pane（`addSeries(LineSeries, ..., 1)`），0–100 区间，画 30 / 70 两条参考线（`createPriceLine`）。
- **MACD(12,26,9)**：第三 pane，包含 DIF 线、DEA 线、柱状（Histogram）。

> 计算逻辑放 `frontend/src/lib/indicators.ts`，纯函数 + 单测占位（本期不写 test，留接口）。

### A.4.5 自动滚动

- 数据增量更新到尾部时，调用 `chart.timeScale().scrollToRealTime()`。
- 但用户主动拖动过 timescale 后**不再自动滚**（监听 `subscribeVisibleLogicalRangeChange`，若用户落在非"最右"位置则关闭自动滚；用户再次双击空白 / 右下角按钮恢复）。

### A.4.6 重建 vs 增量

当前实现把整段 `data` 每次 `setData`（在 `useEffect` deps 中），周期切换 / 大量数据时无明显问题。本次保持现状：

- `data` 引用变化 → 整段 `setData`（性能可接受，<= 1000 根）。
- 指标 / 周期开关切换不重建 chart 实例，只 add / remove series。

## A.5 整体布局草图

```
+========================================================================+
| Logo | Quant Trading      [ 现货 ▼  BTCUSDT 🔍 ]                       |  顶栏（精简）
+------------------------------------------------------------------------+
| Ticker Bar: BTC 67248 +0.19%  ETH …  BNB …  SOL …                      |
+------------------------------------------------------------------------+
| [交易] [市场] [仪表盘]                                                  |  Nav tabs
+--------------------------------------------------+---------------------+
|                                                  |  合约信息（仅 futures）|
|  +--------------------------------------------+  |  ------------------ |
|  | [1m][5m][15m][1h][4h][1d] MA20 EMA50 [ ]   |  |  策略面板             |
|  |                                            |  |                     |
|  |        TradingView 风格主图                |  |  ------------------ |
|  |                                            |  |  信号日志             |
|  +--------------------------------------------+  |                     |
|  |        RSI / MACD 副图（按需）              |  |                     |
|  +--------------------------------------------+  |                     |
|  |        交易明细 Table                       |  |                     |
|  +--------------------------------------------+  |                     |
+--------------------------------------------------+---------------------+
|  ws 🟢 实时 | 刷新 [ 实时 | 5s | 30s | ⏸ ]  ↻  | 上次 12:03:45 | 测试网 v0.2.0|
+========================================================================+
```

窄屏（<1280px）：右侧 sidebar 折叠成下拉抽屉（按钮在顶栏），主区域单列。

## A.6 验收映射

| 任务书要求 | 落点 |
|------|------|
| 抽出统一 `useSWR/usePoll` hook | §A.2.2 `useSWR.ts` |
| 全局刷新频率控制器（1s/5s/30s/暂停） | §A.2.1 `RefreshContext` + `RefreshControl` |
| WebSocket 断线自动重连 + 状态徽标 | §A.2.3 `useWebSocket` + §A.5 status bar |
| TradingChart 加：周期切换、≥1 个叠加指标(MA20)、OHLCV tooltip | §A.4 |
| 响应式适配（窄屏堆叠） | §A.3 `useResponsive` + §A.5 |
| 所有数据流 loading skeleton | `useSWR.loading` → 各组件已有 placeholder 改 skeleton |
| `npm run build` 通过 | 不引入新依赖；TS 类型严格 |

## A.7 不在本次范围

- 主题切换（深色/浅色）→ 留接口（CSS 变量层），实现延后。
- 抽 ws 信道为多 symbol 多路复用（后端目前 1 ws / 1 symbol）。
- 全文搜索/快捷键面板。

---

# Part B — 策略状态终端监控 CLI

## B.1 目标位置 & 命名

- 文件：`tools/strategy_monitor.py`（**单文件**，无包结构，直接 `python tools/strategy_monitor.py` 即可跑）
- 备用入口：`python -m tools.strategy_monitor`（如果 `tools/__init__.py` 存在）
- 依赖：仅追加一行到 `backend/requirements.txt`

  ```
  rich>=13.7.0
  ```

  （`httpx` 已在 requirements 中，可直接复用作 HTTP client）

## B.2 命令行参数

```
usage: strategy_monitor.py [-h] [--api URL] [--interval SEC] [--filter SYM]
                           [--no-color] [--once] [--strategy ID]

Quant Trading — 策略状态实时监控 (terminal)

options:
  -h, --help          show help
  --api URL           后端 API base，默认 http://localhost:8003
  --interval SEC      刷新间隔秒，默认 1.0
  --filter SYM        只显示指定 symbol（如 BTCUSDT）
  --strategy ID       只关注某个策略 id（其它不显示）
  --no-color          关闭颜色（CI/日志友好）
  --once              拉一次就退出（cron / 脚本用）
```

退出码：`0` 正常退出（q 键 / `--once` 完成）；`1` 网络持续失败 > 30s；`2` 参数错误。

## B.3 显示布局（rich Live + Layout）

总体使用 `rich.layout.Layout` 切成三块：顶部 banner、中间策略表、底部状态栏。`Live(refresh_per_second=2)` 平滑渲染。

```
┌──────────────────── Quant Trading Monitor ─ http://localhost:8003 ────────────────┐
│ 总策略数: 4   运行中: 2   总信号: 137   累计 PnL: +123.45 USDT   上次刷新: 14:03:21│
└───────────────────────────────────────────────────────────────────────────────────┘
┌─ Strategies ──────────────────────────────────────────────────────────────────────┐
│ # NAME           SYMBOL     MKT    STATE   PRICE      24H%   POS       PNL   SIG │
│ 1 VolSurge-BTC   BTCUSDT    SPOT   ● RUN   67248.20  +0.19%  L 0.12  +12.45  42  │
│   ↳ params: lookback=30 entry_threshold=2.5  | sig last: BUY @ 67120 (0.81)      │
│   ↳ recent decisions:  BUY  HOLD  HOLD  CLOSE_LONG  HOLD                         │
│ 2 MeanRev-ETH    ETHUSDT    SPOT   ● RUN   3520.10   -0.32%  -        +0.00   31 │
│   ↳ params: lookback=20 z=2.0                                                     │
│   ↳ recent decisions:  HOLD HOLD SELL HOLD HOLD                                  │
│ 3 Funding-BTCP   BTCUSDT    PERP   ○ STOP  —          —      —          —    —   │
│ 4 Breakout-SOL   SOLUSDT    SPOT   ○ STOP  —          —      —          —    —   │
└───────────────────────────────────────────────────────────────────────────────────┘
 [q] quit   [p] pause/resume   [r] refresh now   [↑/↓] select   [Enter] details
```

### B.3.1 列含义

| 列 | 来源 | 颜色规则 |
|---|---|---|
| `STATE` | `strategy.running` / `status` | `● RUN`=亮绿；`○ STOP`=暗灰；`× ERR`=红 |
| `PRICE` | `live_state.last_price` 或 `/market/ticker` 兜底 | 中性白 |
| `24H%` | ticker.change_pct | >0 绿，<0 红 |
| `POS` | `live_state.position`：`L 0.12` / `S 0.05` / `-` | long 绿，short 红 |
| `PNL` | executor_positions.unrealized_pnl + realized_pnl | >0 绿，<0 红 |
| `SIG` | `len(live_state
.signal_history)` | 中性白 |
| `MKT` | `live_state.market_type` | SPOT=蓝；PERP=橙 |

### B.3.2 决策颜色映射 (🎯 重点)

```python
DECISION_STYLES = {
    'BUY':          'bold bright_green',
    'SELL':         'bold bright_red',
    'CLOSE_LONG':   'bold yellow',
    'CLOSE_SHORT':  'bold dark_orange3',
    'HOLD':         'dim grey50',
    'ERROR':        'bold red on grey15',
}
```

上下文带颜色强化：

- 最近决策表（`recent decisions` 行）：按顺序逐个染色；最新一个额外加 `reverse` 高亮。
- `sig last: BUY @ 67120 (0.81)` 行里：`BUY/SELL` 词本身染色、强度 `(0.81)` 按阈值染色：≥0.8 亮绿；0.5–0.8 黄；<0.5 暗灰。
- 换仓信号出现在 PNL > 0 后：额外贴 `✨` emoji（可通过 `--no-color` 关掉）。

### B.3.3 详情视图（Enter 展开）

选中某一行后按 Enter，中间区域切到单策略全屏详情：

```
┌─ VolSurge-BTC · BTCUSDT · SPOT · ● RUN ────────────────────────────────────────────┐
│  Price: 67248.20  (24h +0.19%)         Position: LONG 0.12 BTC @ 67120.00          │
│  Total Signals: 42   Last @ 14:02:18   Realized: +10.20   Unrealized: +2.25        │
│                                                                                     │
│  Parameters                          Risk Limits                                    │
│    lookback         30                 max_position    1.0                          │
│    entry_threshold  2.5                max_leverage    1                            │
│    exit_threshold   0.5                sl_pct          2.0                          │
│                                        tp_pct          5.0                          │
│                                                                                     │
│  Recent 20 Decisions  (新 -> 旧)                                                    │
│   14:02:18  BUY         @ 67120.00  strength=0.81  reason="vol surge +3.2σ"         │
│   14:01:18  HOLD                                                                    │
│   14:00:18  HOLD                                                                    │
│   13:59:18  CLOSE_LONG  @ 67065.00  strength=0.65  reason="tp hit"                  │
│   ...                                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘
 [esc/←] back   [r] refresh   [q] quit
```

详情需要的数据从 `/api/v1/strategies/{sid}/state`（现有接口已返回 live_state）+ `/api/v1/positions` 补充。

### B.3.4 状态栏（底部）

```
  API: ● 200ms   poll: 1.0s   paused=False   errors: 0    last fetch: 14:03:21
```

- API 点点颜色：<300ms 绿；<800ms 黄；超时/错误 红。
- `errors` 计数连续失败次数，成功后归零。

## B.4 键盘交互

| 键 | 动作 |
|---|---|
| `q` / `Q` / `Ctrl-C` | 优雅退出（stop Live，恢复终端模式不留乱码 cursor） |
| `p` / `P` | 暂停/恢复轮询（不清屏，顶部 banner 加 `⏸ PAUSED` 徽标） |
| `r` / `R` | 立即拉一次（不等下个 interval） |
| `↑` / `↓` | 在策略列表上移动 cursor（高亮选中行） |
| `Enter` | 进入选中策略详情视图 |
| `esc` / `←` | 详情视图中返回列表 |
| `f` | 快捷调出 filter 输入（输 symbol 后回车生效；esc 取消） |

实现：用 `rich.live.Live` + 一个后台 `threading.Thread` 读 stdin。**不**引入 `prompt_toolkit/textual`。按键检测用 `sys.stdin` + `termios`（POSIX）；Windows 不支持互动模式（提示「仅支持 `--once`」）。

```python
# 伪代码
from threading import Thread
from queue import Queue
import sys, tty, termios, select

key_q: Queue[str] = Queue()

def _key_reader():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            if select.select([fd], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                key_q.put(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
```

主循环每 tick 随手 try `key_q.get_nowait()`，有键就处理。

## B.5 HTTP client + 错误处理

```python
class APIClient:
    def __init__(self, base: str, timeout: float = 3.0):
        self.base = base.rstrip('/')
        self.client = httpx.Client(timeout=timeout)
        self.errors_in_a_row = 0
        self.last_latency_ms: float | None = None

    def get(self, path: str, **params) -> Any:
        t0 = time.perf_counter()
        try:
            r = self.client.get(f'{self.base}{path}', params=params)
            r.raise_for_status()
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            self.errors_in_a_row = 0
            return r.json()
        except Exception:
            self.errors_in_a_row += 1
            raise
```

主循环错误策略：
- 单次失败：banner 显示红色 `API ERR (n=%d)`，本 tick 复用上次缓存数据。
- 连续 ≥30 次（默认 30s）：CLI 直接退出，exit code = 1。

## B.6 数据抓取策略

每次 tick（默认 1s）顺序拉：

1. `GET /api/v1/strategies`（含 `live_state`）— 主数据源
2. 对每个 `live_state.symbol` 去重后批量 `GET /api/v1/market/ticker/{sym}?market={spot|futures}`（用 `httpx` 串行即可，4-8 个，<200ms）
3. `GET /api/v1/positions` — 取 unrealized PnL（兜底，若 live_state 已有则跳过）

为减小压力，**ticker 缓存 3s**（同一 tick 内多策略共享）。

## B.7 渲染主循环伪代码

```python
def main():
    args = parse_args()
    client = APIClient(args.api, timeout=3.0)
    state = MonitorState(view='list', selected=0, paused=False, filter=args.filter)

    if not args.once:
        Thread(target=_key_reader, daemon=True).start()

    with Live(render(state, None), refresh_per_second=4, screen=True) as live:
        last_fetch = 0
        while True:
            now = time.time()
            do_fetch = (now - last_fetch >= args.interval) and not state.paused

            if do_fetch or state.force_refresh:
                try:
                    data = fetch_all(client, args.filter)
                    state.update(data)
                    last_fetch = now
                    state.force_refresh = False
                except Exception as e:
                    state.last_error = str(e)
                    if client.errors_in_a_row >= 30:
                        sys.exit(1)

            handle_keys(state, key_q)
            live.update(render(state, client))

            if state.should_exit:
                break
            if args.once:
                break
            time.sleep(0.1)
```

## B.8 验收映射

| 任务书要求 | 落点 |
|------|------|
| 单文件可跑 | §B.1 `tools/strategy_monitor.py` |
| 安装 `rich` 写进 requirements | §B.1 |
| 启动命令 `python tools/strategy_monitor.py` | §B.1 |
| 全屏实时刷新的策略表 | §B.3 (rich Live + Layout) |
| 决策颜色清晰区分 | §B.3.2 DECISION_STYLES |
| 至少处理 `q` 键退出 | §B.4 |
| 总览栏（总策略数 / 运行中 / 总信号 / 累计 PnL） | §B.3 banner |
| 命令行参数 (`--api/--interval/--filter`) | §B.2 |
| 详情视图（Enter） | §B.3.3 + §B.4 |

## B.9 不在本次范围

- Windows 互动模式（仅 `--once` 工作）
- TUI 内手动启停策略（→ POST 写操作；安全风险，后期再加）
- 配色主题切换（先固定一套）
- 单测（cli 性质，靠手测）

---

# 实施顺序建议

1. **Part A.2** 基础设施（RefreshContext + useSWR + useWebSocket）→ 单独 commit
2. **Part A.3** 6 个组件迁移 → 一个个组件 commit
3. **Part A.4** TradingChart 升级（按 indicators / 周期 / tooltip / 自动滚 拆 4 个小 commit）
4. **Part A.5** StatusBar + 响应式 → commit
5. **Part B** CLI（独立文件，最后做，不影响前端）→ 1 个 commit

总计约 **10 个 commit**，全部在 `feat/paper-trading` 分支。

---

**END OF DESIGN DRAFT — Ready for review.**
