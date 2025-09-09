import os
import uvicorn
from typing import Optional

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

app = FastAPI()

# -------------------- Security Headers (updated CSP) --------------------
CDN_JS = "https://cdn.jsdelivr.net"
WEB3AUTH = "https://*.web3auth.io"
GOOGLE_FONTS_CSS = "https://fonts.googleapis.com"
GOOGLE_FONTS_STATIC = "https://fonts.gstatic.com"

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        headers = MutableHeaders(resp.headers)
        # Allow required externals for your index.html
        headers["X-Frame-Options"] = "DENY"
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # allow external scripts (jsdelivr, web3auth) + eval for web3auth UMD
            f"script-src 'self' {CDN_JS} {WEB3AUTH} 'unsafe-eval'; "
            # inline styles used in toasts + google fonts css
            f"style-src 'self' 'unsafe-inline' {GOOGLE_FONTS_CSS}; "
            # fonts domain
            f"font-src 'self' {GOOGLE_FONTS_STATIC}; "
            # images local + data: fallback
            "img-src 'self' data:; "
            # connect to your API / RPCs if needed
            "connect-src 'self' https:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none';"
        )
        return resp

app.add_middleware(SecurityHeadersMiddleware)

# -------------------- CORS (include OPTIONS) --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # set domain production bila live
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

# -------------------- Routes --------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ✅ Prevent 405: redirect any GET /validate back to home
@app.get("/validate")
async def validate_get():
    return RedirectResponse(url="/", status_code=303)

@app.post("/validate", response_class=HTMLResponse)
async def validate(request: Request, wallet_addr: str = Form(...)):
    # 1) Validate format
    if not validate_wallet_address(wallet_addr):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "result": "Invalid Xion address format.", "score": None,
             "wallet": None, "metrics": fetch_metrics()}
        )

    # 2) Fetch on-chain info (async)
    wallet_data = await get_wallet_info(wallet_addr)

    # Normalize to avoid None crashes
    wallet_data["balance"] = wallet_data.get("balance", wallet_data.get("balance_total", 0)) or 0
    wallet_data["tx_count"] = wallet_data.get("tx_count", 0) or 0
    wallet_data["failed_txs"] = wallet_data.get("failed_txs", 0) or 0
    wallet_data["anomaly"] = bool(wallet_data.get("anomaly", False))
    wallet_data["duration"] = wallet_data.get("duration", 0.0)
    wallet_data["status"] = wallet_data.get("status", "ok")

    # 3) Risk score with guard
    try:
        score = calculate_risk_score(wallet_data)
    except Exception:
        score = 50  # safe default

    # 4) Log metrics
    try:
        log_metrics(wallet_addr, wallet_data["duration"], score, wallet_data["status"])
    except Exception:
        pass

    # 5) Render
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "result": f"Validation complete for {wallet_addr}.",
            "score": score,
            "wallet": wallet_data,
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
    # Use provided address or the last validated one
    m = fetch_metrics()
    address = wallet_addr or (m[0]["address"] if m else None)
    if not address:
        return Response("No wallet address to export.", status_code=400)
    xml_content = generate_iso_pain001(address)
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="pain001-{address}.xml"'},
    )

# Optional: static logo passthrough
@app.get("/static/Xguard-logo.png")
async def logo():
    return FileResponse("static/Xguard-logo.png")

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True
    )
