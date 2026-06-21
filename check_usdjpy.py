import rpyc
conn = rpyc.connect("127.0.0.1", 18812)
mt5 = conn.root
print("USDJPY rates:", mt5.copy_rates_from_pos("USDJPY#", 16408, 0, 50))
