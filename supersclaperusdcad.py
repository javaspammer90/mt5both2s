"""
supersclaperusdcad.py
Scalper Live — USDCAD# (M15 + H1 Trend)
- Target: 10-20 trade/hari
- Manajemen Risiko: Open Posisi 1% dari Modal (Dynamic Lot)
- Max Daily Drawdown: 2% (Stop trade harian jika tercapai)
- Filter: London/NY Session (07-16 UTC) | ADX>=18 | ATR>ATRmean*0.8 | H1 EMA20
- TP: 2x ATR | SL: 1x ATR
"""

import sys, time, json, math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, time as dtime
sys.path.append("/root")
import rpyc

# === CONFIG ===
SYMBOL      = "USDCAD#"
TF_M15      = 15      # mt5.TIMEFRAME_M15
TF_H1       = 16385   # mt5.TIMEFRAME_H1
BARS_M15    = 200
BARS_H1     = 100
RISK_PCT    = 0.01    # 1% risk per trade
MAX_DAILY_DD= 0.02    # 2% max drawdown per hari
MAX_TRADES  = 20
SLEEP_TIME  = 60      # Loop delay (detik)
MAGIC_NUM   = 123456

# Constants
OP_BUY = 0
OP_SELL = 1

def in_session(ts_unix: float) -> bool:
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    return dtime(7, 0) <= t <= dtime(16, 0)

def wilder_smoothing(series: pd.Series, period: int) -> pd.Series:
    res = np.zeros(len(series))
    alpha = 1.0 / period
    for i in range(len(series)):
        if i == 0:
            res[i] = series.iloc[i]
        else:
            res[i] = (alpha * series.iloc[i]) + ((1 - alpha) * res[i-1])
    return pd.Series(res, index=series.index)

