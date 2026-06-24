"""
botadxxauusdm30.py
Live Trading Bot — XAUUSD# (TF M30)
- Strategi: ADX Breakout Dominance (berdasarkan PDF)
- Trigger: +DMI > -DMI dan tembus level 25 (BUY) / -DMI > +DMI dan tembus level 25 (SELL) + ADX Menanjak.
- Risk/Trade: 1% (Dynamic Lot via ATR)
- Max Drawdown: 5% per hari
- SL: 2.5x ATR | TP: 4.0x ATR | Trailing BE: +1x ATR
- Max Active Posisi: 1 (Tidak ada pyramiding)
"""

import sys, time, json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, time as dtime
sys.path.append("/root")
import rpyc

# === CONFIG ===
SYMBOL       = "XAUUSD#"
TF_M30       = 30      # mt5.TIMEFRAME_M30
BARS_M30     = 100
RISK_PCT     = 0.01    # 1% risk per trade
MAX_DAILY_DD = 0.05    # 5% max drawdown per hari
MAX_TRADES   = 20
MAX_POS      = 1
SLEEP_TIME   = 60      # Loop delay (detik)
MAGIC_NUM    = 999123

OP_BUY = 0
OP_SELL = 1

def in_session(ts_unix: float) -> bool:
    # Trading hanya aktif 01:00 - 22:00 UTC
    t = datetime.fromtimestamp(ts_unix, tz=timezone.utc).time()
    return dtime(1, 0) <= t <= dtime(22, 0)

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
    print(" Mulai Live Bot XAUUSD# M30 (ADX Breakout Dominance)")
    print("=====================================================")
    try:
        conn = rpyc.connect("localhost", 18812)
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
            
            print(f"\n[{now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC] --- SCANNING MARKET XAUUSD# M30 ---")
            
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
            df_tf = get_data(mt5, SYMBOL, TF_M30, BARS_M30)
            if df_tf.empty:
                print("[WARN] Gagal ambil data OHLC dari MT5.")
                time.sleep(SLEEP_TIME)
                continue

            # Menghitung ADX/DMI
            period = 14
            df_tf['up'] = df_tf['high'] - df_tf['high'].shift(1)
            df_tf['down'] = df_tf['low'].shift(1) - df_tf['low']
            df_tf['plus_dm'] = np.where((df_tf['up'] > df_tf['down']) & (df_tf['up'] > 0), df_tf['up'], 0.0)
            df_tf['minus_dm'] = np.where((df_tf['down'] > df_tf['up']) & (df_tf['down'] > 0), df_tf['down'], 0.0)
            df_tf['tr_adx'] = np.maximum(df_tf['high'] - df_tf['low'], np.maximum(abs(df_tf['high'] - df_tf['close'].shift(1)), abs(df_tf['low'] - df_tf['close'].shift(1))))

            df_tf['tr_sm'] = df_tf['tr_adx'].ewm(alpha=1/period, adjust=False).mean()
            df_tf['plus_dm_sm'] = df_tf['plus_dm'].ewm(alpha=1/period, adjust=False).mean()
            df_tf['minus_dm_sm'] = df_tf['minus_dm'].ewm(alpha=1/period, adjust=False).mean()

            df_tf['+di'] = 100 * (df_tf['plus_dm_sm'] / df_tf['tr_sm'])
            df_tf['-di'] = 100 * (df_tf['minus_dm_sm'] / df_tf['tr_sm'])
            dx = 100 * abs(df_tf['+di'] - df_tf['-di']) / (df_tf['+di'] + df_tf['-di']).replace(0, 1e-10)
            df_tf['adx'] = dx.ewm(alpha=1/period, adjust=False).mean()

            # Menghitung ATR untuk SL/TP
            high_low = df_tf['high'] - df_tf['low']
            high_close = np.abs(df_tf['high'] - df_tf['close'].shift())
            low_close = np.abs(df_tf['low'] - df_tf['close'].shift())
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df_tf['atr'] = true_range.rolling(14).mean()

            curr = df_tf.iloc[-1]
            prev = df_tf.iloc[-2]
            
            atr_val = curr['atr']
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
            print(f"[PRICE] Bid: {bid:.3f} | Ask: {ask:.3f} | ATR M30: {atr_val:.3f}")

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
                            "action": 3, 
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

            last_time = df_tf['time_s'].iloc[-1]
            if not in_session(last_time):
                print("[INFO] Di luar sesi aktif. Skip entry.")
                time.sleep(SLEEP_TIME)
                continue
            
            print(f"[IND-ADX] +DI: {curr['+di']:.2f} | -DI: {curr['-di']:.2f} | ADX: {curr['adx']:.2f} (Prev: {prev['adx']:.2f})")
            
            # LOGIC ADX BREAKOUT DOMINANCE
            buy_signal = (
                curr['+di'] > curr['-di'] and
                curr['+di'] > 25 and prev['+di'] <= 25 and
                curr['adx'] > prev['adx']
            )
            
            sell_signal = (
                curr['-di'] > curr['+di'] and
                curr['-di'] > 25 and prev['-di'] <= 25 and
                curr['adx'] > prev['adx']
            )

            if buy_signal: print("[SIGNAL] ADX Breakout +DI valid! (BUY)")
            if sell_signal: print("[SIGNAL] ADX Breakout -DI valid! (SELL)")

            if buy_signal or sell_signal:
                sym_raw = mt5.symbol_info(SYMBOL)
                if isinstance(sym_raw, str):
                    sym_info = json.loads(sym_raw)
                else:
                    sym_info = {}
                    for k in ['point','trade_tick_value','trade_tick_size','volume_min','volume_max']:
                        try: sym_info[k] = sym_raw[k]
                        except: pass
                point = float(sym_info['point']) if 'point' in sym_info else 0.001
                
                # SL 2.5 ATR | TP 4.0 ATR
                sl_dist = atr_val * 2.5
                tp_dist = atr_val * 4.0
                
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
                    "comment": "XAU_ADX_M30",
                    "type_time": 0, 
                    "type_filling": 1,
                }

                print(f"[ACTION] Kirim order {'BUY' if buy_signal else 'SELL'} Lot: {lot} SL: {request['sl']:.3f} TP: {request['tp']:.3f}")
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