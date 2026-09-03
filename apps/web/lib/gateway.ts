import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';

/**
 * Next.js authentication gateway helpers.
 *
 * The Next.js server is the only entry point to the private FastAPI backend.
 * Every server→backend call must (1) validate the NextAuth session and (2)
 * forward the trusted identity headers FastAPI relies on. This module is the
 * single place that does both, so route handlers and Server Components can't
 * drift or forget a check.
 */

export interface GatewayContext {
  businessUserId: string;
  orgId: string;
  role: string;
}

/** Raised when the session is missing or lacks business-user context. */
export class GatewayAuthError extends Error {
  constructor(readonly detail: string) {
    super(detail);
    this.name = 'GatewayAuthError';
  }
}

/**
 * Validate the NextAuth session and extract the trusted user context.
 * Throws {@link GatewayAuthError} if unauthenticated or context is incomplete.
 */
export async function getGatewayContext(): Promise<GatewayContext> {
  const session = await getServerSession(authOptions);
  if (!session) {
    throw new GatewayAuthError('Authentication required');
  }
  const user = session.user as
    | { businessUserId?: string; orgId?: string; role?: string }
    | undefined;
  if (!user?.businessUserId || !user?.orgId) {
    throw new GatewayAuthError('Session missing user context');
  }
  return {
    businessUserId: user.businessUserId,
    orgId: user.orgId,
    role: user.role || 'user',
  };
}

/** Build the trusted headers FastAPI expects, merged over any `extra` headers. */
export function trustedHeaders(ctx: GatewayContext, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set('X-Business-User-Id', ctx.businessUserId);
  headers.set('X-Org-Id', ctx.orgId);
  headers.set('X-User-Role', ctx.role);
  return headers;
}

/** Base URL of the private FastAPI backend (server-to-server). */
export function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}

type GatewayRouteHandler<Ctx> = (
  request: NextRequest,
  gateway: GatewayContext,
  routeContext: Ctx,
) => Promise<NextResponse> | NextResponse;

/**
 * Wrap a route handler so the session is validated and the trusted context is
 * resolved before it runs. Unauthenticated requests get a 401 and the handler
 * never executes.
 */
export function withGateway<Ctx = unknown>(handler: GatewayRouteHandler<Ctx>) {
  return async (request: NextRequest, routeContext: Ctx): Promise<NextResponse> => {
    let gateway: GatewayContext;
    try {
      gateway = await getGatewayContext();
    } catch (error) {
      if (error instanceof GatewayAuthError) {
        return NextResponse.json({ detail: error.detail }, { status: 401 });
      }
      throw error;
    }
    return handler(request, gateway, routeContext);
  };
}
