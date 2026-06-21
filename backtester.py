import pandas as pd
import numpy as np
from datetime import datetime
from modules.mt5_service import MT5Service

# Set config
SYMBOL = "XAUUSD#"
TIMEFRAME = 15 # M5 = 5, M15 = 15
DAYS = 24
BARS = (24 * 60 * 24) // 5 # max per hari, M5
INITIAL_BALANCE = 100.0
LOT_SIZE = 0.01

def run_backtest():
    print(f"Connecting to MT5 to fetch data for {SYMBOL}...")
    mt5 = MT5Service()
    mt5.connect()
    
    # 1. Fetch History Rates (misal ambil 10000 bar terakhir untuk history)
    rates_netref = mt5.get_rates(SYMBOL, 5, 8000) 
    if not rates_netref:
        print("Failed to fetch rates!")
        return

    rates = []
    for r in rates_netref:
        rates.append({
            'time': pd.to_datetime(float(r['time']), unit='s'),
            'open': float(r['open']), 
            'high': float(r['high']), 
            'low': float(r['low']), 
            'close': float(r['close'])
        })

    df = pd.DataFrame(rates)
    
    # 2. Build Indicators (Sistem EA: BB 20, RSI 14, EMA 50)
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # BB
    df['bb_middle'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (2 * bb_std)
    df['bb_lower'] = df['bb_middle'] - (2 * bb_std)
    
    # ATR 14
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = true_range.rolling(14).mean()

    df = df.dropna().reset_index(drop=True)
    
    # 3. Simulate Trade
    balance = INITIAL_BALANCE
    equity = INITIAL_BALANCE
    position = 0 # 1 = Buy, -1 = Sell
    entry_price = 0
    trade_count = 0
    win_count = 0
    loss_count = 0
    max_dd = 0
    max_balance = INITIAL_BALANCE
    
    # Tick value untuk XAUUSD (Standard: 100oz per lot, jadi 0.01 lot = 1 oz = $1 per $1 gerak)
    contract_size = 100
    
    for i in range(1, len(df)):
        row = df.iloc[i-1] # previous bar (confirmed signal)
        curr = df.iloc[i]  # execution bar
        
        # Cek Stop Loss / Take profit dinamis jika ada posisi
        if position != 0:
            pnl = 0
            if position == 1:
                # Cek hit SL/TP (Simplified based on previous ATR)
                sl = entry_price - (row['atr'] * 2)
                tp = entry_price + (row['atr'] * 3)
                
                if curr['low'] <= sl:
                    pnl = (sl - entry_price) * LOT_SIZE * contract_size
                    position = 0
                elif curr['high'] >= tp:
                    pnl = (tp - entry_price) * LOT_SIZE * contract_size
                    position = 0
                    
            elif position == -1:
                sl = entry_price + (row['atr'] * 2)
                tp = entry_price - (row['atr'] * 3)
                
                if curr['high'] >= sl:
                    pnl = (entry_price - sl) * LOT_SIZE * contract_size
                    position = 0
                elif curr['low'] <= tp:
                    pnl = (entry_price - tp) * LOT_SIZE * contract_size
                    position = 0
            
            if position == 0:
                balance += pnl
                trade_count += 1
                if pnl > 0: win_count += 1
                else: loss_count += 1
                
                if balance > max_balance: max_balance = balance
                dd = max_balance - balance
                if dd > max_dd: max_dd = dd
                
            continue # Skip buka posisi baru jika masih open

        # EA Logic: Buy jika nembus BB Lower + RSI < 30 + Trend M15 (EMA50) Up
        buy_signal = row['close'] <= row['bb_lower'] and row['rsi'] <= 30 and row['close'] > row['ema50']
        # Sell jika nembus BB Upper + RSI > 70 + Trend M15 Down
        sell_signal = row['close'] >= row['bb_upper'] and row['rsi'] >= 70 and row['close'] < row['ema50']
        
        if buy_signal:
            position = 1
            entry_price = curr['open']
        elif sell_signal:
            position = -1
            entry_price = curr['open']

    # Final stats
    print("=== BACKTEST RESULT (24 Days M5 - SCLAPER EA LOGIC) ===")
    print(f"Initial Balance : ${INITIAL_BALANCE}")
    print(f"Final Balance   : ${balance:.2f}")
    print(f"Net Profit      : ${balance - INITIAL_BALANCE:.2f}")
    print(f"Max Drawdown    : ${max_dd:.2f}")
    print(f"Total Trades    : {trade_count}")
    
    if trade_count > 0:
        win_rate = (win_count / trade_count) * 100
        print(f"Win Rate        : {win_rate:.1f}% ({win_count} Win / {loss_count} Loss)")
    
if __name__ == "__main__":
    run_backtest()
