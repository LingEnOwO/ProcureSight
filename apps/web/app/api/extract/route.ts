/**
* TODO: Right now this is not used because the frontend is directly calling the FastAPI backend for simplicity. 
In the future, we may want to route all API calls through Next.js for better security and session handling.

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';


 * Gateway route handlers for /api/extract/*
 * 
 * These endpoints receive file uploads from the browser and forward them
 * to the private FastAPI backend with authenticated user context.
 * 
 * Supported endpoints:
 * - POST /api/extract/structured
 * - POST /api/extract/unstructured


async function handleExtract(request: NextRequest, endpoint: string) {
  // Validate session
  const session = await getServerSession(authOptions);
  
  if (!session) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 });
  }

  // Extract validated user context
  const user = session.user as any;
  const businessUserId = user?.businessUserId;
  const orgId = user?.orgId;
  const role = user?.role;

  if (!businessUserId || !orgId) {
    return NextResponse.json({ detail: 'Session missing user context' }, { status: 401 });
  }

  try {
    // Get form data from request
    const formData = await request.formData();
    
    // Forward to private FastAPI backend with trusted headers
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    
    const response = await fetch(`${backendUrl}/extract/${endpoint}`, {
      method: 'POST',
      headers: {
        'X-Business-User-Id': businessUserId,
        'X-Org-Id': orgId,
        'X-User-Role': role || 'user',
      },
      body: formData,
    });
    
    // Forward backend response
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
    
  } catch (error: any) {
    console.error(`Extract ${endpoint} proxy error:`, error);
    return NextResponse.json(
      { detail: `Extract failed: ${error.message}` },
      { status: 500 }
    );
  }
}

// Route: POST /api/extract/structured
export async function POST(request: NextRequest) {
  // Extract the path segment from the URL
  const url = new URL(request.url);
  const pathSegments = url.pathname.split('/').filter(Boolean);
  
  // pathSegments = ['api', 'extract', 'structured' or 'unstructured']
  const endpoint = pathSegments[pathSegments.length - 1] || 'structured';
  
  return handleExtract(request, endpoint);
}
 */
