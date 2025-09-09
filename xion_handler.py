import os
import re
import time
import httpx
from typing import List, Dict, Any, Optional

# ... [network, endpoints, helper, sum functions: kekal, tak perlu ubah] ...

async def get_wallet_info(address: str) -> dict:
    """
    Return fields utama (unit = XION float!):
      uxion (TOTAL), spendable_uxion, liquid_uxion, staked_uxion, unbonding_uxion
    """
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
    DENOM = "uxion"  # 6 decimals

    async with httpx.AsyncClient(headers={"User-Agent": "xguard-xion/1.2"}) as client:
        for base in ENDPOINTS:
            try:
                acct = await _fetch_account(client, base, address)
                balances   = await _fetch_balances(client, base, address)   or {}
                spendables = await _fetch_spendable(client, base, address)  or {}
                deleg      = await _fetch_delegations(client, base, address) or {}
                unb        = await _fetch_unbonding(client, base, address)   or {}

                tx_count = await _fetch_tx_count(client, base, address)
                status = "ok" if tx_count is not None else "partial"
                tx_count = tx_count or 0

                # Debug print - audit API response
                print(f"[DEBUG] balances response from {base}: {balances}")

                # pecahan (unit: uxion int)
                liquid_uxion    = _sum_coin_list(balances,   "balances", DENOM)
                spendable_uxion = _sum_coin_list(spendables, "balances", DENOM)
                staked_uxion    = _sum_delegations(deleg)
                unbonding_uxion = _sum_unbonding(unb)
                total_uxion     = liquid_uxion + staked_uxion + unbonding_uxion

                # Convert ke XION float untuk UI
                def to_xion(val): return round(val / 1_000_000, 6)
                liquid_XION    = to_xion(liquid_uxion)
                spendable_XION = to_xion(spendable_uxion)
                staked_XION    = to_xion(staked_uxion)
                unbonding_XION = to_xion(unbonding_uxion)
                total_XION     = to_xion(total_uxion)

                anomaly = (total_XION == 0.0 and tx_count == 0)
                chosen = base

                # Return sentiasa, jangan skip walaupun acct kosong!
                return {
                    "address": address,
                    "status": status,
                    "endpoint": chosen,
                    "duration": round(time.time() - start, 3),

                    # key balances (XION float untuk UI)
                    "uxion": total_XION,              # explorer-style TOTAL, float
                    "spendable_uxion": spendable_XION,
                    "liquid_uxion": liquid_XION,
                    "staked_uxion": staked_XION,
                    "unbonding_uxion": unbonding_XION,

                    "balances": balances.get("balances", []) if isinstance(balances, dict) else [],
                    "tx_count": tx_count,
                    "failed_txs": 0,
                    "anomaly": anomaly,
                }
            except Exception as e:
                last_reason = str(e)
                print(f"[ERROR] {base}: {e}")
                continue

    # Semua endpoint gagal
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
