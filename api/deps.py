from dataclasses import dataclass
from typing import Generator
from fastapi import Depends, HTTPException, Cookie, status
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models import Client, Organization, OrganizationMember
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
    if client is None or client.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client not found")

    return client


@dataclass
class CurrentOrg:
    """The organisation an authenticated request is scoped to, plus the
    caller's role within it. Routes should filter all org-scoped queries by
    `org.id`, never by `client.id`.
    """
    organization: Organization
    role: str  # 'owner' | 'admin' | 'viewer'

    @property
    def id(self) -> str:
        return self.organization.id


def get_current_org(
    access_token: str | None = Cookie(default=None),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
) -> CurrentOrg:
    """
    Resolve the organisation the current request is scoped to.

    The JWT's `org_id` claim is a convenience, not a trust boundary: it is
    always re-checked against a live `OrganizationMember` row so a stale or
    tampered claim can never grant access to an org the client was removed
    from. Falls back to the client's sole membership if the JWT predates
    the org_id claim or omits it (e.g. an old access token still in a
    browser at deploy time) and the client belongs to exactly one org.
    """
    payload = decode_access_token(access_token) if access_token else None
    org_id = payload.get("org_id") if payload else None

    query = db.query(OrganizationMember).filter(OrganizationMember.client_id == client.id)

    if org_id:
        membership = query.filter(OrganizationMember.org_id == org_id).first()
    else:
        memberships = query.all()
        membership = memberships[0] if len(memberships) == 1 else None

    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active organisation")

    org = db.query(Organization).filter(Organization.id == membership.org_id).first()
    if org is None or org.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organisation not found")

    return CurrentOrg(organization=org, role=membership.role)


def require_role(*allowed_roles: str):
    """Dependency factory: raise 403 unless the current org role is one of
    `allowed_roles`. Use as `Depends(require_role("owner"))` etc.
    """
    def _check(current_org: CurrentOrg = Depends(get_current_org)) -> CurrentOrg:
        if current_org.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_org
    return _check
