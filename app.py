import os
from fastapi import FastAPI, Request, Form, Depends, Response, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.background import BackgroundTasks
from starlette.datastructures import MutableHeaders
from typing import Optional
from xion_handler import validate_wallet_address, get_wallet_info
from risk_engine import calculate_risk_score
from rwa_handler import get_rwa_assets
from iso_export import generate_iso_pain001
from metrics import log_metrics, fetch_metrics
from utils import rate_limiter, rotate_endpoints
import uvicorn

app = FastAPI()

# Security Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = MutableHeaders(response.headers)
        headers["X-Frame-Options"] = "DENY"
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self'"
        return response

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Static & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Rate limiting - simple IP based
@app.middleware("http")
async def ip_rate_limit_middleware(request: Request, call_next):
    ip = request.client.host
    allowed = rate_limiter(ip)
    if not allowed:
        return Response(content="Too many requests. Try again later.", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return await call_next(request)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/validate", response_class=HTMLResponse)
async def validate(request: Request, wallet_addr: str = Form(...)):
    # Input validation
    valid = validate_wallet_address(wallet_addr)
    if not valid:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "result": "Invalid Xion address format.",
            "score": None,
            "wallet": None,
            "metrics": fetch_metrics(),
        })
    # Info fetch
    wallet_data = await get_wallet_info(wallet_addr)
    score = calculate_risk_score(wallet_data)
    log_metrics(wallet_addr, wallet_data['duration'], score, wallet_data['status'])
    return templates.TemplateResponse("index.html", {
        "request": request,
        "result": f"Validation complete for {wallet_addr}.",
        "score": score,
        "wallet": wallet_data,
        "metrics": fetch_metrics(),
    })

@app.get("/metrics", response_class=HTMLResponse)
async def metrics(request: Request):
    metrics = fetch_metrics()
    return templates.TemplateResponse("index.html", {"request": request, "metrics": metrics})

@app.get("/rwa/assets", response_class=HTMLResponse)
async def rwa_assets(request: Request):
    assets = await get_rwa_assets()
    return templates.TemplateResponse("index.html", {"request": request, "rwa": assets})

@app.get("/iso/pain001.xml")
async def iso_export(wallet_addr: Optional[str] = None):
    # If no address, export last validated
    metrics = fetch_metrics()
    address = wallet_addr or (metrics[0]['address'] if metrics else None)
    if not address:
        return Response(content="No wallet address to export.", status_code=400)
    xml_content = generate_iso_pain001(address)
    return Response(content=xml_content, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="pain001-{address}.xml"'
    })

# Dummy logo route (for placeholder)
@app.get("/static/Xguard-logo.png")
async def logo():
    return FileResponse("static/Xguard-logo.png")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)