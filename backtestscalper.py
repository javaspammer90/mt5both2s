"""
backtestscalper.py
Scalper Backtest — USDJPY# M5
Inline logika dari backtest_usdjpy.py + decision_engine V3 + session_filter
Fetch via bulk_rates_json (cepat, tidak timeout)

Optimasi untuk USDJPY M5:
  - PnL dikonversi JPY → USD (pnl_jpy / price)
  - CONTRACT = 100,000 (forex standard)
  - Filter sesi London + NY (07:00 - 22:00 UTC)
  - Filter volatilitas ATR > ATR_mean20
  - Scoring Engine V3: EMA50/200 + MACD + ADX + Fractal + Candle Strength
  - Multi SL/TP test: Test A, B, C
"""

import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, time as dtime
sys.path.append("/root")
import rpyc

# === CONFIG ===
SYMBOL      = "XAUUSD#"
TIMEFRAME   = 15            # M15
BARS        = 5760          # ~20 hari trading M15
INITIAL_BAL = 100.0
LOT_SIZE    = 0.01
LEVERAGE    = 200
CONTRACT    = 100           # XAUUSD 100 oz per lot
SPREAD      = 300           # estimasi spread XAUUSD

# === SESSION FILTER ===
def in_session(ts_unix: float) -> bool:
    """07:00 - 11:00 UTC (London Open saja — peak momentum USDJPY)"""
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    return dtime(7, 0) <= t <= dtime(11, 0)

# === FETCH DATA ===
print(f"Connecting to MT5 RPyC 127.0.0.1:18812 ...")
t0 = time.time()
c   = rpyc.connect("127.0.0.1", 18812)
j   = c.root.bulk_rates_json(SYMBOL, TIMEFRAME, BARS)
raw = json.loads(j)
print(f"Fetched {len(raw)} bars {SYMBOL} M5 in {time.time()-t0:.2f}s")

n  = len(raw)
op = np.array([r[0] for r in raw], dtype=float)
hi = np.array([r[1] for r in raw], dtype=float)
lo = np.array([r[2] for r in raw], dtype=float)
cl = np.array([r[3] for r in raw], dtype=float)

# Simulasi timestamp M5 (300 detik per bar)
now_ts     = int(time.time())
timestamps = [now_ts - (n - i) * 300 for i in range(n)]

# === INDICATORS ===
print("Calculating indicators (EMA50/200 + MACD + ADX + ATR + Fractal)...")
df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": cl})

ema50  = df["close"].ewm(span=50,  adjust=False).mean().values
ema200 = df["close"].ewm(span=200, adjust=False).mean().values

ema12     = df["close"].ewm(span=12, adjust=False).mean()
ema26     = df["close"].ewm(span=26, adjust=False).mean()
macd_line = (ema12 - ema26).values
macd_sig  = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
histogram = macd_line - macd_sig

# ATR 14
hl   = df["high"] - df["low"]
hc   = np.abs(df["high"] - df["close"].shift())
lc   = np.abs(df["low"]  - df["close"].shift())
tr   = pd.concat([hl, hc, lc], axis=1).max(axis=1)
atr  = tr.rolling(14).mean().values
atr_mean20 = tr.rolling(14).mean().rolling(20).mean().values

# ADX 14
up_move   = df["high"] - df["high"].shift()
down_move = df["low"].shift() - df["low"]
plus_dm   = np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0)
minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
tr_ser    = pd.Series(tr)
plus_di   = (100 * (pd.Series(plus_dm).rolling(14).mean()  / tr_ser.rolling(14).mean())).values
minus_di  = (100 * (pd.Series(minus_dm).rolling(14).mean() / tr_ser.rolling(14).mean())).values
with np.errstate(divide="ignore", invalid="ignore"):
    dx  = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
adx = pd.Series(dx).rolling(14).mean().values

# Fractal Williams (2 bar kiri & kanan)
fractal_up   = np.zeros(n)
fractal_down = np.zeros(n)
for idx in range(2, n - 2):
    if hi[idx] > hi[idx-1] and hi[idx] > hi[idx-2] and hi[idx] > hi[idx+1] and hi[idx] > hi[idx+2]:
        fractal_up[idx] = hi[idx]
    if lo[idx] < lo[idx-1] and lo[idx] < lo[idx-2] and lo[idx] < lo[idx+1] and lo[idx] < lo[idx+2]:
        fractal_down[idx] = lo[idx]

print(f"Indicators done in {time.time()-t0:.2f}s")

