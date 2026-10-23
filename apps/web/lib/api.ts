/**
 * Thin typed API client wrapper. Hand-written (unlike lib/api-types.ts,
 * which is generated/placeholder — see its header comment) because this is
 * plumbing: it just parameterizes openapi-fetch's createClient with the
 * generated `paths` type and points it at the API base URL.
 *
 * Use this for typed JSON GET/PATCH/etc. calls. The one exception is the
 * applicant form's multipart POST /applications submit (apps/web/app/
 * (applicant)/apply/ApplyForm.tsx) — openapi-fetch's typed body doesn't
 * comfortably express `FormData`/multipart, so that call uses plain
 * `fetch` directly against API_BASE_URL instead of this client.
 */

import createClient from "openapi-fetch";

import type { paths } from "./api-types";

// Two different base URLs are needed in Docker: the browser (client-side
// fetches, and server-rendered pages viewed directly) reaches the api
// container via its published host port (localhost:8000), but Next.js's
// own server-side rendering runs *inside* the web container, where
// "localhost" refers to the web container itself, not the api one — it
// must use the Docker Compose service name instead (api:8000).
// API_BASE_URL_INTERNAL has no NEXT_PUBLIC_ prefix so it's never inlined
// into the client bundle; it's only read here, server-side.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const API_BASE_URL_INTERNAL = process.env.API_BASE_URL_INTERNAL ?? API_BASE_URL;

export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? API_BASE_URL_INTERNAL : API_BASE_URL,
});
