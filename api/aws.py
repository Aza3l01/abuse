"""api/aws.py: cross-account AWS access via sts:AssumeRole (phase 2).

Centralizes AWS session construction for the four places Clew talks to a
customer's AWS account: S3 ingestion (workers/tasks/process_logs.py), the S3
connection test (api/routes/clients.py), WAF blocking (workers/tasks/
push_blocks.py, via blocking/aws_waf.py), and the WAF connection test
(api/routes/settings.py).

If an org has aws_role_arn set, Clew assumes that role in the customer's own
account using the org's own External ID (never customer-chosen, generated at
org creation). If not, this falls back to Clew's shared ambient credentials,
which is the pre-phase-2 behavior, so any org that has not yet configured a
role keeps working unchanged.

Returned sessions self-refresh: their credentials are wrapped in botocore's
RefreshableCredentials, so a single long-running task (e.g. a large
first-connection 7-day backfill) that outlives one assumed session's 1-hour
lifetime transparently re-calls sts:AssumeRole instead of starting to fail
mid-run. The session object itself is cached in-process per org id so a busy
poll loop does not call sts:AssumeRole on every single S3/WAF call either.

Deliberately minimal imports: no import from api.routes or db.models, so
this stays importable from workers/ and (if ever needed) detection/ without
pulling in unrelated app code.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

import boto3
from botocore.credentials import RefreshableCredentials
from botocore.exceptions import ClientError
from botocore.session import Session as BotocoreSession

logger = logging.getLogger(__name__)

_SESSION_DURATION_SECONDS = 3600

CLEW_AWS_ACCOUNT_ID = os.environ.get("CLEW_AWS_ACCOUNT_ID", "")


class OrgLike(Protocol):
    """The minimal shape aws_session_for_org needs. A Protocol (not a direct
    import of db.models.Organization) keeps this module decoupled from the
    ORM, matching the pattern S3Reader already uses for detection/."""
    id: str
    aws_role_arn: str | None
    aws_external_id: str | None


class AWSAccessError(Exception):
    """Raised when assuming a customer's IAM role fails. Carries a
    customer-readable message, since api/routes/clients.py's and
    api/routes/settings.py's connection tests surface this directly."""


_cache_lock = threading.Lock()
_session_cache: dict[tuple[str, str, str | None], boto3.Session] = {}


def _assume_role_metadata(org: OrgLike) -> dict:
    """One sts:AssumeRole call, returned in the dict shape botocore's
    RefreshableCredentials expects. Used both for the initial credentials
    and, later, as the automatic refresh callback."""
    # RoleSessionName shows up in the customer's own CloudTrail, so they can
    # see exactly which of their tenants Clew acted for. Max 64 chars, and a
    # UUID org id fits comfortably within that.
    session_name = f"clew-{org.id}"[:64]
    try:
        sts = boto3.client("sts")
        resp = sts.assume_role(
            RoleArn=org.aws_role_arn,
            RoleSessionName=session_name,
            ExternalId=org.aws_external_id,
            DurationSeconds=_SESSION_DURATION_SECONDS,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "AccessDenied":
            raise AWSAccessError(
                "Clew could not assume the IAM role. Check that the trust policy's "
                "sts:ExternalId condition matches the External ID shown in Settings, "
                "and that the role trusts Clew's AWS account."
            ) from exc
        if code == "InvalidClientTokenId":
            raise AWSAccessError(
                "AWS rejected Clew's own credentials while assuming this role. "
                "This is a Clew-side configuration issue, contact support@clewsec.com."
            ) from exc
        raise AWSAccessError(f"Failed to assume role: {code or str(exc)}") from exc

    creds = resp["Credentials"]
    return {
        "access_key": creds["AccessKeyId"],
        "secret_key": creds["SecretAccessKey"],
        "token": creds["SessionToken"],
        "expiry_time": creds["Expiration"].isoformat(),
    }


def aws_session_for_org(org: OrgLike) -> boto3.Session:
    """Return a boto3 Session scoped to `org`'s AWS account.

    Assumes org.aws_role_arn (cross-account, with the External ID condition)
    when set. Falls back to Clew's shared ambient credentials otherwise,
    the fallback path every org used before phase 2 and that any
    not-yet-migrated org keeps using.
    """
    if not org.aws_role_arn:
        return boto3.Session()

    # Keyed on role_arn + external_id (not just org.id) so a rotated External
    # ID or a changed role ARN is a cache miss, forcing a fresh assume-role
    # call instead of silently reusing a session built under the old value.
    cache_key = (org.id, org.aws_role_arn, org.aws_external_id)
    with _cache_lock:
        cached = _session_cache.get(cache_key)
        if cached is not None:
            return cached

    # The initial assume-role call happens eagerly here, so a bad role ARN
    # or a mismatched External ID raises AWSAccessError synchronously, which
    # is what the settings-page connection tests need. Later refreshes (past
    # the ~1-hour mark) happen lazily inside botocore, triggered by whatever
    # S3/WAF call needed fresh credentials.
    refreshable_credentials = RefreshableCredentials.create_from_metadata(
        metadata=_assume_role_metadata(org),
        refresh_using=lambda: _assume_role_metadata(org),
        method="sts-assume-role",
    )
    botocore_session = BotocoreSession()
    botocore_session._credentials = refreshable_credentials
    session = boto3.Session(botocore_session=botocore_session)

    with _cache_lock:
        _session_cache[cache_key] = session

    return session
