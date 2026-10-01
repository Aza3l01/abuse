import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance imported by main.py and all route files.
#
# Item 58: PM2 runs uvicorn with --workers 2, and slowapi's default
# memory:// storage is per-process, so every limit above was effectively
# doubled and reset on every deploy/respawn. REDIS_URL is already a hard
# dependency of the API process (auth.py, org.py), so backing the limiter
# with it adds no new infrastructure, just makes counts shared and durable.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    # slowapi defaults to key_style="url", which embeds the resolved request
    # path (path params substituted in) in every Redis rate-limiter key.
    # For routes with a secret in the path (e.g. POST /org/invite/{token}/
    # accept), that puts the raw, un-hashed invite token in plaintext in
    # Redis, even though org_invites.token_hash never stores it unhashed.
    # "endpoint" scopes the key by the route function's module.name instead,
    # which is stable and secret-free, and still gives every route its own
    # independent limit bucket exactly like "url" did.
    key_style="endpoint",
)
