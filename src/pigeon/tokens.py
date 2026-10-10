from __future__ import annotations

import hashlib
import hmac


def hash_token(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def token_hash_matches(secret: str, pepper: str, expected: str) -> bool:
    return hmac.compare_digest(hash_token(secret, pepper), expected)
