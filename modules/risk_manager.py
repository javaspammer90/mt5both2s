from typing import Dict, Any

def calculate_risk(balance: float, equity: float, daily_start_equity: float, risk_percent: float = 1.0, sl_points: int = 500, tick_value: float = 1.0) -> Dict[str, Any]:
    if balance <= 0 or sl_points <= 0:
        return {"recommended_lot": 0.01, "can_trade": False, "reason": "Invalid balance or SL"}
        
    # --- PROP FIRM DAILY PROFIT TARGET CHECK ---
    # Target Take Profit per hari: 10% dari equity awal hari
    daily_profit_target_pct = 0.10
    target_daily_profit = daily_start_equity * daily_profit_target_pct
    current_daily_profit = equity - daily_start_equity
    
    if current_daily_profit >= target_daily_profit:
        return {
            "recommended_lot": 0.0, 
            "can_trade": False, 
            "reason": f"DAILY PROFIT TARGET REACHED! Profit: +${current_daily_profit:.2f} >= Target: +${target_daily_profit:.2f}. Trading dihentikan."
        }
    # -------------------------------------------
        
    # --- PROP FIRM DAILY DRAWDOWN CHECK ---
    # Batas drawdown per hari: 2% dari equity awal hari
    daily_dd_limit = 0.02
    max_daily_loss = daily_start_equity * daily_dd_limit
    current_daily_loss = daily_start_equity - equity
    
    # Sisa jatah loss hari ini
    remaining_daily_loss = max_daily_loss - current_daily_loss
    
    if remaining_daily_loss <= 0:
        return {
            "recommended_lot": 0.0, 
            "can_trade": False, 
            "reason": f"DAILY DRAWDOWN LIMIT REACHED! Loss: -${current_daily_loss:.2f} > Max: -${max_daily_loss:.2f}"
        }
    # --------------------------------------

    # Kalkulasi Lot berdasarkan resiko (Risk % dari Balance)
    risk_amount = balance * (risk_percent / 100.0)
    
    # PASTIKAN risk amount untuk order ini tidak melebihi sisa jatah loss harian
    if risk_amount > remaining_daily_loss:
        risk_amount = remaining_daily_loss # Potong risk agar pas dengan sisa DD
        
    # lot = risk_amount / (sl_points * tick_value)
    lot = risk_amount / sl_points 
    
    # Conservative bounds
    lot = max(0.01, round(lot, 2))
    
    return {
        "recommended_lot": lot,
        "can_trade": True,
        "max_daily_loss_allowed": max_daily_loss,
        "remaining_daily_loss": remaining_daily_loss,
        "target_daily_profit": target_daily_profit,
        "current_daily_profit": current_daily_profit,
        "risk_allocated_for_this_trade": risk_amount
    }
