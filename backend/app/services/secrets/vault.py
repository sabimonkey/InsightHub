"""Encrypted provider API key vault (ciphertext in PostgreSQL, master key outside DB)."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings, get_settings

MASTER_KEY_ENV = "INSIGHTHUB_CREDENTIALS_MASTER_KEY"
MASTER_KEY_RELATIVE = Path("data/secrets/credentials.master")


class CredentialVaultError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _master_key_path() -> Path:
    path = (PROJECT_ROOT / MASTER_KEY_RELATIVE).resolve()
    root = PROJECT_ROOT.resolve()
    if path != root and root not in path.parents:
        raise CredentialVaultError("MASTER_KEY_PATH_INVALID", "凭据主密钥路径无效。")
    return path


def _load_master_key_bytes() -> bytes | None:
    env = (os.environ.get(MASTER_KEY_ENV) or "").strip()
    if env:
        try:
            return env.encode("utf-8")
        except OSError as exc:
            raise CredentialVaultError("MASTER_KEY_INVALID", "环境变量中的凭据主密钥无效。") from exc
    path = _master_key_path()
    if not path.is_file():
        return None
    raw = path.read_bytes().strip()
    if not raw:
        return None
    return raw


def _ensure_master_key_bytes() -> bytes:
    existing = _load_master_key_bytes()
    if existing:
        return existing
    key = Fernet.generate_key()
    path = _master_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    material = _load_master_key_bytes()
    if not material:
        raise CredentialVaultError("MASTER_KEY_MISSING", "凭据主密钥未配置，无法读取已保存的 API Key。")
    try:
        return Fernet(material)
    except (ValueError, TypeError) as exc:
        raise CredentialVaultError("MASTER_KEY_INVALID", "凭据主密钥无效，无法解密 API Key。") from exc


def _fernet_for_write() -> Fernet:
    return Fernet(_ensure_master_key_bytes())


def encrypt_secret(plaintext: str) -> str:
    token = _fernet_for_write().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        raw = _fernet().decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        raise CredentialVaultError("DECRYPT_FAILED", "无法解密已保存的 API Key，请检查主密钥或重新保存密钥。") from exc
    return raw.decode("utf-8")


def vault_has_entry(session: Session, provider_type: str) -> bool:
    from app.models.analysis import LLMProviderCredential

    row = session.get(LLMProviderCredential, provider_type)
    return row is not None and bool(row.ciphertext)


def read_vault_secret(session: Session, provider_type: str) -> str | None:
    from app.models.analysis import LLMProviderCredential

    row = session.get(LLMProviderCredential, provider_type)
    if row is None or not row.ciphertext:
        return None
    return decrypt_secret(row.ciphertext)


def write_vault_secret(session: Session, provider_type: str, api_key: str) -> None:
    from app.models.analysis import LLMProviderCredential

    cleaned = api_key.strip()
    if not cleaned:
        raise CredentialVaultError("EMPTY_KEY", "API Key 不能为空。")
    now = datetime.now(timezone.utc)
    ciphertext = encrypt_secret(cleaned)
    row = session.get(LLMProviderCredential, provider_type)
    if row is None:
        row = LLMProviderCredential(provider_type=provider_type, ciphertext=ciphertext, updated_at=now)
        session.add(row)
    else:
        row.ciphertext = ciphertext
        row.updated_at = now
    session.commit()


def clear_vault_secret(session: Session, provider_type: str) -> bool:
    from app.models.analysis import LLMProviderCredential

    row = session.get(LLMProviderCredential, provider_type)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