# === SCORING ENGINE V3 (inline dari decision_engine.py) ===
def score_v3(i, last_frac_up, last_frac_down):
    """Return (action, buy_score, sell_score)"""
    close   = cl[i]
    body    = abs(cl[i] - op[i])
    rng     = hi[i] - lo[i]
    cstr    = body / rng if rng > 0 else 0.0
    bullish = cl[i] > op[i]

    fractal_brk = "NONE"
    if last_frac_up > 0 and close > last_frac_up:
        fractal_brk = "UP"
    elif last_frac_down > 0 and close < last_frac_down:
        fractal_brk = "DOWN"

    buy_s = sell_s = 0

    # Trend (max 25)
    t_ema = 15 if ema50[i] > ema200[i] else 0
    buy_s  += t_ema;         sell_s += (15 - t_ema)
    p_ema  = 10 if close > ema50[i] else 0
    buy_s  += p_ema;         sell_s += (10 - p_ema)

    # Momentum MACD (max 35)
    mc = 20 if macd_line[i] > macd_sig[i] else 0
    buy_s  += mc;            sell_s += (20 - mc)
    hist_up3   = bool(histogram[i] > histogram[i-1] > histogram[i-2] > histogram[i-3])
    hist_down3 = bool(histogram[i] < histogram[i-1] < histogram[i-2] < histogram[i-3])
    if hist_up3:   buy_s  += 15
    if hist_down3: sell_s += 15

    # ADX (max 25) — threshold dinaikkan ke 30
    adx_s = 15 if adx[i] > 30 else 0
    buy_s  += adx_s;         sell_s += adx_s
    di_d   = 10 if plus_di[i] > minus_di[i] else 0
    buy_s  += di_d;          sell_s += (10 - di_d)

    # Candle Strength (max 15)
    if cstr > 0.7:
        if bullish: buy_s  += 15
        else:       sell_s += 15

    # Fractal (max 5)
    if fractal_brk == "UP":   buy_s  += 5
    elif fractal_brk == "DOWN": sell_s += 5

    total = buy_s + sell_s
    if total == 0:
        return "WAIT", 0, 0

    confidence = abs(buy_s - sell_s) / total
    dominant   = "BUY" if buy_s >= sell_s else "SELL"

    if confidence < 0.60:
        return "WAIT", buy_s, sell_s

    action = "WAIT"
    if dominant == "BUY"  and buy_s  >= 75 and buy_s  > sell_s + 15:
        action = "BUY"
    elif dominant == "SELL" and sell_s >= 75 and sell_s > buy_s  + 15:
        action = "SELL"

    return action, buy_s, sell_s

# === SIMULASI MULTI TEST ===
def run_test(sl_mult, tp_mult, label):
    bal          = INITIAL_BAL
    max_bal      = INITIAL_BAL
    max_dd       = 0.0
    pos          = 0
    entry_price  = 0.0
    margin_calls = 0
    pnl_history  = []
    last_frac_up = last_frac_down = 0.0
    WARMUP = 220

    for i in range(WARMUP, n - 1):
        curr_open  = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT) / LEVERAGE

        # Update fractal tracker (konfirmasi 2 bar lalu)
        if fractal_up[i-2]   > 0: last_frac_up   = fractal_up[i-2]
        if fractal_down[i-2] > 0: last_frac_down  = fractal_down[i-2]

        # === CEK SL/TP posisi aktif ===
        if pos != 0:
            atr_val = max(atr[i], 0.050)
            sl = (entry_price - atr_val * sl_mult) if pos == 1 else (entry_price + atr_val * sl_mult)
            tp = (entry_price + atr_val * tp_mult) if pos == 1 else (entry_price - atr_val * tp_mult)
            pnl = None

            if pos == 1:
                if lo[i+1] <= sl:
                    pnl = (sl - entry_price) * LOT_SIZE * CONTRACT; pos = 0
                elif hi[i+1] >= tp:
                    pnl = (tp - entry_price) * LOT_SIZE * CONTRACT; pos = 0
            elif pos == -1:
                if hi[i+1] >= sl:
                    pnl = (entry_price - sl) * LOT_SIZE * CONTRACT; pos = 0
                elif lo[i+1] <= tp:
                    pnl = (entry_price - tp) * LOT_SIZE * CONTRACT; pos = 0

            if pos == 0 and pnl is not None:
                bal += pnl
                pnl_history.append(pnl)
                if bal > max_bal: max_bal = bal
                dd = max_bal - bal
                if dd > max_dd: max_dd = dd
                if bal <= req_margin * 0.2:
                    margin_calls += 1
                    break
            continue

        # === HARD FILTER ===
        # 1. Sesi trading
        if not in_session(timestamps[i]):
            continue
        # 2. ATR harus lebih tinggi dari rata-rata (volatilitas cukup)
        if np.isnan(atr_mean20[i]) or atr[i] < atr_mean20[i]:
            continue

        # === SCORING V3 ===
        action, bs, ss = score_v3(i, last_frac_up, last_frac_down)
        if action not in ("BUY", "SELL"):
            continue
        if req_margin > bal:
            continue

        pos         = 1 if action == "BUY" else -1
        entry_price = curr_open

    pnl_arr    = np.array(pnl_history)
    trades     = len(pnl_arr)
    wins       = int(np.sum(pnl_arr > 0))
    losses     = int(np.sum(pnl_arr < 0))
    total_gain = float(np.sum(pnl_arr[pnl_arr > 0])) if wins > 0 else 0.0
    total_loss = float(np.sum(pnl_arr[pnl_arr < 0])) if losses > 0 else 0.0
    pf         = abs(total_gain / total_loss) if total_loss != 0 else (999.0 if total_gain > 0 else 0.0)
    avg_win    = float(np.mean(pnl_arr[pnl_arr > 0])) if wins > 0 else 0.0
    avg_loss   = float(np.mean(pnl_arr[pnl_arr < 0])) if losses > 0 else 0.0
    win_rate   = wins / trades if trades > 0 else 0.0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss) if trades > 0 else 0.0
    rr_real    = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

    return {
        "label":       label,
        "net_profit":  bal - INITIAL_BAL,
        "final_bal":   bal,
        "trades":      trades,
        "wins":        wins,
        "losses":      losses,
        "win_rate":    win_rate * 100,
        "profit_factor": pf,
        "expectancy":  expectancy,
        "avg_win":     avg_win,
        "avg_loss":    avg_loss,
        "rr_real":     rr_real,
        "max_dd":      max_dd,
        "margin_calls": margin_calls,
    }

