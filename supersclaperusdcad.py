"""
supersclaperusdcad.py
Scalper Live — USDCAD# (Agresif M5)
- Target: 10-20 trade/hari
- Manajemen Risiko: Open Posisi 1% dari Modal (Dynamic Lot)
- Max Daily Drawdown: 2% (Stop trade harian jika tercapai)
- Filter: H4 EMA50/200, H1 EMA50/200, M5 EMA20/50, Pullback RSI
- SL: 1.5x ATR | TP: 2.4x ATR | BE: +1 ATR
- Max Active Posisi: 3 (Pyramiding)
"""

import sys, time, json, math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta, time as dtime
import rpyc

# === CONFIG ===
SYMBOL      = "USDCAD#"
TF_M5       = 5       # mt5.TIMEFRAME_M5
TF_H1       = 16385   # mt5.TIMEFRAME_H1
TF_H4       = 16388   # mt5.TIMEFRAME_H4
BARS_M5     = 100
BARS_H1     = 100
BARS_H4     = 50
RISK_PCT    = 0.01    # 1% risk per trade
MAX_DAILY_DD= 0.02    # 2% max drawdown per hari
MAX_TRADES  = 20
MAX_POS     = 5
SLEEP_TIME  = 30      # Loop delay (detik)
MAGIC_NUM   = 1234567

# Constants
OP_BUY = 0
OP_SELL = 1

def in_session(ts_unix: float) -> bool:
    # 07:00 - 16:00 UTC (Bebas disesuaikan)
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    return dtime(6, 0) <= t <= dtime(21, 0)

def get_data(mt5, symbol, tf, count):
    res_raw = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if not res_raw: return pd.DataFrame()
    
    data = []
    for r in res_raw:
        row_dict = dict(r) if hasattr(r, 'keys') else r
        if isinstance(row_dict, dict):
            data.append({
                'time_s': float(row_dict['time']),
                'open': float(row_dict['open']),
                'high': float(row_dict['high']),
                'low': float(row_dict['low']),
                'close': float(row_dict['close']),
            })
    
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data)
    df['time'] = pd.to_datetime(df['time_s'], unit='s')
    return df

