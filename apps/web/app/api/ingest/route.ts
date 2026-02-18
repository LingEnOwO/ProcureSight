import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';

/**
 * Gateway route handler for /api/ingest
 * 
 * This endpoint receives file uploads from the browser and forwards them
 * to the private FastAPI backend with authenticated user context.
 * 
 * Flow:
 * 1. Browser POST multipart/form-data → /api/ingest
 * 2. Validate NextAuth session
 * 3. Forward to FastAPI with trusted headers
 * 4. Return FastAPI response to browser
 */
export async function POST(request: NextRequest) {
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
    
    // Forward to private FastAPI backend  with trusted headers
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    
    // Create new FormData with trusted headers as regular headers
    // (multipart form-data goes in body, auth goes in headers)
    const response = await fetch(`${backendUrl}/ingest`, {
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
    console.error('Ingest proxy error:', error);
    return NextResponse.json(
      { detail: `Ingest failed: ${error.message}` },
      { status: 500 }
    );
  }
}
