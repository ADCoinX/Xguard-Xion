import os
import re
import time
import httpx
from typing import List, Dict, Any, Optional

ADDR_RE = re.compile(r"^xion1[0-9a-z]{20,90}$")

def validate_wallet_address(address: str) -> bool:
    return bool(address) and bool(ADDR_RE.match(address))

# Network & Endpoints
XION_NETWORK = os.getenv("XION_NETWORK", "mainnet").strip().lower()

TESTNET_ENDPOINTS = [
    "https://api.xion-testnet-1.burnt.dev",
]

MAINNET_ENDPOINTS = [
    "https://xion-rest.publicnode.com",
    "https://api.mainnet.xion.burnt.com",
]

DEFAULT_ENDPOINTS = MAINNET_ENDPOINTS if XION_NETWORK == "mainnet" else TESTNET_ENDPOINTS

_env_list = os.getenv("XION_API_ENDPOINTS")
if _env_list:
    ENDPOINTS = [e.strip() for e in _env_list.split(",") if e.strip()]
else:
    ENDPOINTS = DEFAULT_ENDPOINTS

# Helper functions
async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 6.5) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return {}
        return None
    except Exception:
        return None

async def _fetch_account(client, base, address):
    return await _get_json(client, f"{base}/cosmos/auth/v1beta1/accounts/{address}")

async def _fetch_balances(client, base, address):
    return await _get_json(client, f"{base}/cosmos/bank/v1beta1/balances/{address}")

async def _fetch_spendable(client, base, address):
    return await _get_json(client, f"{base}/cosmos/bank/v1beta1/spendable_balances/{address}")

async def _fetch_tx_count(client, base, address):
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

async def _fetch_delegations(client, base, address):
    return await _get_json(client, f"{base}/cosmos/staking/v1beta1/delegations/{address}")

async def _fetch_unbonding(client, base, address):
    return await _get_json(client, f"{base}/cosmos/staking/v1beta1/delegations/{address}/unbonding_delegations")

def _sum_coin_list(container: Dict[str, Any], key: str, denom: str) -> int:
    total = 0
    for c in (container.get(key) or []):
        if c.get("denom") == denom:
            try:
                total += int(c.get("amount", "0"))
            except Exception:
                pass
    return total

def _sum_delegations(deleg: Dict[str, Any]) -> int:
    total = 0
    for d in (deleg.get("delegation_responses") or []):
        bal = d.get("balance", {})
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

def get_all_balances(balances_json):
    result = []
    for coin in balances_json.get("balances", []):
        denom = coin.get("denom")
        amount = coin.get("amount")
        if denom == "uxion":
            symbol = "XION"
            amount_disp = round(int(amount) / 1_000_000, 6)
        elif denom.startswith("ibc/"):
            symbol = denom
            amount_disp = int(amount)
        else:
            symbol = denom
            amount_disp = int(amount)
        result.append({
            "denom": denom,
            "symbol": symbol,
            "amount": amount_disp
        })
    return result

# Main wallet info
async def get_wallet_info(address: str) -> dict:
    if not validate_wallet_address(address):
        return {
            "address": address,
            "status": "invalid_address",
            "reason": "Invalid Xion bech32 format",
            "endpoint": None,
            "duration": 0.0,
            "uxion": 0.0,
            "spendable_uxion": 0.0,
            "liquid_uxion": 0.0,
            "staked_uxion": 0.0,
            "unbonding_uxion": 0.0,
            "balances": [],
            "tx_count": 0,
            "failed_txs": 0,
            "anomaly": True,
        }

    start = time.time()
    last_reason = None
    chosen = None
    DENOM = "uxion"

    async with httpx.AsyncClient(headers={"User-Agent": "xguard-xion/1.2"}) as client:
        for base in ENDPOINTS:
            try:
                acct = await _fetch_account(client, base, address)
                balances   = await _fetch_balances(client, base, address)   or {}
                spendables = await _fetch_spendable(client, base, address)  or {}
                deleg      = await _fetch_delegations(client, base, address) or {}
                unb        = await _fetch_unbonding(client, base, address)   or {}

                print(f"[DEBUG] balances response from {base}: {balances}")

                # Kalau balances kosong atau tiada "balances", cuba endpoint lain!
                if not balances or not balances.get("balances"):
                    last_reason = f"{base} returned empty balances"
                    continue

                tx_count = await _fetch_tx_count(client, base, address)
                status = "ok" if tx_count is not None else "partial"
                tx_count = tx_count or 0

                liquid_uxion    = _sum_coin_list(balances,   "balances", DENOM)
                spendable_uxion = _sum_coin_list(spendables, "balances", DENOM)
                staked_uxion    = _sum_delegations(deleg)
                unbonding_uxion = _sum_unbonding(unb)
                total_uxion     = liquid_uxion + staked_uxion + unbonding_uxion

                def to_xion(val): return round(val / 1_000_000, 6)
                liquid_XION    = to_xion(liquid_uxion)
                spendable_XION = to_xion(spendable_uxion)
                staked_XION    = to_xion(staked_uxion)
                unbonding_XION = to_xion(unbonding_uxion)
                total_XION     = to_xion(total_uxion)

                anomaly = (total_XION == 0.0 and tx_count == 0)
                chosen = base

                balances_list = get_all_balances(balances)

                print(f"[DEBUG] Returning balances from {base}: {balances_list}")

                return {
                    "address": address,
                    "status": status,
                    "endpoint": chosen,
                    "duration": round(time.time() - start, 3),
                    "uxion": total_XION,
                    "spendable_uxion": spendable_XION,
                    "liquid_uxion": liquid_XION,
                    "staked_uxion": staked_XION,
                    "unbonding_uxion": unbonding_XION,
                    "balances": balances_list,
                    "tx_count": tx_count,
                    "failed_txs": 0,
                    "anomaly": anomaly,
                }
            except Exception as e:
                last_reason = str(e)
                print(f"[ERROR] {base}: {e}")
                continue

    print(f"[ERROR] Semua endpoint gagal. Last reason: {last_reason}, endpoint: {chosen}")
    return {
        "address": address,
        "status": "unreachable",
        "reason": last_reason or "All endpoints failed",
        "endpoint": chosen,
        "duration": round(time.time() - start, 3),
        "uxion": 0.0,
        "spendable_uxion": 0.0,
        "liquid_uxion": 0.0,
        "staked_uxion": 0.0,
        "unbonding_uxion": 0.0,
        "balances": [],
        "tx_count": 0,
        "failed_txs": 0,
        "anomaly": True,
    }
