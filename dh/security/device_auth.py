from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.api.dependencies import v1_session
from dh.config import settings
from dh.db.models import DeviceCredential, PairingCode

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    id: int | None
    name: str


def hash_device_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _hash_pairing_code(code: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        code.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )


async def require_device(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(v1_session)],
) -> DeviceIdentity:
    if not settings.api_v1_auth_required:
        return DeviceIdentity(id=None, name="development")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="device bearer token required",
        )
    digest = hash_device_token(credentials.credentials)
    row = (
        await session.execute(
            select(DeviceCredential).where(
                DeviceCredential.token_hash == digest,
                DeviceCredential.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked device token",
        )
    row.last_seen_at = dt.datetime.now(dt.UTC)
    return DeviceIdentity(id=row.id, name=row.device_name)


async def create_pairing_code(
    session: AsyncSession, *, ttl_minutes: int = 10
) -> tuple[str, PairingCode]:
    code = secrets.token_urlsafe(18)
    salt = secrets.token_bytes(16)
    row = PairingCode(
        code_hash=_hash_pairing_code(code, salt),
        salt=salt,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=ttl_minutes),
    )
    session.add(row)
    await session.flush()
    return code, row


async def complete_pairing(
    session: AsyncSession, *, code: str, device_name: str
) -> tuple[DeviceCredential, str]:
    now = dt.datetime.now(dt.UTC)
    rows = (
        (
            await session.execute(
                select(PairingCode)
                .where(
                    PairingCode.consumed_at.is_(None),
                    PairingCode.expires_at > now,
                )
                .order_by(PairingCode.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    match: PairingCode | None = None
    for row in rows:
        candidate = _hash_pairing_code(code, row.salt)
        if hmac.compare_digest(candidate, row.code_hash):
            match = row
            break
    if match is None:
        raise ValueError("pairing code is invalid or expired")

    token = secrets.token_urlsafe(32)
    device = DeviceCredential(
        device_name=device_name.strip()[:128],
        token_hash=hash_device_token(token),
        last_seen_at=now,
    )
    session.add(device)
    match.consumed_at = now
    await session.flush()
    return device, token
