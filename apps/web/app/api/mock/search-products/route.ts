import { NextResponse } from 'next/server';

import {
  type CustomerQualities,
  isShopperCategory,
  recommendProducts,
} from '../../../../lib/shopper-flow';

type SearchProductsBody = {
  category?: unknown;
  styleGoal?: unknown;
  qualities?: unknown;
};

async function readJsonBody(request: Request): Promise<SearchProductsBody | null> {
  try {
    return (await request.json()) as SearchProductsBody;
  } catch {
    return null;
  }
}

function isCustomerQualities(value: unknown): value is CustomerQualities {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const qualities = value as Partial<CustomerQualities>;

  return (
    typeof qualities.hairColor === 'string' &&
    typeof qualities.skinTone === 'string' &&
    typeof qualities.contrast === 'string' &&
    typeof qualities.undertone === 'string' &&
    Array.isArray(qualities.styleNotes) &&
    qualities.styleNotes.every((note) => typeof note === 'string') &&
    typeof qualities.summary === 'string'
  );
}

export async function POST(request: Request) {
  const body = await readJsonBody(request);

  if (!body) {
    return NextResponse.json({ error: 'Expected a JSON request body.' }, { status: 400 });
  }

  if (!isShopperCategory(body.category)) {
    return NextResponse.json({ error: 'category must be hats or tshirts.' }, { status: 400 });
  }

  if (!isCustomerQualities(body.qualities)) {
    return NextResponse.json({ error: 'qualities are required.' }, { status: 400 });
  }

  const products = await recommendProducts({
    category: body.category,
    styleGoal: typeof body.styleGoal === 'string' ? body.styleGoal : undefined,
    qualities: body.qualities,
  });

  return NextResponse.json({ products });
}
