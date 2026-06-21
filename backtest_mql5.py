import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.append("/root")
from mt5both2s.modules.mt5_service import MT5Service

# === CONFIG ===
SYMBOL      = "USDJPY#"
TIMEFRAME   = 5           # M5
BARS        = 5760        # ~20 hari trading M5
INITIAL_BAL = 20.0        # Modal $20
LOT_SIZE    = 0.01        # Minimum lot size
LEVERAGE    = 200         # Leverage 1:200
CONTRACT    = 100000      # 1 Lot USDJPY = 100,000 USD (contract_size)
MAGIC       = 123456

# EA Parameters
InpMinEntryScore = 60
InpMinConfidenceScore = 50
InpRSIPeriod = 14
InpRSIOverbought = 70.0
InpRSIOversold = 30.0

def run_backtest_mql5():
    t0 = time.time()
    mt5 = MT5Service()
    if not mt5.connect():
        print("Failed to connect to MT5.")
        return

    print(f"Fetching {BARS} bars {SYMBOL} M5 via fast bulk JSON...")
    raw_json = mt5.get_bulk_rates(SYMBOL, TIMEFRAME, BARS)
    if not raw_json:
        print("Failed to fetch rates via bulk.")
        return
        
    n = len(raw_json)
    print(f"Got {n} bars in {time.time()-t0:.2f}s. Building arrays...")

    op  = np.array([float(r[0]) for r in raw_json])
    hi  = np.array([float(r[1]) for r in raw_json])
    lo  = np.array([float(r[2]) for r in raw_json])
    cl  = np.array([float(r[3]) for r in raw_json])

    # Simulasi tick volume & timestamps untuk bypass RPyC overhead yang lambat
    tick_vol = np.ones(n) * 100
    timestamps = [int(time.time() - (n - i)*300) for i in range(n)]

    df = pd.DataFrame(raw_json, columns=['open', 'high', 'low', 'close'])

    print("Pre-calculating indicators for ScalperM5 MQL5 simulation...")
    # 1. Bollinger Bands (20, 2)
    bb_middle = df['close'].rolling(window=20).mean().values
    bb_std = df['close'].rolling(window=20).std().values
    bb_upper = bb_middle + (2 * bb_std)
    bb_lower = bb_middle - (2 * bb_std)

    # 2. RSI 14
    delta = df['close'].diff()
    gain  = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).values

    # 3. ATR (14) & average ATR 20
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).mean().values
    
    # 4. ADX (14)
    up_move = df['high'] - df['high'].shift()
    down_move = df['low'].shift() - df['low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_di = (100 * (pd.Series(plus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    minus_di = (100 * (pd.Series(minus_dm).rolling(14).mean() / pd.Series(true_range).rolling(14).mean())).values
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = pd.Series(dx).rolling(14).mean().values

    # 5. EMA 50 for M15 and H1 MTF simulated proxy on M5
    ema_m15_proxy = df['close'].ewm(span=150, adjust=False).mean().values
    ema_h1_proxy = df['close'].ewm(span=600, adjust=False).mean().values

    # Simulation loop
    WARMUP = 600 
    bal = INITIAL_BAL
    max_bal = INITIAL_BAL
    max_dd = 0.0
    pos = 0 
    entry_price = 0.0
    pnl_history = []

    diffs = cl - op
    
    # Optimize historical similarity dengan kalkulasi vektor korelasi bergulir (vectorized Pearson)
    print("Pre-calculating Pearson Correlation matrix for history engine...")
    corr_cache = np.full(n, 50.0)
    # Lakukan loop sliding window secara cepat
    for idx in range(WARMUP, n - 1):
        curr_p = diffs[idx-7:idx+1]
        std_c = curr_p.std()
        if std_c == 0:
            continue
            
        # Pindai 150 bar ke belakang (tapi menyisakan 12 bar terakhir untuk menghindari forward-looking bias)
        lookback_start = max(WARMUP - 150, idx - 142)
        lookback_end = idx - 10
        
        matches = 0
        successes = 0
        
        for h in range(lookback_start, lookback_end):
            hist_p = diffs[h:h+8]
            std_h = hist_p.std()
            if std_h == 0: continue
            
            # Covariance / Pearson Correlation manual yang super cepat
            cov = np.dot(curr_p - curr_p.mean(), hist_p - hist_p.mean()) / 8
            corr = cov / (std_c * std_h)
            
            if corr > 0.70:
                matches += 1
                # evaluasi arah harga 3 bar ke depan
                if cl[h+11] > cl[h+8]:
                    successes += 1
                    
        if matches > 0:
            corr_cache[idx] = (successes / matches) * 100.0

    print("Simulating trading loop...")
    for i in range(WARMUP, n - 1):
        curr_open = op[i+1]
        req_margin = (LOT_SIZE * CONTRACT) / LEVERAGE  

        if pos != 0:
            # Trailing stop ATR based (TSStart: 1.5, TStop: 1.0)
            atr_val = max(atr[i], 0.050)
            sl = (entry_price - atr_val * 2.0) if pos == 1 else (entry_price + atr_val * 2.0)
            tp = (entry_price + atr_val * 3.0) if pos == 1 else (entry_price - atr_val * 3.0)

            pnl = None
            if pos == 1:
                if lo[i+1] <= sl:
                    pnl = ((sl - entry_price) * LOT_SIZE * CONTRACT) / curr_open
                    pos = 0
                elif hi[i+1] >= tp:
                    pnl = ((tp - entry_price) * LOT_SIZE * CONTRACT) / curr_open
                    pos = 0
            elif pos == -1:
                if hi[i+1] >= sl:
                    pnl = ((entry_price - sl) * LOT_SIZE * CONTRACT) / curr_open
                    pos = 0
                elif lo[i+1] <= tp:
                    pnl = ((entry_price - tp) * LOT_SIZE * CONTRACT) / curr_open
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

        # 1. BB & RSI base signals
        buy_sig = cl[i] <= bb_lower[i] and rsi[i] <= InpRSIOversold
        sell_sig = cl[i] >= bb_upper[i] and rsi[i] >= InpRSIOverbought

        if not (buy_sig or sell_sig):
            continue

        # 2. Confidence Filter
        confidence = corr_cache[i]
        if confidence < InpMinConfidenceScore:
            continue

        # 3. Calculate Entry score (0-100)
        entry_score = 0
        
        # MTF Trend score (20 pts)
        if buy_sig:
            if cl[i] > ema_m15_proxy[i]: entry_score += 10
            if cl[i] > ema_h1_proxy[i]: entry_score += 10
        else:
            if cl[i] < ema_m15_proxy[i]: entry_score += 10
            if cl[i] < ema_h1_proxy[i]: entry_score += 10
            
        # Momentum RSI score (20 pts)
        rsi_slope = rsi[i] - rsi[i-1]
        if buy_sig:
            if rsi[i] <= InpRSIOversold: entry_score += 10
            if rsi_slope > 0: entry_score += 10
        else:
            if rsi[i] >= InpRSIOverbought: entry_score += 10
            if rsi_slope < 0: entry_score += 10

        # Volatility BB Width score (15 pts)
        entry_score += 15.0 # ideal width

        # Structure score (15 pts)
        if buy_sig:
            if cl[i] <= bb_lower[i]: entry_score += 15
        else:
            if cl[i] >= bb_upper[i]: entry_score += 15

        # Volume score (10 pts)
        avg_vol = tick_vol[i-20:i].mean()
        if tick_vol[i] >= avg_vol: entry_score += 10
        else: entry_score += 5

        # Spread & Similarity score (20 pts)
        entry_score += 10 
        if confidence >= 60.0: entry_score += 10
        elif confidence >= 50.0: entry_score += 5

        # Min Entry score filter
        if entry_score < InpMinEntryScore:
            continue

        # Regime Filtering
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

        # Entry position
        pos = 1 if buy_sig else -1
        entry_price = curr_open

    # Metric evaluation
    pnl_arr = np.array(pnl_history)
    trades = len(pnl_arr)
    wins = np.sum(pnl_arr > 0)
    losses = np.sum(pnl_arr < 0)
    
    total_gain = np.sum(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    total_loss = np.sum(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    profit_factor = abs(total_gain / total_loss) if total_loss != 0 else (999.0 if total_gain > 0 else 0.0)
    avg_win = np.mean(pnl_arr[pnl_arr > 0]) if np.any(pnl_arr > 0) else 0.0
    avg_loss = np.mean(pnl_arr[pnl_arr < 0]) if np.any(pnl_arr < 0) else 0.0
    
    rr_real = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    win_rate = (wins / trades) * 100 if trades > 0 else 0.0
    expectancy = (win_rate/100 * avg_win) + ((1.0 - win_rate/100) * avg_loss) if trades > 0 else 0.0
    
    print(f"\n{'='*72}")
    print(f"  BACKTEST MQL5 SIMULATOR: {SYMBOL} M5 | ~20 Hari | Modal $20")
    print(f"  EA Logic: ScalperM5.mq5 (BB, RSI, Regime, Pearson Correlation)")
    print(f"{'='*72}")
    print(f"  Net Profit     : ${bal - INITIAL_BAL:.2f}  ({(bal - INITIAL_BAL)/INITIAL_BAL*100:.1f}%)")
    print(f"  Profit Factor  : {profit_factor:.2f}")
    print(f"  Expectancy     : ${expectancy:.3f} per trade")
    print(f"  Total Trades   : {trades}")
    print(f"  Win Rate       : {win_rate:.1f}%  ({wins}W / {losses}L)")
    print(f"  Max Drawdown   : ${max_dd:.2f}")
    print(f"  Realized RR    : 1:{rr_real:.2f}")
    print(f"{'='*72}")

if __name__ == "__main__":
    run_backtest_mql5()
