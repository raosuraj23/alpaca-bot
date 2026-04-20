/**
 * Central API base URL — reads NEXT_PUBLIC_API_URL from env, falls back to
 * localhost for local development.  Import this everywhere instead of hardcoding.
 */
export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

export const WS_BASE = API_BASE.replace(/^http/, "ws");
