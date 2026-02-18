/**
 * Gateway proxy route for client-side requests to FastAPI backend.
 * 
 * ARCHITECTURE:
 * Browser → /api/backend/* → (this proxy validates session) → FastAPI (private)
 * 
 * This catch-all route handles ANY backend path, e.g.:
 *   fetch("/api/backend/vendors")           → FastAPI /vendors
 *   fetch("/api/backend/ingest")            → FastAPI /ingest
 *   fetch("/api/backend/extract/structured") → FastAPI /extract/structured
 * 
 * NOTE ON DEDICATED ROUTE FILES:
 * /api/ingest/route.ts and /api/extract/structured|unstructured/route.ts are
 * redundant with this catch-all for plain proxying. They only make sense if you
 * need special behavior for a specific endpoint, such as:
 *   - Different auth or rate limiting logic
 *   - Response transformation or streaming
 *   - Endpoint-specific error handling
 * TODO: Otherwise, prefer calling /api/backend/<path> directly and let this catch-all handle it.
 * 
 * Security:
 * - Browser can only reach FastAPI through this proxy
 * - FastAPI is not directly accessible from browser
 * - All authentication happens here (FastAPI trusts headers)
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params;
  return proxyToBackend(request, params.path);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params;
  return proxyToBackend(request, params.path);
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params;
  return proxyToBackend(request, params.path);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params;
  return proxyToBackend(request, params.path);
}

async function proxyToBackend(request: NextRequest, pathSegments: string[]) {
  // Validate session (authentication happens here)
  const session = await getServerSession(authOptions);
  
  if (!session) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 });
  }

  // Extract validated user context from session
  const user = session.user as any;
  const businessUserId = user?.businessUserId;
  const orgId = user?.orgId;
  const role = user?.role;

  if (!businessUserId || !orgId) {
    return NextResponse.json({ detail: 'Session missing user context' }, { status: 401 });
  }

  // Build backend URL (private, server-to-server)
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const path = pathSegments.join('/');
  const url = `${backendUrl}/${path}${request.nextUrl.search}`;

  // Forward request with trusted headers (FastAPI will trust these)
  const headers = new Headers();
  headers.set('X-Business-User-Id', businessUserId);
  headers.set('X-Org-Id', orgId);
  headers.set('X-User-Role', role || 'user');
  headers.set('Content-Type', request.headers.get('Content-Type') || 'application/json');

  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: request.method !== 'GET' && request.method !== 'HEAD' 
        ? await request.text() 
        : undefined,
    });

    // Forward response from backend
    const data = await response.text();
    return new NextResponse(data, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    });
  } catch (error) {
    console.error('Backend proxy error:', error);
    return NextResponse.json(
      { detail: 'Backend request failed' },
      { status: 502 }
    );
  }
}
