"""
backtestscalperxauusd.py
Scalper Backtest — XAUUSD# M15 + H1 Trend Confirmation
Logic tambahan vs backtestscalper.py:
  - ADX < 20 → SKIP (hanya masuk saat trend cukup kuat)
  - H1 EMA20 bias: BUY hanya jika H1 close > EMA20 (H1 bullish)
                   SELL hanya jika H1 close < EMA20 (H1 bearish)
  - PnL langsung USD (XAUUSD, bukan forex)
  - Multi SL/TP test: A, B, C, D
"""

import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, time as dtime
sys.path.append("/root")
import rpyc

# === CONFIG ===
SYMBOL      = "XAUUSD#"
TF_M15      = 15            # M15
TF_H1       = 16385         # H1 (MT5 enum)
BARS_M15    = 5760          # ~60 hari M15
BARS_H1     = 500           # ~500 jam H1
INITIAL_BAL = 1000.0
LOT_SIZE    = 0.01
LEVERAGE    = 200
CONTRACT    = 100           # XAUUSD 100 oz per lot
SPREAD      = 300           # spread estimasi XAUUSD (point)

# === SESSION FILTER: London 07:00-11:00 UTC ===
def in_session(ts_unix: float) -> bool:
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    london = dtime(7, 0) <= t <= dtime(11, 0)
    return london

# === FETCH DATA ===
print("Connecting to MT5 RPyC 127.0.0.1:18812 ...")
t0 = time.time()
c  = rpyc.connect("127.0.0.1", 18812)

# M15 data
j_m15  = c.root.bulk_rates_json(SYMBOL, TF_M15, BARS_M15)
raw_m15 = json.loads(j_m15)
print(f"Fetched {len(raw_m15)} bars M15 in {time.time()-t0:.2f}s")

# H1 data
j_h1   = c.root.bulk_rates_json(SYMBOL, TF_H1, BARS_H1)
raw_h1  = json.loads(j_h1)
print(f"Fetched {len(raw_h1)} bars H1 in {time.time()-t0:.2f}s")

# === PARSE M15 ===
n   = len(raw_m15)
op  = np.array([r[0] for r in raw_m15], dtype=float)
hi  = np.array([r[1] for r in raw_m15], dtype=float)
lo  = np.array([r[2] for r in raw_m15], dtype=float)
cl  = np.array([r[3] for r in raw_m15], dtype=float)

# Simulasi timestamp M15 (900 detik per bar)
now_ts      = int(time.time())
ts_m15      = [now_ts - (n - i) * 900 for i in range(n)]

# === PARSE H1 ===
n_h1   = len(raw_h1)
cl_h1  = np.array([r[3] for r in raw_h1], dtype=float)