def calc_adx(df: pd.DataFrame, period=14):
    df['up'] = df['high'] - df['high'].shift(1)
    df['down'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up'] > df['down']) & (df['up'] > 0), df['up'], 0.0)
    df['minus_dm'] = np.where((df['down'] > df['up']) & (df['down'] > 0), df['down'], 0.0)
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
    
    df['tr_sm'] = wilder_smoothing(df['tr'].fillna(0), period)
    df['plus_dm_sm'] = wilder_smoothing(df['plus_dm'].fillna(0), period)
    df['minus_dm_sm'] = wilder_smoothing(df['minus_dm'].fillna(0), period)
    
    df['+di'] = 100 * (df['plus_dm_sm'] / df['tr_sm'].replace(0, np.nan))
    df['-di'] = 100 * (df['minus_dm_sm'] / df['tr_sm'].replace(0, np.nan))
    
    dx = 100 * abs(df['+di'] - df['-di']) / (df['+di'] + df['-di']).replace(0, np.nan)
    df['adx'] = wilder_smoothing(dx.fillna(0), period)
    return df

def get_data(mt5, symbol, tf, count):
    res = mt5.bulk_rates_json(symbol, tf, 0, count)
    data = json.loads(res)
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    df.rename(columns={'time':'time_s', 'open':'open', 'high':'high', 'low':'low', 'close':'close', 'tick_volume':'tick_volume'}, inplace=True)
    return df

def run_bot():
    print("Mulai Super Scalper USDCAD#")
    try:
        conn = rpyc.connect("localhost", 18812)
        mt5 = conn.root
        # Di RPyC server-side, tidak perlu client init. Server sudah running & connected.
        
        info = mt5.symbol_info(SYMBOL)
        if info is None or info == "null":
            print(f"{SYMBOL} tidak ditemukan.")
            return
            
        if isinstance(info, str): info = json.loads(info)
        if not info.get('visible', False):
            mt5.symbol_select(SYMBOL, True)
            
        print("Koneksi MT5 sukses.")
        
    except Exception as e:
        print(f"Error koneksi: {e}")
        return

    trades_today = 0
    def get_acc(m):
        try:
            acc = m.account_info()
            if isinstance(acc, str):
                return json.loads(acc)
            
            # netref conversion
            keys = ["login","trade_mode","leverage","limit_orders","margin_so_mode",
                    "trade_allowed","trade_expert","margin_mode","currency_digits",
                    "fifo_close","balance","credit","profit","equity","margin",
                    "margin_free","margin_level","margin_so_call","margin_so_so",
                    "margin_initial","margin_maintenance","assets","liabilities",
                    "commission_blocked","name","server","currency","company"]
            res = {}
            for k in keys:
                try: res[k] = acc[k]
                except: pass
            return res
        except Exception as e:
            print(f"get_acc err: {e}")
            return {}

    start_acc = get_acc(mt5)
    start_bal = start_acc.get('balance', 0)
    current_day = datetime.now(timezone.utc).date()

    while True:
        try:
            now_day = datetime.now(timezone.utc).date()
            if now_day != current_day:
                current_day = now_day
                trades_today = 0
                start_acc = get_acc(mt5)
                start_bal = start_acc.get('balance', 0)
                print(f"Hari baru. Reset trade count. Start balance: {start_bal}")

            acc = get_acc(mt5)
            if not acc:
                print("Gagal ambil info akun.")
                time.sleep(SLEEP_TIME)
                continue
            
            eq = acc.get('equity', 0)
            start_bal_val = start_bal if isinstance(start_bal, (float, int)) else start_bal['balance']
            dd_pct = (start_bal_val - eq) / start_bal_val if start_bal_val > 0 else 0
            
            if dd_pct >= MAX_DAILY_DD:
                print(f"Drawdown {dd_pct*100:.2f}% >= {MAX_DAILY_DD*100}%. STOP HARI INI.")
                time.sleep(3600)
                continue

            if trades_today >= MAX_TRADES:
                print(f"Target {MAX_TRADES} trade tercapai hari ini. Istirahat.")
                time.sleep(3600)
                continue

            # Cek posisi terbuka
            pos_raw = mt5.positions_get(SYMBOL)
            positions = json.loads(pos_raw) if isinstance(pos_raw, str) else list(pos_raw) if pos_raw else []
            if len(positions) > 0:
                print(f"Sedang ada posisi {SYMBOL}. Tunggu close.")
                time.sleep(SLEEP_TIME)
                continue

            # Load Data
            df15 = get_data(mt5, SYMBOL, TF_M15, BARS_M15)
            dfh1 = get_data(mt5, SYMBOL, TF_H1, BARS_H1)
            
            if df15.empty or dfh1.empty:
                print("Gagal ambil data bar.")
                time.sleep(SLEEP_TIME)
                continue
                
            last_time = df15['time_s'].iloc[-1]
            if not in_session(last_time):
                print("Di luar sesi aktif.")
                time.sleep(SLEEP_TIME)
                continue

            # Indikator M15
            df15 = calc_adx(df15, 14)
            df15['tr_tmp'] = np.maximum(df15['high'] - df15['low'], 
                                   np.maximum(abs(df15['high'] - df15['close'].shift(1)), abs(df15['low'] - df15['close'].shift(1))))
            df15['atr'] = df15['tr_tmp'].rolling(14).mean()
            df15['atr_mean'] = df15['atr'].rolling(50).mean()
            
            # Indikator H1
            dfh1['ema20'] = dfh1['close'].ewm(span=20, adjust=False).mean()

            curr_15 = df15.iloc[-2]  # Bar close terakhir
            curr_h1 = dfh1.iloc[-2]
            
            adx_val = curr_15['adx']
            atr_val = curr_15['atr']
            atr_mean = curr_15['atr_mean']
            
            close_15 = curr_15['close']
            ema20_h1 = curr_h1['ema20']
            
            # Sinyal
            signal = None
            if adx_val >= 18 and atr_val > (atr_mean * 0.8):
                if close_15 > ema20_h1 and curr_15['+di'] > curr_15['-di']:
                    signal = OP_BUY
                elif close_15 < ema20_h1 and curr_15['-di'] > curr_15['+di']:
                    signal = OP_SELL

            if signal is not None:
                tick_raw = mt5.symbol_info_tick(SYMBOL)
                if not tick_raw: continue
                if isinstance(tick_raw, str):
                    tick = json.loads(tick_raw)
                else:
                    tick = {}
                    for k in ['time','bid','ask','last','volume','time_msc','flags','volume_real']:
                        try: tick[k] = tick_raw[k]
                        except: pass
                
                ask = tick.get('ask', 0)
                bid = tick.get('bid', 0)
                
                sym_raw = mt5.symbol_info(SYMBOL)
                if isinstance(sym_raw, str):
                    sym_info = json.loads(sym_raw)
                else:
                    sym_info = {}
                    for k in ['point','trade_tick_value','trade_tick_size','volume_min','volume_max']:
                        try: sym_info[k] = sym_raw[k]
                        except: pass
                point = sym_info.get('point', 0.00001)
                
                sl_dist = atr_val
                tp_dist = atr_val * 2.0
                
                # Risk calc
                risk_amt = eq * RISK_PCT
                tick_value = sym_info.get('trade_tick_value', 1.0)
                tick_size = sym_info.get('trade_tick_size', point)
                if tick_size == 0 or tick_value == 0: continue
                
                sl_points = sl_dist / point
                lot_calc = risk_amt / (sl_points * (tick_value / (tick_size / point)))
                
                lot = round(lot_calc, 2)
                min_lot = sym_info.get('volume_min', 0.01)
                max_lot = sym_info.get('volume_max', 100.0)
                lot = max(min_lot, min(lot, max_lot))

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": SYMBOL,
                    "volume": lot,
                    "type": mt5.ORDER_TYPE_BUY if signal == OP_BUY else mt5.ORDER_TYPE_SELL,
                    "price": ask if signal == OP_BUY else bid,
                    "sl": (ask - sl_dist) if signal == OP_BUY else (bid + sl_dist),
                    "tp": (ask + tp_dist) if signal == OP_BUY else (bid - tp_dist),
                    "deviation": 20,
                    "magic": MAGIC_NUM,
                    "comment": "SuperScalper",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }

                print(f"Kirim order {request['type']} Lot: {lot} SL: {request['sl']} TP: {request['tp']}")
                req_raw = mt5.order_send(json.dumps(request)) if isinstance(mt5.order_send, type(lambda: None)) else mt5.order_send(request)
                result = json.loads(req_raw) if isinstance(req_raw, str) else dict(req_raw) if req_raw else {'retcode': -1}
                if result.get('retcode') != 10009: # TRADE_RETCODE_DONE
                    print(f"Gagal OP. Code: {result.get('retcode')}")
                else:
                    print(f"Sukses OP. Ticket: {result.get('order')}")
                    trades_today += 1

        except Exception as e:
            print(f"Error loop: {e}")
        
        time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    run_bot()
