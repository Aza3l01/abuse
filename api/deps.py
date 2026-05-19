from typing import Generator
from fastapi import Depends, HTTPException, Cookie, status
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import Client
from api.auth_utils import decode_access_token


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session, always closing it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_client(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Client:
    """
    Read the access_token cookie, validate the JWT, and return the Client row.
    Raises 401 if missing, invalid, or the client no longer exists.
    """
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    client_id: str = payload.get("sub")
    if not client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client not found")

    return client