# EMA20 H1
def ema_np(arr, span):
    k   = 2.0 / (span + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

ema20_h1   = ema_np(cl_h1, 20)
# Timestamp H1 (3600 detik per bar)
ts_h1      = [now_ts - (n_h1 - i) * 3600 for i in range(n_h1)]

def get_h1_bias(ts_unix: float) -> str:
    """Cari H1 bar terdekat sebelum ts_unix, return BULL/BEAR/NEUTRAL"""
    # cari index H1 terakhir sebelum ts_unix
    idx = -1
    for j in range(n_h1 - 1, -1, -1):
        if ts_h1[j] <= ts_unix:
            idx = j
            break
    if idx < 0 or np.isnan(ema20_h1[idx]):
        return "NEUTRAL"
    return "BULL" if cl_h1[idx] > ema20_h1[idx] else "BEAR"

# === M15 INDICATORS ===
print("Calculating M15 indicators (EMA50/200 + MACD + ADX + ATR + Fractal)...")
df = pd.DataFrame({"open": op, "high": hi, "low": lo, "close": cl})

ema50  = df["close"].ewm(span=50,  adjust=False).mean().values
ema200 = df["close"].ewm(span=200, adjust=False).mean().values

ema12     = df["close"].ewm(span=12, adjust=False).mean()
ema26     = df["close"].ewm(span=26, adjust=False).mean()
macd_line = (ema12 - ema26).values
macd_sig  = pd.Series(macd_line).ewm(span=9, adjust=False).mean().values
histogram = macd_line - macd_sig

# ATR 14
hl  = df["high"] - df["low"]
hc  = np.abs(df["high"] - df["close"].shift())
lc  = np.abs(df["low"]  - df["close"].shift())
tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
atr = tr.rolling(14).mean().values
atr_mean20 = tr.rolling(14).mean().rolling(20).mean().values

# ADX 14
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

# Fractal Williams (2 bar kiri & kanan)
fractal_up   = np.zeros(n)
fractal_down = np.zeros(n)
for idx in range(2, n - 2):
    if hi[idx] > hi[idx-1] and hi[idx] > hi[idx-2] and hi[idx] > hi[idx+1] and hi[idx] > hi[idx+2]:
        fractal_up[idx] = hi[idx]
    if lo[idx] < lo[idx-1] and lo[idx] < lo[idx-2] and lo[idx] < lo[idx+1] and lo[idx] < lo[idx+2]:
        fractal_down[idx] = lo[idx]

print(f"Indicators done in {time.time()-t0:.2f}s")

# === SCORING ENGINE V3 (inline) ===
def score_v3(i, last_frac_up, last_frac_down):
    close   = cl[i]
    body    = abs(cl[i] - op[i])
    rng     = hi[i] - lo[i]
    cstr    = body / rng if rng > 0 else 0.0
    bullish = cl[i] > op[i]

    fbrk = "NONE"
    if last_frac_up > 0 and close > last_frac_up:
        fbrk = "UP"
    elif last_frac_down > 0 and close < last_frac_down:
        fbrk = "DOWN"

    buy_s = sell_s = 0

    # Trend EMA (max 25)
    t_ema = 15 if ema50[i] > ema200[i] else 0
    buy_s += t_ema;          sell_s += (15 - t_ema)
    p_ema = 10 if close > ema50[i] else 0
    buy_s += p_ema;          sell_s += (10 - p_ema)

    # MACD (max 35)
    mc = 20 if macd_line[i] > macd_sig[i] else 0
    buy_s += mc;             sell_s += (20 - mc)
    h3u = bool(histogram[i] > histogram[i-1] > histogram[i-2] > histogram[i-3])
    h3d = bool(histogram[i] < histogram[i-1] < histogram[i-2] < histogram[i-3])
    if h3u: buy_s  += 15
    if h3d: sell_s += 15

    # ADX (max 25) — threshold 30
    adx_s = 15 if adx[i] > 30 else 0
    buy_s += adx_s;          sell_s += adx_s
    di_d  = 10 if plus_di[i] > minus_di[i] else 0
    buy_s += di_d;           sell_s += (10 - di_d)

    # Candle Strength (max 15)
    if cstr > 0.7:
        if bullish: buy_s  += 15
        else:       sell_s += 15

    # Fractal (max 5)
    if fbrk == "UP":   buy_s  += 5
    elif fbrk == "DOWN": sell_s += 5

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

# === SIMULASI ===
def run_test(sl_mult, tp_mult, label):
    bal          = INITIAL_BAL
    max_bal      = INITIAL_BAL
    max_dd       = 0.0
    pos          = 0
    entry_price  = 0.0
    margin_calls = 0
    pnl_history  = []
    last_frac_up = last_frac_down = 0.0
    skipped_adx = skipped_h1 = skipped_session = skipped_vol = 0
    WARMUP = 220

    for i in range(WARMUP, n - 1):
        curr_open  = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT * curr_open) / LEVERAGE

        if fractal_up[i-2]   > 0: last_frac_up   = fractal_up[i-2]
        if fractal_down[i-2] > 0: last_frac_down  = fractal_down[i-2]

        # === CEK SL/TP posisi aktif ===
        if pos != 0:
            atr_val = max(atr[i], 0.5)
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

        # === HARD FILTER 1: Session ===
        if not in_session(ts_m15[i]):
            skipped_session += 1
            continue

        # === HARD FILTER 2: Volatilitas ATR > ATRmean × 0.8 ===
        if np.isnan(atr_mean20[i]) or atr[i] < atr_mean20[i] * 0.8:
            skipped_vol += 1
            continue

        # === HARD FILTER 3: ADX < 18 → SKIP ===
        if np.isnan(adx[i]) or adx[i] < 18:
            skipped_adx += 1
            continue

        # === SCORING V3 ===
        action, bs, ss = score_v3(i, last_frac_up, last_frac_down)
        if action not in ("BUY", "SELL"):
            continue

        # === HARD FILTER 4: H1 Konfirmasi EMA20 ===
        h1_bias = get_h1_bias(ts_m15[i])
        if action == "BUY"  and h1_bias != "BULL":
            skipped_h1 += 1
            continue
        if action == "SELL" and h1_bias != "BEAR":
            skipped_h1 += 1
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
        "label":          label,
        "net_profit":     bal - INITIAL_BAL,
        "final_bal":      bal,
        "trades":         trades,
        "wins":           wins,
        "losses":         losses,
        "win_rate":       win_rate * 100,
        "profit_factor":  pf,
        "expectancy":     expectancy,
        "avg_win":        avg_win,
        "avg_loss":       avg_loss,
        "rr_real":        rr_real,
        "max_dd":         max_dd,
        "margin_calls":   margin_calls,
        "skip_session":   skipped_session,
        "skip_vol":       skipped_vol,
        "skip_adx":       skipped_adx,
        "skip_h1":        skipped_h1,
    }

