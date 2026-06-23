import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from modules.mt5_service import MT5Service

SYMBOL = "USDCAD#"
DAYS = 30
INITIAL_BALANCE = 10000.0
RISK_PCT = 0.0025
HC_RISK_PCT = 0.005

print(f"Memulai koneksi ke MT5...")
mt5 = MT5Service()
if not mt5.connect():
    print("Koneksi gagal.")
    exit()

bars_m5 = (DAYS * 24 * 60) // 5 + 300
bars_h1 = (DAYS * 24) + 300
bars_h4 = (DAYS * 6) + 300

print(f"Mengambil data {SYMBOL} {DAYS} Hari...")
rates_m5 = mt5.get_bulk_rates(SYMBOL, 5, bars_m5)
rates_h1 = mt5.get_bulk_rates(SYMBOL, 16385, bars_h1)
rates_h4 = mt5.get_bulk_rates(SYMBOL, 16388, bars_h4)

if not rates_m5 or not rates_h1 or not rates_h4:
    print("Gagal ambil data!")
    exit()

# Mock time for simulation since bulk_rates only returns OHLC on your RPyC setup
now = datetime.utcnow()
def build_df(rates, timeframe_minutes):
    df = pd.DataFrame(rates, columns=['open', 'high', 'low', 'close'])
    times = [now - timedelta(minutes=timeframe_minutes * (len(df) - 1 - i)) for i in range(len(df))]
    df['time'] = times
    return df

df_m5 = build_df(rates_m5, 5)
df_h1 = build_df(rates_h1, 60)
df_h4 = build_df(rates_h4, 240)

print("Menghitung Indikator...")
# H4
df_h4['ema50_h4'] = df_h4['close'].ewm(span=50, adjust=False).mean()
df_h4['ema200_h4'] = df_h4['close'].ewm(span=200, adjust=False).mean()

# H1
df_h1['ema50_h1'] = df_h1['close'].ewm(span=50, adjust=False).mean()
df_h1['ema200_h1'] = df_h1['close'].ewm(span=200, adjust=False).mean()

# M5
df_m5['ema20_m5'] = df_m5['close'].ewm(span=20, adjust=False).mean()
df_m5['ema50_m5'] = df_m5['close'].ewm(span=50, adjust=False).mean()

