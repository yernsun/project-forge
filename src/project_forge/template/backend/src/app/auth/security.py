from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

# Explicit Argon2id policy. Tune it against the production hardware before raising costs.
PASSWORD_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("project-forge-dummy-password")


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    valid: bool
    needs_rehash: bool


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_token(token), expected_hash)


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> PasswordVerification:
    """Verify real and missing users with the same Argon2 code path."""

    candidate_hash = password_hash or DUMMY_PASSWORD_HASH
    try:
        PASSWORD_HASHER.verify(candidate_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return PasswordVerification(valid=False, needs_rehash=False)
    if password_hash is None:
        return PasswordVerification(valid=False, needs_rehash=False)
    return PasswordVerification(
        valid=True,
        needs_rehash=PASSWORD_HASHER.check_needs_rehash(password_hash),
    )


def hmac_subject(secret: str, scope: str, subject: str) -> str:
    """Pseudonymize rate-limit subjects before persistence."""

    payload = f"{scope}\0{subject}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
