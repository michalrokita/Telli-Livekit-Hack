import { describe, expect, it, vi } from 'vitest';

import {
  getDesignCategoryChoice,
  runShopperDemoFlow,
  type ShopperFlowFetch,
} from '../lib/design-adapter';

describe('design adapter wiring', () => {
  it('maps design category choices to the existing shopper-flow categories', () => {
    expect(getDesignCategoryChoice('hats')).toEqual({
      category: 'hats',
      label: 'Hats',
      styleGoal: 'finish the look',
      supported: true,
    });

    expect(getDesignCategoryChoice('sneakers')).toEqual({
      category: null,
      label: 'Looks',
      styleGoal: '',
      supported: false,
    });
  });

  it('runs the mock shopper API flow with Worker A endpoint payloads', async () => {
    const fetchMock = vi.fn<ShopperFlowFetch>(async (url, init) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {};

      if (url === '/api/mock/analyze-image') {
        expect(body).toEqual({
          imageDataUrl: 'data:image/jpeg;base64,demo',
          category: 'hats',
        });

        return jsonResponse({
          analysis: {
            hairColor: 'dark brown',
            skinTone: 'warm olive',
            contrast: 'medium',
            undertone: 'golden',
            styleNotes: ['warm neutrals'],
            summary: 'Warm olive skin and dark hair.',
          },
        });
      }

      if (url === '/api/mock/search-products') {
        expect(body.category).toBe('hats');
        expect(body.styleGoal).toBe('finish the look');
        expect(body.qualities.skinTone).toBe('warm olive');

        return jsonResponse({
          products: [
            product('hat-1', 'Marseille Straw Panama'),
            product('hat-2', 'Noir Felt Fedora'),
            product('hat-3', 'Olive Canvas Cap'),
          ],
        });
      }

      if (url === '/api/mock/generate-tryon') {
        expect(body.customerImageId).toBe('customer-design-demo');
        expect(body.selectedProductIds).toEqual(['hat-1', 'hat-2']);
        expect(body.products).toHaveLength(3);

        return jsonResponse({
          jobs: [
            {
              id: 'tryon-customer-design-demo-hat-1-1',
              customerImageId: 'customer-design-demo',
              productId: 'hat-1',
              productName: 'Marseille Straw Panama',
              status: 'complete',
              imageUrl: 'https://example.com/hat-1-tryon.jpg',
              generatedAt: '2026-06-27T00:00:00.000Z',
            },
            {
              id: 'tryon-customer-design-demo-hat-2-2',
              customerImageId: 'customer-design-demo',
              productId: 'hat-2',
              productName: 'Noir Felt Fedora',
              status: 'complete',
              imageUrl: 'https://example.com/hat-2-tryon.jpg',
              generatedAt: '2026-06-27T00:00:00.000Z',
            },
          ],
        });
      }

      throw new Error(`Unexpected URL: ${String(url)}`);
    });

    const result = await runShopperDemoFlow(
      {
        category: 'hats',
        imageDataUrl: 'data:image/jpeg;base64,demo',
        customerImageId: 'customer-design-demo',
        selectedProductIds: ['hat-1', 'hat-2'],
      },
      { fetch: fetchMock },
    );

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.analysis.summary).toContain('Warm olive');
    expect(result.products.map((item) => item.id)).toEqual(['hat-1', 'hat-2', 'hat-3']);
    expect(result.tryOnJobs.map((job) => job.productId)).toEqual(['hat-1', 'hat-2']);
    expect(result.cartSummary).toEqual({
      itemCount: 2,
      justAddedCount: 2,
      isEmpty: false,
    });
  });

  it('rejects unsupported design-only categories before calling shopper APIs', async () => {
    const fetchMock = vi.fn<ShopperFlowFetch>();

    await expect(
      runShopperDemoFlow(
        {
          category: 'sneakers',
          imageDataUrl: 'data:image/jpeg;base64,demo',
        },
        { fetch: fetchMock },
      ),
    ).rejects.toThrow('Unsupported shopper category');

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function product(id: string, name: string) {
  return {
    id,
    category: 'hats',
    name,
    brand: 'Atelier Cove',
    price: 84,
    currency: 'USD',
    imageUrl: `https://example.com/${id}.jpg`,
    tryOnImageUrl: `https://example.com/${id}-tryon.jpg`,
    colorStory: 'honey straw',
    material: 'woven palm straw',
    fitNotes: 'structured crown',
    recommendationReason: 'Frames the face well.',
  };
}
