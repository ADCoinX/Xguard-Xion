import requests
from bs4 import BeautifulSoup

def get_xion_explorer_assets(address: str):
    # URL baru untuk mainnet explorer burnt.com (2025)
    url = f"https://explorer.burnt.com/xion-mainnet-1/account/{address}"
    r = requests.get(url, timeout=8)
    if r.status_code != 200 or not r.text:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = []

    # Cuba selector paling tepat untuk "AssetRow" di burnt.com 2025
    # Cuba cari table atau div yang ada asset
    asset_rows = soup.select(".AssetRow")
    if not asset_rows:
        # Cuba selector table rows (kadang2 burnt.com pakai table)
        asset_rows = soup.select("table tr")

    for row in asset_rows:
        # Cuba cari symbol (kadang2 burnt.com letak di cell ke-2)
        symbol = None
        amount = None
        # Cuba pelbagai kemungkinan class
        symbol_tag = row.select_one(".AssetSymbol") or row.select_one(".symbol") or row.select_one("td:nth-child(2)")
        amount_tag = row.select_one(".AssetAmount") or row.select_one(".amount") or row.select_one("td:nth-child(3)")
        if symbol_tag and amount_tag:
            symbol = symbol_tag.text.strip()
            amount = amount_tag.text.strip()
        else:
            # Cuba cell2 table kalau tiada class
            cells = row.find_all("td")
            if len(cells) >= 3:
                symbol = cells[1].text.strip()
                amount = cells[2].text.strip()
        if symbol and amount and symbol != "Symbol":
            out.append({
                "symbol": symbol,
                "amount": amount
            })
    return out

if __name__ == "__main__":
    addr = "xion1cmnhhvesgtu5s00c9l3nphw7285266vpwqxdw5qjz78jvfl4vps65u3h7"
    assets = get_xion_explorer_assets(addr)
    print(assets)
