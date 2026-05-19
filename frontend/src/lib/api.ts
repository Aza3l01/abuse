/**
 * Base URL for all FastAPI calls.
 *
 * Set NEXT_PUBLIC_API_URL in frontend/.env.local.
 * Local dev default: http://localhost:8000
 * Production:        https://api.clewsec.com
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
