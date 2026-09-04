"""
api/routes/org.py — Organisation membership: invites and team management.

Routes
------
POST   /org                          — create an organisation for the current
                                        client (dashboard first-run step;
                                        also usable to create an additional org)
POST   /org/invite                   — send a directed, tokenized invite
GET    /org/invites                  — list pending invites (owner/admin)
POST   /org/invites/{invite_id}/resend — invalidate + resend (owner/admin)
DELETE /org/invites/{invite_id}       — cancel a pending invite (owner/admin)
GET    /org/members                  — list team members (owner/admin)
PATCH  /org/members/{member_id}      — change a member's role (owner only)
DELETE /org/members/{member_id}      — remove a member (owner only)
POST   /org/members/{member_id}/transfer-ownership : hand ownership to an
                                        existing admin (owner only)
GET    /org/invite/{token}           — public: validate an invite token
POST   /org/invite/{token}/accept    — public: accept an invite
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import hash_password, hash_token, send_org_invite_email
from api.deps import CurrentOrg, get_current_client, get_current_org, get_db, require_role
from api.limiter import limiter
from api.routes.auth import _issue_tokens
from db.models import Client, Organization, OrganizationMember, OrgInvite

router = APIRouter(tags=["org"])

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

_INVITE_EXPIRE_DAYS = 7
_ROLES = {"owner", "admin", "viewer"}
_INVITABLE_ROLES = {"admin", "viewer"}  # owner is never assigned via invite


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


# ---------------------------------------------------------------------------
# POST /org — create an organisation for the current client and become owner
#
# Registration only creates the login (Client); no org exists yet. The
# dashboard checks GET /auth/me's `orgs` list and, if empty, prompts for a
# company name and calls this endpoint. Also doubles as the mechanism for a
# client to create an additional org later (self-serve "+ New organisation",
# cut to post-MVP for the UI — the endpoint itself costs nothing extra to
# leave general-purpose).
# ---------------------------------------------------------------------------

class CreateOrgBody(BaseModel):
    company_name: str


@router.post("/org", status_code=201)
@limiter.limit("10/hour")
async def create_org(
    request: Request,
    response: Response,
    body: CreateOrgBody,
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    company_name = body.company_name.strip()
    if not company_name:
        raise HTTPException(status_code=422, detail="Company name is required.")

    org = Organization(
        company_name=company_name,
        domain=_email_domain(client.email),
        tier="free",
    )
    db.add(org)
    db.flush()  # populate org.id without committing yet
    db.add(OrganizationMember(client_id=client.id, org_id=org.id, role="owner"))
    db.commit()

    # Select the new org immediately so the client doesn't land on a
    # dashboard with no active organisation right after creating one.
    _issue_tokens(response, db, client, request, org_id=org.id)
    return {"id": org.id, "company_name": org.company_name, "role": "owner"}


def _check_resend_rate(email: str) -> bool:
    """Item 9: resend is rate-limited to once per hour per invited email."""
    key = f"clew:invite_resend:{email.lower()}"
    if _redis.get(key):
        return False
    _redis.setex(key, 3600, "1")
    return True


# ---------------------------------------------------------------------------
# POST /org/invite
# ---------------------------------------------------------------------------

class InviteBody(BaseModel):
    email: str
    role: Literal["admin", "viewer"]


@router.post("/org/invite", status_code=201)
@limiter.limit("20/hour")
async def invite_member(
    request: Request,
    body: InviteBody,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invited_email = body.email.lower()
    role = body.role
    org = current_org.organization

    # Invite permission rules: owner may invite admin or viewer; admin may
    # only invite viewer.
    if current_org.role == "admin" and role != "viewer":
        raise HTTPException(status_code=403, detail="Admins can only invite viewers.")

    # Domain-based role ceiling, enforced server-side regardless of what the
    # UI shows: external email + non-viewer role is rejected outright.
    if org.domain and _email_domain(invited_email) != org.domain and role != "viewer":
        raise HTTPException(
            status_code=400,
            detail="External collaborators can only be invited as Viewer.",
        )

    existing_client = db.query(Client).filter(Client.email == invited_email).first()
    if existing_client:
        already_member = (
            db.query(OrganizationMember)
            .filter(
                OrganizationMember.client_id == existing_client.id,
                OrganizationMember.org_id == org.id,
            )
            .first()
        )
        if already_member:
            raise HTTPException(
                status_code=400, detail="This person is already a member of your organisation."
            )

    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    invite = OrgInvite(
        org_id=org.id,
        invited_email=invited_email,
        role=role,
        token_hash=hash_token(raw_token),
        expires_at=now + timedelta(days=_INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    db.commit()

    accept_url = f"{FRONTEND_URL}/accept-invite?token={raw_token}"
    send_org_invite_email(
        to=invited_email,
        inviter_name=client.email,
        company_name=org.company_name,
        role=role,
        accept_url=accept_url,
        existing_account=existing_client is not None,
    )
    return {"message": "Invite sent."}


# ---------------------------------------------------------------------------
# GET /org/invites — pending invites (not accepted; expired ones still show
# so Team Members can offer Resend rather than silently disappearing)
# ---------------------------------------------------------------------------

@router.get("/org/invites")
async def list_invites(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    invites = (
        db.query(OrgInvite)
        .filter(
            OrgInvite.org_id == current_org.id,
            OrgInvite.accepted_at.is_(None),
        )
        .order_by(OrgInvite.created_at.desc())
        .all()
    )
    now = datetime.now(timezone.utc)
    return [
        {
            "id":            inv.id,
            "invited_email": inv.invited_email,
            "role":          inv.role,
            "expires_at":    inv.expires_at,
            "expired":       inv.expires_at < now,
            "created_at":    inv.created_at,
        }
        for inv in invites
    ]


# ---------------------------------------------------------------------------
# POST /org/invites/{invite_id}/resend
# ---------------------------------------------------------------------------

@router.post("/org/invites/{invite_id}/resend")
async def resend_invite(
    invite_id: str,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(OrgInvite)
        .filter(OrgInvite.id == invite_id, OrgInvite.org_id == current_org.id)
        .first()
    )
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invite not found.")

    if not _check_resend_rate(invite.invited_email):
        raise HTTPException(status_code=429, detail="Resend is limited to once per hour for this address.")

    raw_token = secrets.token_urlsafe(32)
    invite.token_hash = hash_token(raw_token)
    invite.expires_at = datetime.now(timezone.utc) + timedelta(days=_INVITE_EXPIRE_DAYS)
    db.commit()

    accept_url = f"{FRONTEND_URL}/accept-invite?token={raw_token}"
    send_org_invite_email(
        to=invite.invited_email,
        inviter_name=client.email,
        company_name=current_org.organization.company_name,
        role=invite.role,
        accept_url=accept_url,
        existing_account=db.query(Client).filter(Client.email == invite.invited_email).first() is not None,
    )
    return {"message": "Invite resent."}


# ---------------------------------------------------------------------------
# DELETE /org/invites/{invite_id} — cancel a pending invite
# ---------------------------------------------------------------------------

@router.delete("/org/invites/{invite_id}")
async def cancel_invite(
    invite_id: str,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(OrgInvite)
        .filter(OrgInvite.id == invite_id, OrgInvite.org_id == current_org.id)
        .first()
    )
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found.")
    db.delete(invite)
    db.commit()
    return {"message": "Invite cancelled."}


# ---------------------------------------------------------------------------
# GET /org/members — team list
# ---------------------------------------------------------------------------

@router.get("/org/members")
async def list_members(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(OrganizationMember, Client)
        .join(Client, Client.id == OrganizationMember.client_id)
        .filter(OrganizationMember.org_id == current_org.id)
        .order_by(OrganizationMember.created_at.asc())
        .all()
    )
    return [
        {
            "id":         member.id,
            "client_id":  member.client_id,
            "email":      cli.email,
            "role":       member.role,
            "created_at": member.created_at,
        }
        for member, cli in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /org/members/{member_id} — owner only: change a member's role
# ---------------------------------------------------------------------------

class RoleChangeBody(BaseModel):
    role: Literal["admin", "viewer"]


@router.patch("/org/members/{member_id}")
async def change_member_role(
    member_id: str,
    body: RoleChangeBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == member_id, OrganizationMember.org_id == current_org.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="The organisation owner's role cannot be changed.")

    if body.role == "admin":
        cli = db.query(Client).filter(Client.id == member.client_id).first()
        org = current_org.organization
        if not cli or not org.domain or _email_domain(cli.email) != org.domain:
            raise HTTPException(
                status_code=400,
                detail="Promotion to Admin requires an email on your organisation's domain.",
            )

    member.role = body.role
    db.commit()
    return {"message": "Role updated."}


# ---------------------------------------------------------------------------
# DELETE /org/members/{member_id} — owner only: remove a member
# ---------------------------------------------------------------------------

@router.delete("/org/members/{member_id}")
async def remove_member(
    member_id: str,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == member_id, OrganizationMember.org_id == current_org.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="The organisation owner cannot be removed.")

    db.delete(member)
    db.commit()
    return {"message": "Member removed."}


# ---------------------------------------------------------------------------
# POST /org/members/{member_id}/transfer-ownership: owner only, hand the
# owner role to an existing admin, demoting the caller to admin in exchange.
#
# Restricted to admins-only targets: an admin already cleared the same
# domain-ceiling check applied at promotion time (change_member_role above),
# so this doesn't need to re-derive that rule. A viewer must be promoted to
# admin first.
# ---------------------------------------------------------------------------

@router.post("/org/members/{member_id}/transfer-ownership")
async def transfer_ownership(
    member_id: str,
    client: Client = Depends(get_current_client),
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    new_owner = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == member_id, OrganizationMember.org_id == current_org.id)
        .first()
    )
    if new_owner is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    if new_owner.role == "owner":
        raise HTTPException(status_code=400, detail="This member is already the owner.")
    if new_owner.role != "admin":
        raise HTTPException(status_code=400, detail="Only an Admin can be made the owner. Promote this member to Admin first.")

    current_owner = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.client_id == client.id,
            OrganizationMember.org_id == current_org.id,
            OrganizationMember.role == "owner",
        )
        .first()
    )
    if current_owner is None:
        raise HTTPException(status_code=403, detail="You are not the owner of this organisation.")

    new_owner.role = "owner"
    current_owner.role = "admin"
    db.commit()
    return {"message": "Ownership transferred."}


# ---------------------------------------------------------------------------
# GET /org/invite/{token} — public: validate a token for the accept page
# ---------------------------------------------------------------------------

class InviteInfoOut(BaseModel):
    valid: bool
    reason: Optional[str] = None  # "not_found" | "expired" | "used"
    company_name: Optional[str] = None
    role: Optional[str] = None
    invited_email: Optional[str] = None
    account_exists: Optional[bool] = None


@router.get("/org/invite/{token}", response_model=InviteInfoOut)
async def get_invite(token: str, db: Session = Depends(get_db)):
    invite = db.query(OrgInvite).filter(OrgInvite.token_hash == hash_token(token)).first()
    if invite is None:
        return InviteInfoOut(valid=False, reason="not_found")
    if invite.accepted_at is not None:
        return InviteInfoOut(valid=False, reason="used")
    if invite.expires_at < datetime.now(timezone.utc):
        return InviteInfoOut(valid=False, reason="expired")

    org = db.query(Organization).filter(Organization.id == invite.org_id).first()
    account_exists = db.query(Client).filter(Client.email == invite.invited_email).first() is not None
    return InviteInfoOut(
        valid=True,
        company_name=org.company_name if org else None,
        role=invite.role,
        invited_email=invite.invited_email,
        account_exists=account_exists,
    )


# ---------------------------------------------------------------------------
# POST /org/invite/{token}/accept — public: accept an invite
# ---------------------------------------------------------------------------

class AcceptInviteBody(BaseModel):
    password: Optional[str] = None  # required only when no account exists yet


@router.post("/org/invite/{token}/accept")
@limiter.limit("10/hour")
async def accept_invite(
    request: Request,
    response: Response,
    token: str,
    body: AcceptInviteBody,
    db: Session = Depends(get_db),
):
    invite = db.query(OrgInvite).filter(OrgInvite.token_hash == hash_token(token)).first()
    if invite is None or invite.accepted_at is not None:
        raise HTTPException(
            status_code=400, detail="This invitation has already been accepted or does not exist."
        )
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This invitation has expired.")

    client = db.query(Client).filter(Client.email == invite.invited_email).first()
    if client is None:
        if not body.password:
            raise HTTPException(status_code=400, detail="Password is required to set up your account.")
        client = Client(
            email=invite.invited_email,
            password_hash=hash_password(body.password),
            email_verified=True,  # the invite link itself is proof of ownership
        )
        db.add(client)
        db.flush()  # populate client.id without committing yet

    already_member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.client_id == client.id, OrganizationMember.org_id == invite.org_id)
        .first()
    )
    if not already_member:
        db.add(OrganizationMember(client_id=client.id, org_id=invite.org_id, role=invite.role))

    invite.accepted_at = datetime.now(timezone.utc)
    db.commit()

    _issue_tokens(response, db, client, request, org_id=invite.org_id)
    return {"message": "Invitation accepted."}
