import { NextResponse } from 'next/server';

import { isShopperCategory } from '../../../../lib/shopper-flow';
import { createTryOnJobsWithStylistFallback } from '../../../../lib/stylist-service';

type AnalyzeImageBody = {
  imageDataUrl?: unknown;
  category?: unknown;
};

async function readJsonBody(request: Request): Promise<AnalyzeImageBody | null> {
  try {
    return (await request.json()) as AnalyzeImageBody;
  } catch {
    return null;
  }
}

export async function POST(request: Request) {
  const body = await readJsonBody(request);

  if (!body) {
    return NextResponse.json({ error: 'Expected a JSON request body.' }, { status: 400 });
  }

  if (typeof body.imageDataUrl !== 'string' || body.imageDataUrl.length === 0) {
    return NextResponse.json({ error: 'imageDataUrl is required.' }, { status: 400 });
  }

  if (!isShopperCategory(body.category)) {
    return NextResponse.json({ error: 'category must be hats or tshirts.' }, { status: 400 });
  }

  const { analysis, profile } = await createTryOnJobsWithStylistFallback.analyze({
    imageDataUrl: body.imageDataUrl,
    category: body.category,
  });

  return NextResponse.json({ analysis, profile });
}
