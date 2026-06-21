import sys
import pandas as pd
import numpy as np
sys.path.append("/root/mt5both2s")
from modules.mt5_service import MT5Service

svc = MT5Service()
svc.connect()
rates_netref = svc.get_rates("BTCUSD#", 16408, 30000)
rates = [{'time': r['time'], 'close': r['close'], 'high': r['high'], 'low': r['low']} for r in rates_netref]
df = pd.DataFrame(rates)

df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
delta = df['close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
df['rsi'] = 100 - (100 / (1 + gain/loss))

cond = (df['ema20'] < df['ema50']) & (df['rsi'] >= 58) & (df['rsi'] <= 64)
matches = df.index[cond].tolist()

win_buy = sum(1 for i in matches if i+24 < len(df) and df.loc[i+24, 'close'] > df.loc[i, 'close'])
win_sell = sum(1 for i in matches if i+24 < len(df) and df.loc[i+24, 'close'] < df.loc[i, 'close'])
valid = win_buy + win_sell

print(f"Total candle ditarik: {len(df)}")
print(f"Kejadian Historis dengan kondisi ini: {valid}")
print(f"Probabilitas NAIK (BUY): {win_buy/valid*100:.1f}%")
print(f"Probabilitas TURUN (SELL): {win_sell/valid*100:.1f}%")