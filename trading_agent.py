"""
AI Trading Agent - USDJPY# M5 (Scalping-Oriented Scoring V3)
Alur: Analisa -> Cek Drawdown -> Open Posisi -> Laporan Telegram
Logic: Scoring V3 + ATR hard filter + Session Filter + Test B Risk/Reward (SL=1xATR, TP=2xATR)
"""
import sys
import os
import json
import time
import requests
import numpy as np
from datetime import datetime, timezone

sys.path.append("/root")

from mt5both2s.modules.mt5_service import MT5Service
from mt5both2s.modules.risk_manager import calculate_risk
from mt5both2s.modules.indicator_engine import calculate_indicators
from mt5both2s.modules.decision_engine import calculate_decision

# ============================================================
# CONFIG
# ============================================================
SYMBOL        = "USDJPY#"
TIMEFRAME     = 5           # M5
BARS          = 250
RISK_PCT      = 0.5         # 0.5% risk per trade
CONTRACT      = 100000      # USDJPY Contract Size: 100k
LOT_MIN       = 0.01
LOT_MAX       = 0.50
MAGIC         = 20250620

# Test B Settings
ATR_SL_MULT   = 1.0
ATR_TP_MULT   = 2.0

TG_TOKEN  = os.environ.get("TG_TOKEN", "8845288812:***")
TG_CHATID = os.environ.get("TG_CHATID", "1220498273")

# ============================================================
# HELPERS
# ============================================================
def send_telegram(msg: str):
    if not TG_TOKEN:
        print(f"[TG] {msg}")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHATID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"[TG ERROR] {e}")

def calc_lot(balance: float, atr: float) -> float:
    """
    Lot = (balance * risk%) / (ATR * SL_mult * Contract)
    Convert JPY profit back to USD for proper lot calculation since contract is in base currency (USD)
    but profit is calculated in JPY.
    """
    risk_amount = balance * (RISK_PCT / 100.0)
    # USDJPY ATR 0.050 JPY = 50 pips. 50 pips * contract_size (100k) * lot = Profit in JPY.
    # To risk 'risk_amount' in USD, we convert SL to USD value per 1 lot.
    # SL JPY per 1 lot = ATR * ATR_SL_MULT * CONTRACT
    # Conversion to USD = SL JPY / Current_USDJPY_Price
    # We estimate current price to be around 161 (or grab exact tick price)
    est_price = 161.0
    sl_jpy = atr * ATR_SL_MULT * CONTRACT
    sl_usd = sl_jpy / est_price
    
    if sl_usd <= 0:
        return LOT_MIN
    lot = risk_amount / sl_usd
    lot = round(max(LOT_MIN, min(LOT_MAX, lot)), 2)
    return lot

def positions_for_symbol(mt5: MT5Service, symbol: str) -> list:
    return [p for p in mt5.get_positions() if p.get("symbol") == symbol]

def open_order(mt5: MT5Service, action: int, symbol: str, lot: float,
               sl: float, tp: float, comment: str) -> dict:
    tick = mt5.get_tick(symbol)
    if not tick:
        return {"retcode": -1, "comment": "No tick"}

    price  = tick["ask"] if action == 0 else tick["bid"]  # 0=BUY, 1=SELL
    
    # USDJPY uses 3 decimal places
    sl     = round(sl, 3)
    tp     = round(tp, 3)
    price  = round(price, 3)

    ORDER_FILLING_IOC = 1

    req = {
        "action":    1,          # TRADE_ACTION_DEAL
        "symbol":    symbol,
        "volume":    lot,
        "type":      action,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "deviation": 20,
        "magic":     MAGIC,
        "comment":   comment,
        "type_time": 0,          # ORDER_TIME_GTC
        "type_filling": ORDER_FILLING_IOC,
    }
    return mt5.order_send(req)

