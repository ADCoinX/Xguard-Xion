import httpx

COSMWASM_CONTRACTS = [
    "https://rwa-cosmwasm1.com/query",
    "https://rwa-cosmwasm2.com/query",
]

async def get_rwa_assets():
    assets = []
    for endpoint in COSMWASM_CONTRACTS:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(endpoint)
                if resp.status_code == 200:
                    data = resp.json()
                    assets.extend(data.get("assets", []))
        except Exception:
            continue
    # Deduplicate by asset id
    seen = set()
    unique_assets = []
    for asset in assets:
        if asset.get("id") not in seen:
            unique_assets.append(asset)
            seen.add(asset.get("id"))
    return unique_assets