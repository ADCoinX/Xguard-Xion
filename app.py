import os
from typing import Optional
import uvicorn

from fastapi import FastAPI, Request, Form, status
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.datastructures import MutableHeaders

from xion_handler import validate_wallet_address, get_wallet_info
from risk_engine import calculate_risk_score
from rwa_handler import get_rwa_assets
from iso_export import generate_iso_pain001
from metrics import log_metrics, fetch_metrics
from utils import rate_limiter

from xion_explorer_scraper import get_xion_explorer_assets  # <-- fallback scraper

app = FastAPI()

# -------------------- Security Headers (updated CSP) --------------------
CDN_JS = "https://cdn.jsdelivr.net"
TORUS = "https://*.toruswallet.io"
GOOGLE_FONTS_CSS = "https://fonts.googleapis.com"
GOOGLE_FONTS_STATIC = "https://fonts.gstatic.com"
IMG_REMOTE = "https://*.githubusercontent.com https://avatars.githubusercontent.com"

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        headers = MutableHeaders(resp.headers)
        headers["X-Frame-Options"] = "DENY"
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' {CDN_JS} 'unsafe-eval'; "
            f"style-src 'self' 'unsafe-inline' {GOOGLE_FONTS_CSS}; "
            f"font-src 'self' {GOOGLE_FONTS_STATIC}; "
            f"img-src 'self' data: {IMG_REMOTE}; "
            "connect-src 'self' "
                "https://api.xion-testnet-2.burnt.com "
                "https://api.xion-mainnet-1.burnt.com "
                "https://xion-rest.publicnode.com "
                f"{TORUS} "
                "https://api.github.com https://github.com; "
            f"frame-src {TORUS}; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none';"
        )
        return resp

app.add_middleware(SecurityHeadersMiddleware)

# -------------------- CORS (include OPTIONS) --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# -------------------- Static & Templates --------------------
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# -------------------- Simple IP rate limit --------------------
@app.middleware("http")
async def ip_rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter(ip):
        return Response("Too many requests. Try again later.", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return await call_next(request)

# -------------------- Health check --------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True, "release": os.getenv("RELEASE", "dev")}

# -------------------- Routes --------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/validate")
async def validate_get():
    return RedirectResponse(url="/", status_code=303)

@app.post("/validate", response_class=HTMLResponse)
async def validate_post(request: Request, wallet_addr: str = Form(...)):
    if not validate_wallet_address(wallet_addr):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "result": "Invalid Xion address format.", "score": None,
             "wallet": None, "metrics": fetch_metrics()}
        )
    w = await get_wallet_info(wallet_addr)
    # --- PATCH: fallback to explorer scrape if no real balance ---
    uxion_val = float(w.get("uxion") or w.get("balance_total") or 0)
    tx_count_val = int(w.get("tx_count") or 0)
    fallback_assets = None
    if (uxion_val == 0.0 and tx_count_val == 0):
        # REST failed, try scrape explorer
        try:
            fallback_assets = get_xion_explorer_assets(wallet_addr)
            # PATCH: Paparkan semua asset explorer burnt.com
            # Jumlahkan XION untuk balance, tapi fallback_assets dihantar penuh ke UI
            if fallback_assets:
                uxion_balances = [
                    float(a["amount"].replace(",", ""))
                    for a in fallback_assets
                    if "XION" in a["symbol"] and a["amount"].replace(",", "").replace(".", "").isdigit()
                ]
                uxion_val = sum(uxion_balances) if uxion_balances else uxion_val
        except Exception as e:
            print("Fallback error:", e)
            fallback_assets = None

    wallet_view = {
        "address": w.get("address"),
        "balance": uxion_val,
        "tx_count": tx_count_val,
        "failed_txs": int(w.get("failed_txs") or 0),
        "anomaly": bool(w.get("anomaly", False)),
        "status": (w.get("status") or "ok"),
        "duration": float(w.get("duration") or 0.0),
        "endpoint": w.get("endpoint"),
        "fallback_assets": fallback_assets,  # <-- PATCH: Papar semua asset explorer burnt.com
    }
    try:
        score = calculate_risk_score({
            "status": wallet_view["status"],
            "uxion": wallet_view["balance"],
            "tx_count": wallet_view["tx_count"],
            "failed_txs": wallet_view["failed_txs"],
            "anomaly": wallet_view["anomaly"],
        })
    except Exception:
        score = 50
    try:
        log_metrics(wallet_addr, wallet_view["duration"], score, wallet_view["status"])
    except Exception:
        pass
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "result": f"Validation complete for {wallet_addr}.",
            "score": score,
            "wallet": wallet_view,
            "metrics": fetch_metrics(),
        },
    )

@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "metrics": fetch_metrics()})

@app.get("/rwa/assets", response_class=HTMLResponse)
async def rwa_assets(request: Request):
    assets = await get_rwa_assets()
    return templates.TemplateResponse("index.html", {"request": request, "rwa": assets})

@app.get("/iso/pain001.xml")
async def iso_export(wallet_addr: Optional[str] = None):
    m = fetch_metrics()
    address = wallet_addr or (m[0]["address"] if m else None)
    if not address:
        return Response("No wallet address to export.", status_code=400)
    xml_content = generate_iso_pain001(address)
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename=\"pain001-{address}.xml\"'},
    )

@app.get("/static/Xguard-logo.png")
async def logo():
    return FileResponse("static/Xguard-logo.png")
