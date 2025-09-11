import requests
from bs4 import BeautifulSoup
import re

def get_xion_explorer_assets(address: str):
    # URL explorer mainnet burnt.com (2025)
    url = f"https://explorer.burnt.com/xion/account/{address}"
    r = requests.get(url, timeout=8)
    if r.status_code != 200 or not r.text:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out = []

    # Cari semua div yang ada asset, pattern: "amount symbol"
    for div in soup.find_all("div"):
        txt = div.get_text(strip=True)
        # Cari pattern: nombor (boleh ada koma/desimal) + space + symbol
        m = re.match(r"^([\d\.,]+)\s+([A-Za-z0-9\/]+)$", txt)
        if m:
            amt, sym = m.group(1), m.group(2)
            # Ignore 0 atau kosong
            if amt.replace(",", "").replace(".", "") != "0":
                out.append({"symbol": sym, "amount": amt})
    return out

if __name__ == "__main__":
    addr = "xion1cmnhhvgesqtu5s00c9l3nphw7285266vpwqxdw5qjz78jvfl4vps65u3h7"
    assets = get_xion_explorer_assets(addr)
    print(assets)