# ADX Calculation
df_m5['up'] = df_m5['high'] - df_m5['high'].shift(1)
df_m5['down'] = df_m5['low'].shift(1) - df_m5['low']
df_m5['plus_dm'] = np.where((df_m5['up'] > df_m5['down']) & (df_m5['up'] > 0), df_m5['up'], 0.0)
df_m5['minus_dm'] = np.where((df_m5['down'] > df_m5['up']) & (df_m5['down'] > 0), df_m5['down'], 0.0)
df_m5['tr_adx'] = np.maximum(df_m5['high'] - df_m5['low'], np.maximum(abs(df_m5['high'] - df_m5['close'].shift(1)), abs(df_m5['low'] - df_m5['close'].shift(1))))
df_m5['tr_sm'] = df_m5['tr_adx'].ewm(alpha=1/14, adjust=False).mean()
df_m5['plus_dm_sm'] = df_m5['plus_dm'].ewm(alpha=1/14, adjust=False).mean()
df_m5['minus_dm_sm'] = df_m5['minus_dm'].ewm(alpha=1/14, adjust=False).mean()
df_m5['+di'] = 100 * (df_m5['plus_dm_sm'] / df_m5['tr_sm'])
df_m5['-di'] = 100 * (df_m5['minus_dm_sm'] / df_m5['tr_sm'])
dx = 100 * abs(df_m5['+di'] - df_m5['-di']) / (df_m5['+di'] + df_m5['-di'])
df_m5['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()

delta = df_m5['close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss
df_m5['rsi'] = 100 - (100 / (1 + rs))
df_m5['prev_rsi'] = df_m5['rsi'].shift(1)

df_m5['bullish'] = df_m5['close'] > df_m5['open']
df_m5['bearish'] = df_m5['close'] < df_m5['open']

high_low = df_m5['high'] - df_m5['low']
high_close = np.abs(df_m5['high'] - df_m5['close'].shift())
low_close = np.abs(df_m5['low'] - df_m5['close'].shift())
true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df_m5['atr'] = true_range.rolling(14).mean()

# Merge H4 to H1 to M5
df_h4_sub = df_h4[['time', 'ema50_h4', 'ema200_h4']].dropna()
df_h1 = pd.merge_asof(df_h1, df_h4_sub, on='time', direction='backward')

df_h1_sub = df_h1[['time', 'ema50_h1', 'ema200_h1', 'ema50_h4', 'ema200_h4']].dropna()
df_m5 = pd.merge_asof(df_m5, df_h1_sub, on='time', direction='backward')
df_m5 = df_m5.dropna().reset_index(drop=True)

sym_info_raw = mt5.get_symbol_info(SYMBOL)
sym_info = sym_info_raw if isinstance(sym_info_raw, dict) else dict(sym_info_raw) if sym_info_raw else {}

spread = float(sym_info.get('spread', 12)) * float(sym_info.get('point', 0.00001))
contract_size = float(sym_info.get('trade_contract_size', 100000))
point = float(sym_info.get('point', 0.00001))

print("=========================================")
print(f"Data M5: {len(df_m5)} bars")
print(f"Spread: {sym_info.get('spread', 12)} points")
print("Mulai Simulasi...")

balance = INITIAL_BALANCE
equity = INITIAL_BALANCE
peak_equity = INITIAL_BALANCE
max_dd = 0.0
max_dd_pct = 0.0

active_pos = []
trades = []

MAX_POSITIONS = 3
SL_MULT = 1.5
TP_MULT = 2.4
MAX_DAILY_DD = 0.05

current_day = df_m5.iloc[0]['time'].date()
start_of_day_balance = INITIAL_BALANCE
halt_today = False
halt_count = 0

for i in range(1, len(df_m5)):
    curr = df_m5.iloc[i]
    curr_date = curr['time'].date()
    if curr_date != current_day:
        current_day = curr_date
        start_of_day_balance = equity
        halt_today = False
    
    floating_pnl_total = 0.0
    closed_pos = []
    
    for p in active_pos:
        closed = False
        pnl = 0.0
        
        if p['type'] == 'BUY':
            if curr['low'] <= p['sl']:
                pnl = (p['sl'] - p['entry']) * p['lot'] * contract_size
                p['reason'] = 'SL' if p['sl'] < p['entry'] else 'BE'
                closed = True
            elif curr['high'] >= p['tp']:
                pnl = (p['tp'] - p['entry']) * p['lot'] * contract_size
                p['reason'] = 'TP'
                closed = True
            else:
                if curr['high'] >= p['entry'] + p['atr_entry']:
                    if p['sl'] < p['entry']:
                        p['sl'] = p['entry']
                floating_pnl_total += (curr['close'] - p['entry']) * p['lot'] * contract_size
        else:
            if curr['high'] >= p['sl']:
                pnl = (p['entry'] - p['sl']) * p['lot'] * contract_size
                p['reason'] = 'SL' if p['sl'] > p['entry'] else 'BE'
                closed = True
            elif curr['low'] <= p['tp']:
                pnl = (p['entry'] - p['tp']) * p['lot'] * contract_size
                p['reason'] = 'TP'
                closed = True
            else:
                if curr['low'] <= p['entry'] - p['atr_entry']:
                    if p['sl'] > p['entry']:
                        p['sl'] = p['entry']
                floating_pnl_total += (p['entry'] - curr['close']) * p['lot'] * contract_size
                
        if closed:
            balance += pnl
            p['exit_time'] = curr['time']
            p['pnl'] = pnl
            p['balance_after'] = balance
            trades.append(p)
            closed_pos.append(p)
            
    for cp in closed_pos:
        active_pos.remove(cp)
        
    equity = balance + floating_pnl_total
    if equity > peak_equity: peak_equity = equity
    dd = peak_equity - equity
    if dd > max_dd: max_dd = dd
    if peak_equity > 0 and (dd/peak_equity)*100 > max_dd_pct: max_dd_pct = (dd/peak_equity)*100
    
    daily_dd = (start_of_day_balance - equity) / start_of_day_balance if start_of_day_balance > 0 else 0
    if daily_dd >= MAX_DAILY_DD and not halt_today:
        halt_today = True
        halt_count += 1
    
    if len(active_pos) < MAX_POSITIONS and not halt_today:
        
        buy_signal = (
            curr['bullish'] and
            curr['ema50_h4'] > curr['ema200_h4'] and
            curr['ema50_h1'] > curr['ema200_h1'] and
            curr['ema20_m5'] > curr['ema50_m5'] and
            curr['rsi'] < 55 and
            curr['rsi'] > curr['prev_rsi']
        )
        
        sell_signal = (
            curr['bearish'] and
            curr['ema50_h4'] < curr['ema200_h4'] and
            curr['ema50_h1'] < curr['ema200_h1'] and
            curr['ema20_m5'] < curr['ema50_m5'] and
            curr['rsi'] > 45 and
            curr['rsi'] < curr['prev_rsi']
        )
        
        # --- HIGH CONFIDENCE CHECK ---
        is_hc = False
        if buy_signal and curr['adx'] > 25: is_hc = True
        if sell_signal and curr['adx'] > 25: is_hc = True
        
        # --- PYRAMIDING LOGIC ---
        if len(active_pos) > 0:
            current_type = active_pos[0]['type']
            last_entry = active_pos[-1]['entry']
            
            # Kunci arah (No Hedging) + Filter jarak antar entry (Min 0.5 ATR)
            if current_type == 'BUY':
                sell_signal = False
                if buy_signal and abs(curr['open'] - last_entry) < (curr['atr'] * 0.5):
                    buy_signal = False
            elif current_type == 'SELL':
                buy_signal = False
                if sell_signal and abs(curr['open'] - last_entry) < (curr['atr'] * 0.5):
                    sell_signal = False

        if buy_signal or sell_signal:
            entry_atr = curr['atr']
            if entry_atr == 0 or np.isnan(entry_atr): continue
            
            if buy_signal:
                entry_price = curr['open'] + spread
                sl = entry_price - (entry_atr * SL_MULT)
                tp = entry_price + (entry_atr * TP_MULT)
                typ = 'BUY'
            else:
                entry_price = curr['open'] - spread
                sl = entry_price + (entry_atr * SL_MULT)
                tp = entry_price - (entry_atr * TP_MULT)
                typ = 'SELL'
                
            used_risk = HC_RISK_PCT if is_hc else RISK_PCT
            risk_amt = balance * used_risk
            sl_dist = abs(entry_price - sl)
            loss_1_lot = sl_dist * contract_size
            lot = round(risk_amt / loss_1_lot, 2) if loss_1_lot > 0 else 0.01
            lot = max(0.01, lot)
            
            active_pos.append({
                'type': typ,
                'entry_time': curr['time'],
                'entry': entry_price,
                'sl': sl,
                'tp': tp,
                'atr_entry': entry_atr,
                'lot': lot,
                'is_hc': is_hc
            })

for p in active_pos:
    last_close = df_m5.iloc[-1]['close']
    if p['type'] == 'BUY':
        pnl = (last_close - p['entry']) * p['lot'] * contract_size
    else:
        pnl = (p['entry'] - last_close) * p['lot'] * contract_size
    balance += pnl
    p['exit_time'] = df_m5.iloc[-1]['time']
    p['pnl'] = pnl
    p['reason'] = 'FINAL'
    p['balance_after'] = balance
    trades.append(p)

print("\n=========================================")
print(f"HASIL BACKTEST AGRESIF USDCAD# ({DAYS} HARI M5)")
print("=========================================")
print(f"Total Trades : {len(trades)}")
if trades:
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100
    
    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    be_count = sum(1 for t in trades if t['reason'] == 'BE')
    
    print(f"Win Rate     : {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"BE Hit       : {be_count} trades")
    print(f"Net Profit   : ${balance - INITIAL_BALANCE:.2f}")
    print(f"Final Balance: ${balance:.2f}")
    print(f"Profit Factor: {pf:.2f}")
    print(f"Max Drawdown : {max_dd_pct:.2f}% (${max_dd:.2f})")
    print(f"Days Halted  : {halt_count} hari (Kena cut-off 2%)")