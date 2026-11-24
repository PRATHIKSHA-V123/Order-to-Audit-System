from services.stock import all_balances

for r in all_balances():
    qty = r["bal"]
    if r["unit"] == "g":
        text = f"{qty / 1000} kg"
    elif r["unit"] == "ml":
        text = f"{qty / 1000} L"
    else:
        text = f"{qty} pieces"
    print(f"{r['name']:25} {text}")