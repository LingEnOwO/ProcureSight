import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';

/**
 * Server-side API client for Next.js Server Components.
 * 
 * GATEWAY PATTERN:
 * ----------------
 * This function acts as part of the Next.js authentication gateway.
 * It validates NextAuth sessions and forwards authenticated requests to the private FastAPI backend.
 * 
 * Flow:
 * 1. Validate NextAuth session (server-side)
 * 2. Extract user context from validated session
 * 3. Forward request to FastAPI with trusted headers
 * 4. FastAPI trusts these headers (no JWT verification needed)
 * 
 * Security:
 * - FastAPI must be in a private network (not publicly accessible)
 * - Only Next.js server can reach FastAPI
 * - Browser never communicates directly with FastAPI
 */
export async function serverFetch(path: string, options: RequestInit = {}) {
  // Validate NextAuth session (this is where authentication happens)
  const session = await getServerSession(authOptions);
  
  if (!session) {
    throw new Error('Not authenticated');
  }

  // Extract validated user context from session
  const user = session.user as any;
  const businessUserId = user?.businessUserId;
  const orgId = user?.orgId;
  const role = user?.role;

  if (!businessUserId || !orgId) {
    throw new Error('Session missing business user context');
  }

  // Forward to FastAPI with trusted headers (server-to-server communication)
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const url = `${backendUrl}${path}`;

  const headers = new Headers(options.headers);
  headers.set('X-Business-User-Id', businessUserId);
  headers.set('X-Org-Id', orgId);
  headers.set('X-User-Role', role || 'user');
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
