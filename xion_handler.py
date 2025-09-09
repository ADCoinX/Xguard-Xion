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
    "https://api.mainnet.xion.burnt.com",
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

# ---- bank/auth/tx/staking endpoints
async def _fetch_account(client, base, address):    # exist/sequence
    return await _get_json(client, f"{base}/cosmos/auth/v1beta1/accounts/{address}")

async def _fetch_balances(client, base, address):   # total coins on account (liquid)
    return await _get_json(client, f"{base}/cosmos/bank/v1beta1/balances/{address}")

async def _fetch_spendable(client, base, address):  # spendable subset of balances
    return await _get_json(client, f"{base}/cosmos/bank/v1beta1/spendable_balances/{address}")

async def _fetch_tx_count(client, base, address):   # total tx (count_total might be off on some nodes)
    # Kira tx sebagai sender ATAU recipient untuk lebih tepat
    # NB: beberapa node tak enable count_total → return None (kita tandakan partial)
    qs = [
        f"{base}/cosmos/tx/v1beta1/txs?events=message.sender%3D'{address}'&pagination.limit=1&pagination.count_total=true",
        f"{base}/cosmos/tx/v1beta1/txs?events=transfer.recipient%3D'{address}'&pagination.limit=1&pagination.count_total=true",
    ]
    total = 0
    saw_any = False
    for q in qs:
        data = await _get_json(client, q)
        if data is None:
            continue
        saw_any = True
        try:
            total += int(data.get("pagination", {}).get("total", "0"))
        except Exception:
            pass
    if not saw_any:
        return None
    return total

async def _fetch_delegations(client, base, address):      # staked funds
    return await _get_json(client, f"{base}/cosmos/staking/v1beta1/delegations/{address}")

async def _fetch_unbonding(client, base, address):        # unbonding funds
    return await _get_json(client, f"{base}/cosmos/staking/v1beta1/delegations/{address}/unbonding_delegations")

# =========================
# Sum helpers
# =========================
def _sum_coin_list(container: Dict[str, Any], key: str, denom: str) -> int:
    total = 0
    for c in (container.get(key) or []):
        if c.get("denom") == denom:
            try:
                total += int(c.get("amount", "0"))
            except Exception:
                pass
    return total

def _sum_balances(balances: Dict[str, Any], denom: Optional[str] = None) -> int:
    # jumlah semua denom atau satu denom
    total = 0
    for c in (balances.get("balances") or []):
        try:
            if denom is None or c.get("denom") == denom:
                total += int(c.get("amount", "0"))
        except Exception:
            pass
    return total

def _sum_delegations(deleg: Dict[str, Any]) -> int:
    total = 0
    for d in (deleg.get("delegation_responses") or []):
        bal = d.get("balance", {})  # Cosmos SDK newer field
        try:
            total += int(bal.get("amount", "0"))
        except Exception:
            pass
    return total

def _sum_unbonding(unb: Dict[str, Any]) -> int:
    total = 0
    for e in (unb.get("unbonding_responses") or []):
        for entry in (e.get("entries") or []):
            try:
                total += int(entry.get("balance", "0"))
            except Exception:
                pass
    return total

# =========================
# Public API
# =========================
async def get_wallet_info(address: str) -> dict:
    """
    Live data:
      - account exist
      - balances (liquid)
      - spendable
      - staking delegations (staked)
      - unbonding
      - tx_count (sender+recipient)
    Return fields utama (unit = uxion):
      uxion (TOTAL), spendable_uxion, liquid_uxion, staked_uxion, unbonding_uxion
    Status: invalid_address | ok | partial | empty-account | unreachable
    """
    if not validate_wallet_address(address):
        return {
            "address": address,
            "status": "invalid_address",
            "reason": "Invalid Xion bech32 format",
            "endpoint": None,
            "duration": 0.0,
            "uxion": 0,
            "spendable_uxion": 0,
            "liquid_uxion": 0,
            "staked_uxion": 0,
            "unbonding_uxion": 0,
            "balances": [],
            "tx_count": 0,
            "failed_txs": 0,
            "anomaly": True,
        }

    start = time.time()
    last_reason = None
    chosen = None
    DENOM = "uxion"  # 6 decimals

    async with httpx.AsyncClient(headers={"User-Agent": "xguard-xion/1.2"}) as client:
        for base in ENDPOINTS:
            try:
                acct = await _fetch_account(client, base, address)
                if acct is None:
                    last_reason = f"account query failed @ {base}"
                    continue

                balances   = await _fetch_balances(client, base, address)   or {}
                spendables = await _fetch_spendable(client, base, address)  or {}
                deleg      = await _fetch_delegations(client, base, address) or {}
                unb        = await _fetch_unbonding(client, base, address)   or {}

                tx_count = await _fetch_tx_count(client, base, address)
                status = "ok" if tx_count is not None else "partial"
                tx_count = tx_count or 0

                # pecahan
                liquid_uxion    = _sum_coin_list(balances,   "balances", DENOM)
                spendable_uxion = _sum_coin_list(spendables, "balances", DENOM)
                staked_uxion    = _sum_delegations(deleg)
                unbonding_uxion = _sum_unbonding(unb)
                total_uxion     = spendable_uxion + staked_uxion + unbonding_uxion

                anomaly = (total_uxion == 0 and tx_count == 0)
                chosen = base

                return {
                    "address": address,
                    "status": status if (acct is not None) else "empty-account",
                    "endpoint": chosen,
                    "duration": round(time.time() - start, 3),

                    # key balances (uxion)
                    "uxion": total_uxion,               # TOTAL (≈ explorer’s base for USD calc)
                    "spendable_uxion": spendable_uxion, # boleh belanja
                    "liquid_uxion": liquid_uxion,       # bank liquid (tak semestinya spendable)
                    "staked_uxion": staked_uxion,       # delegated
                    "unbonding_uxion": unbonding_uxion, # dalam proses unbond

                    "balances": balances.get("balances", []),
                    "tx_count": tx_count,
                    "failed_txs": 0,    # boleh tambah sampling kalau perlu
                    "anomaly": anomaly,
                }
            except Exception as e:
                last_reason = str(e)
                continue

    # Semua endpoint gagal
    return {
        "address": address,
        "status": "unreachable",
        "reason": last_reason or "All endpoints failed",
        "endpoint": chosen,
        "duration": round(time.time() - start, 3),
        "uxion": 0,
        "spendable_uxion": 0,
        "liquid_uxion": 0,
        "staked_uxion": 0,
        "unbonding_uxion": 0,
        "balances": [],
        "tx_count": 0,
        "failed_txs": 0,
        "anomaly": True,
    }
