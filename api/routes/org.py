"""
api/routes/org.py — Organisation membership: invites and team management.

Routes
------
POST   /org                          — create an organisation for the current
                                        client (dashboard first-run step;
                                        also usable to create an additional org)
POST   /org/scanning/pause           : pause log scanning for the org (owner/admin)
POST   /org/scanning/resume          : resume log scanning (owner/admin)
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
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth_utils import ahash_password, hash_token, send_org_invite_email
from api.deps import CurrentOrg, get_current_client, get_current_org, get_db, get_optional_client, require_role
from api.limiter import limiter
from api.referrals import REFERRAL_CODE_MAX_REDEMPTIONS, code_unavailable_reason, generate_referral_code
from api.routes.auth import _issue_tokens
from api.validation import check_password, clean_email, clean_text
from db.models import Client, Organization, OrganizationMember, OrgInvite, PromoCode, PromoCodeRedemption

router = APIRouter(tags=["org"])

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

# Phase 12b: the fixed answers to the optional signup question "how did you
# hear about us". Order here is the order the Metrics table and the register
# select use. "other" is the only one that keeps free text.
SIGNUP_SOURCES = (
    "search_engine",
    "llm",
    "social_forums",
    "product_listings",
    "word_of_mouth",
    "direct_outreach",
    "other",
)
SIGNUP_SOURCE_DETAIL_MAX = 200

_INVITE_EXPIRE_DAYS = 7
_ROLES = {"owner", "admin", "viewer"}
_INVITABLE_ROLES = {"admin", "viewer"}  # owner is never assigned via invite

try:
    import maxminddb as _maxminddb
    _MAXMIND_AVAILABLE = True
except ImportError:
    _MAXMIND_AVAILABLE = False

_GEOIP_CITY_PATH = os.environ.get("GEOIP_MMDB_PATH") or str(
    Path(__file__).resolve().parent.parent.parent / "detection" / "datasets" / "GeoLite2-City.mmdb"
)
_geoip_reader = None


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def _geolocate_country(ip: Optional[str]) -> Optional[str]:
    """Best-effort ISO 3166-1 alpha-2 country for a signup's remote IP.
    Not currently used to default Organization.home_country (left None
    until the client sets it in Settings); kept available for other
    potential uses. Never raises, returns None on any failure (missing IP,
    no maxminddb, no .mmdb file, bad IP).
    """
    if not ip or not _MAXMIND_AVAILABLE:
        return None
    global _geoip_reader
    if _geoip_reader is None:
        if not os.path.exists(_GEOIP_CITY_PATH):
            return None
        try:
            _geoip_reader = _maxminddb.open_database(_GEOIP_CITY_PATH)
        except Exception:
            return None
    try:
        record = _geoip_reader.get(ip)
        if record and "country" in record:
            return record["country"].get("iso_code")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# create_organization: item 63's one place a new Organization + owner
# OrganizationMember row gets created. Used by both POST /auth/register and
# POST /org below so trial dates, tier, and the owner row are always set
# identically. POST /org previously hardcoded tier="starter" with no trial
# columns at all, diverging from registration's real trial setup.
# ---------------------------------------------------------------------------

def create_organization(
    db: Session,
    company_name: str,
    owner_client: Client,
    promo_code: Optional[str] = None,
    remote_ip: Optional[str] = None,
    signup_source: Optional[str] = None,
    signup_source_detail: Optional[str] = None,
) -> Organization:
    """Create an Organization + owner OrganizationMember row. Caller commits.

    Item 53 (section 4): self-serve signup (no code) lands directly on the
    permanent free Starter tier, no trial, no expiry, no card ever.

    TODO.md priority item 5: the `code` field is dual-purpose. An
    admin-generated code (kind="admin") behaves exactly as before: it must
    exist and be unredeemed (item 26/27), grants a 30-day Growth trial
    (the founder's manual-outreach pilot mechanism), and is marked redeemed
    here in the same transaction, with an atomic claim so two simultaneous
    signups cannot both redeem it. A code auto-generated for a regular org
    (kind="referral") has no redemption cap and grants no trial at all, it
    only marks this new org as referred (referred_by_promo_code_id), so its
    first generated bill is free and its referrer earns a credit once it
    pays (Phase 12, api/referrals.py's confirm_first_payment, called from
    billing_payments.py, not here). A referral code whose owner is deleted
    or purged refuses new signups. Every new
    org also gets its own shareable referral code, regardless of whether
    it used one itself, an org can simultaneously be referred and refer
    others.

    remote_ip: currently unused (home_country is left None at creation and
    filled in by the client in Settings), kept as a parameter in case a
    future default is reintroduced.

    signup_source / signup_source_detail (Phase 12b): the optional "how did
    you hear about us" answer. An unknown signup_source is a 422. The
    detail is trimmed, capped at SIGNUP_SOURCE_DETAIL_MAX characters, and
    stored only when the source is "other". Neither affects pricing or access.
    """
    company_name = clean_text(company_name, "Company name")  # Phase 14 (F-004): trimmed, 1 to 255

    source: Optional[str] = None
    source_detail: Optional[str] = None
    if signup_source:
        if signup_source not in SIGNUP_SOURCES:
            raise HTTPException(status_code=422, detail="Unknown signup source.")
        source = signup_source
        if source == "other" and signup_source_detail:
            source_detail = signup_source_detail.strip()[:SIGNUP_SOURCE_DETAIL_MAX] or None

    now = datetime.now(timezone.utc)
    pilot_code = promo_code.strip().upper() if promo_code else None
    promo: Optional[PromoCode] = None
    referred_by_promo_code_id: Optional[str] = None
    if pilot_code:
        promo = db.query(PromoCode).filter(PromoCode.code == pilot_code).first()
        if code_unavailable_reason(promo, db) is not None:
            raise HTTPException(status_code=400, detail="This promo code is no longer available.")
        if promo.kind == "admin":
            tier = "growth"
            trial_source = "manual_outreach"
            trial_ends_at = now + timedelta(days=30)
            billing_provider = "pilot"
        else:
            # Item 53: no trial for referral signups either. Phase 12: the
            # reward is a free first bill and a credit for the referrer,
            # both handled by the billing engine, nothing is granted here.
            tier = "starter"
            trial_source = None
            trial_ends_at = None
            billing_provider = None
            referred_by_promo_code_id = promo.id
    else:
        # Item 53: no trial at all for self-serve, the free Starter tier
        # never expires so there is nothing to count down.
        tier = "starter"
        trial_source = None
        trial_ends_at = None
        billing_provider = None

    org = Organization(
        company_name=company_name,
        domain=_email_domain(owner_client.email),
        tier=tier,
        trial_source=trial_source,
        trial_ends_at=trial_ends_at,
        pilot_code_used=pilot_code,
        referred_by_promo_code_id=referred_by_promo_code_id,
        signup_source=source,
        signup_source_detail=source_detail,
        billing_provider=billing_provider,
        # No default: left None until the client sets it in Settings
        # (a geolocation-based guess previously pre-filled this, which
        # silently marked the onboarding "set your home country" step done
        # before the user ever touched it).
        home_country=None,
        # Phase 2: every org gets its own External ID from the moment it
        # exists, including orgs that never configure S3/AWS at all, so the
        # value is stable and can be shown in Settings immediately, never
        # generated lazily and never chosen by the customer.
        aws_external_id=secrets.token_urlsafe(32),
    )
    db.add(org)
    db.flush()  # populate org.id without committing yet
    if promo is not None:
        if promo.kind == "admin":
            # Atomic claim: the UPDATE only matches while the code is still
            # unredeemed, so of two simultaneous signups only one gets it.
            claimed = (
                db.query(PromoCode)
                .filter(PromoCode.id == promo.id, PromoCode.redeemed_at.is_(None))
                .update({"redeemed_at": now, "redeemed_by_org_id": org.id}, synchronize_session=False)
            )
            if claimed != 1:
                raise HTTPException(status_code=400, detail="This promo code is no longer available.")
        else:
            db.add(PromoCodeRedemption(promo_code_id=promo.id, redeemed_by_org_id=org.id, redeemed_at=now))
    db.add(PromoCode(
        code=generate_referral_code(db),
        kind="referral",
        owner_org_id=org.id,
        max_redemptions=REFERRAL_CODE_MAX_REDEMPTIONS,
    ))
    db.add(OrganizationMember(client_id=owner_client.id, org_id=org.id, role="owner"))
    return org


# ---------------------------------------------------------------------------
# POST /org: create an organisation for the current client and become owner
#
# Registration (POST /auth/register) creates Client + Organization together
# atomically via create_organization() above. This route uses the same
# helper, so it exists to create an *additional* org for an already-logged-in
# client (self-serve "+ New organisation", cut to post-MVP for the UI, the
# endpoint itself costs nothing extra to leave general-purpose) rather than
# as a first-run fallback.
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
    remote_ip = request.client.host if request.client else None
    org = create_organization(db, body.company_name, client, remote_ip=remote_ip)
    db.commit()

    # Select the new org immediately so the client doesn't land on a
    # dashboard with no active organisation right after creating one.
    _issue_tokens(response, db, client, request, org_id=org.id)
    return {"id": org.id, "company_name": org.company_name, "role": "owner"}


# ---------------------------------------------------------------------------
# POST /org/scanning/pause and /org/scanning/resume (Phase 12b)
#
# A customer-controlled pause of log scanning. Owner or admin only. Both are
# idempotent: pausing a paused org or resuming a running one changes nothing
# and returns the current state, so a double click never rewrites who paused
# or when. The scan path (workers/tasks/process_logs.py) skips a paused org
# before touching any scan state, so the pause does not move the cursor, the
# monthly counters, or the plan-limit logic. Resume records scanning_resumed_at
# so the next scan skips what arrived during the pause.
# ---------------------------------------------------------------------------

def _scanning_state(org: Organization) -> dict:
    paused_at = org.scanning_paused_at
    return {"scanning_paused_at": paused_at.isoformat() if paused_at else None}


@router.post("/org/scanning/pause")
async def pause_scanning(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    # Phase 14 (F-013): one UPDATE that only matches while the org is running,
    # so of several simultaneous calls exactly one writes and the rest read its
    # timestamp back. A read-then-write let each caller write its own.
    db.query(Organization).filter(
        Organization.id == org.id, Organization.scanning_paused_at.is_(None)
    ).update(
        {"scanning_paused_at": datetime.now(timezone.utc), "scanning_paused_by": client.id},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(org)
    return _scanning_state(org)


@router.post("/org/scanning/resume")
async def resume_scanning(
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    org = current_org.organization
    db.query(Organization).filter(
        Organization.id == org.id, Organization.scanning_paused_at.isnot(None)
    ).update(
        {
            "scanning_paused_at": None,
            "scanning_paused_by": None,
            "scanning_resumed_at": datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )
    db.commit()
    db.refresh(org)
    return _scanning_state(org)


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
    invited_email = clean_email(body.email)  # Phase 14 (F-012): trimmed, lower-cased, validated, at most 254
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

    # Phase 14 (F-012): one open invite per address. A second one would send a
    # second email and sidestep the once-per-hour resend limit. Resend revives
    # an expired one.
    already_invited = (
        db.query(OrgInvite)
        .filter(
            OrgInvite.org_id == org.id,
            OrgInvite.invited_email == invited_email,
            OrgInvite.accepted_at.is_(None),
        )
        .first()
    )
    if already_invited:
        raise HTTPException(
            status_code=400,
            detail="This address already has an open invite. Use Resend on the Team page, or cancel it first.",
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

    accept_url = f"{DASHBOARD_URL}/accept-invite?token={raw_token}"
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
@limiter.limit("20/hour")
async def resend_invite(
    request: Request,
    invite_id: uuid.UUID,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    client: Client = Depends(get_current_client),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(OrgInvite)
        .filter(OrgInvite.id == str(invite_id), OrgInvite.org_id == current_org.id)
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

    accept_url = f"{DASHBOARD_URL}/accept-invite?token={raw_token}"
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
@limiter.limit("30/hour")
async def cancel_invite(
    request: Request,
    invite_id: uuid.UUID,
    current_org: CurrentOrg = Depends(require_role("owner", "admin")),
    db: Session = Depends(get_db),
):
    invite = (
        db.query(OrgInvite)
        .filter(OrgInvite.id == str(invite_id), OrgInvite.org_id == current_org.id)
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
            "full_name":  cli.full_name,
            "role":       member.role,
            "is_billing_contact": bool(member.is_billing_contact),
            "created_at": member.created_at,
        }
        for member, cli in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /org/members/{member_id}/billing-contact: owner only
#
# Marks whether a member receives billing emails when the org's recipient
# setting is "selected" (see api/billing_emails.py).
# ---------------------------------------------------------------------------

class BillingContactBody(BaseModel):
    is_billing_contact: bool


@router.patch("/org/members/{member_id}/billing-contact")
@limiter.limit("60/hour")
async def set_billing_contact(
    request: Request,
    member_id: uuid.UUID,
    body: BillingContactBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == str(member_id), OrganizationMember.org_id == current_org.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found.")
    member.is_billing_contact = body.is_billing_contact
    db.commit()
    return {"is_billing_contact": member.is_billing_contact}


# ---------------------------------------------------------------------------
# PATCH /org/members/{member_id} — owner only: change a member's role
# ---------------------------------------------------------------------------

class RoleChangeBody(BaseModel):
    role: Literal["admin", "viewer"]


@router.patch("/org/members/{member_id}")
@limiter.limit("30/hour")
async def change_member_role(
    request: Request,
    member_id: uuid.UUID,
    body: RoleChangeBody,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == str(member_id), OrganizationMember.org_id == current_org.id)
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
@limiter.limit("30/hour")
async def remove_member(
    request: Request,
    member_id: uuid.UUID,
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == str(member_id), OrganizationMember.org_id == current_org.id)
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
@limiter.limit("10/hour")
async def transfer_ownership(
    request: Request,
    member_id: uuid.UUID,
    client: Client = Depends(get_current_client),
    current_org: CurrentOrg = Depends(require_role("owner")),
    db: Session = Depends(get_db),
):
    new_owner = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.id == str(member_id), OrganizationMember.org_id == current_org.id)
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
    full_name: Optional[str] = None  # required only when no account exists yet


@router.post("/org/invite/{token}/accept")
@limiter.limit("10/hour")
async def accept_invite(
    request: Request,
    response: Response,
    token: str,
    body: AcceptInviteBody,
    db: Session = Depends(get_db),
    current_client: Optional[Client] = Depends(get_optional_client),
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
        check_password(body.password)  # Phase 14 (F-002)
        if not body.full_name or not body.full_name.strip():
            raise HTTPException(status_code=400, detail="Full name is required to set up your account.")
        client = Client(
            email=invite.invited_email,
            password_hash=await ahash_password(body.password),
            full_name=clean_text(body.full_name, "Full name"),  # Phase 14 (F-004): at most 255
            email_verified=True,  # the invite link itself is proof of ownership
        )
        db.add(client)
        db.flush()  # populate client.id without committing yet
    else:
        # An invite for an email that already has an account must never mint a
        # session by itself: the token alone proves nothing about who is
        # holding it (it could be forwarded, intercepted, or left in a shared
        # inbox). Require the caller to already be signed in as that exact
        # account, which means they passed the normal login flow, MFA
        # included, before the invite can be accepted.
        if current_client is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in to your existing account to accept this invitation.",
            )
        if current_client.id != client.id:
            raise HTTPException(
                status_code=403,
                detail=f"This invitation is for {invite.invited_email}. Sign in as that account to accept it.",
            )

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

