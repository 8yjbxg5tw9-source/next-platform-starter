"""Request/response schemas for the license API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password_hash: str = Field(min_length=64, max_length=64)  # sha256 hex
    hwid: str = Field(min_length=8, max_length=64)


class LoginResponse(BaseModel):
    ok: bool
    token: Optional[str] = None
    expires_at: Optional[str] = None
    message: str = ""


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
