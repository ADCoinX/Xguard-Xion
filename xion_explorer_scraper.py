import requests
from bs4 import BeautifulSoup

def get_xion_explorer_assets(address: str):
    url = f"https://explorer.burnt.com/xion/account/{address}"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []

    # Asset rows (liquid, delegasi, ibc, dsb)
    for row in soup.select(".AssetRow"):
        symbol = row.select_one(".AssetSymbol")
        amount = row.select_one(".AssetAmount")
        if symbol and amount:
            out.append({
                "symbol": symbol.text.strip(),
                "amount": amount.text.strip()
            })
    return out

if __name__ == "__main__":
    addr = "xion1cmnhhvesgtu5s00c9l3nphw7285266vpwqxdw5qjz78jvfl4vps65u3h7"
    assets = get_xion_explorer_assets(addr)
    print(assets)
