import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.append("/root")
from mt5both2s.modules.mt5_service import MT5Service
from mt5both2s.modules.decision_engine import calculate_decision
from mt5both2s.modules.session_filter import is_in_trading_session

# === CONFIG ===
SYMBOL      = "XAUUSD#"
TIMEFRAME   = 15          # M15
BARS        = 2880        # ~30 hari trading M15
INITIAL_BAL = 100.0       # Modal $100 (XAUUSD disarankan $100 karena contract size dan margin requirement)
LOT_SIZE    = 0.01        # Minimum lot size
LEVERAGE    = 200         # Leverage 1:200
CONTRACT    = 100         # 1 Lot XAUUSD = 100 Oz

# MQL5 Parameters
InpMinEntryScore = 60
InpMinConfidenceScore = 50
InpRSIPeriod = 14
InpRSIOverbought = 70.0
InpRSIOversold = 30.0

def run_python_ai_backtest(raw_json, timestamps):
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

    # Gunakan setting terbaik: Test B (SL=1.0xATR, TP=2.0xATR)
    sl_mult = 1.0
    tp_mult = 2.0

    for i in range(WARMUP, n - 1):
        curr_open = op[i+1]
        # XAUUSD required margin in USD: (lot * contract * price) / leverage
        # e.g. (0.01 * 100 * 4150) / 200 = $20.75 margin
        req_margin = (LOT_SIZE * CONTRACT * curr_open) / LEVERAGE  

        if fractal_up[i-2] > 0:
            last_frac_up = fractal_up[i-2]
        if fractal_down[i-2] > 0:
            last_frac_down = fractal_down[i-2]

        if pos != 0:
            atr_val = max(atr[i], 2.0) # minimal 2 USD move
            sl = (entry_price - atr_val * sl_mult) if pos == 1 else (entry_price + atr_val * sl_mult)
            tp = (entry_price + atr_val * tp_mult) if pos == 1 else (entry_price - atr_val * tp_mult)

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
            "spread": 240 # XAUUSD spread simulation: 240 points
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
    
    total_gain = np.sum(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    total_loss = np.sum(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    profit_factor = abs(total_gain / total_loss) if total_loss != 0 else (999.0 if total_gain > 0 else 0.0)
    avg_win = np.mean(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    avg_loss = np.mean(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    rr_real = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    win_rate = (wins / trades) * 100 if trades > 0 else 0.0
    expectancy = (win_rate/100 * avg_win) + ((1.0 - win_rate/100) * avg_loss) if trades > 0 else 0.0
    
    return {
        "net_profit": bal - INITIAL_BAL,
        "trades": trades,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr_real": rr_real,
        "max_dd": max_dd
    }

def run_mql5_backtest(raw_json, timestamps):
    n = len(raw_json)
    op  = np.array([float(r[0]) for r in raw_json])
    hi  = np.array([float(r[1]) for r in raw_json])
    lo  = np.array([float(r[2]) for r in raw_json])
    cl  = np.array([float(r[3]) for r in raw_json])

    tick_vol = np.ones(n) * 100

    df = pd.DataFrame(raw_json, columns=['open', 'high', 'low', 'close'])
    
    bb_middle = df['close'].rolling(window=20).mean().values
    bb_std = df['close'].rolling(window=20).std().values
    bb_upper = bb_middle + (2 * bb_std)
    bb_lower = bb_middle - (2 * bb_std)

    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).values

    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).mean().values
    
    up_move = df['high'] - df['high'].shift()
    down_move = df['low'].shift() - df['low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = (100 * (pd.Series(plus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    minus_di = (100 * (pd.Series(minus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx).rolling(14).mean().values

    # MTF (M15 & H1 simulated on M15 -> M45 and H3)
    ema_m15_proxy = df['close'].ewm(span=150, adjust=False).mean().values
    ema_h1_proxy = df['close'].ewm(span=600, adjust=False).mean().values

    WARMUP = 600
    bal = INITIAL_BAL
    max_bal = INITIAL_BAL
    max_dd = 0.0
    pos = 0 
    entry_price = 0.0
    pnl_history = []

    diffs = cl - op
    corr_cache = np.full(n, 50.0)
    
    for idx in range(WARMUP, n - 1):
        curr_p = diffs[idx-7:idx+1]
        std_c = curr_p.std()
        if std_c == 0: continue
            
        lookback_start = max(WARMUP - 150, idx - 142)
        lookback_end = idx - 10
        matches = 0
        successes = 0
        
        for h in range(lookback_start, lookback_end):
            hist_p = diffs[h:h+8]
            std_h = hist_p.std()
            if std_h == 0: continue
            
            cov = np.dot(curr_p - curr_p.mean(), hist_p - hist_p.mean()) / 8
            corr = cov / (std_c * std_h)
            
            if corr > 0.70:
                matches += 1
                if cl[h+11] > cl[h+8]: successes += 1
                    
        if matches > 0:
            corr_cache[idx] = (successes / matches) * 100.0

    for i in range(WARMUP, n - 1):
        curr_open = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT * curr_open) / LEVERAGE  

        if pos != 0:
            # Trailing stop ATR based (TSStart: 1.5, TStop: 1.0)
            atr_val = max(atr[i], 2.0)
            sl = (entry_price - atr_val * 2.0) if pos == 1 else (entry_price + atr_val * 2.0)
            tp = (entry_price + atr_val * 3.0) if pos == 1 else (entry_price - atr_val * 3.0)

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
                bal += pnl
                pnl_history.append(pnl)
                if bal > max_bal: max_bal = bal
                dd = max_bal - bal
                if dd > max_dd: max_dd = dd
                if bal <= req_margin * 0.2:
                    break
            continue

        buy_sig = cl[i] <= bb_lower[i] and rsi[i] <= InpRSIOversold
        sell_sig = cl[i] >= bb_upper[i] and rsi[i] >= InpRSIOverbought

        if not (buy_sig or sell_sig):
            continue

        confidence = corr_cache[i]
        if confidence < InpMinConfidenceScore:
            continue

        entry_score = 0
        if buy_sig:
            if cl[i] > ema_m15_proxy[i]: entry_score += 10
            if cl[i] > ema_h1_proxy[i]: entry_score += 10
        else:
            if cl[i] < ema_m15_proxy[i]: entry_score += 10
            if cl[i] < ema_h1_proxy[i]: entry_score += 10
            
        rsi_slope = rsi[i] - rsi[i-1]
        if buy_sig:
            if rsi[i] <= InpRSIOversold: entry_score += 10
            if rsi_slope > 0: entry_score += 10
        else:
            if rsi[i] >= InpRSIOverbought: entry_score += 10
            if rsi_slope < 0: entry_score += 10

        entry_score += 15.0 # ideal width
        if buy_sig:
            if cl[i] <= bb_lower[i]: entry_score += 15
        else:
            if cl[i] >= bb_upper[i]: entry_score += 15

        avg_vol = tick_vol[i-20:i].mean()
        if tick_vol[i] >= avg_vol: entry_score += 10
        else: entry_score += 5

        entry_score += 10 
        if confidence >= 60.0: entry_score += 10
        elif confidence >= 50.0: entry_score += 5

        if entry_score < InpMinEntryScore:
            continue

        sum_atr_20 = atr[i-20:i].mean()
        regime = "RANGING"
        if atr[i] > sum_atr_20 * 1.5:
            regime = "VOLATILE"
        elif atr[i] < sum_atr_20 * 0.5:
            regime = "QUIET"
        elif adx[i] > 25:
            regime = "TRENDING"

        trend_dir = "UP" if (cl[i] > ema_m15_proxy[i] and cl[i] > ema_h1_proxy[i]) else "DOWN"
        if regime == "TRENDING":
            if buy_sig and trend_dir == "DOWN": continue
            if sell_sig and trend_dir == "UP": continue

        pos = 1 if buy_sig else -1
        entry_price = curr_open

    pnl_arr = np.array(pnl_history)
    trades = len(pnl_arr)
    wins = np.sum(pnl_arr > 0)
    
    total_gain = np.sum(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    total_loss = np.sum(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    profit_factor = abs(total_gain / total_loss) if total_loss != 0 else (999.0 if total_gain > 0 else 0.0)
    avg_win = np.mean(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    avg_loss = np.mean(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    rr_real = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    win_rate = (wins / trades) * 100 if trades > 0 else 0.0
    expectancy = (win_rate/100 * avg_win) + ((1.0 - win_rate/100) * avg_loss) if trades > 0 else 0.0
    
    return {
        "net_profit": bal - INITIAL_BAL,
        "trades": trades,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr_real": rr_real,
        "max_dd": max_dd
    }

if __name__ == "__main__":
    t0 = time.time()
    mt5 = MT5Service()
    if not mt5.connect():
        print("Failed to connect to MT5.")
        sys.exit(1)

    print(f"Fetching {BARS} bars {SYMBOL} M15 via fast bulk JSON...")
    raw_json = mt5.get_bulk_rates(SYMBOL, TIMEFRAME, BARS)
    if not raw_json:
        print("Failed to fetch rates via bulk.")
        sys.exit(1)
        
    print("Generating simulated timestamps for M15 (15 minutes per candle)...")
    # 900 seconds per candle for M15
    now_ts = int(time.time())
    timestamps = [now_ts - (len(raw_json) - i) * 900 for i in range(len(raw_json))]

    print("Running Python AI (Scoring V3 + Test B) Backtest...")
    py_res = run_python_ai_backtest(raw_json, timestamps)

    print("Running MQL5 Simulator (ScalperM5) Backtest...")
    mql_res = run_mql5_backtest(raw_json, timestamps)

    print(f"\n{'='*72}")
    print(f"  COMPARISON: {SYMBOL} M15 | ~30 Hari | Modal ${INITIAL_BAL} | Leverage 1:{LEVERAGE}")
    print(f"{'='*72}")
    print(f" ⚙️ Python AI (Scoring V3 + Test B)")
    print(f"  Net Profit     : ${py_res['net_profit']:.2f}  ({py_res['net_profit']/INITIAL_BAL*100:.1f}%)")
    print(f"  Profit Factor  : {py_res['profit_factor']:.2f}")
    print(f"  Expectancy     : ${py_res['expectancy']:.3f} per trade")
    print(f"  Total Trades   : {py_res['trades']}")
    print(f"  Win Rate       : {py_res['win_rate']:.1f}%")
    print(f"  Avg Win/Loss   : ${py_res['avg_win']:.2f} / ${py_res['avg_loss']:.2f}")
    print(f"  Realized RR    : 1:{py_res['rr_real']:.2f}")
    print(f"  Max Drawdown   : ${py_res['max_dd']:.2f}")
    print(f"{'-'*72}")
    print(f" ⚙️ MQL5 Simulator (ScalperM5)")
    print(f"  Net Profit     : ${mql_res['net_profit']:.2f}  ({mql_res['net_profit']/INITIAL_BAL*100:.1f}%)")
    print(f"  Profit Factor  : {mql_res['profit_factor']:.2f}")
    print(f"  Expectancy     : ${mql_res['expectancy']:.3f} per trade")
    print(f"  Total Trades   : {mql_res['trades']}")
    print(f"  Win Rate       : {mql_res['win_rate']:.1f}%")
    print(f"  Avg Win/Loss   : ${mql_res['avg_win']:.2f} / ${mql_res['avg_loss']:.2f}")
    print(f"  Realized RR    : 1:{mql_res['rr_real']:.2f}")
    print(f"  Max Drawdown   : ${mql_res['max_dd']:.2f}")
    print(f"{'='*72}")
