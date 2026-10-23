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

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const api = createClient<paths>({ baseUrl: API_BASE_URL });
