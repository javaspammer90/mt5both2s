import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
sys.path.append("/root")
from mt5both2s.modules.mt5_service import MT5Service
from mt5both2s.modules.decision_engine import calculate_decision
from mt5both2s.modules.session_filter import is_in_trading_session

# === CONFIG ===
SYMBOL      = "USDJPY#"
TIMEFRAME   = 5           # M5
BARS        = 5760        # ~20 hari trading M5
INITIAL_BAL = 20.0        # Modal $20
LOT_SIZE    = 0.01        # Minimum lot size
LEVERAGE    = 200         # Leverage 1:200
CONTRACT    = 100000      # 1 Lot USDJPY = 100,000 USD (contract_size)

def run_test(sl_mult, tp_mult, label, raw_json, timestamps):
    n = len(raw_json)
    op  = np.array([float(r[0]) for r in raw_json])
    hi  = np.array([float(r[1]) for r in raw_json])
    lo  = np.array([float(r[2]) for r in raw_json])
    cl  = np.array([float(r[3]) for r in raw_json])

    df = pd.DataFrame(raw_json, columns=['open', 'high', 'low', 'close'])
    ema50 = df['close'].ewm(span=50, adjust=False).mean().values
    ema200 = df['close'].ewm(span=200, adjust=False).mean().values
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = (macd_line - signal_line).values
    macd_l = macd_line.values
    macd_s = signal_line.values
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).mean().values
    atr_mean_20 = true_range.rolling(14).mean().rolling(20).mean().values
    
    up_move = df['high'] - df['high'].shift()
    down_move = df['low'].shift() - df['low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = (100 * (pd.Series(plus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    minus_di = (100 * (pd.Series(minus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx).rolling(14).mean().values
    
    fractal_up = np.zeros(n)
    fractal_down = np.zeros(n)
    for idx in range(2, n - 2):
        if (hi[idx] > hi[idx-1] and hi[idx] > hi[idx-2] and hi[idx] > hi[idx+1] and hi[idx] > hi[idx+2]):
            fractal_up[idx] = hi[idx]
        if (lo[idx] < lo[idx-1] and lo[idx] < lo[idx-2] and lo[idx] < lo[idx+1] and lo[idx] < lo[idx+2]):
            fractal_down[idx] = lo[idx]

    WARMUP = 220
    bal      = INITIAL_BAL
    max_bal  = INITIAL_BAL
    max_dd   = 0.0
    pos      = 0          
    entry_price = 0.0
    margin_calls = 0

    pnl_history = []
    last_frac_up = 0.0
    last_frac_down = 0.0

    for i in range(WARMUP, n - 1):
        curr_open = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT) / LEVERAGE  

        if fractal_up[i-2] > 0:
            last_frac_up = fractal_up[i-2]
        if fractal_down[i-2] > 0:
            last_frac_down = fractal_down[i-2]

        if pos != 0:
            atr_val = max(atr[i], 0.050)
            sl = (entry_price - atr_val * sl_mult) if pos == 1 else (entry_price + atr_val * sl_mult)
            tp = (entry_price + atr_val * tp_mult) if pos == 1 else (entry_price - atr_val * tp_mult)

            pnl = None
            if pos == 1:
                if lo[i+1] <= sl:
                    pnl_jpy = (sl - entry_price) * LOT_SIZE * CONTRACT
                    pnl = pnl_jpy / curr_open
                    pos = 0
                elif hi[i+1] >= tp:
                    pnl_jpy = (tp - entry_price) * LOT_SIZE * CONTRACT
                    pnl = pnl_jpy / curr_open
                    pos = 0
            elif pos == -1:
                if hi[i+1] >= sl:
                    pnl_jpy = (entry_price - sl) * LOT_SIZE * CONTRACT
                    pnl = pnl_jpy / curr_open
                    pos = 0
                elif lo[i+1] <= tp:
                    pnl_jpy = (entry_price - tp) * LOT_SIZE * CONTRACT
                    pnl = pnl_jpy / curr_open
                    pos = 0

            if pos == 0 and pnl is not None:
                bal    += pnl
                pnl_history.append(pnl)
                if bal > max_bal: max_bal = bal
                dd = max_bal - bal
                if dd > max_dd: max_dd = dd
                if bal <= req_margin * 0.2:
                    margin_calls += 1
                    break
            continue

        candle_utc_time = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)
        if not is_in_trading_session(candle_utc_time):
            continue

        if atr[i] < atr_mean_20[i]:
            continue

        body = abs(cl[i] - op[i])
        rng = hi[i] - lo[i]
        candle_strength = body / rng if rng > 0 else 0.0
        is_bullish = cl[i] > op[i]

        current_close = cl[i]
        fractal_breakout = "NONE"
        if last_frac_up > 0 and current_close > last_frac_up:
            fractal_breakout = "UP"
        elif last_frac_down > 0 and current_close < last_frac_down:
            fractal_breakout = "DOWN"

        market_data = {
            "symbol": SYMBOL,
            "current_close": current_close,
            "ema50": ema50[i],
            "ema200": ema200[i],
            "macd_main": macd_l[i],
            "macd_sig": macd_s[i],
            "macd_hist_up_3": bool(histogram[i] > histogram[i-1] and histogram[i-1] > histogram[i-2] and histogram[i-2] > histogram[i-3]),
            "macd_hist_down_3": bool(histogram[i] < histogram[i-1] and histogram[i-1] < histogram[i-2] and histogram[i-2] < histogram[i-3]),
            "adx": adx[i],
            "plus_di": plus_di[i],
            "minus_di": minus_di[i],
            "atr": atr[i],
            "atr_mean_20": atr_mean_20[i],
            "fractal_breakout": fractal_breakout,
            "candle_strength": candle_strength,
            "is_bullish": is_bullish,
            "spread": 12 
        }

        decision = calculate_decision(market_data, similarity_score=0.0)
        
        if decision["action"] in ["BUY", "SELL"]:
            if req_margin > bal:
                continue
            pos         = 1 if decision["action"] == "BUY" else -1
            entry_price = curr_open

    pnl_arr = np.array(pnl_history)
    trades = len(pnl_arr)
    wins = np.sum(pnl_arr > 0)
    losses = np.sum(pnl_arr < 0)
    
    total_gain = np.sum(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    total_loss = np.sum(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    profit_factor = abs(total_gain / total_loss) if total_loss != 0 else (999.0 if total_gain > 0 else 0.0)
    
    avg_win = np.mean(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    avg_loss = np.mean(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    largest_win = np.max(pnl_arr) if np.any(pnl_arr > 0) else 0.0
    largest_loss = np.min(pnl_arr) if np.any(pnl_arr < 0) else 0.0
    
    rr_real = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    
    win_rate = (wins / trades) if trades > 0 else 0.0
    expectancy = (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss) if trades > 0 else 0.0
    
    net_profit = bal - INITIAL_BAL
    
    return {
        "label": label,
        "net_profit": net_profit,
        "trades": trades,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "rr_real": rr_real,
        "expectancy": expectancy,
        "win_rate": win_rate * 100
    }

if __name__ == "__main__":
    t0 = time.time()
    mt5 = MT5Service()
    if not mt5.connect():
        print("Failed to connect to MT5.")
        sys.exit(1)

    print(f"Fetching {BARS} bars {SYMBOL} M5 via fast bulk JSON...")
    raw_json = mt5.get_bulk_rates(SYMBOL, TIMEFRAME, BARS)
    if not raw_json:
        print("Failed to fetch rates via bulk.")
        sys.exit(1)
        
    print("Generating simulated timestamps to avoid slow RPyC loops...")
    # Menghindari loop konversi RPyC dict yang lambat (46 detik) dengan simulasi timestamp 5 menit per candle
    now_ts = int(time.time())
    timestamps = [now_ts - (len(raw_json) - i) * 300 for i in range(len(raw_json))]

    tests = [
        (1.5, 3.0, "Test A (SL ATRx1.5, TP ATRx3.0, RR 1:2)"),
        (1.0, 2.0, "Test B (SL ATRx1.0, TP ATRx2.0, RR 1:2)"),
        (1.0, 3.0, "Test C (SL ATRx1.0, TP ATRx3.0, RR 1:3)"),
    ]
    
    results = []
    for sl, tp, label in tests:
        res = run_test(sl, tp, label, raw_json, timestamps)
        if res:
            results.append(res)
            
    print(f"\n{'='*72}")
    print(f"  COMPARISON: USDJPY# M5 | ~20 Hari | Modal $20 | Leverage 1:200")
    print(f"{'='*72}")
    for r in results:
        print(f" {r['label']}")
        print(f"  Net Profit     : ${r['net_profit']:.2f}")
        print(f"  Profit Factor  : {r['profit_factor']:.2f}")
        print(f"  Expectancy     : ${r['expectancy']:.3f} per trade")
        print(f"  Total Trades   : {r['trades']}")
        print(f"  Win Rate       : {r['win_rate']:.1f}%")
        print(f"  Avg Win/Loss   : ${r['avg_win']:.2f} / ${r['avg_loss']:.2f}")
        print(f"  Largest W/L    : ${r['largest_win']:.2f} / ${r['largest_loss']:.2f}")
        print(f"  Realized RR    : 1:{r['rr_real']:.2f}")
        print(f"{'-'*72}")
