"""Shared FastAPI dependencies: auth token, DB session."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from leadbeast.config import get_settings
from leadbeast.db.session import SessionLocal


def db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().api_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token")


# Alias so route signatures stay tidy.
SessionDep = Depends(db_session)
AuthDep = Depends(require_token)
