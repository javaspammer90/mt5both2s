from typing import Dict, Any
from datetime import datetime, timezone
from .session_filter import is_in_trading_session
from .candle_strength import get_candle_interpretation

def calculate_decision(market_data: Dict[str, Any], similarity_score: float = 0.0) -> Dict[str, Any]:
    """
    Scoring Engine V3 (Scalping-Oriented)
    - 70% Indicator Score + 30% Similarity Score
    - ATR current < ATR SMA20 hard filter
    - London & NY Session active hours filter (07:00 - 22:00 UTC)
    """
    symbol = market_data.get('symbol', '')
    current_close = market_data.get('current_close', 0.0)
    ema50 = market_data.get('ema50', 0.0)
    ema200 = market_data.get('ema200', 0.0)
    macd_main = market_data.get('macd_main', 0.0)
    macd_sig = market_data.get('macd_sig', 0.0)
    macd_hist_up_3 = market_data.get('macd_hist_up_3', False)
    macd_hist_down_3 = market_data.get('macd_hist_down_3', False)
    adx = market_data.get('adx', 0.0)
    plus_di = market_data.get('plus_di', 0.0)
    minus_di = market_data.get('minus_di', 0.0)
    atr = market_data.get('atr', 0.0)
    atr_mean_20 = market_data.get('atr_mean_20', 0.0)
    fractal_breakout = market_data.get('fractal_breakout', 'NONE')
    candle_strength = market_data.get('candle_strength', 0.0)
    is_bullish = market_data.get('is_bullish', True)
    spread = market_data.get('spread', 0)
    
    # 1. Hard Filter: Session Check (07:00 - 22:00 UTC)
    # Gunakan waktu server UTC atau fallback datetime.now(timezone.utc)
    utc_now = datetime.now(timezone.utc)
    if not is_in_trading_session(utc_now):
        return {
            "action": "WAIT",
            "dominant_action": "NONE",
            "buy_score": 0.0,
            "sell_score": 0.0,
            "confidence": 0.0,
            "reason": "OUTSIDE_TRADING_SESSION"
        }
        
    # 2. Hard Filter: Low Volatility Check
    if atr < atr_mean_20:
        return {
            "action": "WAIT",
            "dominant_action": "NONE",
            "buy_score": 0.0,
            "sell_score": 0.0,
            "confidence": 0.0,
            "reason": "LOW_VOLATILITY_FILTER"
        }
        
    # SCORING ENGINE V3
    buy_score = 0
    sell_score = 0
    
    # --- 1. Trend Score (Max 25) ---
    # EMA50 > EMA200 (15 pts)
    trend_ema = 15 if ema50 > ema200 else 0
    buy_score += trend_ema
    sell_score += (15 - trend_ema)
    
    # Price > EMA50 (10 pts)
    price_ema = 10 if current_close > ema50 else 0
    buy_score += price_ema
    sell_score += (10 - price_ema)
    
    # --- 2. Momentum Score (Max 35) ---
    # MACD Main > Signal (20 pts)
    macd_cross = 20 if macd_main > macd_sig else 0
    buy_score += macd_cross
    sell_score += (20 - macd_cross)
    
    # Histogram 3 consecutive direction (15 pts)
    if macd_hist_up_3:
        buy_score += 15
    elif macd_hist_down_3:
        sell_score += 15
        
    # --- 3. ADX Score (Max 25) ---
    # ADX > 25 (15 pts)
    adx_strength = 15 if adx > 25 else 0
    buy_score += adx_strength
    sell_score += adx_strength
    
    # DI Dominance (10 pts)
    di_dom = 10 if plus_di > minus_di else 0
    buy_score += di_dom
    sell_score += (10 - di_dom)
    
    # --- 4. Candle Strength Score (Max 15) ---
    if candle_strength > 0.7:
        if is_bullish:
            buy_score += 15
        else:
            sell_score += 15
            
    # --- 5. Fractal Score (Max 5) ---
    if fractal_breakout == "UP":
        buy_score += 5
    elif fractal_breakout == "DOWN":
        sell_score += 5
        
    # Final Scoring Calculation
    # Scaled with V2 Weight logic: Final = Indicator(70%) + Similarity(30%)
    final_buy = (buy_score * 0.7) + (similarity_score * 0.3)
    final_sell = (sell_score * 0.7) + (similarity_score * 0.3)
    
    # Confidence calculation: dominant_score / (buy_score + sell_score) [0.0 - 1.0]
    total_score = final_buy + final_sell
    if total_score > 0:
        if final_buy >= final_sell:
            confidence = final_buy / total_score
            dominant_action = "BUY"
        else:
            confidence = final_sell / total_score
            dominant_action = "SELL"
    else:
        confidence = 0.0
        dominant_action = "WAIT"
        
    # Rule Entry Execution Logic V3
    action = "WAIT"
    reason = "No signal threshold reached."
    
    # Spread filter check
    if spread > 30:
        action = "WAIT"
        reason = f"Filter: Spread too high ({spread} points)"
    # Confidence Threshold checks (confidence < 0.60 = NO TRADE)
    elif confidence < 0.60:
        action = "WAIT"
        reason = f"Filter: Low Confidence ({confidence:.2f})"
    else:
        # Check rule entry score thresholds
        if dominant_action == "BUY" and final_buy >= 70:
            if final_buy > final_sell + 15:
                action = "BUY"
                reason = "Rule Entry BUY terpenuhi"
        elif dominant_action == "SELL" and final_sell >= 70:
            if final_sell > final_buy + 15:
                action = "SELL"
                reason = "Rule Entry SELL terpenuhi"
                
    # Compile Detailed Decision Logging Reasons
    detailed_reasons = []
    if final_buy > final_sell:
        if ema50 > ema200 and current_close > ema50:
            detailed_reasons.append("Strong Trend")
        if macd_main > macd_sig and macd_hist_up_3:
            detailed_reasons.append("Strong Momentum")
        if adx > 25:
            detailed_reasons.append("High ADX")
        if candle_strength > 0.7 and is_bullish:
            detailed_reasons.append("Strong Candle")
    else:
        if ema50 < ema200 and current_close < ema50:
            detailed_reasons.append("Strong Trend")
        if macd_main < macd_sig and macd_hist_down_3:
            detailed_reasons.append("Strong Momentum")
        if adx > 25:
            detailed_reasons.append("High ADX")
        if candle_strength > 0.7 and not is_bullish:
            detailed_reasons.append("Strong Candle")
            
    final_reason = reason if action == "WAIT" else ", ".join(detailed_reasons)
    
    return {
        "action": action,
        "dominant_action": dominant_action,
        "buy_score": round(final_buy, 1),
        "sell_score": round(final_sell, 1),
        "confidence": round(confidence, 2),
        "adx": round(adx, 2),
        "atr": atr,
        "atr_mean_20": atr_mean_20,
        "candle_strength": round(candle_strength, 2),
        "spread": spread,
        "reason": final_reason
    }
