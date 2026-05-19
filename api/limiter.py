from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance imported by main.py and all route files
limiter = Limiter(key_func=get_remote_address)
