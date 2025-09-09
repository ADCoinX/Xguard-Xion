import os
import re
import time
import httpx
from typing import List, Dict, Any, Optional

# ===== CONFIG =====
# Senarai REST endpoint rasmi/alternatif (boleh tambah)
ENDPOINTS: List[str] = [
    # Testnet Xion (rasmi)
    "https://api.xion-testnet-1.burnt.dev",
]
# Boleh override dengan env (comma-separated)
ENV_ENDPOINTS = os.getenv("XION_API_ENDPOINTS")
if ENV_ENDPOINTS:
    ENDPOINTS = [e.strip() for e in ENV_ENDPOINTS.split(",") if e.strip()]

# Regex Bech32 Xion (tak fix length)
ADDR_RE = re.compile(r"^xion1[0-9a-z]{20,90}$")

def validate_wallet_address(address: str) -> bool:
    """Semak format Bech32 Xion secara ringkas (tanpa decode bech32)."""
    return bool(ADDR_RE.match(address))

async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 6.0) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        # 404 ⇒ address wujud tapi tiada data pada modul itu (treat as empty)
        if r.status_code == 404:
            return {}
        # lain2 error ⇒ naikkan None untuk cuba endpoint lain
        return None
    except Exception:
        return None

async def _fetch_balances(client: httpx.AsyncClient, base: str, address: str) -> Optional[Dict[str, Any]]:
    # Cosmos bank module
    url = f"{base}/cosmos/bank/v1beta1/balances/{address}"
    return await _get_json(client, url)

async def _fetch_tx_count(client: httpx.AsyncClient, base: str, address: str) -> Optional[int]:
    # Cosmos tx module – kira total tx melalui pagination.count_total
    # NOTE: tak semua node enable count_total; kalau None, kita fallback 0
    q = (
        f"{base}/cosmos/tx/v1beta1/txs"
        f"?events=message.sender%3D'{address}'"
        f"&pagination.limit=1&pagination.count_total=true&order_by=ORDER_BY_DESC"
    )
    data = await _get_json(client, q)
    if data is None:
        return None
    # Struktur standard: {"tx_responses":[...], "pagination":{"total":"123", ...}}
    try:
        total = int(data.get("pagination", {}).get("total", "0"))
        return total
    except Exception:
        return 0

def _sum_amount(balances: Dict[str, Any]) -> int:
    total = 0
    for c in (balances.get("balances") or []):
        try:
            total += int(c.get("amount", "0"))
        except Exception:
            pass
    return total

async def get_wallet_info(address: str) -> dict:
    """
    Query live data dari REST Xion (balances + tx_count).
    Tiada hardcode. Kalau semua endpoint gagal → status 'unreachable'.
    """
    if not validate_wallet_address(address):
        return {
            "address": address,
            "balance_total": 0,
            "balances": [],
            "tx_count": 0,
            "failed_txs": None,   # Tak available dari REST standard
            "anomaly": True,
            "status": "invalid_address",
            "reason": "Invalid Xion bech32 format",
            "duration": 0.0,
        }

    start = time.time()

    # Reuse single client; cuba beberapa endpoint
    async with httpx.AsyncClient() as client:
        last_reason = None
        for base in ENDPOINTS:
            try:
                # Balances
                balances = await _fetch_balances(client, base, address)
                if balances is None:
                    last_reason = f"balances query failed at {base}"
                    continue  # cuba endpoint lain

                # Tx count (optional; kalau node tak support count_total → maybe 0)
                tx_count = await _fetch_tx_count(client, base, address)
                if tx_count is None:
                    # Node tak support endpoint/param – treat as 0, tapi status 'partial'
                    tx_count = 0
                    status = "partial"
                else:
                    status = "ok"

                total_amt = _sum_amount(balances)

                # Anomali simple:
                # - tiada baki DAN tiada tx ⇒ mungkin akaun baru / belum aktif
                anomaly = (total_amt == 0 and tx_count == 0)

                return {
                    "address": address,
                    "balance_total": total_amt,
                    "balances": balances.get("balances", []),
                    "tx_count": tx_count,
                    "failed_txs": None,  # Perlu indexer khusus kalau nak yang tepat
                    "anomaly": anomaly,
                    "status": status,
                    "duration": round(time.time() - start, 3),
                }
            except Exception as e:
                last_reason = str(e)
                continue

    # Semua endpoint gagal
    return {
        "address": address,
        "balance_total": 0,
        "balances": [],
        "tx_count": 0,
        "failed_txs": None,
        "anomaly": True,
        "status": "unreachable",
        "reason": last_reason or "All endpoints failed",
        "duration": round(time.time() - start, 3),
    }
