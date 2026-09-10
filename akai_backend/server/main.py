"""Akai license server — FastAPI application.

Run locally:      uvicorn server.main:app --host 0.0.0.0 --port 8000
Run in prod:      behind HTTPS (clients hash credentials before sending).

Endpoints
---------
POST /api/v1/login   username + sha256(password) + HWID  ->  session token
GET  /api/v1/health  liveness probe
GET  /api/v1/verify  bearer-token validation (used by the client heartbeat)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from . import __version__
from .schemas import HealthResponse, LoginRequest, LoginResponse
from .security import issue_token, load_secret, sha256_hex, verify_token
from .store import (
    ACCOUNT_DISABLED,
    BAD_CREDENTIALS,
    HWID_MISMATCH,
    SUBSCRIPTION_EXPIRED,
    UserStore,
)

BASE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = Path(os.environ.get("AKAI_USERS_FILE", BASE_DIR / "users.json"))

_store = UserStore(USERS_FILE)
_secret = load_secret()

app = FastAPI(title="Akai License Server", version=__version__, docs_url=None,
              redoc_url=None)

_MESSAGES = {
    BAD_CREDENTIALS: "İstifadəçi adı və ya şifrə yanlışdır.",
    HWID_MISMATCH: "Bu abunəlik başqa cihazda aktivdir!",
    SUBSCRIPTION_EXPIRED: "Abunəlik müddəti bitmişdir.",
    ACCOUNT_DISABLED: "Hesab deaktiv edilib. Administrator ilə əlaqə saxlayın.",
}


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="akai-license", version=__version__)


@app.post("/api/v1/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    ok, reason, record = _store.check_login(
        body.username, body.password_hash, sha256_hex(body.hwid)
    )
    if not ok:
        status = 401 if reason == BAD_CREDENTIALS else 403
        raise HTTPException(status_code=status, detail=_MESSAGES.get(reason, reason))
    return LoginResponse(
        ok=True,
        token=issue_token(_secret, str(record["username"])),
        expires_at=record.get("expires_at"),
        message="Xoş gəldiniz!",
    )


@app.get("/api/v1/verify")
def verify(request: Request) -> dict:
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    data = verify_token(_secret, token)
    if data is None:
        raise HTTPException(status_code=401, detail="Sessiya etibarsızdır.")
    return {"ok": True, "username": data.get("u")}
