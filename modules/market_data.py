from typing import Optional, Dict, Any
from .mt5_service import MT5Service

def get_market_snapshot(mt5_service: MT5Service, symbol: str) -> Optional[Dict[str, Any]]:
    tick = mt5_service.get_tick(symbol)
    if not tick:
        return None
        
    return {
        "symbol": symbol,
        "bid": tick["bid"],
        "ask": tick["ask"],
        "spread": tick["ask"] - tick["bid"],
        "time": tick["time"]
    }
