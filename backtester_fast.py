import sys, time
import numpy as np
sys.path.append("/root")
from mt5both2s.modules.mt5_service import MT5Service

# === CONFIG ===
SYMBOL      = "XAUUSD#"
TIMEFRAME   = 15
BARS        = 2880        # ~30 hari trading M15
INITIAL_BAL = 100.0
LOT_SIZE    = 0.01
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
    out = np.full(len(arr), np.nan)
    for i in range(w-1, len(arr)):
        out[i] = arr[i-w+1:i+1].mean()
    return out

def rolling_std(arr, w):
    out = np.full(len(arr), np.nan)
    for i in range(w-1, len(arr)):
        out[i] = arr[i-w+1:i+1].std()
    return out

def run_backtest():
    t0 = time.time()
    mt5 = MT5Service()
    mt5.connect()

    print(f"Fetching {BARS} bars {SYMBOL} M15...")
    raw = mt5.get_rates(SYMBOL, TIMEFRAME, BARS)
    n   = len(raw)
    print(f"Got {n} bars in {time.time()-t0:.2f}s. Building arrays...")

    op  = np.array([float(r['open'])  for r in raw])
    hi  = np.array([float(r['high'])  for r in raw])
    lo  = np.array([float(r['low'])   for r in raw])
    cl  = np.array([float(r['close']) for r in raw])

    print(f"Calculating indicators...")
    ema50 = ema_np(cl, 50)

    # RSI 14
    delta = np.diff(cl, prepend=cl[0])
    gain  = rolling_mean(np.where(delta > 0, delta, 0), 14)
    loss  = rolling_mean(np.where(delta < 0, -delta, 0), 14)
    with np.errstate(divide='ignore', invalid='ignore'):
        rs  = np.where(loss == 0, 100, gain / loss)
    rsi = 100 - (100 / (1 + rs))

    # BB 20
    bm  = rolling_mean(cl, 20)
    bs  = rolling_std(cl, 20)
    bu  = bm + 2 * bs
    bl  = bm - 2 * bs

    # ATR 14
    tr  = np.maximum(hi - lo, np.maximum(np.abs(hi - np.roll(cl, 1)), np.abs(lo - np.roll(cl, 1))))
    tr[0] = hi[0] - lo[0]
    atr = rolling_mean(tr, 14)

    # warmup: mulai dari bar 60 (biar semua indikator stabil)
    WARMUP = 60

    print(f"Simulating... (bars={n}, warmup={WARMUP})")
    bal      = INITIAL_BAL
    max_bal  = INITIAL_BAL
    max_dd   = 0.0
    pos      = 0
    entry_price = 0.0
    trades   = 0
    wins     = 0
    skipped  = 0
    margin_calls = 0

    for i in range(WARMUP, n - 1):
        curr_open = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT * curr_open) / LEVERAGE

        if pos != 0:
            sl = (entry_price - atr[i] * 2) if pos == 1 else (entry_price + atr[i] * 2)
            tp = (entry_price + atr[i] * 3) if pos == 1 else (entry_price - atr[i] * 3)

            pnl = None
            if pos == 1:
                if lo[i+1] <= sl:
                    pnl = (sl - entry_price) * LOT_SIZE * CONTRACT
                    pos = 0
                elif hi[i+1] >= tp:
                    pnl = (tp - entry_price) * LOT_SIZE * CONTRACT
                    pos = 0
            elif pos == -1:
                if hi[i+1] >= sl:
                    pnl = (entry_price - sl) * LOT_SIZE * CONTRACT
                    pos = 0
                elif lo[i+1] <= tp:
                    pnl = (entry_price - tp) * LOT_SIZE * CONTRACT
                    pos = 0

            if pos == 0 and pnl is not None:
                bal    += pnl
                trades += 1
                if pnl > 0: wins += 1
                if bal > max_bal: max_bal = bal
                dd = max_bal - bal
                if dd > max_dd: max_dd = dd
                if bal <= 0:
                    margin_calls += 1
                    break
            continue

        # Signal (EA Logic: BB + RSI + EMA Trend)
        buy_sig  = cl[i] <= bl[i] and rsi[i] <= 30 and cl[i] > ema50[i]
        sell_sig = cl[i] >= bu[i] and rsi[i] >= 70 and cl[i] < ema50[i]

        if buy_sig or sell_sig:
            if req_margin > bal:
                skipped += 1
                continue
            pos         = 1 if buy_sig else -1
            entry_price = curr_open

    t1 = time.time()
    profit = bal - INITIAL_BAL
    wr = (wins / trades * 100) if trades > 0 else 0

    print(f"\n{'='*52}")
    print(f"  BACKTEST: {SYMBOL} M15 | ~30 Hari | Lev 1:{LEVERAGE}")
    print(f"{'='*52}")
    print(f"  Modal Awal     : ${INITIAL_BAL:.2f}")
    print(f"  Final Balance  : ${bal:.2f}")
    print(f"  Net Profit     : ${profit:.2f}  ({profit/INITIAL_BAL*100:.1f}%)")
    print(f"  Total Trades   : {trades}")
    print(f"  Win Rate       : {wr:.1f}%  ({wins}W / {trades-wins}L)")
    print(f"  Max Drawdown   : ${max_dd:.2f}  ({max_dd/INITIAL_BAL*100:.1f}%)")
    print(f"  Margin Calls   : {margin_calls}")
    print(f"  Skipped (no mg): {skipped}")
    print(f"  Elapsed        : {t1-t0:.1f}s")
    print(f"{'='*52}")

run_backtest()
