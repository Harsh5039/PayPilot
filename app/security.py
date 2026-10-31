"""Private browser ownership for the sandbox (not a Paytm account login)."""
import hashlib
import secrets

from fastapi import HTTPException, Request, Response

from app import db

COOKIE = "paypilot_owner"


def owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def establish_owner(request: Request, response: Response) -> str:
    token = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 30)
    return owner_hash(token)


async def authorize(request: Request) -> None:
    """Resolve ownership for every private resource before invoking its handler."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "cross_origin_write_denied")
    sid = request.path_params.get("session_id")
    for param, table in (("app_id", "applications"), ("policy_id", "policies")):
        if param in request.path_params:
            row = db.one(f"SELECT session_id FROM {table} WHERE id = ?", (request.path_params[param],))
            if not row:
                raise HTTPException(404, "resource_not_found")
            sid = row["session_id"]
    if request.url.path == "/api/chat":
        body = await request.json()
        sid = body.get("session_id") if isinstance(body, dict) else None
    if not sid:
        return
    row = db.one("SELECT owner_hash FROM sessions WHERE id = ?", (sid,))
    token = request.cookies.get(COOKIE, "")
    if not row or not token or not row["owner_hash"] or not secrets.compare_digest(row["owner_hash"], owner_hash(token)):
        raise HTTPException(404, "session_not_found")
