from typing import Dict, Any

def analyze_trend(ema20: float, ema50: float) -> Dict[str, Any]:
    if ema20 > ema50:
        trend = "BULLISH"
        diff = ema20 - ema50
        confidence = min(100, 50 + int((diff / ema50) * 10000))
    elif ema20 < ema50:
        trend = "BEARISH"
        diff = ema50 - ema20
        confidence = min(100, 50 + int((diff / ema50) * 10000))
    else:
        trend = "NEUTRAL"
        confidence = 50
        
    return {
        "trend": trend,
        "confidence": max(0, min(100, confidence))
    }
