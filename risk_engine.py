def calculate_risk_score(wallet_data: dict) -> int:
    # Simple transparent heuristic
    score = 100
    if wallet_data['anomaly']:
        score -= 50
    score -= min(wallet_data['failed_txs'] * 5, 25)
    score -= max(0, 10 - wallet_data['tx_count'])
    if wallet_data['balance'] == 0:
        score -= 30
    score = max(0, min(100, score))
    return score