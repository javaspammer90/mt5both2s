import rpyc
conn = rpyc.classic.connect("localhost", 18812)
mt5 = conn.modules.MetaTrader5
print("Init:", mt5.initialize())
acc = mt5.account_info()
if acc:
    print("Login:", acc.login, acc.name, acc.server)
else:
    print("Not logged in. Error:", mt5.last_error())
