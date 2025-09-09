def _to_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default

def calculate_risk_score(wallet_data: dict) -> int:
    # Normalisasi semua field
    anomaly    = bool(wallet_data.get("anomaly", False))
    failed_txs = _to_int(wallet_data.get("failed_txs", 0), 0)
    tx_count   = _to_int(wallet_data.get("tx_count", 0), 0)
    balance    = _to_int(wallet_data.get("balance", 0), 0)

    # Heuristik ringkas
    score = 100
    if anomaly:
        score -= 50
    score -= min(failed_txs * 5, 25)    # penalti max -25
    score -= max(0, 10 - tx_count)      # penalti kalau tx sikit
    if balance == 0:
        score -= 30

    return max(0, min(100, score))      # clamp 0–100
