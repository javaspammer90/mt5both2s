import sys, time, json
import numpy as np
sys.path.append("/root")
import rpyc

SYMBOL      = "XAUUSD#"
TIMEFRAME   = 15
BARS        = 2880        # ~30 hari M15
INITIAL_BAL = 20.0
LOT_SIZE    = 0.001
LEVERAGE    = 200
CONTRACT    = 100         # XAUUSD 100 oz/lot standar

def ema_np(arr, span):
    k = 2.0 / (span + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out

def rolling_mean(arr, w):
    cs = np.cumsum(arr)
    cs[w:] = cs[w:] - cs[:-w]
    out = np.full(len(arr), np.nan)
    out[w-1:] = cs[w-1:] / w
    return out

def rolling_std(arr, w):
    out = np.full(len(arr), np.nan)
    for i in range(w-1, len(arr)):
        out[i] = arr[i-w+1:i+1].std()
    return out

t0 = time.time()
c  = rpyc.connect("127.0.0.1", 18812)
j  = c.root.bulk_rates_json(SYMBOL, TIMEFRAME, BARS)
raw = json.loads(j)
print(f"Fetched {len(raw)} bars in {time.time()-t0:.2f}s")

op = np.array([r[0] for r in raw])
hi = np.array([r[1] for r in raw])
lo = np.array([r[2] for r in raw])
cl = np.array([r[3] for r in raw])

print("Calculating indicators (Python AI Logic: EMA20/50 + BB20,2 + RSI14 + ATR14 + Regime)...")

# === PYTHON AI INDICATORS (sama dengan indicator_engine.py) ===

# EMA 20 & 50
ema20 = ema_np(cl, 20)
ema50 = ema_np(cl, 50)

# RSI 14
delta = np.diff(cl, prepend=cl[0])
gain  = rolling_mean(np.where(delta > 0, delta, 0.0), 14)
loss  = rolling_mean(np.where(delta < 0, -delta, 0.0), 14)
with np.errstate(divide='ignore', invalid='ignore'):
    rsi = np.where(loss == 0, 100.0, 100 - 100 / (1 + gain / loss))

# BB 20
bm  = rolling_mean(cl, 20)
bs  = rolling_std(cl, 20)
bu  = bm + 2 * bs
bl  = bm - 2 * bs

# ATR 14
tr  = np.maximum(hi - lo,
      np.maximum(np.abs(hi - np.roll(cl, 1)),
                 np.abs(lo - np.roll(cl, 1))))
tr[0] = hi[0] - lo[0]
atr = rolling_mean(tr, 14)

# avg ATR 20 (untuk regime)
avg_atr20 = rolling_mean(atr, 20)

print(f"Indicators done in {time.time()-t0:.2f}s. Simulating (Python AI decision_engine logic)...")

WARMUP  = 70  # beri cukup buffer agar semua indikator stabil
bal     = INITIAL_BAL
max_bal = INITIAL_BAL
max_dd  = 0.0
pos     = 0
entry_p = 0.0
trades = wins = skipped = margin_calls = 0
trade_log = []

for i in range(WARMUP, len(cl) - 1):
    # Margin check XAUUSD: (lot * contract * price) / leverage
    req_margin = (LOT_SIZE * CONTRACT * op[i+1]) / LEVERAGE

    if pos != 0:
        sl = (entry_p - atr[i] * 2) if pos == 1 else (entry_p + atr[i] * 2)
        tp = (entry_p + atr[i] * 3) if pos == 1 else (entry_p - atr[i] * 3)
        pnl = None

        if pos == 1:
            if lo[i+1] <= sl:
                pnl = (sl - entry_p) * LOT_SIZE * CONTRACT; pos = 0
            elif hi[i+1] >= tp:
                pnl = (tp - entry_p) * LOT_SIZE * CONTRACT; pos = 0
        else:
            if hi[i+1] >= sl:
                pnl = (entry_p - sl) * LOT_SIZE * CONTRACT; pos = 0
            elif lo[i+1] <= tp:
                pnl = (entry_p - tp) * LOT_SIZE * CONTRACT; pos = 0

        if pos == 0 and pnl is not None:
            bal    += pnl
            trades += 1
            if pnl > 0: wins += 1
            if bal > max_bal: max_bal = bal
            dd = max_bal - bal
            if dd > max_dd: max_dd = dd
            trade_log.append(round(float(pnl), 4))
            if bal <= 0:
                margin_calls += 1
                break
        continue

    # === PYTHON AI DECISION ENGINE LOGIC ===
    # Trend alignment (EMA20 vs EMA50)
    trend_up   = ema20[i] > ema50[i]
    trend_down = ema20[i] < ema50[i]

    # Regime (TRENDING jika ADX proxy: ema slope kuat)
    # Kita gunakan simplified: atr vs avg_atr20
    if not np.isnan(avg_atr20[i]):
        if atr[i] > avg_atr20[i] * 1.5:
            regime = "VOLATILE"
        elif atr[i] < avg_atr20[i] * 0.5:
            regime = "QUIET"
        else:
            regime = "RANGING"
    else:
        regime = "RANGING"

    # BB Signal
    bb_buy  = cl[i] <= bl[i]       # nembus lower band
    bb_sell = cl[i] >= bu[i]       # nembus upper band

    # RSI Confirmation
    rsi_buy  = rsi[i] <= 30
    rsi_sell = rsi[i] >= 70

    # Strict Trend Filter (AI: anulir counter-trend)
    buy_sig  = bb_buy  and rsi_buy  and trend_up   and regime != "VOLATILE"
    sell_sig = bb_sell and rsi_sell and trend_down and regime != "VOLATILE"

    if buy_sig or sell_sig:
        if req_margin > bal:
            skipped += 1
            continue
        pos     = 1 if buy_sig else -1
        entry_p = op[i+1]

elapsed = time.time() - t0
profit  = bal - INITIAL_BAL
wr      = (wins / trades * 100) if trades > 0 else 0.0

print(f"\n{'='*56}")
print(f"  BACKTEST  {SYMBOL}  M15  ~30 Hari  Leverage 1:{LEVERAGE}")
print(f"  Logic: Python AI (BB+RSI+EMA Trend+Regime Filter)")
print(f"{'='*56}")
print(f"  Modal Awal     : ${INITIAL_BAL:.2f}")
print(f"  Final Balance  : ${bal:.4f}")
print(f"  Net Profit     : ${profit:.4f}  ({profit/INITIAL_BAL*100:.2f}%)")
print(f"  Total Trades   : {trades}")
print(f"  Win Rate       : {wr:.1f}%  ({wins}W / {trades-wins}L)")
print(f"  Max Drawdown   : ${max_dd:.4f}  ({max_dd/INITIAL_BAL*100:.2f}%)")
print(f"  Margin Calls   : {margin_calls}")
print(f"  Skipped        : {skipped}")
print(f"  Trade PnL Log  : {trade_log}")
print(f"  Elapsed        : {elapsed:.2f}s")
print(f"{'='*56}")
