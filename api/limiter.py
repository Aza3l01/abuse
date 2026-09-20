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
)
