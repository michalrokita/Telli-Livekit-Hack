import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createTryOnJobsWithStylistFallback,
  mapStyleProfileToCustomerQualities,
  resolveStylistRuntimeEnv,
  tryAnalyzeWithStylist,
  tryCreateTryOnJobsWithStylist,
  type StylistPythonRunner,
} from '../lib/stylist-service';
import type { ProductRecommendation } from '../lib/shopper-flow';

const styleProfile = {
  coloring: {
    hair_color: 'dark_brown',
    skin_depth: 'medium',
    skin_undertone: 'warm',
    contrast_level: 'high',
    season: 'autumn',
    undertone_cues: ['golden cheek cast', 'warm-brown hair'],
  },
  current_style: {
    detected_vibe: ['casual', 'streetwear'],
    currently_wearing: 'dark crewneck tee',
  },
  image_quality: {
    usable: true,
    issues: [],
  },
};

const products: ProductRecommendation[] = [
  {
    id: 'hat-1',
    category: 'hats',
    name: 'Noir Felt Fedora',
    brand: 'Northline Studio',
    price: 112,
    currency: 'USD',
    imageUrl: 'https://example.com/hat.jpg',
    tryOnImageUrl: 'https://example.com/mock-hat-tryon.jpg',
    colorStory: 'soft black felt',
    material: 'brushed wool felt',
    fitNotes: 'pinched crown',
    recommendationReason: 'Adds crisp contrast.',
  },
];

describe('stylist service adapter', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('uses live stylist mode by default when an OpenAI key is available', () => {
    expect(resolveStylistRuntimeEnv({ OPENAI_API_KEY: 'sk-demo' }).STYLIST_LIVE).toBe('1');
    expect(resolveStylistRuntimeEnv({ OPENAI_API_KEY: 'sk-demo', STYLIST_LIVE: '0' }).STYLIST_LIVE).toBe('0');
  });

  it('maps StyleProfile output into the existing CustomerQualities shape', () => {
    const qualities = mapStyleProfileToCustomerQualities(styleProfile, 'hats');

    expect(qualities).toEqual({
      hairColor: 'dark brown',
      skinTone: 'medium warm',
      contrast: 'high',
      undertone: 'warm',
      palette: 'autumn',
      styleNotes: [
        'palette: autumn',
        'golden cheek cast',
        'warm-brown hair',
        'casual, streetwear',
        'currently wearing: dark crewneck tee',
      ],
      summary:
        'For hats, lean into a autumn palette, high contrast, and warm undertones.',
    });
  });

  it('runs stylist analyze against decoded image bytes and maps stdout', async () => {
    const runner: StylistPythonRunner = vi.fn((request) => {
      expect(request.kind).toBe('analyze');
      expect(request.imagePath).toMatch(/stylist-web-/);
      return { ok: true, stdout: JSON.stringify(styleProfile) };
    });

    const result = await tryAnalyzeWithStylist({
      imageDataUrl: 'data:image/png;base64,ZGVtbw==',
      category: 'hats',
      runner,
    });

    expect(runner).toHaveBeenCalledOnce();
    expect(result?.qualities.hairColor).toBe('dark brown');
    expect(result?.qualities.palette).toBe('autumn');
    expect(result?.profile).toEqual(styleProfile);
  });

  it('falls back to shopper-flow analysis when stylist analyze is unavailable', async () => {
    vi.stubEnv('STYLIST_LIVE', '0');
    const runner: StylistPythonRunner = vi.fn(() => {
      throw new Error('python unavailable');
    });

    const { analysis } = await createTryOnJobsWithStylistFallback.analyze({
      imageDataUrl: 'data:image/png;base64,ZGVtbw==',
      category: 'hats',
      runner,
    });

    expect(analysis.summary.toLowerCase()).toContain('hat');
  });

  it('does not silently mock analysis when live stylist mode fails', async () => {
    vi.stubEnv('STYLIST_LIVE', '1');
    const runner: StylistPythonRunner = vi.fn(() => {
      throw new Error('python unavailable');
    });

    await expect(
      createTryOnJobsWithStylistFallback.analyze({
        imageDataUrl: 'data:image/png;base64,ZGVtbw==',
        category: 'hats',
        runner,
      }),
    ).rejects.toThrow('Live stylist image analysis failed.');
  });

  it('uses browser-readable stylist try-on images for matching selected products', async () => {
    const runner: StylistPythonRunner = vi.fn((request) => {
      expect(request.kind).toBe('tryon');
      expect(request.optionIds).toEqual(['hat-1']);
      return {
        ok: true,
        stdout: JSON.stringify({
          image_url: 'https://example.com/stylist-render.png',
          status: 'pending',
          rendered_option_ids: ['hat-1'],
          retry_count: 0,
          critic_report: null,
        }),
      };
    });

    const jobs = await tryCreateTryOnJobsWithStylist({
      customerImageId: 'customer-demo',
      customerImageDataUrl: 'data:image/png;base64,ZGVtbw==',
      products,
      selectedProductIds: ['hat-1'],
      runner,
    });

    expect(jobs).toHaveLength(1);
    expect(jobs?.[0].imageUrl).toBe('https://example.com/stylist-render.png');
  });

  it('keeps product try-on images when stylist returns a local file path', async () => {
    const runner: StylistPythonRunner = vi.fn(() => ({
      ok: true,
      stdout: JSON.stringify({
        image_url: '/tmp/stylist_tryon/render.png',
        status: 'pending',
        rendered_option_ids: ['hat-1'],
        retry_count: 0,
        critic_report: null,
      }),
    }));

    const jobs = await tryCreateTryOnJobsWithStylist({
      customerImageId: 'customer-demo',
      customerImageDataUrl: 'data:image/png;base64,ZGVtbw==',
      products,
      selectedProductIds: ['hat-1'],
      runner,
    });

    expect(jobs?.[0].imageUrl).toBe('https://example.com/mock-hat-tryon.jpg');
  });
});
