import createClient from "openapi-fetch";
import type { paths } from "@procuresight/types";

/**
 * ⚠️ DEPRECATED - Gateway Pattern Migration
 * 
 * This client is deprecated in favor of the gateway pattern where Next.js
 * handles all authentication and forwards requests to the private FastAPI backend.
 * 
 * RECOMMENDED ALTERNATIVES:
 * 
 * For Server Components:
 *   Use serverFetch() from @/lib/serverApiClient
 *   Example: const response = await serverFetch('/vendors');
 * 
 * For Client Components:
 *   Use Next.js route handlers (e.g., /api/backend/*, /api/ingest, /api/extract/*)
 *   Example: fetch('/api/backend/vendors')
 * 
 * WHY DEPRECATED:
 *   - This client proxies through /api/backend/* which is OK
 *   - But promotes direct backend access patterns
 *   - Gateway pattern makes authentication boundary clearer
 *   - Easier to add rate limiting, caching, etc. at gateway layer
 */

// Use Next.js API proxy instead of direct backend URL
// This solves the cross-port cookie issue by keeping everything on localhost:3000
// For server-side (like Server Components), we need an absolute URL
// For client-side, we can use a relative URL
const isServer = typeof window === 'undefined';
const baseUrl = isServer 
  ? "http://localhost:3000/api/backend"  // Absolute URL for server-side
  : "/api/backend";  // Relative URL for client-side

/**
 * Typed OpenAPI client.
 * Usage:
 *   const { data, error } = await api.GET("/health");
 */
export const api = createClient<paths>({
  baseUrl,

  // If your backend uses cookies/sessions, keep this ON.
  // If your backend uses Bearer tokens only, we can change later.
  fetch: (request: Request) => {
    // openapi-fetch passes a fully constructed Request object.
    // We clone it to force cookies to be included in cross-origin requests.
    return fetch(new Request(request, { credentials: "include" }));
  },
});

/**
 * Optional helper: throw on non-2xx so pages can use try/catch.
 */
export async function apiGet<P extends keyof paths>(
  path: P,
  ...args: paths[P] extends { get: any }
    ? [
        params?: paths[P]["get"] extends { parameters: infer Params }
          ? Params
          : never
      ]
    : never
) {
  const params = (args[0] as any) ?? {};
  const res = await (api as any).GET(path as any, params);
  if (res.error) throw res.error;
  return res.data as any;
}