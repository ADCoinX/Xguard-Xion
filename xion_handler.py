import os
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from xion_client import get_wallet_info, validate_wallet_address

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=os.getenv("TEMPLATE_DIR", "templates"))

# ----- simple risk score (stub, transparen) -----------------
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

# ----- helpers ------------------------------------------------
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

# ----- pages --------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index_html(request: Request):
    return TEMPLATES.TemplateResponse("index.html", ctx_base(request))

# HTML form submit
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

    # PATCH: Use correct testnet endpoint if in testnet
    # You may want to check ENV or wallet_addr prefix for mainnet/testnet
    # For this patch, we force testnet to match new docs:
    os.environ["XION_API_ENDPOINTS"] = "https://api.xion-testnet-2.burnt.com"

    info = await get_wallet_info(wallet_addr)

    ctx.update({
        "result": "OK" if info.get("status") in ("ok", "partial") else info.get("status"),
        "status": info.get("status"),
        "debug_reason": info.get("debug_reason") or info.get("reason") or "-",
        "endpoint": info.get("endpoint"),
        "wallet": {
            "address": info.get("address"),
            "balance": f'{info.get("uxion", 0.0)} XION',
            "tx_count": info.get("tx_count", 0),
            "failed_txs": info.get("failed_txs", 0),
            "anomaly": info.get("anomaly", False),
            "balances": info.get("balances", []),
        },
    })
    ctx["score"] = risk_score(info)
    return TEMPLATES.TemplateResponse("index.html", ctx)

# JSON API (supports form OR raw JSON body)
@router.post("/api/validate")
async def validate_api(request: Request, wallet_addr: str = Form(None)):
    # Try form first; if empty, try JSON body
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

    # PATCH: Use correct testnet endpoint if in testnet
    os.environ["XION_API_ENDPOINTS"] = "https://api.xion-testnet-2.burnt.com"

    info = await get_wallet_info(wallet_addr)
    info["risk_score"] = risk_score(info)
    # Ensure debug fields always present (better DX)
    if not info.get("debug_reason") and info.get("reason"):
        info["debug_reason"] = info["reason"]
    return JSONResponse(info)
