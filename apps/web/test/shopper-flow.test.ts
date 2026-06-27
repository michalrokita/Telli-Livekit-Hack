import { describe, expect, it } from 'vitest';

import {
  analyzeCustomerImage,
  createTryOnJobs,
  getCartSummary,
  recommendProducts,
} from '../lib/shopper-flow';

describe('shopper flow helpers', () => {
  it('returns a concise personal style analysis from a captured image', async () => {
    const analysis = await analyzeCustomerImage({
      imageDataUrl: 'data:image/jpeg;base64,demo',
      category: 'hats',
    });

    expect(analysis.hairColor).toBeTruthy();
    expect(analysis.skinTone).toBeTruthy();
    expect(analysis.styleNotes.length).toBeGreaterThanOrEqual(3);
    expect(analysis.summary.toLowerCase()).toContain('hat');
  });

  it('recommends exactly five products for the selected category', async () => {
    const products = await recommendProducts({
      category: 'tshirts',
      styleGoal: 'clean summer basics',
      qualities: {
        hairColor: 'dark brown',
        skinTone: 'warm olive',
        contrast: 'medium',
        undertone: 'golden',
        styleNotes: ['warm neutrals', 'soft structure', 'matte textures'],
        summary: 'Warm olive skin and dark hair.',
      },
    });

    expect(products).toHaveLength(5);
    expect(products.every((product) => product.category === 'tshirts')).toBe(true);
    expect(products.every((product) => product.price > 0)).toBe(true);
  });

  it('creates try-on jobs only for selected products', async () => {
    const products = await recommendProducts({
      category: 'hats',
      styleGoal: 'city weekend',
      qualities: {
        hairColor: 'dark brown',
        skinTone: 'warm olive',
        contrast: 'medium',
        undertone: 'golden',
        styleNotes: ['warm neutrals', 'soft structure', 'matte textures'],
        summary: 'Warm olive skin and dark hair.',
      },
    });

    const selected = products.slice(0, 3).map((product) => product.id);
    const jobs = await createTryOnJobs({
      customerImageId: 'customer-demo',
      products,
      selectedProductIds: selected,
    });

    expect(jobs).toHaveLength(3);
    expect(jobs.map((job) => job.productId)).toEqual(selected);
    expect(jobs.every((job) => job.status === 'complete')).toBe(true);
  });

  it('summarizes cart additions for the animated cart badge', () => {
    const summary = getCartSummary([
      { productId: 'hat-1', quantity: 1 },
      { productId: 'hat-2', quantity: 2 },
    ]);

    expect(summary.itemCount).toBe(3);
    expect(summary.justAddedCount).toBe(2);
  });
});
