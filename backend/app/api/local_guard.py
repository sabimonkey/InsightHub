"""Restrict sensitive settings mutations to local frontend origins."""

from __future__ import annotations

from fastapi import HTTPException, Request

ALLOWED_ORIGINS = frozenset({"http://127.0.0.1:5174", "http://localhost:5174"})
ALLOWED_CLIENT_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def require_local_settings_mutation(request: Request) -> None:
    host = (request.client.host if request.client else "").lower()
    if host not in ALLOWED_CLIENT_HOSTS:
        raise HTTPException(status_code=403, detail={"code": "LOCAL_ONLY", "message": "仅允许本机访问该设置操作。"})
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail={"code": "ORIGIN_NOT_ALLOWED", "message": "请求来源不被允许。"})
