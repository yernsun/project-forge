from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.domain.base import StrictDomainModel


class User(StrictDomainModel):
    user_id: UUID = Field(description="Stable user ID")
    email: str = Field(min_length=3, max_length=320, description="Normalized login email")
    password_hash: str = Field(min_length=1, description="Argon2 password hash")
    created_at: datetime = Field(description="UTC creation time")


class SessionPrincipal(StrictDomainModel):
    session_id: UUID = Field(description="Database session ID")
    user_id: UUID = Field(description="Authenticated user ID")
    email: str = Field(description="Authenticated email")
    csrf_hash: str = Field(description="Hash of the double-submit token")
    expires_at: datetime = Field(description="Session expiry")


class Workspace(StrictDomainModel):
    workspace_id: UUID = Field(description="Workspace ID")
    name: str = Field(min_length=1, max_length=120, description="Workspace name")
    created_at: datetime = Field(description="UTC creation time")


class IssuedSession(StrictDomainModel):
    principal: SessionPrincipal = Field(description="Authenticated principal")
    session_token: str = Field(min_length=32, description="Opaque token returned only at issuance")
    csrf_token: str = Field(min_length=32, description="CSRF token returned only at issuance")
