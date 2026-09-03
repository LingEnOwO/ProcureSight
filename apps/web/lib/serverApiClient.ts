import { backendBaseUrl, getGatewayContext, trustedHeaders } from '@/lib/gateway';

/**
 * Server-side API client for Next.js Server Components.
 *
 * Part of the Next.js authentication gateway: it validates the NextAuth session
 * and forwards authenticated requests to the private FastAPI backend with
 * trusted identity headers (see @/lib/gateway). FastAPI trusts these headers
 * because it is only reachable from the Next.js server, never the browser.
 */
export async function serverFetch(path: string, options: RequestInit = {}) {
  // Validate the session and resolve trusted context (throws if unauthenticated).
  const gateway = await getGatewayContext();

  const url = `${backendBaseUrl()}${path}`;
  const headers = trustedHeaders(gateway, options.headers);
  headers.set('Content-Type', 'application/json');

  const response = await fetch(url, {
    ...options,
    cache: 'no-store', // Never cache — responses are user/org-specific
    headers,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Backend error (${response.status}): ${errorText}`);
  }

  return response;
}

export async function serverGet(path: string) {
  const response = await serverFetch(path, { method: 'GET' });
  return response.json();
}

export async function serverPost(path: string, body: unknown) {
  const response = await serverFetch(path, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  return response.json();
}
