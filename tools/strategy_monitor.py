#!/usr/bin/env python3
"""
Quant Trading — 策略状态终端监控
启动: python tools/strategy_monitor.py [--api URL] [--interval SEC]
"""
import argparse, json, select, sys, termios, time, tty
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Any
import httpx
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

DECISION_STYLES = {
    "BUY": "bold bright_green", "SELL": "bold bright_red",
    "CLOSE_LONG": "bold yellow", "CLOSE_SHORT": "bold dark_orange3",
    "CLOSE_BUY": "bold yellow", "CLOSE_SELL": "bold dark_orange3",
    "HOLD": "dim grey50", "ERROR": "bold red on grey15",
}

@dataclass
class Row:
    id: str = ""; name: str = ""; symbol: str = ""; market_type: str = "spot"
    running: bool = False
    state: dict = field(default_factory=dict)
    ticker: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)

@dataclass
class State:
    rows: list = field(default_factory=list)
    last_fetch: float = 0.0; paused: bool = False
    force_refresh: bool = False; should_exit: bool = False
    selected: int = 0; view: str = "list"
    last_error: str | None = None

class Client:
    def __init__(self, base: str, timeout: float = 3.0):
        self.base = base.rstrip("/"); self.client = httpx.Client(timeout=timeout)
        self.errors = 0; self.latency = None
    def get(self, path: str, **kw) -> Any:
        t0 = time.perf_counter()
        try:
            r = self.client.get(f"{self.base}{path}", params=kw)
            r.raise_for_status(); self.latency = (time.perf_counter()-t0)*1000
            self.errors = 0; return r.json()
        except: self.errors += 1; raise

_ticker_cache = {}
def fetch(client, filt_sym, filt_sid):
    rows = []
    for s in (client.get("/api/v1/strategies") or []):
        if filt_sid and s["id"] != filt_sid: continue
        sym = s.get("symbol","")
        if filt_sym and sym.upper() != filt_sym.upper(): continue
        live = s.get("live_state",{}); mkt = live.get("market_type","spot")
        tk_key = f"{mkt}:{sym}"; now = time.time(); ticker = None
        cached = _ticker_cache.get(tk_key)
        if cached and now-cached[0]<3: ticker = cached[1]
        else:
            try:
                t = client.get(f"/api/v1/market/ticker/{sym}", market=mkt)
                if t and "error" not in t: ticker=t; _ticker_cache[tk_key]=(now,t)
            except: pass
        try: params = s.get("params",{})
        except: params={}
        rows.append(Row(id=s["id"],name=s.get("name","?"),symbol=sym,
                        market_type=mkt,running=bool(s.get("running")),
                        state=live,ticker=ticker or {},params=params or {}))
    return rows

key_q = Queue()
def reader():
    try: old = termios.tcgetattr(sys.stdin.fileno())
    except: return
    try:
        tty.setcbreak(sys.stdin.fileno())
        while True:
            if select.select([sys.stdin],[],[],.1)[0]:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    n1=sys.stdin.read(1); n2=sys.stdin.read(1)
                    if n1=="[": key_q.put({"A":"UP","B":"DOWN","D":"LEFT"}.get(n2,""))
                    else: key_q.put("ESC")
                else: key_q.put(ch)
    except: pass
    finally:
        try: termios.tcsetattr(sys.stdin.fileno(),termios.TCSADRAIN,old)
        except: pass

