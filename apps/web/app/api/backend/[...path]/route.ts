/**
 * Gateway proxy route for client-side requests to FastAPI backend.
 *
 * ARCHITECTURE:
 * Browser → /api/backend/* → (this proxy validates session) → FastAPI (private)
 *
 * This catch-all route handles ANY backend path, e.g.:
 *   fetch("/api/backend/vendors")            → FastAPI /vendors
 *   fetch("/api/backend/ingest")             → FastAPI /ingest
 *   fetch("/api/backend/extract/structured") → FastAPI /extract/structured
 *
 * Session validation and trusted-header forwarding live in @/lib/gateway, so
 * the browser can only reach FastAPI through this proxy and FastAPI is never
 * directly accessible from the browser.
 */

import { NextRequest, NextResponse } from 'next/server';
import { GatewayContext, backendBaseUrl, trustedHeaders, withGateway } from '@/lib/gateway';

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxyToBackend(
  request: NextRequest,
  gateway: GatewayContext,
  routeContext: RouteContext,
): Promise<NextResponse> {
  const { path: pathSegments } = await routeContext.params;
  const path = pathSegments.join('/');
  const url = `${backendBaseUrl()}/${path}${request.nextUrl.search}`;

  const headers = trustedHeaders(gateway, {
    'Content-Type': request.headers.get('Content-Type') || 'application/json',
  });

  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body:
        request.method !== 'GET' && request.method !== 'HEAD'
          ? await request.text()
          : undefined,
    });

    const data = await response.text();
    return new NextResponse(data, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') || 'application/json',
      },
    });
  } catch (error) {
    console.error('Backend proxy error:', error);
    return NextResponse.json({ detail: 'Backend request failed' }, { status: 502 });
  }
}

export const GET = withGateway<RouteContext>(proxyToBackend);
export const POST = withGateway<RouteContext>(proxyToBackend);
export const PUT = withGateway<RouteContext>(proxyToBackend);
export const DELETE = withGateway<RouteContext>(proxyToBackend);
