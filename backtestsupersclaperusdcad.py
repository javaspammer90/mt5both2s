"""
backtestsupersclaperusdcad.py
Scalper Backtest — USDCAD# (M15 + H1 Trend)
- Manajemen Risiko: Open Posisi 1% dari Modal (Dynamic Lot)
- Max Daily Drawdown: 2% (Stop trade harian jika tercapai)
- Target: 10-20 trade per hari (Limit max_trades di backtest)
- Filter: London/NY Session (07-16 UTC) | ADX>=18 | ATR>ATRmean*0.8 | H1 EMA20
"""

import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, time as dtime
sys.path.append("/root")
import rpyc

# === CONFIG ===
SYMBOL      = "USDCAD#"
TF_M15      = 15
TF_H1       = 16385
BARS_M15    = 5760
BARS_H1     = 500
INITIAL_BAL = 1000.0
RISK_PCT    = 0.01        # 1% risk per trade
MAX_DAILY_DD= 0.02        # 2% max drawdown per hari
MAX_TRADES  = 20
LEVERAGE    = 200
CONTRACT    = 100000

def in_session(ts_unix: float) -> bool:
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    return dtime(7, 0) <= t <= dtime(16, 0)

def ema_np(arr, span):
    k   = 2.0 / (span + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

def get_h1_bias(ts_unix, ts_h1, ema20_h1, cl_h1, n_h1):
    idx = -1
    for j in range(n_h1 - 1, -1, -1):
        if ts_h1[j] <= ts_unix:
            idx = j
            break
    if idx < 0 or np.isnan(ema20_h1[idx]):
        return "NEUTRAL"
    return "BULL" if cl_h1[idx] > ema20_h1[idx] else "BEAR"

print(f"Connecting to MT5 RPyC 127.0.0.1:18812 ...")
t0 = time.time()
c  = rpyc.connect("127.0.0.1", 18812)

# Fetch Data
j_m15  = c.root.bulk_rates_json(SYMBOL, TF_M15, BARS_M15)
raw_m15 = json.loads(j_m15)
j_h1   = c.root.bulk_rates_json(SYMBOL, TF_H1, BARS_H1)
raw_h1  = json.loads(j_h1)

n   = len(raw_m15)
op  = np.array([r[0] for r in raw_m15], dtype=float)
hi  = np.array([r[1] for r in raw_m15], dtype=float)
lo  = np.array([r[2] for r in raw_m15], dtype=float)
cl  = np.array([r[3] for r in raw_m15], dtype=float)

now_ts = int(time.time())
ts_m15 = [now_ts - (n - i) * 900 for i in range(n)]

n_h1   = len(raw_h1)
cl_h1  = np.array([r[3] for r in raw_h1], dtype=float)
ema20_h1 = ema_np(cl_h1, 20)
ts_h1  = [now_ts - (n_h1 - i) * 3600 for i in range(n_h1)]

# Indicators
df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": cl})
ema50  = df["close"].ewm(span=50,  adjust=False).mean().values
ema200 = df["close"].ewm(span=200, adjust=False).mean().values
ema12     = df["close"].ewm(span=12, adjust=False).mean()
ema26     = df["close"].ewm(span=26, adjust=False).mean()
macd_line = (ema12 - ema26).values
macd_sig  = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
histogram = macd_line - macd_sig

hl  = df["high"] - df["low"]
hc  = np.abs(df["high"] - df["close"].shift())
lc  = np.abs(df["low"]  - df["close"].shift())
tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
atr = tr.rolling(14).mean().values
atr_mean20 = tr.rolling(14).mean().rolling(20).mean().values

up_move   = df["high"] - df["high"].shift()
down_move = df["low"].shift() - df["low"]
plus_dm   = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
tr_ser    = pd.Series(tr.values)
plus_di   = (100 * (pd.Series(plus_dm).rolling(14).mean()  / tr_ser.rolling(14).mean())).values
minus_di  = (100 * (pd.Series(minus_dm).rolling(14).mean() / tr_ser.rolling(14).mean())).values
with np.errstate(divide="ignore", invalid="ignore"):
    dx  = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
adx = pd.Series(dx).rolling(14).mean().values

fractal_up   = np.zeros(n)
fractal_down = np.zeros(n)
for idx in range(2, n - 2):
    if hi[idx] > hi[idx-1] and hi[idx] > hi[idx-2] and hi[idx] > hi[idx+1] and hi[idx] > hi[idx+2]:
        fractal_up[idx] = hi[idx]
    if lo[idx] < lo[idx-1] and lo[idx] < lo[idx-2] and lo[idx] < lo[idx+1] and lo[idx] < lo[idx+2]:
        fractal_down[idx] = lo[idx]

def score_v3(i, last_frac_up, last_frac_down):
    close   = cl[i]
    body    = abs(cl[i] - op[i])
    rng     = hi[i] - lo[i]
    cstr    = body / rng if rng > 0 else 0.0
    bullish = cl[i] > op[i]

    fbrk = "NONE"
    if last_frac_up > 0 and close > last_frac_up: fbrk = "UP"
    elif last_frac_down > 0 and close < last_frac_down: fbrk = "DOWN"

    buy_s = sell_s = 0
    t_ema = 15 if ema50[i] > ema200[i] else 0
    buy_s += t_ema; sell_s += (15 - t_ema)
    p_ema = 10 if close > ema50[i] else 0
    buy_s += p_ema; sell_s += (10 - p_ema)
    mc = 20 if macd_line[i] > macd_sig[i] else 0
    buy_s += mc; sell_s += (20 - mc)
    h3u = bool(histogram[i] > histogram[i-1] > histogram[i-2] > histogram[i-3])
    h3d = bool(histogram[i] < histogram[i-1] < histogram[i-2] < histogram[i-3])
    if h3u: buy_s  += 15
    if h3d: sell_s += 15
    adx_s = 15 if adx[i] > 18 else 0
    buy_s += adx_s; sell_s += adx_s
    di_d  = 10 if plus_di[i] > minus_di[i] else 0
    buy_s += di_d; sell_s += (10 - di_d)
    if cstr > 0.7:
        if bullish: buy_s += 15
        else: sell_s += 15
    if fbrk == "UP": buy_s += 5
    elif fbrk == "DOWN": sell_s += 5

    total = buy_s + sell_s
    if total == 0: return "WAIT"
    conf = abs(buy_s - sell_s) / total
    dom  = "BUY" if buy_s >= sell_s else "SELL"
    if conf < 0.60: return "WAIT"

    if dom == "BUY"  and buy_s  >= 75 and buy_s  > sell_s + 15: return "BUY"
    if dom == "SELL" and sell_s >= 75 and sell_s > buy_s  + 15: return "SELL"
    return "WAIT"

def run_test(sl_mult, tp_mult, label):
    bal          = INITIAL_BAL
    max_bal      = INITIAL_BAL
    max_dd       = 0.0
    pos          = 0
    entry_price  = 0.0
    current_lot  = 0.0
    pnl_history  = []
    last_frac_up = last_frac_down = 0.0
    
    last_date = None
    start_day_bal = INITIAL_BAL
    daily_limit_hit = False
    days_hit_limit = 0
    trades_today = 0

    for i in range(220, n - 1):
        curr_open = op[i+1]
        
        # Daily Drawdown Tracker
        dt_curr = datetime.fromtimestamp(ts_m15[i], tz=timezone.utc)
        curr_date = dt_curr.date()

        if curr_date != last_date:
            last_date = curr_date
            start_day_bal = bal
            daily_limit_hit = False
            trades_today = 0

        if fractal_up[i-2] > 0: last_frac_up = fractal_up[i-2]
        if fractal_down[i-2] > 0: last_frac_down = fractal_down[i-2]

        if pos != 0:
            atr_val = max(atr[i], 0.00050)
            sl = (entry_price - atr_val * sl_mult) if pos == 1 else (entry_price + atr_val * sl_mult)
            tp = (entry_price + atr_val * tp_mult) if pos == 1 else (entry_price - atr_val * tp_mult)
            pnl = None

            if pos == 1:
                if lo[i+1] <= sl: pnl = (sl - entry_price) * current_lot * CONTRACT / curr_open; pos = 0
                elif hi[i+1] >= tp: pnl = (tp - entry_price) * current_lot * CONTRACT / curr_open; pos = 0
            elif pos == -1:
                if hi[i+1] >= sl: pnl = (entry_price - sl) * current_lot * CONTRACT / curr_open; pos = 0
                elif lo[i+1] <= tp: pnl = (entry_price - tp) * current_lot * CONTRACT / curr_open; pos = 0

            if pos == 0 and pnl is not None:
                bal += pnl
                pnl_history.append(pnl)
                if bal > max_bal: max_bal = bal
                dd = max_bal - bal
                if dd > max_dd: max_dd = dd
                
                # Check Daily DD Limit after trade closes
                if bal <= start_day_bal * (1 - MAX_DAILY_DD):
                    daily_limit_hit = True
                    days_hit_limit += 1
            continue

        if daily_limit_hit:
            continue
            
        if trades_today >= MAX_TRADES:
            continue

        if not in_session(ts_m15[i]): continue
        if np.isnan(atr_mean20[i]) or atr[i] < atr_mean20[i] * 0.8: continue
        if np.isnan(adx[i]) or adx[i] < 18: continue

        action = score_v3(i, last_frac_up, last_frac_down)
        if action not in ("BUY", "SELL"): continue

        h1_bias = get_h1_bias(ts_m15[i], ts_h1, ema20_h1, cl_h1, n_h1)
        if action == "BUY"  and h1_bias != "BULL": continue
        if action == "SELL" and h1_bias != "BEAR": continue

        # Dynamic Lot Size Calculation (Risk 1%)
        risk_amount = bal * RISK_PCT
        atr_val = max(atr[i], 0.00050)
        sl_dist = atr_val * sl_mult
        
        # Hitung PnL untuk 1 lot jika kena SL (loss diconvert ke USD)
        loss_per_1_lot = sl_dist * CONTRACT / curr_open
        
        calculated_lot = risk_amount / loss_per_1_lot
        current_lot = round(calculated_lot, 2)
        if current_lot < 0.01: current_lot = 0.01

        pos = 1 if action == "BUY" else -1
        entry_price = curr_open
        trades_today += 1

    pnl_arr    = np.array(pnl_history)
    trades     = len(pnl_arr)
    wins       = int(np.sum(pnl_arr > 0))
    losses     = int(np.sum(pnl_arr < 0))
    tg         = float(np.sum(pnl_arr[pnl_arr > 0])) if wins > 0 else 0.0
    tl         = float(np.sum(pnl_arr[pnl_arr < 0])) if losses > 0 else 0.0
    pf         = abs(tg / tl) if tl != 0 else (999.0 if tg > 0 else 0.0)

    return {
        "label": label,
        "net_profit": bal - INITIAL_BAL,
        "final_bal": bal,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "pf": pf,
        "max_dd": max_dd,
        "max_dd_pct": max_dd / INITIAL_BAL * 100,
        "days_hit_limit": days_hit_limit
    }

tests = [
    (1.0, 2.0, "SL 1.0x TP 2.0x (1:2)"),
    (1.0, 3.0, "SL 1.0x TP 3.0x (1:3)"),
    (1.5, 3.0, "SL 1.5x TP 3.0x (1:2)")
]

results = []
for sl, tp, label in tests:
    results.append(run_test(sl, tp, label))

print(f"\n{'='*70}")
print(f"  USDCAD SUPER SCALPER - 1% RISK PER TRADE & MAX {MAX_DAILY_DD*100}% DAILY DD")
print(f"  Max Trades: {MAX_TRADES}/hari | Modal Awal: ${INITIAL_BAL} | Lev: 1:{LEVERAGE}")
print(f"{'='*70}")
for r in results:
    wr = (r['wins']/r['trades']*100) if r['trades']>0 else 0
    print(f"\n[{r['label']}]")
    print(f"  Net Profit    : ${r['net_profit']:.2f} ({(r['net_profit']/INITIAL_BAL)*100:.2f}%)")
    print(f"  Final Balance : ${r['final_bal']:.2f}")
    print(f"  Profit Factor : {r['pf']:.2f} | Win Rate: {wr:.1f}% ({r['wins']}W / {r['losses']}L)")
    print(f"  Max Drawdown  : ${r['max_dd']:.2f} ({r['max_dd_pct']:.2f}%)")
    print(f"  Hari Kena DD  : {r['days_hit_limit']} kali")
print(f"{'='*70}")
