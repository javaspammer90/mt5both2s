import sys
sys.path.append("/root/mt5both2s")
from modules.mt5_service import MT5Service
from modules.decision_engine import calculate_decision
from modules.indicator_engine import calculate_indicators
import time

svc = MT5Service()
svc.connect()

pairs = [
    "BTCUSD#", "BTCAUD#", "BTCBCH#", "BTCCAD#", 
    "BTCCHF#", "BTCETH#", "BTCEUR#", "BTCGBP#", 
    "BTCJPY#", "BTCLTC#", "BTCNZD#"
]

print(f"{'SYMBOL':<10} | {'TREND':<10} | {'CONFIDENCE':<16} | {'BUY SCORE':<10} | {'SELL SCORE':<10}")
print("-" * 75)

for symbol in pairs:
    # Trigger symbol load via tick request (since symbol_select is internal to the server now)
    svc.get_tick(symbol)
    
    inds = calculate_indicators(svc, symbol, 16408, 200)
    
    if inds:
        base_data = {
            "symbol": symbol,
            "ema20": inds['ema20'],
            "ema50": inds['ema50'],
            "rsi": inds['rsi'],
            "atr": inds['atr']
        }
        dec = calculate_decision(base_data)
        
        conf_str = f"{dec['confidence']}% ({dec['strength']})"
        print(f"{symbol:<10} | {dec['action']:<10} | {conf_str:<16} | {dec['buy_score']:<10} | {dec['sell_score']:<10}")
    else:
        print(f"{symbol:<10} | {'NO DATA':<10} | {'-':<16} | {'-':<10} | {'-':<10}")
        
    time.sleep(0.5)

print("-" * 75)
