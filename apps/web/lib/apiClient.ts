import createClient from "openapi-fetch";
import type { paths } from "@procuresight/types";

const baseUrl =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

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