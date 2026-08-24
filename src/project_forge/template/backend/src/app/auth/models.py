from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr

from app.domain.base import StrictDomainModel


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class UserIdentity(StrictDomainModel):
    """User identity without password material."""

    user_id: UUID = Field(description="Stable user ID")
    email: EmailStr = Field(description="Canonical login email")
    status: UserStatus = Field(description="Account lifecycle status")
    version: int = Field(ge=1, description="Optimistic-lock version")
    created_at: datetime = Field(description="UTC creation time")
    updated_at: datetime = Field(description="UTC last-update time")


class PasswordCredential(StrictDomainModel):
    """Persistence-facing credential data, kept separate from identity DTOs."""

    user_id: UUID = Field(description="Owning user ID")
    password_hash: str = Field(min_length=1, description="Argon2id password hash", repr=False)
    password_updated_at: datetime = Field(description="UTC password update time")


class UserWithCredential(StrictDomainModel):
    identity: UserIdentity = Field(description="Safe user identity")
    credential: PasswordCredential = Field(description="Private password credential", repr=False)


class SessionPrincipal(StrictDomainModel):
    session_id: UUID = Field(description="Database session ID")
    user_id: UUID = Field(description="Authenticated user ID")
    email: EmailStr = Field(description="Authenticated email")
    csrf_hash: str = Field(description="Hash of the double-submit token", repr=False)
    expires_at: datetime = Field(description="Session expiry")


class Workspace(StrictDomainModel):
    workspace_id: UUID = Field(description="Workspace ID")
    name: str = Field(min_length=1, max_length=120, description="Workspace name")
    created_at: datetime = Field(description="UTC creation time")


class IssuedSession(StrictDomainModel):
    principal: SessionPrincipal = Field(description="Authenticated principal")
    session_token: SecretStr = Field(
        min_length=32, description="Opaque token returned only at issuance", repr=False
    )
    csrf_token: SecretStr = Field(
        min_length=32, description="CSRF token returned only at issuance", repr=False
    )
