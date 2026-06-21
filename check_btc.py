import sys, rpyc, json
sys.path.append("/root")
c = rpyc.connect("127.0.0.1", 18812)
si = json.loads(c.root.symbol_info("BTCUSD#"))
print("BTCUSD# info:", si)
