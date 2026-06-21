import sys
sys.path.append("/root/mt5both2s")
from modules.mt5_service import MT5Service
from modules.indicator_engine import calculate_indicators
from modules.decision_engine import calculate_decision

svc = MT5Service()
svc.connect()
inds = calculate_indicators(svc, "USDJPY#")
print("Indicators:", inds)
if inds:
    print("Decision:", calculate_decision({"symbol": "USDJPY#", **inds}))
