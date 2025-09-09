import time

# Very simple in-memory rate limit per IP
RATE_LIMIT = {}
WINDOW = 60  # seconds
MAX_REQ = 15

def rate_limiter(ip: str):
    now = time.time()
    if ip not in RATE_LIMIT:
        RATE_LIMIT[ip] = []
    # Remove old timestamps
    RATE_LIMIT[ip] = [t for t in RATE_LIMIT[ip] if now - t < WINDOW]
    if len(RATE_LIMIT[ip]) >= MAX_REQ:
        return False
    RATE_LIMIT[ip].append(now)
    return True

def rotate_endpoints(endpoints: list):
    return endpoints[:]  # Could randomize/shuffle for true rotation