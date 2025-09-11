import os
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from xion_client import get_wallet_info, validate_wallet_address
from xion_explorer_scraper import get_xion_explorer_assets

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=os.getenv("TEMPLATE_DIR", "templates"))

def risk_score(wallet: Dict[str, Any]) -> int:
    score = 100
    if wallet.get("tx_count", 0) == 0:
        score -= 25
    if float(wallet.get("uxion", 0.0)) == 0.0:
        score -= 25
    if wallet.get("anomaly"):
        score -= 20
    if wallet.get("status") == "partial":
        score -= 10
    return max(1, min(100, score))

def ctx_base(request: Request) -> Dict[str, Any]:
    return {
        "request": request,
        "now": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "result": None,
        "status": None,
        "debug_reason": None,
        "endpoint": None,
        "score": None,
        "wallet": None,
        "metrics": None,
    }

@router.get("/", response_class=HTMLResponse)
async def index_html(request: Request):
    return TEMPLATES.TemplateResponse("index.html", ctx_base(request))

@router.post("/validate", response_class=HTMLResponse)
async def validate_html(request: Request, wallet_addr: str = Form(...)):
    ctx = ctx_base(request)

    if not validate_wallet_address(wallet_addr):
        ctx.update({
            "result": "Invalid address format (xion1…)",
            "status": "invalid_address",
            "wallet": {"address": wallet_addr},
            "score": 1,
        })
        return TEMPLATES.TemplateResponse("index.html", ctx)

    # Force mainnet burnt.com endpoint
    os.environ["XION_API_ENDPOINTS"] = "https://api.xion-mainnet-1.burnt.com"

    info = await get_wallet_info(wallet_addr)

    # fallback: scrape explorer burnt.com if REST fails
    uxion_val = float(info.get("uxion", 0.0))
    tx_count_val = int(info.get("tx_count", 0))
    fallback_assets = None

    # Only fallback if REST node returns totally empty
    if uxion_val == 0.0 and tx_count_val == 0:
        try:
            fallback_assets = get_xion_explorer_assets(wallet_addr)
            print("[DEBUG] Fallback explorer assets:", fallback_assets)
            if fallback_assets:
                # PATCH: Ambil semua XION dari explorer assets (liquid, staked, reward)
                uxion_balances = [
                    float(a["amount"].replace(",", ""))
                    for a in fallback_assets
                    if "XION" in a["symbol"] and a["amount"].replace(",", "").replace(".", "").replace(" ", "").isdigit()
                ]
                if uxion_balances:
                    uxion_val = sum(uxion_balances)
        except Exception as e:
            print("[DEBUG] Fallback error:", e)
            fallback_assets = None

    # If fallback_assets used and ada XION, ubah status untuk UI
    display_status = info.get("status")
    if fallback_assets and uxion_val > 0:
        display_status = "fallback_explorer"

    ctx.update({
        "result": "OK" if display_status in ("ok", "partial", "fallback_explorer") else display_status,
        "status": display_status,
        "debug_reason": info.get("debug_reason") or info.get("reason") or "-",
        "endpoint": info.get("endpoint"),
        "wallet": {
            "address": info.get("address"),
            "balance": f'{uxion_val} XION',
            "tx_count": info.get("tx_count", 0),
            "failed_txs": info.get("failed_txs", 0),
            "anomaly": info.get("anomaly", False),
            "balances": info.get("balances", []),
            "fallback_assets": fallback_assets,  # <-- Papar asset explorer burnt.com
        },
    })
    ctx["score"] = risk_score({"uxion": uxion_val, "tx_count": ctx["wallet"]["tx_count"], "anomaly": ctx["wallet"]["anomaly"], "status": display_status})
    return TEMPLATES.TemplateResponse("index.html", ctx)

@router.post("/api/validate")
async def validate_api(request: Request, wallet_addr: str = Form(None)):
    # Try form, then JSON
    if not wallet_addr:
        try:
            data = await request.json()
            wallet_addr = (data or {}).get("wallet_addr", "")
        except Exception:
            wallet_addr = ""

    if not validate_wallet_address(wallet_addr):
        return JSONResponse(
            {"status": "invalid_address", "reason": "Invalid Xion bech32 format", "address": wallet_addr},
            status_code=400,
        )

    os.environ["XION_API_ENDPOINTS"] = "https://api.xion-mainnet-1.burnt.com"
    info = await get_wallet_info(wallet_addr)
    uxion_val = float(info.get("uxion", 0.0))
    tx_count_val = int(info.get("tx_count", 0))
    fallback_assets = None

    if uxion_val == 0.0 and tx_count_val == 0:
        try:
            fallback_assets = get_xion_explorer_assets(wallet_addr)
            if fallback_assets:
                uxion_balances = [
                    float(a["amount"].replace(",", ""))
                    for a in fallback_assets
                    if "XION" in a["symbol"] and a["amount"].replace(",", "").replace(".", "").replace(" ", "").isdigit()
                ]
                if uxion_balances:
                    uxion_val = sum(uxion_balances)
        except Exception as e:
            print("[DEBUG] Fallback error:", e)
            fallback_assets = None

    display_status = info.get("status")
    if fallback_assets and uxion_val > 0:
        display_status = "fallback_explorer"

    info["risk_score"] = risk_score({"uxion": uxion_val, "tx_count": info.get("tx_count", 0), "anomaly": info.get("anomaly", False), "status": display_status})
    info["fallback_assets"] = fallback_assets
    info["balance"] = uxion_val
    info["status"] = display_status
    if not info.get("debug_reason") and info.get("reason"):
        info["debug_reason"] = info["reason"]
    return JSONResponse(info)
