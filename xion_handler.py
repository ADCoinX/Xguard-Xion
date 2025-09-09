# xion_client.py (fixed)
import os, re, time, asyncio, httpx
from typing import List, Dict, Any, Optional, Tuple

ADDR_RE = re.compile(r"^xion1[0-9a-z]{20,90}$")
def validate_wallet_address(address: str) -> bool:
    return bool(address) and bool(ADDR_RE.match(address))

# =========================
# Network & Endpoints
# =========================
XION_NETWORK = os.getenv("XION_NETWORK", "mainnet").strip().lower()

TESTNET_ENDPOINTS = [
    "https://api.xion-testnet-1.burnt.dev",
]

MAINNET_ENDPOINTS = [
    "https://xion-rest.publicnode.com",
    "https://api.mainnet.xion.burnt.com",
    "https://xion-mainnet-rest.chainlayer.network",
    "https://xion-mainnet-api.bigdipper.live",
    "https://xion-mainnet-api.customnode.com",
]

DEFAULT_ENDPOINTS = MAINNET_ENDPOINTS if XION_NETWORK == "mainnet" else TESTNET_ENDPOINTS

# ✅ Safe env override (optional). If empty → fallback to DEFAULT_ENDPOINTS.
_env_list = (os.getenv("XION_API_ENDPOINTS") or "").strip()
ENDPOINTS: List[str] = [e.strip() for e in _env_list.split(",") if e.strip()] or DEFAULT_ENDPOINTS

# =========================
# Circuit breaker (simple TTL)
# =========================
_CB: Dict[str, float] = {}
def _cb_blocked(base: str) -> bool: return _CB.get(base, 0) > time.time()
def _cb_trip(base: str, seconds: int = 180): _CB[base] = time.time() + seconds

# =========================
# HTTP helpers
# =========================
async def _get_json(client: httpx.AsyncClient, url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url, timeout=timeout, follow_redirects=True)
        if r.status_code == 200 and r.content:
            return r.json()
        return None  # non-200 dianggap gagal
    except Exception:
        return None

def _balance_paths(address: str) -> List[str]:
    return [
        f"/cosmos/bank/v1beta1/balances/{address}?pagination.limit=1000",
        f"/bank/balances/{address}",  # legacy/alt
    ]

def _spendable_paths(address: str) -> List[str]:
    return [
        f"/cosmos/bank/v1beta1/spendable_balances/{address}?pagination.limit=1000",
        f"/bank/spendable_balances/{address}",
    ]

def _account_paths(address: str) -> List[str]:
    return [
        f"/cosmos/auth/v1beta1/accounts/{address}",
        f"/auth/accounts/{address}",  # legacy
    ]

async def _fetch_first_ok(client: httpx.AsyncClient, base: str, rel_paths: List[str]) -> Optional[Dict[str, Any]]:
    for p in rel_paths:
        data = await _get_json(client, base.rstrip("/") + p)
        if data is not None:
            return data
    return None

def _parse_balances_shape(obj: Optional[Dict[str, Any]]) -> Optional[list]:
    """
    Terima dua bentuk:
    {"balances":[...]}  ATAU  {"balances":{"balances":[...]}}
    """
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("balances"), list):
        return obj["balances"]
    if isinstance(obj.get("balances"), dict):
        inner = obj["balances"].get("balances")
        if isinstance(inner, list):
            return inner
    return None

# =========================
# Sum helpers
# =========================
def _sum_coin_list(container: Dict[str, Any], key: str, denom: str) -> int:
    total = 0
    for c in (container.get(key) or []):
        if c.get("denom") == denom:
            try: total += int(c.get("amount", "0"))
            except Exception: pass
    return total

def _sum_delegations(deleg: Dict[str, Any]) -> int:
    total = 0
    for d in (deleg.get("delegation_responses") or []):
        try: total += int((d.get("balance") or {}).get("amount", "0"))
        except Exception: pass
    return total

def _sum_unbonding(unb: Dict[str, Any]) -> int:
    total = 0
    for e in (unb.get("unbonding_responses") or []):
        for entry in (e.get("entries") or []):
            try: total += int(entry.get("balance", "0"))
            except Exception: pass
    return total

def get_all_balances(balances_json: Dict[str, Any]):
    out = []
    for coin in (balances_json.get("balances") or []):
        denom = coin.get("denom")
        amount = str(coin.get("amount", "0"))
        if denom == "uxion":
            out.append({"denom": denom, "symbol": "XION", "amount": round(int(amount)/1_000_000, 6)})
        else:
            out.append({"denom": denom, "symbol": denom, "amount": int(amount) if amount.isdigit() else 0})
    return out

