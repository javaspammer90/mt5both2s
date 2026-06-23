import pandas as pd
from modules.mt5_service import MT5Service
mt5 = MT5Service()
mt5.connect()
r = mt5.get_bulk_rates("USDCAD#", 5, 100)
print(r[0] if r else "No data")
