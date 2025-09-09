import httpx
from utils import rotate_endpoints
import time

# List of fallback endpoints (RPC/REST)
ENDPOINTS = [
    "https://api.xion.blockchain1.com",
    "https://api.xion.blockchain2.com",
    "https://api.xion.blockchain3.com",
]

def validate_wallet_address(address: str) -> bool:
    return address.startswith("xion1") and len(address) == 42

async def get_wallet_info(address: str) -> dict:
    endpoints = rotate_endpoints(ENDPOINTS)
    for url in endpoints:
        try:
            start = time.time()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/wallet/{address}")
                if resp.status_code == 200:
                    data = resp.json()
                    # Minimal info expected: balance, tx_count, failed_txs
                    anomaly = data.get("failed_txs", 0) > 3 or data.get("balance", 0) == 0
                    return {
                        "address": address,
                        "balance": data.get("balance", 0),
                        "tx_count": data.get("tx_count", 0),
                        "failed_txs": data.get("failed_txs", 0),
                        "anomaly": anomaly,
                        "status": "ok",
                        "duration": round(time.time() - start, 3),
                    }
        except Exception:
            continue
    # Fallback: if all endpoints fail
    return {
        "address": address,
        "balance": 0,
        "tx_count": 0,
        "failed_txs": 0,
        "anomaly": True,
        "status": "unreachable",
        "duration": 0.0,
    }