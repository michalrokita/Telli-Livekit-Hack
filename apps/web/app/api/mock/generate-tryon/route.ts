import { NextResponse } from 'next/server';

import { type ProductRecommendation } from '../../../../lib/shopper-flow';
import { createTryOnJobsWithStylistFallback } from '../../../../lib/stylist-service';

type GenerateTryOnBody = {
  customerImageId?: unknown;
  customerImageDataUrl?: unknown;
  imageDataUrl?: unknown;
  products?: unknown;
  selectedProductIds?: unknown;
};

async function readJsonBody(request: Request): Promise<GenerateTryOnBody | null> {
  try {
    return (await request.json()) as GenerateTryOnBody;
  } catch {
    return null;
  }
}

function isProductRecommendationList(value: unknown): value is ProductRecommendation[] {
  return (
    Array.isArray(value) &&
    value.every(
      (product) =>
        product &&
        typeof product === 'object' &&
        typeof (product as ProductRecommendation).id === 'string' &&
        typeof (product as ProductRecommendation).name === 'string' &&
        typeof (product as ProductRecommendation).tryOnImageUrl === 'string',
    )
  );
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

export async function POST(request: Request) {
  const body = await readJsonBody(request);

  if (!body) {
    return NextResponse.json({ error: 'Expected a JSON request body.' }, { status: 400 });
  }

  if (typeof body.customerImageId !== 'string' || body.customerImageId.length === 0) {
    return NextResponse.json({ error: 'customerImageId is required.' }, { status: 400 });
  }

  if (!isProductRecommendationList(body.products)) {
    return NextResponse.json({ error: 'products are required.' }, { status: 400 });
  }

  if (!isStringList(body.selectedProductIds)) {
    return NextResponse.json({ error: 'selectedProductIds are required.' }, { status: 400 });
  }

  const imageDataUrl =
    typeof body.customerImageDataUrl === 'string'
      ? body.customerImageDataUrl
      : typeof body.imageDataUrl === 'string'
        ? body.imageDataUrl
        : undefined;

  const jobs = await createTryOnJobsWithStylistFallback.tryOns({
    customerImageId: body.customerImageId,
    customerImageDataUrl: imageDataUrl,
    products: body.products,
    selectedProductIds: body.selectedProductIds,
  });

  return NextResponse.json({ jobs });
}
