import { NextResponse } from 'next/server';
import { backendBaseUrl, trustedHeaders, withGateway } from '@/lib/gateway';

/**
 * Gateway route handler for /api/extract/unstructured.
 */
export const POST = withGateway(async (request, gateway) => {
  const rawDocId = request.nextUrl.searchParams.get('raw_doc_id');
  if (!rawDocId) {
    return NextResponse.json({ detail: 'raw_doc_id is required' }, { status: 400 });
  }

  try {
    const response = await fetch(
      `${backendBaseUrl()}/extract/unstructured?raw_doc_id=${rawDocId}`,
      { method: 'POST', headers: trustedHeaders(gateway) },
    );
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('Extract unstructured proxy error:', error);
    return NextResponse.json({ detail: `Extract failed: ${error.message}` }, { status: 500 });
  }
});
