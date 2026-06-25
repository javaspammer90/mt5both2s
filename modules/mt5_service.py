import rpyc
import json
from typing import Optional, List, Dict, Any

class MT5Service:
    def __init__(self, host: str = "127.0.0.1", port: int = 18812):
        self.host = host
        self.port = port
        self.conn = None

    def connect(self) -> bool:
        try:
            self.conn = rpyc.classic.connect(self.host, self.port)
            self.conn.execute("""
import MetaTrader5 as mt5
import json

mt5.initialize()

def get_rates_json(symbol, timeframe, count):
    res = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if res is None: return '[]'
    return json.dumps([list(x) for x in res])
""")
            return True
        except Exception as e:
            print(f"Error connecting to MT5 via RPyC: {e}")
            return False

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        pass

    def get_bulk_rates(self, symbol: str, timeframe: int, count: int) -> Optional[List[List[float]]]:
        if not self.conn: return None
        try:
            # Panggil fungsi yang sudah di-injeksi di server RPyC
            j = self.conn.namespace['get_rates_json'](symbol, timeframe, count)
            return json.loads(j)
        except Exception as e:
            print("Error bulk rates:", e)
            return []

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.conn: return None
        try:
            mt5 = self.conn.modules.MetaTrader5
            info = mt5.symbol_info(symbol)
            return info._asdict() if info else None
        except Exception as e:
            return None