# =========================
# TX count (sender/recipient)
# =========================
async def _fetch_tx_count(client: httpx.AsyncClient, base: str, address: str) -> Optional[int]:
    qs = [
        f"/cosmos/tx/v1beta1/txs?events=message.sender%3D'{address}'&pagination.limit=1&pagination.count_total=true",
        f"/cosmos/tx/v1beta1/txs?events=transfer.recipient%3D'{address}'&pagination.limit=1&pagination.count_total=true",
    ]
    total, saw = 0, False
    for q in qs:
        data = await _get_json(client, base.rstrip("/") + q)
        if data is None: 
            continue
        saw = True
        try: total += int(data.get("pagination", {}).get("total", "0"))
        except Exception: pass
    return total if saw else None

# =========================
# Probe satu endpoint
# =========================
async def _probe_endpoint(client: httpx.AsyncClient, base: str, address: str) -> Tuple[str, Optional[Dict[str, Any]], str]:
    if _cb_blocked(base):
        return base, None, "circuit_open"
    try:
        # Liveness: akaun
        acct = await _fetch_first_ok(client, base, _account_paths(address))

        # Baki
        balances = await _fetch_first_ok(client, base, _balance_paths(address))
        blist = _parse_balances_shape(balances)

        # ✅ Jika balances tiada tetapi 'acct' wujud → akaun hidup, baki 0 (anggap success)
        if blist is None:
            if isinstance(acct, dict) and acct.get("account"):
                blist = []
            else:
                _cb_trip(base)
                return base, None, f"{base} returned empty balances"

        spendables = await _fetch_first_ok(client, base, _spendable_paths(address)) or {}
        deleg      = await _get_json(client, base.rstrip("/") + f"/cosmos/staking/v1beta1/delegations/{address}") or {}
        unb        = await _get_json(client, base.rstrip("/") + f"/cosmos/staking/v1beta1/delegations/{address}/unbonding_delegations") or {}

        tx_count = await _fetch_tx_count(client, base, address)
        status = "ok" if tx_count is not None else "partial"
        tx_count = tx_count or 0

        DENOM = "uxion"
        liquid    = _sum_coin_list({"balances": blist}, "balances", DENOM)
        spendable = _sum_coin_list(spendables or {}, "balances", DENOM)
        staked    = _sum_delegations(deleg or {})
        unbonding = _sum_unbonding(unb or {})
        total     = liquid + staked + unbonding
        to_x = lambda v: round(v/1_000_000, 6)

        result = {
            "status": status,
            "endpoint": base,
            "uxion": to_x(total),
            "spendable_uxion": to_x(spendable),
            "liquid_uxion": to_x(liquid),
            "staked_uxion": to_x(staked),
            "unbonding_uxion": to_x(unbonding),
            "balances": get_all_balances({"balances": blist}),
            "tx_count": tx_count,
            "failed_txs": 0,
        }
        return base, result, "ok"
    except Exception as e:
        _cb_trip(base)
        return base, None, f"{base} error: {e}"

# =========================
# Public API
# =========================
async def get_wallet_info(address: str) -> dict:
    if not validate_wallet_address(address):
        return {
            "address": address, "status": "invalid_address",
            "reason": "Invalid Xion bech32 format", "endpoint": None,
            "duration": 0.0, "uxion": 0.0, "spendable_uxion": 0.0,
            "liquid_uxion": 0.0, "staked_uxion": 0.0, "unbonding_uxion": 0.0,
            "balances": [], "tx_count": 0, "failed_txs": 0, "anomaly": True,
        }

    t0 = time.time(); reasons: List[str] = []
    async with httpx.AsyncClient(headers={"User-Agent": "xguard-xion/1.3"}, timeout=5.5) as client:
        tasks = [asyncio.create_task(_probe_endpoint(client, base, address))
                 for base in ENDPOINTS if not _cb_blocked(base)]

        for fut in asyncio.as_completed(tasks):
            base, result, reason = await fut
            if result is not None:
                result.update({
                    "address": address,
                    "duration": round(time.time() - t0, 3),
                    "anomaly": (result["uxion"] == 0.0 and result["tx_count"] == 0),
                })
                return result
            reasons.append(reason)

    last_reason = reasons[-1] if reasons else "unknown"
    return {
        "address": address, "status": "unreachable",
        "reason": f"All endpoints failed. Last: {last_reason}",
        "endpoint": None, "duration": round(time.time() - t0, 3),
        "uxion": 0.0, "spendable_uxion": 0.0, "liquid_uxion": 0.0,
        "staked_uxion": 0.0, "unbonding_uxion": 0.0,
        "balances": [], "tx_count": 0, "failed_txs": 0, "anomaly": True,
    }