def run_bot():
    print("=====================================================")
    print(" Mulai Super Scalper USDCAD# (Agresif M5 + H4/H1) ")
    print("=====================================================")
    try:
        conn = rpyc.connect('localhost', 18812)
        mt5 = conn.root
        
        info = mt5.symbol_info(SYMBOL)
        if info is None or info == "null":
            print(f"[ERROR] {SYMBOL} tidak ditemukan di Market Watch.")
            return
            
        if isinstance(info, str): info = json.loads(info)
        visible = info['visible'] if 'visible' in info else False
        if not visible:
            mt5.symbol_select(SYMBOL, True)
            
        print("[INFO] Koneksi MT5 sukses via RPyC.")
        
    except Exception as e:
        print(f"[ERROR] Koneksi gagal: {e}")
        return

    trades_today = 0
    def get_acc(m):
        try:
            acc = m.account_info()
            if isinstance(acc, str):
                return json.loads(acc)
            keys = ["login","balance","equity"]
            res = {}
            for k in keys:
                try: res[k] = acc[k]
                except: pass
            return res
        except Exception as e:
            return {}

    start_acc = get_acc(mt5)
    start_bal = float(start_acc['balance']) if 'balance' in start_acc else 0.0
    current_day = datetime.now(timezone.utc).date()

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_day = now_utc.date()
            
            print(f"\n[{now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC] --- SCANNING MARKET ---")
            
            if now_day != current_day:
                current_day = now_day
                trades_today = 0
                start_acc = get_acc(mt5)
                start_bal = float(start_acc['balance']) if 'balance' in start_acc else 0.0
                print(f"[INFO] Hari trading baru. Reset trade count. Start balance: ${start_bal:.2f}")

            acc = get_acc(mt5)
            if not acc:
                print("[WARN] Gagal ambil info akun, skip cycle ini.")
                time.sleep(SLEEP_TIME)
                continue
            
            eq = float(acc['equity']) if 'equity' in acc else 0.0
            start_bal_val = start_bal if isinstance(start_bal, (float, int)) else start_bal['balance']
            dd_pct = (start_bal_val - eq) / start_bal_val if start_bal_val > 0 else 0
            
            print(f"[ACC] Bal: ${start_bal_val:.2f} | Eq: ${eq:.2f} | DD: {dd_pct*100:.2f}% | Trades Today: {trades_today}/{MAX_TRADES}")
            
            if dd_pct >= MAX_DAILY_DD:
                print(f"[ALERT] Drawdown {dd_pct*100:.2f}% >= {MAX_DAILY_DD*100}%. STOP TRADING HARI INI.")
                time.sleep(3600)
                continue

            if trades_today >= MAX_TRADES:
                print(f"[INFO] Target {MAX_TRADES} trade tercapai hari ini. Istirahat.")
                time.sleep(3600)
                continue

            # Load Active Positions
            pos_raw = mt5.positions_get()
            all_positions = json.loads(pos_raw) if isinstance(pos_raw, str) else list(pos_raw) if pos_raw else []
            positions = [p for p in all_positions if (p['symbol'] if 'symbol' in p else getattr(p, 'symbol', '')) == SYMBOL and (p['magic'] if 'magic' in p else getattr(p, 'magic', 0)) == MAGIC_NUM]
            
            print(f"[POS] Active Positions: {len(positions)}/{MAX_POS}")
            for idx, p in enumerate(positions):
                p_type = 'BUY' if (p['type'] if 'type' in p else getattr(p, 'type', -1)) == OP_BUY else 'SELL'
                p_ticket = p['ticket'] if 'ticket' in p else getattr(p, 'ticket', 0)
                p_open = p['price_open'] if 'price_open' in p else getattr(p, 'price_open', 0)
                p_profit = p['profit'] if 'profit' in p else getattr(p, 'profit', 0)
                print(f"      {idx+1}. {p_type} | Ticket: {p_ticket} | Entry: {p_open} | PnL: ${p_profit}")
            
            # Load Data
            dfm5 = get_data(mt5, SYMBOL, TF_M5, BARS_M5)
            dfh1 = get_data(mt5, SYMBOL, TF_H1, BARS_H1)
            dfh4 = get_data(mt5, SYMBOL, TF_H4, BARS_H4)
            
            if dfm5.empty or dfh1.empty or dfh4.empty:
                print("[WARN] Gagal ambil data OHLC dari MT5.")
                time.sleep(SLEEP_TIME)
                continue

            # M5 Indicator Update (ATR calculation)
            high_low = dfm5['high'] - dfm5['low']
            high_close = np.abs(dfm5['high'] - dfm5['close'].shift())
            low_close = np.abs(dfm5['low'] - dfm5['close'].shift())
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            dfm5['atr'] = true_range.rolling(14).mean()
            
            curr_m5 = dfm5.iloc[-1]
            atr_val = curr_m5['atr']
            if atr_val == 0 or np.isnan(atr_val):
                print("[WARN] ATR bernilai 0 atau NaN.")
                time.sleep(SLEEP_TIME)
                continue
                
            tick_raw = mt5.symbol_tick(SYMBOL)
            if not tick_raw: 
                print("[WARN] Gagal ambil data tick.")
                time.sleep(SLEEP_TIME)
                continue
                
            if isinstance(tick_raw, str):
                tick = json.loads(tick_raw)
            else:
                tick = {}
                for k in ['bid','ask']:
                    try: tick[k] = tick_raw[k]
                    except: pass
            
            ask = float(tick['ask']) if 'ask' in tick else 0.0
            bid = float(tick['bid']) if 'bid' in tick else 0.0
            print(f"[PRICE] Bid: {bid:.5f} | Ask: {ask:.5f} | ATR M5: {atr_val:.5f}")

            # --- BREAK EVEN TRAILING ---
            for p in positions:
                ticket = p['ticket'] if 'ticket' in p else getattr(p, 'ticket', 0)
                ptype = p['type'] if 'type' in p else getattr(p, 'type', -1)
                p_open = float(p['price_open'] if 'price_open' in p else getattr(p, 'price_open', 0))
                p_sl = float(p['sl'] if 'sl' in p else getattr(p, 'sl', 0))
                
                # Cek jika profit sudah > 1 ATR
                be_level = atr_val
                if ptype == OP_BUY:
                    if bid >= p_open + be_level and p_sl < p_open:
                        req_be = {
                            "action": 3, # mt5.TRADE_ACTION_SLTP
                            "symbol": SYMBOL,
                            "position": ticket,
                            "sl": p_open,
                            "tp": float(p['tp'] if 'tp' in p else getattr(p, 'tp', 0))
                        }
                        mt5.order_send(json.dumps(req_be))
                        print(f"[TRAIL] Pindah BE BUY Ticket {ticket} ke harga entry {p_open}")
                        
                elif ptype == OP_SELL:
                    if ask <= p_open - be_level and (p_sl > p_open or p_sl == 0):
                        req_be = {
                            "action": 3, 
                            "symbol": SYMBOL,
                            "position": ticket,
                            "sl": p_open,
                            "tp": float(p['tp'] if 'tp' in p else getattr(p, 'tp', 0))
                        }
                        mt5.order_send(json.dumps(req_be))
                        print(f"[TRAIL] Pindah BE SELL Ticket {ticket} ke harga entry {p_open}")

            if len(positions) >= MAX_POS:
                print(f"[INFO] Jumlah posisi max ({MAX_POS}) tercapai. Menunggu posisi close.")
                time.sleep(SLEEP_TIME)
                continue

            last_time = dfm5['time_s'].iloc[-1]
            if not in_session(last_time):
                print("[INFO] Di luar sesi aktif (06:00 - 21:00 UTC). Skip entry.")
                time.sleep(SLEEP_TIME)
                continue

            # Indicators Calculation
            # H4
            dfh4['ema50'] = dfh4['close'].ewm(span=50, adjust=False).mean()
            dfh4['ema200'] = dfh4['close'].ewm(span=200, adjust=False).mean()
            # H1
            dfh1['ema50'] = dfh1['close'].ewm(span=50, adjust=False).mean()
            dfh1['ema200'] = dfh1['close'].ewm(span=200, adjust=False).mean()
            # M5
            dfm5['ema20'] = dfm5['close'].ewm(span=20, adjust=False).mean()
            dfm5['ema50'] = dfm5['close'].ewm(span=50, adjust=False).mean()
            
            delta = dfm5['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            dfm5['rsi'] = 100 - (100 / (1 + rs))

            curr_h4 = dfh4.iloc[-1]
            curr_h1 = dfh1.iloc[-1]
            curr_m5 = dfm5.iloc[-1]
            prev_m5 = dfm5.iloc[-2]
            
            print(f"[IND-H4] EMA50: {curr_h4['ema50']:.5f} | EMA200: {curr_h4['ema200']:.5f} => {'UP' if curr_h4['ema50'] > curr_h4['ema200'] else 'DOWN'}")
            print(f"[IND-H1] EMA50: {curr_h1['ema50']:.5f} | EMA200: {curr_h1['ema200']:.5f} => {'UP' if curr_h1['ema50'] > curr_h1['ema200'] else 'DOWN'}")
            print(f"[IND-M5] EMA20: {curr_m5['ema20']:.5f} | EMA50 : {curr_m5['ema50']:.5f} => {'UP' if curr_m5['ema20'] > curr_m5['ema50'] else 'DOWN'}")
            print(f"[IND-RSI] Current: {curr_m5['rsi']:.2f} | Previous: {prev_m5['rsi']:.2f}")
            
            # Sinyal
            signal = None
            bullish_m5 = curr_m5['close'] > curr_m5['open']
            bearish_m5 = curr_m5['close'] < curr_m5['open']
            
            buy_h4_ok = curr_h4['ema50'] > curr_h4['ema200']
            buy_h1_ok = curr_h1['ema50'] > curr_h1['ema200']
            buy_m5_ok = curr_m5['ema20'] > curr_m5['ema50']
            buy_rsi_ok = curr_m5['rsi'] < 55 and curr_m5['rsi'] > prev_m5['rsi']
            
            sell_h4_ok = curr_h4['ema50'] < curr_h4['ema200']
            sell_h1_ok = curr_h1['ema50'] < curr_h1['ema200']
            sell_m5_ok = curr_m5['ema20'] < curr_m5['ema50']
            sell_rsi_ok = curr_m5['rsi'] > 45 and curr_m5['rsi'] < prev_m5['rsi']
            
            buy_signal = bullish_m5 and buy_h4_ok and buy_h1_ok and buy_m5_ok and buy_rsi_ok
            sell_signal = bearish_m5 and sell_h4_ok and sell_h1_ok and sell_m5_ok and sell_rsi_ok

            # --- PYRAMIDING LOGIC ---
            if len(positions) > 0:
                # Ambil data posisi terakhir (paling baru masuk)
                last_pos = positions[-1]
                current_type = 'BUY' if (last_pos['type'] if 'type' in last_pos else getattr(last_pos, 'type', -1)) == OP_BUY else 'SELL'
                last_entry = float(last_pos['price_open'] if 'price_open' in last_pos else getattr(last_pos, 'price_open', 0))
                
                print(f"[LOGIC] Ada posisi {current_type}. Cek spacing pyramiding (Min distance: {atr_val*0.5:.5f})")
                
                # Kunci arah (No Hedging) + Filter jarak antar entry (Min 0.5 ATR)
                if current_type == 'BUY':
                    sell_signal = False
                    if buy_signal:
                        jarak = abs(ask - last_entry)
                        if jarak < (atr_val * 0.5):
                            print(f"[LOGIC] BUY di-cancel! Jarak entry ({jarak:.5f}) < 0.5 ATR ({atr_val*0.5:.5f})")
                            buy_signal = False
                        else:
                            print(f"[LOGIC] Jarak BUY aman ({jarak:.5f} >= {atr_val*0.5:.5f})")
                            
                elif current_type == 'SELL':
                    buy_signal = False
                    if sell_signal:
                        jarak = abs(bid - last_entry)
                        if jarak < (atr_val * 0.5):
                            print(f"[LOGIC] SELL di-cancel! Jarak entry ({jarak:.5f}) < 0.5 ATR ({atr_val*0.5:.5f})")
                            sell_signal = False
                        else:
                            print(f"[LOGIC] Jarak SELL aman ({jarak:.5f} >= {atr_val*0.5:.5f})")

            if buy_signal: print("[SIGNAL] Setup BUY valid!")
            if sell_signal: print("[SIGNAL] Setup SELL valid!")

            if buy_signal or sell_signal:
                sym_raw = mt5.symbol_info(SYMBOL)
                if isinstance(sym_raw, str):
                    sym_info = json.loads(sym_raw)
                else:
                    sym_info = {}
                    for k in ['point','trade_tick_value','trade_tick_size','volume_min','volume_max']:
                        try: sym_info[k] = sym_raw[k]
                        except: pass
                point = float(sym_info['point']) if 'point' in sym_info else 0.00001
                
                sl_dist = atr_val * 1.5
                tp_dist = atr_val * 2.4
                
                # Risk calc
                risk_amt = eq * RISK_PCT
                tick_value = float(sym_info['trade_tick_value']) if 'trade_tick_value' in sym_info else 1.0
                tick_size = float(sym_info['trade_tick_size']) if 'trade_tick_size' in sym_info else point
                if tick_size == 0 or tick_value == 0: 
                    print("[ERROR] Tick value/size 0, skip OP.")
                    time.sleep(SLEEP_TIME)
                    continue
                
                sl_points = sl_dist / point
                lot_calc = risk_amt / (sl_points * (tick_value / (tick_size / point)))
                
                lot = round(lot_calc, 2)
                min_lot = float(sym_info['volume_min']) if 'volume_min' in sym_info else 0.01
                max_lot = float(sym_info['volume_max']) if 'volume_max' in sym_info else 100.0
                lot = max(min_lot, min(lot, max_lot))

                request = {
                    "action": 1, # mt5.TRADE_ACTION_DEAL
                    "symbol": SYMBOL,
                    "volume": lot,
                    "type": 0 if buy_signal else 1,
                    "price": ask if buy_signal else bid,
                    "sl": (ask - sl_dist) if buy_signal else (bid + sl_dist),
                    "tp": (ask + tp_dist) if buy_signal else (bid - tp_dist),
                    "deviation": 20,
                    "magic": MAGIC_NUM,
                    "comment": "USDCAD_AGR",
                    "type_time": 0, 
                    "type_filling": 1,
                }

                print(f"[ACTION] Kirim order {'BUY' if buy_signal else 'SELL'} Lot: {lot} SL: {request['sl']:.5f} TP: {request['tp']:.5f}")
                req_raw = mt5.order_send(json.dumps(request))
                result = json.loads(req_raw) if isinstance(req_raw, str) else dict(req_raw) if req_raw else {'retcode': -1}
                retcode = result['retcode'] if 'retcode' in result else -1
                if retcode != 10009: 
                    print(f"[ERROR] Gagal OP. Code: {retcode}")
                else:
                    order_id = result['order'] if 'order' in result else -1
                    print(f"[SUCCESS] OP Berhasil! Ticket: {order_id}")
                    trades_today += 1
            else:
                print("[LOGIC] Tidak ada sinyal entry pada siklus ini.")

        except Exception as e:
            print(f"[ERROR] Exception in main loop: {e}")
        
        time.sleep(SLEEP_TIME)

if __name__ == "__main__":
    run_bot()