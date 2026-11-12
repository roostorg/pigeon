from __future__ import annotations

from dataclasses import dataclass
import hmac
from typing import Awaitable, Callable, Literal, Optional

from fastapi import Header, HTTPException

from .settings import Settings
from .store import Store
from .tokens import hash_token


@dataclass(frozen=True)
class AuthContext:
    kind: Literal["master", "org"]
    org_id: Optional[str] = None
    token_id: Optional[str] = None


def make_auth(settings: Settings, store: Store) -> Callable[[str], Awaitable[AuthContext]]:
    async def get_auth(authorization: str = Header(default="")) -> AuthContext:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")
        token = token.strip()
        if hmac.compare_digest(token, settings.master_token):
            return AuthContext(kind="master")
        row = store.resolve_api_token(hash_token(token, settings.token_pepper))
        if row is None:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")
        return AuthContext(kind="org", org_id=row["org_id"], token_id=row["id"])

    return get_auth


def require_org(auth: AuthContext) -> str:
    if auth.kind != "org" or not auth.org_id:
        raise HTTPException(status_code=403, detail="master token is for admin APIs only")
    return auth.org_id


def require_master(auth: AuthContext) -> None:
    if auth.kind != "master":
        raise HTTPException(status_code=403, detail="master token required")
