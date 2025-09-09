import os
import re
import time
import httpx
from typing import List, Dict, Any, Optional

# =========================
# Network & Endpoints
# =========================
XION_NETWORK = os.getenv("XION_NETWORK", "testnet").strip().lower()

TESTNET_ENDPOINTS: List[str] = [
    "https://api.xion-testnet-1.burnt.dev",
]

MAINNET_ENDPOINTS: List[str] = [
    # Tukar ikut doc rasmi bila final
    "https://api.mainnet.xion.burnt.com",
    # Fallback pihak ke-3 (guna kalau dipercayai)
    "https://xion-rest.publicnode.com",
]

DEFAULT_ENDPOINTS = TESTNET_ENDPOINTS if XION_NETWORK != "mainnet" else MAINNET_ENDPOINTS

# Allow override via env (comma-separated)
_env_list = os.getenv("XION_API_ENDPOINTS")
if _env_list:
    ENDPOINTS: List[str] = [e.strip() for e in _env_list.split(",") if e.strip()]
else:
    ENDPOINTS: List[str] = DEFAULT_ENDPOINTS

# =========================
# Address validation
# =========================
ADDR_RE = re.compile(r"^xion1[0-9a-z]{20,90}$")

def validate_wallet_address(address: str) -> bool:
    """Lightweight Bech32 pattern check (cukup untuk UI)."""
    return bool(address) and bool(ADDR_RE.match(address))

# =========================
# REST helpers
# =========================
async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 6.5) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            # treat as empty result (akaun wujud tapi modul tak ada rekod)
            return {}
        return None  # try next endpoint
    except Exception:
        return None

async def _fetch_balances(client: httpx.AsyncClient, base: str, address: str) -> Optional[Dict[str, Any]]:
    return await _get_json(client, f"{base}/cosmos/bank/v1beta1/balances/{address}")

async def _fetch_account(client: httpx.AsyncClient, base: str, address: str) -> Optional[Dict[str, Any]]:
    return await _get_json(client, f"{base}/cosmos/auth/v1beta1/accounts/{address}")

async def _fetch_tx_count(client: httpx.AsyncClient, base: str, address: str) -> Optional[int]:
    # Cosmos tx REST; tak semua node enable count_total, so guard
    q = (
        f"{base}/cosmos/tx/v1beta1/txs"
        f"?events=message.sender%3D'{address}'"
        f"&pagination.limit=1&pagination.count_total=true&order_by=ORDER_BY_DESC"
    )
    data = await _get_json(client, q)
    if data is None:
        return None
    try:
        return int(data.get("pagination", {}).get("total", "0"))
    except Exception:
        return 0

async def _fetch_failed_txs_sample(client: httpx.AsyncClient, base: str, address: str, sample: int = 50) -> Optional[int]:
    # Optional sampling: tarik beberapa tx_responses dan kira yang code != 0
    # Elak heavy pagination (cukup untuk heuristic)
    q = (
        f"{base}/cosmos/tx/v1beta1/txs"
        f"?events=message.sender%3D'{address}'"
        f"&pagination.limit={sample}&order_by=ORDER_BY_DESC"
    )
    data = await _get_json(client, q)
    if data is None:
        return None
    failures = 0
    for txr in data.get("tx_responses", []) or []:
        try:
            code = int(txr.get("code", 0))
            if code != 0:
                failures += 1
        except Exception:
            pass
    return failures

def _sum_amount(balances: Dict[str, Any], denom: Optional[str] = None) -> int:
    total = 0
    for c in (balances.get("balances") or []):
        try:
            if denom is None or c.get("denom") == denom:
                total += int(c.get("amount", "0"))
        except Exception:
            pass
    return total

# =========================
# Public API
# =========================
async def get_wallet_info(address: str) -> dict:
    """
    Tarik live data dari REST Xion:
      - account (untuk detect kewujudan)
      - balances (bank)
      - tx_count (tx)
      - failed_txs (sample; optional)
    Status yang mungkin: invalid_address | ok | partial | empty-account | unreachable
    """
    if not validate_wallet_address(address):
        return {
            "address": address,
            "balance_total": 0,
            "balances": [],
            "tx_count": 0,
            "failed_txs": 0,
            "anomaly": True,
            "status": "invalid_address",
            "reason": "Invalid Xion bech32 format",
            "endpoint": None,
            "duration": 0.0,
        }

    start = time.time()
    last_reason = None
    chosen = None

    # Optional: enable failed-tx sampling via env
    ENABLE_FAIL_SAMPLE = os.getenv("XION_SAMPLE_FAILED_TXS", "0") in ("1", "true", "True")

    async with httpx.AsyncClient(headers={"User-Agent": "xguard-xion/1.0"}) as client:
        for base in ENDPOINTS:
            try:
                # 1) Account info → detect kewujudan (elak treat down as empty)
                acct = await _fetch_account(client, base, address)
                if acct is None:
                    last_reason = f"account query failed @ {base}"
                    continue

                # 2) Balances
                balances = await _fetch_balances(client, base, address)
                if balances is None:
                    last_reason = f"balances query failed @ {base}"
                    continue

                # 3) Tx count
                tx_count = await _fetch_tx_count(client, base, address)
                status = "ok" if tx_count is not None else "partial"
                tx_count = tx_count or 0

                # 4) Failed txs (optional sampling)
                failed_txs = 0
                if ENABLE_FAIL_SAMPLE and tx_count > 0:
                    ft = await _fetch_failed_txs_sample(client, base, address, sample=50)
                    failed_txs = (ft or 0)

                total_amt = _sum_amount(balances)  # semua denom
                uxion_amt = _sum_amount(balances, "uxion")  # denom utama
                anomaly = (uxion_amt == 0 and tx_count == 0)

                chosen = base
                return {
                    "address": address,
                    "balance_total": total_amt,
                    "uxion": uxion_amt,
                    "balances": balances.get("balances", []),
                    "tx_count": tx_count,
                    "failed_txs": failed_txs,
                    "anomaly": anomaly,
                    "status": status if (total_amt or tx_count or acct is not None) else "empty-account",
                    "endpoint": chosen,
                    "duration": round(time.time() - start, 3),
                }
            except Exception as e:
                last_reason = str(e)
                continue

    # Semua endpoint gagal
    return {
        "address": address,
        "balance_total": 0,
        "uxion": 0,
        "balances": [],
        "tx_count": 0,
        "failed_txs": 0,
        "anomaly": True,
        "status": "unreachable",
        "reason": last_reason or "All endpoints failed",
        "endpoint": chosen,
        "duration": round(time.time() - start, 3),
    }