# === RUN TESTS ===
tests = [
    (1.5, 3.0, "Test A  SL×1.5  TP×3.0  RR 1:2"),
    (1.0, 2.0, "Test B  SL×1.0  TP×2.0  RR 1:2"),
    (1.0, 3.0, "Test C  SL×1.0  TP×3.0  RR 1:3"),
    (2.0, 4.0, "Test D  SL×2.0  TP×4.0  RR 1:2"),
]

results = []
for sl, tp, label in tests:
    print(f"Running {label} ...")
    res = run_test(sl, tp, label)
    results.append(res)

elapsed = time.time() - t0

# === PRINT RESULT ===
print(f"\n{'='*68}")
print(f"  SCALPER BACKTEST  {SYMBOL}  M5  {BARS} Bars (~20 Hari)")
print(f"  Modal: ${INITIAL_BAL}  Lot: {LOT_SIZE}  Leverage 1:{LEVERAGE}")
print(f"  Logic: Scoring V3 (EMA50/200+MACD+ADX+Fractal+CandleStr+Session)")
print(f"{'='*68}")
for r in results:
    print(f"\n  [{r['label']}]")
    print(f"  Net Profit     : ${r['net_profit']:.4f}  ({r['net_profit']/INITIAL_BAL*100:.2f}%)")
    print(f"  Final Balance  : ${r['final_bal']:.4f}")
    print(f"  Total Trades   : {r['trades']}  ({r['wins']}W / {r['losses']}L)")
    print(f"  Win Rate       : {r['win_rate']:.1f}%")
    print(f"  Profit Factor  : {r['profit_factor']:.2f}")
    print(f"  Expectancy     : ${r['expectancy']:.5f} per trade")
    print(f"  Avg Win / Loss : ${r['avg_win']:.5f} / ${r['avg_loss']:.5f}")
    print(f"  Realized RR    : 1:{r['rr_real']:.2f}")
    print(f"  Max Drawdown   : ${r['max_dd']:.4f}  ({r['max_dd']/INITIAL_BAL*100:.2f}%)")
    print(f"  Margin Calls   : {r['margin_calls']}")
    print(f"  {'-'*50}")

# Pilih terbaik berdasarkan profit factor
best = max(results, key=lambda x: x["profit_factor"] if x["trades"] > 0 else -1)
print(f"\n  ★ TERBAIK: {best['label']}")
print(f"    Net Profit ${best['net_profit']:.4f} | PF {best['profit_factor']:.2f} | WR {best['win_rate']:.1f}%")
print(f"\n  Elapsed : {elapsed:.2f}s")
print(f"{'='*68}")
