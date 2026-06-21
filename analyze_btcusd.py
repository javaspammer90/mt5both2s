import json
from mt5both2s.modules.mt5_service import MT5Service
from mt5both2s.modules.indicator_engine import calculate_indicators
from mt5both2s.modules.decision_engine import calculate_decision

def get_multi_tf_analysis(symbol):
    try:
        mt5 = MT5Service()
        mt5.connect()
    except Exception as e:
        print(f"Error connecting to MT5: {e}")
        return
        
    tfs = {
        "M15": 15,
        "M30": 30,
        "H4": 16388 
    }
    
    results = {}
    
    for tf_name, tf_code in tfs.items():
        print(f"[{tf_name}] Menganalisa...")
        indicators = calculate_indicators(mt5, symbol, tf_code, 200)
        
        if not indicators:
            results[tf_name] = {"error": "Gagal get data candle / candle < 50"}
            continue
            
        indicators["symbol"] = symbol
        decision = calculate_decision(indicators)
        
        results[tf_name] = {
            "indicators": indicators,
            "decision": decision
        }
        
    print("\n=== MULTI-TF ANALYSIS RESULT ===")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    get_multi_tf_analysis("BTCUSD#")
