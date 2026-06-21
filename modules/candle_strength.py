def calculate_candle_strength(candle: dict) -> float:
    """
    Calculate candle strength based on body-to-range ratio.
    Input candle must be a dict with keys: 'open', 'high', 'low', 'close'.
    Returns a float between 0.0 and 1.0.
    """
    op = float(candle.get('open', 0))
    hi = float(candle.get('high', 0))
    lo = float(candle.get('low', 0))
    cl = float(candle.get('close', 0))
    
    body = abs(cl - op)
    rng = hi - lo
    
    if rng == 0:
        return 0.0
        
    return body / rng

def get_candle_interpretation(strength: float) -> str:
    """
    Interpret strength score.
    """
    if strength < 0.3:
        return "weak candle"
    elif strength <= 0.6:
        return "normal candle"
    elif strength <= 0.8:
        return "strong candle"
    else:
        return "very strong candle"
