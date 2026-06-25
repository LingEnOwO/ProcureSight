import { NextResponse } from 'next/server';
import { backendBaseUrl, trustedHeaders, withGateway } from '@/lib/gateway';

/**
 * Gateway route handler for /api/ingest.
 *
 * Receives a multipart/form-data upload from the browser and forwards it to the
 * private FastAPI backend with the trusted user context. (Auth handled by
 * withGateway.)
 */
export const POST = withGateway(async (request, gateway) => {
  try {
    const formData = await request.formData();
    // No Content-Type header — fetch sets the multipart boundary from FormData.
    const response = await fetch(`${backendBaseUrl()}/ingest`, {
      method: 'POST',
      headers: trustedHeaders(gateway),
      body: formData,
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    console.error('Ingest proxy error:', error);
    return NextResponse.json({ detail: `Ingest failed: ${error.message}` }, { status: 500 });
  }
});