# ============================================================
# MAIN AGENT
# ============================================================
def run():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now_str}] AI Trading Agent USDJPY M5 START")

    # 1. Koneksi MT5
    mt5 = MT5Service()
    if not mt5.connect():
        msg = f"⚠️ <b>MT5 CONNECTION FAILED</b>\n{now_str}\nRPyC tidak bisa terhubung ke Docker MT5."
        send_telegram(msg)
        return

    # 2. Account info
    acc = mt5.get_account_info()
    if not acc:
        send_telegram(f"⚠️ <b>MT5 Account info gagal</b>\n{now_str}")
        return

    balance      = acc["balance"]
    equity       = acc["equity"]
    # Gunakan balance sebagai proxy daily start equity
    daily_start  = balance 

    # 3. Cek Risk Manager (DD & Profit harian)
    risk = calculate_risk(
        balance         = balance,
        equity          = equity,
        daily_start_equity = daily_start,
        risk_percent    = RISK_PCT,
        sl_points       = 100,   
        tick_value      = 1.0
    )

    if not risk["can_trade"]:
        msg = (
            f"🛑 <b>TRADING DIHENTIKAN</b>\n"
            f"⏰ {now_str}\n"
            f"📌 {risk['reason']}\n"
            f"💰 Balance: ${balance:.2f} | Equity: ${equity:.2f}"
        )
        send_telegram(msg)
        print(f"[STOP] {risk['reason']}")
        return

    # 4. Cek posisi open (Hanya perbolehkan 1 open trade)
    open_pos = positions_for_symbol(mt5, SYMBOL)
    if open_pos:
        p        = open_pos[0]
        pnl      = p.get("profit", 0)
        vol      = p.get("volume", 0)
        ptype    = "BUY" if p.get("type") == 0 else "SELL"
        print(f"[SKIP] Posisi {ptype} {vol} lot sudah open untuk {SYMBOL}. PnL: ${pnl:.2f}")
        return

    # 5. Hitung Indikator & Jalankan Decision Engine V3 (Termasuk filter sesi & ATR di dalamnya)
    inds = calculate_indicators(mt5, SYMBOL, timeframe=TIMEFRAME, bars=BARS)
    if not inds:
        print(f"[SKIP] Gagal menghitung indikator. Market tutup atau data tidak cukup.")
        return

    decision = calculate_decision(inds, similarity_score=0.0)
    action = decision["action"]
    reason = decision["reason"]

    if action not in ["BUY", "SELL"]:
        print(f"[NO SIGNAL/FILTERED] Reason: {reason} | Score: BUY {decision['buy_score']} - SELL {decision['sell_score']} | ADX: {decision['adx']}")
        return

    # 6. Sinyal Diterima -> Eksekusi Order
    atr = inds["atr"]
    lot = calc_lot(balance, atr)

    tick = mt5.get_tick(SYMBOL)
    if not tick:
        send_telegram(f"⚠️ Gagal ambil tick {SYMBOL}")
        return

    entry = tick["ask"] if action == "BUY" else tick["bid"]
    
    # Gunakan setting Test B (SL=1.0xATR, TP=2.0xATR)
    atr_val = max(atr, 0.050) # minimal 50 pips
    
    if action == "BUY":
        order_type = 0 # BUY
        sl_price = entry - atr_val * ATR_SL_MULT
        tp_price = entry + atr_val * ATR_TP_MULT
        signal = "🟢 BUY"
    else:
        order_type = 1 # SELL
        sl_price = entry + atr_val * ATR_SL_MULT
        tp_price = entry - atr_val * ATR_TP_MULT
        signal = "🔴 SELL"

    # Perhitungan USD equivalen untuk notifikasi Telegram
    sl_usd = (atr_val * ATR_SL_MULT * CONTRACT * lot) / entry
    tp_usd = (atr_val * ATR_TP_MULT * CONTRACT * lot) / entry

    comment = f"AI-EA V3 {SYMBOL} M5"
    result  = open_order(mt5, order_type, SYMBOL, lot, sl_price, tp_price, comment)
    retcode = result.get("retcode", -1)
    success = retcode == 10009  # TRADE_RETCODE_DONE

    # 7. Kirim Notifikasi Telegram
    dd_pct   = ((daily_start - equity) / daily_start * 100) if daily_start > 0 else 0
    prof_pct = ((equity - daily_start) / daily_start * 100) if daily_start > 0 else 0

    if success:
        msg = (
            f"✅ <b>ORDER SCALPING BERHASIL</b>\n"
            f"⏰ {now_str}\n\n"
            f"📊 <b>{SYMBOL} M5 (Scalping V3) — {signal}</b>\n"
            f"📥 Entry : <code>{entry:.3f}</code>\n"
            f"🛑 SL    : <code>{sl_price:.3f}</code> (~-${sl_usd:.2f})\n"
            f"🎯 TP    : <code>{tp_price:.3f}</code> (~+${tp_usd:.2f})\n"
            f"📦 Lot   : <code>{lot}</code>\n"
            f"📉 Conf  : <code>{decision['confidence']*100:.1f}%</code>\n"
            f"📝 Reason: <code>{reason}</code>\n\n"
            f"💼 <b>Account</b>\n"
            f"💰 Balance : ${balance:.2f}\n"
            f"📉 DD Hari : {dd_pct:.2f}% (Max 2%)\n"
            f"🔖 Order#  : {result.get('order', '-')}"
        )
    else:
        msg = (
            f"❌ <b>ORDER SCALPING GAGAL</b>\n"
            f"⏰ {now_str}\n\n"
            f"📊 {signal} {SYMBOL} {lot} lot\n"
            f"⚠️ Retcode : {retcode}\n"
            f"💬 Comment : {result.get('comment', '-')}\n\n"
            f"💰 Balance : ${balance:.2f}"
        )

    send_telegram(msg)
    print(f"[ORDER] {signal} | Lot:{lot} | Entry:{entry:.3f} | SL:{sl_price:.3f} | TP:{tp_price:.3f} | Retcode:{retcode} | Reason: {reason}")

if __name__ == "__main__":
    run()
