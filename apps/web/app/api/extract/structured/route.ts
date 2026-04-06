import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/authOptions';

/**
 * Gateway route handler for /api/extract/structured
 */
export async function POST(request: NextRequest) {
  const session = await getServerSession(authOptions);

  if (!session) {
    return NextResponse.json({ detail: 'Authentication required' }, { status: 401 });
  }

  const user = session.user as any;
  const businessUserId = user?.businessUserId;
  const orgId = user?.orgId;
  const role = user?.role;

  if (!businessUserId || !orgId) {
    return NextResponse.json({ detail: 'Session missing user context' }, { status: 401 });
  }

  const rawDocId = request.nextUrl.searchParams.get('raw_doc_id');
  if (!rawDocId) {
    return NextResponse.json({ detail: 'raw_doc_id is required' }, { status: 400 });
  }

  try {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    const response = await fetch(`${backendUrl}/extract/structured?raw_doc_id=${rawDocId}`, {
      method: 'POST',
      headers: {
        'X-Business-User-Id': businessUserId,
        'X-Org-Id': orgId,
        'X-User-Role': role || 'user',
      },
    });

    let data: any;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = { detail: text || 'Unknown error from backend' };
    }
    return NextResponse.json(data, { status: response.status });

  } catch (error: any) {
    console.error('Extract structured proxy error:', error);
    return NextResponse.json(
      { detail: `Extract failed: ${error.message}` },
      { status: 500 }
    );
  }
}
