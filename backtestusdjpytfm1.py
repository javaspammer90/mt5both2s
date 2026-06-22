import random
import pandas as pd
import numpy as np
from datetime import datetime
from modules.mt5_service import MT5Service

# Set config
SYMBOL = "USDJPY#"
TIMEFRAME = 1 # M5 = 5, M15 = 15
DAYS = 2
INITIAL_BALANCE = 10.0

POSITION_MODE = "fixed" # "fixed" or "risk_percent"
LOT_SIZE = 0.01
RISK_PERCENT = 2.0

INTRABAR_MODE = "worst" # "worst", "best", "random"

def run_backtest():
    print(f"Connecting to MT5 to fetch data for {SYMBOL}...")
    mt5 = MT5Service()
    if not mt5.connect():
        print("Failed to connect to MT5 Service!")
        return
    
    # Calculate bars needed based on DAYS and TIMEFRAME
    bars_needed = (DAYS * 24 * 60) // TIMEFRAME
    # Fetch extra bars to offset indicators dropna
    bars_to_fetch = bars_needed + 100
    
    print(f"Fetching {bars_to_fetch} bars for symbol {SYMBOL} with timeframe {TIMEFRAME}...")
    rates_raw = mt5.get_rates(SYMBOL, TIMEFRAME, bars_to_fetch)
    if not rates_raw:
        print("Failed to fetch rates!")
        return

    rates = []
    for r in rates_raw:
        row_dict = dict(r) if hasattr(r, 'keys') else r
        rates.append({
            'time': pd.to_datetime(float(row_dict['time']), unit='s'),
            'open': float(row_dict['open']), 
            'high': float(row_dict['high']), 
            'low': float(row_dict['low']), 
            'close': float(row_dict['close'])
        })

    df = pd.DataFrame(rates)
    
    # Bug #2 Validasi Urutan Data
    if df['time'].iloc[0] > df['time'].iloc[-1]:
        print("Data Order: FIXED FROM DESCENDING")
        df = df.sort_values('time').reset_index(drop=True)
    else:
        print("Data Order: ASCENDING")
    
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
    
    # Keep only the requested number of bars at the end to match DAYS
    if len(df) > bars_needed:
        df = df.iloc[-bars_needed:].reset_index(drop=True)
        
    print("===================================")
    print("DATA VALIDATION")
    print("===================================")
    print(f"First Candle : {df.iloc[0]['time']}")
    print(f"Last Candle  : {df.iloc[-1]['time']}")
    print(f"Bars         : {len(df)}")
    
    # Ambil Spread Asli Broker (Bug #5)
    sym_info = mt5.get_symbol_info(SYMBOL)
    SPREAD_POINTS = 30 # Default
    if sym_info and 'spread' in sym_info and 'point' in sym_info:
        SPREAD_POINTS = sym_info['spread']
        spread = sym_info['spread'] * sym_info['point']
        print(f"Spread Used  : {sym_info['spread']} points (Real)")
    else:
        spread = SPREAD_POINTS * 0.01
        print(f"Spread Used  : {SPREAD_POINTS} points (Fallback)")
    
    # Ambil Contract Size Langsung dari MT5
    contract_size = 100 # Default fallback
    if sym_info and 'trade_contract_size' in sym_info:
        contract_size = sym_info['trade_contract_size']
        print(f"Contract Size: {contract_size}")
        print(f"Digits       : {sym_info.get('digits', 2)}")
        print(f"Point        : {sym_info.get('point', 0.01)}")
    else:
        print("Contract Size: 100 (Fallback)")
        print("Digits       : 2 (Fallback)")
        print("Point        : 0.01 (Fallback)")
        
    print(f"Intrabar Mode: {INTRABAR_MODE}")
    if POSITION_MODE == "risk_percent":
        print(f"Position Mode: risk_percent")
        print(f"Risk %       : {RISK_PERCENT}%")
    else:
        print(f"Position Mode: fixed")
        print(f"Lot Size     : {LOT_SIZE}")
        
    print("===================================")
    
    # 3. Simulate Trade
    balance = INITIAL_BALANCE
    equity = INITIAL_BALANCE
    peak_equity = INITIAL_BALANCE
    max_drawdown = 0.0
    max_drawdown_percent = 0.0
    
    position = 0 # 1 = Buy, -1 = Sell
    entry_price = 0.0
    position_sl = 0.0
    position_tp = 0.0
    entry_atr = 0.0
    entry_time = None
    
    trades = []
    
    COMMISSION_PER_LOT = 0.0 # Setup Commission (Bug #6)
    
    equity_curve = []
    current_lot = LOT_SIZE
    
    for i in range(1, len(df)):
        row = df.iloc[i-1] # previous bar (confirmed signal)
        curr = df.iloc[i]  # execution bar
        
        # Check SL/TP exit if position is open
        closed_this_bar = False
        pnl = 0.0
        exit_price = 0.0
        close_reason = ""
        
        if position != 0:
            sl_hit = False
            tp_hit = False
            
            if position == 1:
                if curr['low'] <= position_sl: sl_hit = True
                if curr['high'] >= position_tp: tp_hit = True
                
                if sl_hit and tp_hit:
                    if INTRABAR_MODE == "worst":
                        tp_hit = False
                    elif INTRABAR_MODE == "best":
                        sl_hit = False
                    elif INTRABAR_MODE == "random":
                        if random.choice([True, False]):
                            tp_hit = False
                        else:
                            sl_hit = False
                            
                if sl_hit:
                    exit_price = position_sl
                    pnl = (exit_price - entry_price) * current_lot * contract_size
                    close_reason = "SL"
                    closed_this_bar = True
                elif tp_hit:
                    exit_price = position_tp
                    pnl = (exit_price - entry_price) * current_lot * contract_size
                    close_reason = "TP"
                    closed_this_bar = True
                    
            elif position == -1:
                if curr['high'] >= position_sl: sl_hit = True
                if curr['low'] <= position_tp: tp_hit = True
                
                if sl_hit and tp_hit:
                    if INTRABAR_MODE == "worst":
                        tp_hit = False
                    elif INTRABAR_MODE == "best":
                        sl_hit = False
                    elif INTRABAR_MODE == "random":
                        if random.choice([True, False]):
                            tp_hit = False
                        else:
                            sl_hit = False
                            
                if sl_hit:
                    exit_price = position_sl
                    pnl = (entry_price - exit_price) * current_lot * contract_size
                    close_reason = "SL"
                    closed_this_bar = True
                elif tp_hit:
                    exit_price = position_tp
                    pnl = (entry_price - exit_price) * current_lot * contract_size
                    close_reason = "TP"
                    closed_this_bar = True
                    
            if closed_this_bar:
                commission = COMMISSION_PER_LOT * current_lot
                pnl -= commission
                
                balance += pnl
                floating_pnl = 0.0
                equity = balance
                
                pos_type = "BUY" if position == 1 else "SELL"
                
                # Validasi Exit time vs Entry time
                valid_trade = True
                if curr['time'] < entry_time:
                    print("ERROR: Exit time earlier than entry time")
                    valid_trade = False
                    
                print(f"[CLOSE {pos_type}] time={curr['time']} reason={close_reason} pnl={pnl:.2f} balance={balance:.2f} comm={commission:.2f}")
                
                trades.append({
                    "type": pos_type,
                    "entry_time": entry_time,
                    "exit_time": curr['time'],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "sl": position_sl,
                    "tp": position_tp,
                    "pnl": pnl,
                    "commission": commission,
                    "balance_after": balance,
                    "valid_trade": valid_trade
                })
                
                # Reset position variables
                position = 0
                entry_price = 0.0
                position_sl = 0.0
                position_tp = 0.0
                entry_atr = 0.0
                entry_time = None

        # Check for new entry signal if no position is open (or just closed)
        if position == 0:
            # EA Logic: Buy if breaks BB Lower + RSI <= 30 + Trend M15 (EMA50) Up
            buy_signal = row['close'] <= row['bb_lower'] and row['rsi'] <= 30 and row['close'] > row['ema50']
            # Sell if breaks BB Upper + RSI >= 70 + Trend M15 Down
            sell_signal = row['close'] >= row['bb_upper'] and row['rsi'] >= 70 and row['close'] < row['ema50']
            
            if buy_signal:
                position = 1
                entry_atr = row['atr']
                entry_price = curr['open'] + spread
                position_sl = entry_price - (entry_atr * 2)
                position_tp = entry_price + (entry_atr * 3)
                
                if POSITION_MODE == "risk_percent":
                    risk_amount = balance * (RISK_PERCENT / 100.0)
                    sl_dist = entry_price - position_sl
                    loss_per_1_lot = sl_dist * contract_size
                    if loss_per_1_lot > 0:
                        current_lot = round(risk_amount / loss_per_1_lot, 2)
                        current_lot = max(0.01, current_lot)
                    else:
                        current_lot = 0.01
                else:
                    current_lot = LOT_SIZE
                    
                entry_time = curr['time']
                print(f"[OPEN BUY] time={entry_time} entry={entry_price:.2f} sl={position_sl:.2f} tp={position_tp:.2f} lot={current_lot}")
            elif sell_signal:
                position = -1
                entry_atr = row['atr']
                entry_price = curr['open'] - spread
                position_sl = entry_price + (entry_atr * 2)
                position_tp = entry_price - (entry_atr * 3)
                
                if POSITION_MODE == "risk_percent":
                    risk_amount = balance * (RISK_PERCENT / 100.0)
                    sl_dist = position_sl - entry_price
                    loss_per_1_lot = sl_dist * contract_size
                    if loss_per_1_lot > 0:
                        current_lot = round(risk_amount / loss_per_1_lot, 2)
                        current_lot = max(0.01, current_lot)
                    else:
                        current_lot = 0.01
                else:
                    current_lot = LOT_SIZE
                    
                entry_time = curr['time']
                print(f"[OPEN SELL] time={entry_time} entry={entry_price:.2f} sl={position_sl:.2f} tp={position_tp:.2f} lot={current_lot}")
                
        # Calculate Floating PnL and Equity for current bar
        if position != 0:
            if position == 1:
                floating_pnl = (curr['close'] - entry_price) * current_lot * contract_size
            else:
                floating_pnl = (entry_price - curr['close']) * current_lot * contract_size
            equity = balance + floating_pnl
        else:
            floating_pnl = 0.0
            equity = balance
            
        # Update Drawdown Metrics based on Equity
        peak_equity = max(peak_equity, equity)
        current_dd = peak_equity - equity
        max_drawdown = max(max_drawdown, current_dd)
        max_drawdown_percent = max(max_drawdown_percent, (current_dd / peak_equity) * 100)
        
        # Save equity curve point
        equity_curve.append({
            'time': curr['time'],
            'balance': balance,
            'equity': equity,
            'floating_pnl': floating_pnl,
            'drawdown': current_dd,
            'drawdown_percent': (current_dd / peak_equity) * 100 if peak_equity > 0 else 0
        })

    # Force Close last open position if any
    if position != 0:
        curr = df.iloc[-1]
        if position == 1:
            exit_price = curr['close']
            pnl = (exit_price - entry_price) * current_lot * contract_size
            close_reason = "FINAL"
            pos_type = "BUY"
        else:
            exit_price = curr['close']
            pnl = (entry_price - exit_price) * current_lot * contract_size
            close_reason = "FINAL"
            pos_type = "SELL"
            
        commission = COMMISSION_PER_LOT * current_lot
        pnl -= commission
        
        balance += pnl
        floating_pnl = 0.0
        equity = balance
        
        valid_trade = True
        if curr['time'] < entry_time:
            print("ERROR: Exit time earlier than entry time")
            valid_trade = False
            
        print(f"[CLOSE {pos_type}] time={curr['time']} reason={close_reason} pnl={pnl:.2f} balance={balance:.2f} comm={commission:.2f}")
        
        trades.append({
            "type": pos_type,
            "entry_time": entry_time,
            "exit_time": curr['time'],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "sl": position_sl,
            "tp": position_tp,
            "pnl": pnl,
            "commission": commission,
            "balance_after": balance,
            "valid_trade": valid_trade
        })
        
        peak_equity = max(peak_equity, equity)
        current_dd = peak_equity - equity
        max_drawdown = max(max_drawdown, current_dd)
        max_drawdown_percent = max(max_drawdown_percent, (current_dd / peak_equity) * 100)
        
        position = 0

    # Save Trade History & Equity Curve
    if trades:
        pd.DataFrame(trades).to_csv("backtest_trades.csv", index=False)
    if equity_curve:
        pd.DataFrame(equity_curve).to_csv("equity_curve.csv", index=False)
        
    # Calculate Statistics
    total_trades = len(trades)
    win_trades = sum(1 for t in trades if t['pnl'] > 0)
    loss_trades = sum(1 for t in trades if t['pnl'] <= 0)
    
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    net_profit = balance - INITIAL_BALANCE
    net_profit_percent = (net_profit / INITIAL_BALANCE) * 100
    
    gross_profit = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gross_loss = sum(abs(t['pnl']) for t in trades if t['pnl'] < 0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)
    
    avg_win = (gross_profit / win_trades) if win_trades > 0 else 0.0
    avg_loss = (gross_loss / loss_trades) if loss_trades > 0 else 0.0
    
    total_commission = sum(t.get('commission', 0) for t in trades)
    
    win_prob = win_trades / total_trades if total_trades > 0 else 0.0
    loss_prob = loss_trades / total_trades if total_trades > 0 else 0.0
    expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)
    
    # Advanced Statistics
    recovery_factor = net_profit / max_drawdown if max_drawdown > 0 else float('inf')
    
    trade_durations = [(t['exit_time'] - t['entry_time']).total_seconds() / 60 for t in trades]
    avg_duration = sum(trade_durations) / len(trade_durations) if trade_durations else 0.0
    
    max_cons_wins = 0
    max_cons_losses = 0
    curr_wins = 0
    curr_losses = 0
    r_multiples = []
    
    for t in trades:
        if t['pnl'] > 0:
            curr_wins += 1
            curr_losses = 0
            if curr_wins > max_cons_wins: max_cons_wins = curr_wins
        elif t['pnl'] < 0:
            curr_losses += 1
            curr_wins = 0
            if curr_losses > max_cons_losses: max_cons_losses = curr_losses
            
        # R-Multiple
        # Risk adalah spread ke SL
        risk_dist = abs(t['entry_price'] - t['sl'])
        if risk_dist > 0:
            risk_usd = risk_dist * contract_size * (t.get('lot', current_lot)) # Approximation using current_lot fallback
            r_multiples.append(t['pnl'] / risk_usd)
            
    avg_r_multiple = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

    # Sanity Check
    if total_trades < 30:
        print("\nWARNING:")
        print("Less than 30 trades.")
        print("Result has low statistical confidence.")
    elif total_trades < 100:
        print("\nINFO:")
        print("Sample size moderate.")
        print("More history recommended.")
    else:
        print("\nSample size acceptable.")

    # Final stats printout
    print(f"\n=== BACKTEST RESULT ({DAYS} Days M{TIMEFRAME} - SCALPER EA LOGIC) ===")
    print(f"Initial Balance : ${INITIAL_BALANCE:.2f}")
    print(f"Final Balance   : ${balance:.2f}")
    print(f"Final Equity    : ${equity:.2f}")
    print(f"Net Profit      : ${net_profit:.2f}")
    print(f"Net Profit %    : {net_profit_percent:.2f}%")
    print(f"Total Commission: ${total_commission:.2f}")
    print(f"Max Drawdown $  : ${max_drawdown:.2f}")
    print(f"Max Drawdown %  : {max_drawdown_percent:.2f}%")
    print(f"Total Trades    : {total_trades}")
    print(f"Win Trades      : {win_trades}")
    print(f"Loss Trades     : {loss_trades}")
    print(f"Win Rate        : {win_rate:.1f}%")
    if profit_factor == float('inf'):
        print("Profit Factor   : inf")
    else:
        print(f"Profit Factor   : {profit_factor:.2f}")
    print(f"Average Win     : ${avg_win:.2f}")
    print(f"Average Loss    : ${avg_loss:.2f}")
    print(f"Expectancy      : ${expectancy:.2f}")
    print(f"Recovery Factor : {recovery_factor:.2f}" if recovery_factor != float('inf') else "Recovery Factor : inf")
    print(f"Avg Duration    : {avg_duration:.1f} mins")
    print(f"Max Cons Wins   : {max_cons_wins}")
    print(f"Max Cons Losses : {max_cons_losses}")
    print(f"Avg R-Multiple  : {avg_r_multiple:.2f}R")

if __name__ == "__main__":
    run_backtest()
