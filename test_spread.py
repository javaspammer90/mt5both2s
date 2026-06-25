import sys
sys.path.append("/root")
import rpyc
import json

conn = rpyc.connect("localhost", 18812)
mt5 = conn.root
info_raw = mt5.symbol_info("XAUUSD#")
info = json.loads(info_raw) if isinstance(info_raw, str) else dict(info_raw)
print(f"Spread: {info.get('spread')}")
