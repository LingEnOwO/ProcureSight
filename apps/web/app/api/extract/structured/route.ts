import { NextResponse } from 'next/server';
import { backendBaseUrl, trustedHeaders, withGateway } from '@/lib/gateway';

/**
 * Gateway route handler for /api/extract/structured.
 */
export const POST = withGateway(async (request, gateway) => {
  const rawDocId = request.nextUrl.searchParams.get('raw_doc_id');
  if (!rawDocId) {
    return NextResponse.json({ detail: 'raw_doc_id is required' }, { status: 400 });
  }

  try {
    const response = await fetch(
      `${backendBaseUrl()}/extract/structured?raw_doc_id=${rawDocId}`,
      { method: 'POST', headers: trustedHeaders(gateway) },
    );

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
    return NextResponse.json({ detail: `Extract failed: ${error.message}` }, { status: 500 });
  }
});
