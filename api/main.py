import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

from api.routes import auth, clients, verdicts, dashboard, ips, billing
from api.limiter import limiter

load_dotenv()

app = FastAPI(
    title="Clew API",
    version="0.1.0",
    # Disable docs in production by checking an env flag if needed later
)

# ------------------------------------------------------------------
# Rate limiter state (slowapi attaches to app)
# ------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ------------------------------------------------------------------
# CORS — only the frontend origin is allowed
# ------------------------------------------------------------------
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
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
