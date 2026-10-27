"""Virtual keys and the operator admin credential.

Virtual keys are stored as SHA-256 hashes. The plaintext is returned once, at
creation or rotation. Local fixture keys are not cloud credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from aigw.models import Team, VirtualKey


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def key_prefix(value: str) -> str:
    return value[:12]


def new_virtual_key() -> str:
    return "local-vk-" + secrets.token_urlsafe(32)


def safe_equals(got: str, expected: str) -> bool:
    got_b = got.encode()
    expected_b = expected.encode()
    if len(got_b) != len(expected_b):
        return False
    return hmac.compare_digest(got_b, expected_b)


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def team_for_key(session: Session, plaintext: str) -> Team | None:
    row = session.scalar(
        select(VirtualKey).where(
            VirtualKey.key_hash == hash_key(plaintext),
            VirtualKey.revoked_at.is_(None),
        )
    )
    if row is None:
        return None
    return session.get(Team, row.team_id)