# === RUN ===
tests = [
    (1.0, 2.0, "Test A  SL×1.0  TP×2.0  RR 1:2"),
    (1.0, 3.0, "Test B  SL×1.0  TP×3.0  RR 1:3"),
    (1.5, 3.0, "Test C  SL×1.5  TP×3.0  RR 1:2"),
]

results = []
for sl, tp, label in tests:
    print(f"Running {label} ...")
    results.append(run_test(sl, tp, label))

elapsed = time.time() - t0

# === OUTPUT ===
print(f"\n{'='*70}")
print(f"  SCALPER BACKTEST  {SYMBOL}  M15 + H1 Konfirmasi")
print(f"  Modal: ${INITIAL_BAL}  Lot: {LOT_SIZE}  Leverage 1:{LEVERAGE}  Spread: {SPREAD}")
print(f"  Filter: Session London 07-11 UTC | ADX≥18 | ATR>ATRmean×0.8 | H1 EMA20")
print(f"{'='*70}")
for r in results:
    print(f"\n  [{r['label']}]")
    print(f"  Net Profit     : ${r['net_profit']:.4f}  ({r['net_profit']/INITIAL_BAL*100:.2f}%)")
    print(f"  Final Balance  : ${r['final_bal']:.4f}")
    print(f"  Total Trades   : {r['trades']}  ({r['wins']}W / {r['losses']}L)")
    print(f"  Win Rate       : {r['win_rate']:.1f}%")
    print(f"  Profit Factor  : {r['profit_factor']:.2f}")
    print(f"  Expectancy     : ${r['expectancy']:.4f} per trade")
    print(f"  Avg Win / Loss : ${r['avg_win']:.4f} / ${r['avg_loss']:.4f}")
    print(f"  Realized RR    : 1:{r['rr_real']:.2f}")
    print(f"  Max Drawdown   : ${r['max_dd']:.4f}  ({r['max_dd']/INITIAL_BAL*100:.2f}%)")
    print(f"  Margin Calls   : {r['margin_calls']}")
    print(f"  Skip Session   : {r['skip_session']}  | Skip Vol: {r['skip_vol']}")
    print(f"  Skip ADX<20    : {r['skip_adx']}  | Skip H1 bias: {r['skip_h1']}")
    print(f"  {'-'*55}")

best = max(results, key=lambda x: x["profit_factor"] if x["trades"] > 0 else -1)
print(f"\n  ★ TERBAIK: {best['label']}")
print(f"    Net Profit ${best['net_profit']:.4f} | PF {best['profit_factor']:.2f} | WR {best['win_rate']:.1f}% | DD {best['max_dd']/INITIAL_BAL*100:.1f}%")
print(f"\n  Elapsed : {elapsed:.2f}s")
print(f"{'='*70}")
