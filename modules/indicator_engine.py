import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from .mt5_service import MT5Service
from .candle_strength import calculate_candle_strength

def calculate_indicators(mt5_service: MT5Service, symbol: str, timeframe: int = 16408, bars: int = 250) -> Optional[Dict[str, Any]]:
    # Fetch rates via fast bulk JSON
    rates_raw = mt5_service.get_bulk_rates(symbol, timeframe, bars)
    if not rates_raw or len(rates_raw) < 220: 
        return None
    
    # Format bulk: [open, high, low, close]
    df = pd.DataFrame(rates_raw, columns=['open', 'high', 'low', 'close'])
    
    # 1. EMA 50 & 200
    ema50 = df['close'].ewm(span=50, adjust=False).mean()
    ema200 = df['close'].ewm(span=200, adjust=False).mean()
    
    # 2. MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    
    # Check if histogram direction is up for last 3 candles
    # hist[i] > hist[i-1] AND hist[i-1] > hist[i-2] AND hist[i-2] > hist[i-3]
    hist_now = histogram.iloc[-1]
    hist_1 = histogram.iloc[-2]
    hist_2 = histogram.iloc[-3]
    hist_3 = histogram.iloc[-4]
    
    macd_hist_up_3 = bool(hist_now > hist_1 and hist_1 > hist_2 and hist_2 > hist_3)
    macd_hist_down_3 = bool(hist_now < hist_1 and hist_1 < hist_2 and hist_2 < hist_3)
    
    # 3. ATR (14) & Rolling Mean ATR 20
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(14).mean()
    atr_mean_20 = atr.rolling(20).mean()
    
    # 4. ADX (14)
    up_move = df['high'] - df['high'].shift()
    down_move = df['low'].shift() - df['low']
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / atr)
    
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(14).mean()
    
    # 5. Fractal (5 bar structure)
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    
    fractal_up = np.zeros(n)
    fractal_down = np.zeros(n)
    
    for idx in range(2, n - 2):
        if (highs[idx] > highs[idx-1] and highs[idx] > highs[idx-2] and 
            highs[idx] > highs[idx+1] and highs[idx] > highs[idx+2]):
            fractal_up[idx] = highs[idx]
        if (lows[idx] < lows[idx-1] and lows[idx] < lows[idx-2] and 
            lows[idx] < lows[idx+1] and lows[idx] < lows[idx+2]):
            fractal_down[idx] = lows[idx]
            
    last_fractal_up = 0.0
    last_fractal_down = 0.0
    for idx in range(n - 3, 1, -1):
        if fractal_up[idx] > 0:
            last_fractal_up = fractal_up[idx]
            break
    for idx in range(n - 3, 1, -1):
        if fractal_down[idx] > 0:
            last_fractal_down = fractal_down[idx]
            break
        
    # 6. Candle Strength calculation for the current candle (index -1)
    current_candle = {
        'open': df['open'].iloc[-1],
        'high': df['high'].iloc[-1],
        'low': df['low'].iloc[-1],
        'close': df['close'].iloc[-1]
    }
    candle_strength = calculate_candle_strength(current_candle)
    is_bullish = current_candle['close'] > current_candle['open']

    # Current Close & Fractal breakout check
    current_close = df['close'].iloc[-1]
    fractal_breakout = "NONE"
    if last_fractal_up > 0 and current_close > last_fractal_up:
        fractal_breakout = "UP"
    elif last_fractal_down > 0 and current_close < last_fractal_down:
        fractal_breakout = "DOWN"
        
    tick = mt5_service.get_tick(symbol)
    spread = tick.get('spread', 0) if tick else 0

    return {
        "symbol": symbol,
        "current_close": float(current_close),
        "ema50": float(ema50.iloc[-1]),
        "ema200": float(ema200.iloc[-1]),
        "macd_main": float(macd_line.iloc[-1]),
        "macd_sig": float(signal_line.iloc[-1]),
        "macd_hist_up_3": macd_hist_up_3,
        "macd_hist_down_3": macd_hist_down_3,
        "adx": float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0.0,
        "plus_di": float(plus_di.iloc[-1]) if not np.isnan(plus_di.iloc[-1]) else 0.0,
        "minus_di": float(minus_di.iloc[-1]) if not np.isnan(minus_di.iloc[-1]) else 0.0,
        "atr": float(atr.iloc[-1]),
        "atr_mean_20": float(atr_mean_20.iloc[-1]),
        "fractal_up": float(last_fractal_up),
        "fractal_down": float(last_fractal_down),
        "fractal_breakout": fractal_breakout,
        "candle_strength": candle_strength,
        "is_bullish": is_bullish,
        "spread": int(spread)
    }