def render(state, client, api, no_color):
    rows = state.rows
    banner_line = []
    running = sum(1 for r in rows if r.running)
    signals = sum(int(r.state.get("signal_count",0)) for r in rows)
    pnl = sum(float((r.state.get("position",{})).get("unrealized_pnl",0)) for r in rows)
    pnl_c = "bright_green" if pnl>=0 else "bright_red"
    last = time.strftime("%H:%M:%S",time.localtime(state.last_fetch)) if state.last_fetch else "--"
    pause_txt = " [yellow]PAUSED[/]" if state.paused else ""
    banner = Panel(Text.from_markup(
        f"Total: [bold]{len(rows)}[/]  Running: [bright_green]{running}[/]  "
        f"Sigs: [cyan]{signals}[/]  PnL: [{pnl_c}]{pnl:+.2f}[/]  "
        f"Last: [dim]{last}[/]{pause_txt}"),
        title=f"Quant Monitor · {api}", border_style="blue")

    t = Table(expand=True,header_style="bold grey50")
    for col in [("#",3),("NAME",18),("SYMBOL",10),("MKT",5),("STATE",8),
                ("PRICE",11),("24H%",8),("POS",11),("PNL",9),("SIG",5)]:
        t.add_column(col[0],width=col[1])
    for i,r in enumerate(rows):
        sel = i==state.selected
        st = "[bright_green]RUN[/]" if r.running else "[dim]STOP[/]"
        p = r.ticker.get("price"); cp = r.ticker.get("change_pct")
        pt = f"{p:,.2f}" if isinstance(p,(int,float)) else "--"
        ct = f"[bright_green]{cp:+.2f}%[/]" if isinstance(cp,(int,float)) and cp>=0 else (f"[bright_red]{cp:+.2f}%[/]" if isinstance(cp,(int,float)) else "[dim]--[/]")
        po = r.state.get("position",{})
        pot = "[dim]--[/]"; pnlt = "[dim]--[/]"
        if po.get("active"):
            sd = (po.get("side") or "").lower(); q = po.get("quantity",0)
            pc = "bright_green" if sd=="long" else "bright_red"
            pot = f"[{pc}]{sd[:1].upper()} {q:.3f}[/]"
            up = po.get("unrealized_pnl")
            if isinstance(up,(int,float)):
                pnlt = f"[bright_green]{up:+.2f}[/]" if up>=0 else f"[bright_red]{up:+.2f}[/]"
        sig = r.state.get("signal_count",0)
        mt = f"[cyan]{r.market_type[:4].upper()}[/]"
        name = f"[reverse]{r.name}[/]" if sel else r.name
        t.add_row(str(i+1),name,r.symbol,mt,st,pt,ct,pot,pnlt,str(sig))

    extras = [t]
    if 0 <= state.selected < len(rows) and rows[state.selected].running:
        sel = rows[state.selected]
        recent = sel.state.get("recent_signals",[])[-7:]
        if recent:
            decs = [(s.get("action","HOLD"),s.get("price"),s.get("strength")) for s in recent]
            dt = Text(f"  \u21b3 {sel.name} decisions: ")
            for i,(a,p,s) in enumerate(decs):
                stl = DECISION_STYLES.get(a.upper(),"")
                if i==len(decs)-1 and not no_color: stl += " reverse"
                dt.append(Text(f" {a.upper()}",style=stl))
            extras.append(dt)
    return Panel(Group(banner,*extras),border_style="dim")

def run(args):
    client = Client(args.api, timeout=3)
    state = State()
    if not args.once:
        Thread(target=reader,daemon=True).start()
    with Live("",refresh_per_second=4) as live:
        while not state.should_exit:
            now = time.time()
            do = (now - state.last_fetch >= args.interval) and not state.paused
            if do or state.force_refresh:
                try:
                    state.rows = fetch(client, args.filter, args.strategy)
                    state.last_fetch = now; state.force_refresh = False
                except Exception as e:
                    state.last_error = str(e)
                    if client.errors >= 30: sys.exit(1)
            # handle keys
            if not args.once:
                while True:
                    try: k = key_q.get_nowait()
                    except: break
                    if k in ("q","Q"): state.should_exit=True
                    elif k in ("p","P"): state.paused = not state.paused
                    elif k in ("r","R"): state.force_refresh=True
                    elif k == "DOWN": state.selected = min(state.selected+1, len(state.rows)-1)
                    elif k == "UP": state.selected = max(state.selected-1, 0)
            live.update(render(state,client,args.api,args.no_color))
            if args.once: break
            time.sleep(0.1)

def main():
    p = argparse.ArgumentParser(description="Quant Trading Monitor")
    p.add_argument("--api",default="http://localhost:8003")
    p.add_argument("--interval",type=float,default=1.0)
    p.add_argument("--filter",help="symbol filter")
    p.add_argument("--strategy",help="strategy id filter")
    p.add_argument("--no-color",action="store_true")
    p.add_argument("--once",action="store_true")
    args = p.parse_args()
    try: run(args)
    except KeyboardInterrupt: pass

if __name__ == "__main__": main()
