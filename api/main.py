import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

from api.routes import auth, clients, verdicts, dashboard, ips, billing
from api.limiter import limiter

load_dotenv()
load_dotenv(".env.local", override=True)  # local dev overrides (gitignored)

_debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Clew API",
    version="0.1.0",
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
    openapi_url="/openapi.json" if _debug else None,
)

# ------------------------------------------------------------------
# Rate limiter state (slowapi attaches to app)
# ------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ------------------------------------------------------------------
# CORS — allow the frontend origin (and its www variant)
# ------------------------------------------------------------------
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")

_cors_origins = [FRONTEND_URL]
# Nginx serves both clewsec.com and www.clewsec.com; include both so that
# a browser on either subdomain can send credentialed requests to the API.
if "://www." in FRONTEND_URL:
    _cors_origins.append(FRONTEND_URL.replace("://www.", "://", 1))
else:
    scheme_sep = FRONTEND_URL.find("://")
    if scheme_sep != -1:
        _cors_origins.append(
            FRONTEND_URL[: scheme_sep + 3] + "www." + FRONTEND_URL[scheme_sep + 3 :]
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,   # required for cookies to be sent cross-origin
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------
app.include_router(auth.router,     prefix="/auth", tags=["auth"])
app.include_router(clients.router,              tags=["clients"])
app.include_router(verdicts.router,             tags=["verdicts"])
app.include_router(dashboard.router,            tags=["dashboard"])
app.include_router(ips.router,                  tags=["ips"])
app.include_router(billing.router,              tags=["billing"])


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}
