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
            self.conn = rpyc.connect(self.host, self.port)
            return True
        except Exception as e:
            print(f"Error connecting to MT5 via RPyC: {e}")
            return False

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        if not self.conn: return None
        raw = self.conn.root.account_info()
        if raw is None: return None
        # RPyC netref dict — copy field by field
        keys = ["login","trade_mode","leverage","limit_orders","margin_so_mode",
                "trade_allowed","trade_expert","margin_mode","currency_digits",
                "fifo_close","balance","credit","profit","equity","margin",
                "margin_free","margin_level","margin_so_call","margin_so_so",
                "margin_initial","margin_maintenance","assets","liabilities",
                "commission_blocked","name","server","currency","company"]
        result = {}
        for k in keys:
            try: result[k] = raw[k]
            except: pass
        return result

    def get_terminal_info(self) -> Optional[Dict[str, Any]]:
        if not self.conn: return None
        return self.conn.root.terminal_info()

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.conn: return []
        raw = self.conn.root.positions_get()
        return [dict(p) for p in raw] if raw else []

    def get_orders(self) -> List[Dict[str, Any]]:
        if not self.conn: return []
        return self.conn.root.orders_get()

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.conn: return None
        raw = self.conn.root.symbol_tick(symbol)
        return dict(raw) if raw else None

    def get_rates(self, symbol: str, timeframe: int, count: int) -> Optional[List[Dict[str, Any]]]:
        if not self.conn: return None
        return self.conn.root.copy_rates_from_pos(symbol, timeframe, 0, count)

    def get_bulk_rates(self, symbol: str, timeframe: int, count: int) -> Optional[List[List[float]]]:
        """Fetch OHLC cepat via JSON bulk — tanpa netref overhead."""
        if not self.conn: return None
        j = self.conn.root.bulk_rates_json(symbol, timeframe, count)
        return json.loads(j)

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.conn: return None
        j = self.conn.root.symbol_info(symbol)
        return json.loads(j)

    def order_send(self, request: Dict) -> Dict:
        """Kirim order ke MT5. Return dict result."""
        if not self.conn: return {"retcode": -1, "comment": "Not connected", "order": 0}
        j = self.conn.root.order_send(json.dumps(request))
        return json.loads(j)
