import rpyc
conn = rpyc.classic.connect("localhost", 18812)
mt5 = conn.modules.MetaTrader5
mt5.initialize()
print("Symbols:", [s.name for s in mt5.symbols_get() if "USDCAD" in s.name])
