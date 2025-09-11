# ... semua import dan fungsi risk_score, ctx_base seperti asal ...

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

    # PATCH: Mainnet/testnet handling (endpoint baru burnt.com mainnet)
    os.environ["XION_API_ENDPOINTS"] = "https://api.xion-mainnet-1.burnt.com"

    info = await get_wallet_info(wallet_addr)

    # PATCH: fallback to explorer scrape if no real data
    uxion_val = float(info.get("uxion", 0.0))
    tx_count_val = int(info.get("tx_count", 0))
    fallback_assets = None

    # Fallback only if REST node returns empty
    if uxion_val == 0.0 and tx_count_val == 0:
        try:
            fallback_assets = get_xion_explorer_assets(wallet_addr)
            print("Fallback explorer assets:", fallback_assets)
            # PATCH: Jumlahkan semua XION, tapi paparkan semua asset
            if fallback_assets:
                uxion_balances = [
                    float(a["amount"].replace(",", ""))
                    for a in fallback_assets
                    if "XION" in a["symbol"] and a["amount"].replace(",", "").replace(".", "").isdigit()
                ]
                # Update balance ikut explorer, tapi tetap paparkan semua asset
                uxion_val = sum(uxion_balances) if uxion_balances else uxion_val
        except Exception as e:
            print("Fallback error:", e)
            fallback_assets = None

    ctx.update({
        "result": "OK" if info.get("status") in ("ok", "partial") else info.get("status"),
        "status": info.get("status"),
        "debug_reason": info.get("debug_reason") or info.get("reason") or "-",
        "endpoint": info.get("endpoint"),
        "wallet": {
            "address": info.get("address"),
            "balance": f'{uxion_val} XION',
            "tx_count": info.get("tx_count", 0),
            "failed_txs": info.get("failed_txs", 0),
            "anomaly": info.get("anomaly", False),
            "balances": info.get("balances", []),
            "fallback_assets": fallback_assets,  # <-- Papar semua asset explorer burnt.com
        },
    })
    ctx["score"] = risk_score(info)
    return TEMPLATES.TemplateResponse("index.html", ctx)

# ... validate_api pun sama logic fallback_assets ...
