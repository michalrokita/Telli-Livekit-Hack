import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  cameraAttributesFromQualities,
  isDeliveryDetailsComplete,
  normalizeRpcCategory,
  normalizeDeliveryDetailsPayload,
  resolveLomaProductIdsFromPayload,
  resolveLiveDisplayProducts,
  voiceStateFromAgentState,
  withTimeoutFallback,
} from '../lib/mira-live-flow';

describe('Mira live voice flow helpers', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('normalizes voice/RPC categories to the supported shopping categories', () => {
    expect(normalizeRpcCategory({ category: 'tees' })).toBe('tshirts');
    expect(normalizeRpcCategory({ category: 'cap' })).toBe('hats');
    expect(normalizeRpcCategory({ category: 'shoes' })).toBe('tshirts');
  });

  it('builds camera readout attributes from analyzed qualities', () => {
    expect(
      cameraAttributesFromQualities({
        hairColor: 'dark brown',
        skinTone: 'warm olive',
        undertone: 'golden',
        contrast: 'medium',
        styleNotes: [],
        summary: 'Warm olive skin and dark hair.',
      }),
    ).toEqual([
      { label: 'Hair', value: 'dark brown' },
      { label: 'Skin tone', value: 'warm olive' },
      { label: 'Undertone', value: 'golden' },
      { label: 'Contrast', value: 'medium' },
    ]);
  });

  it('uses the five-piece LOMA edit when the live agent asks to show recommendations', () => {
    const products = resolveLiveDisplayProducts({
      category: 'tshirts',
      products: [{ id: 'unknown-agent-product' }],
    });

    expect(products).toHaveLength(5);
    expect(products.map((product) => product.id)).toEqual(['clay', 'bone', 'olive', 'camel', 'char']);
  });

  it('resolves selected try-on ids while falling back to the demo picks', () => {
    const products = resolveLiveDisplayProducts({
      selectedProductIds: ['camel', 'missing'],
    });

    expect(products.map((product) => product.id)).toEqual(['camel']);
  });

  it('resolves selected product names from voice tool payloads', () => {
    expect(
      resolveLomaProductIdsFromPayload({
        selectedProducts: ['Clay Pocket Tee', 'camel cap'],
      }),
    ).toEqual(['clay', 'camel']);
  });

  it('normalizes spoken checkout delivery details from agent payloads', () => {
    const details = normalizeDeliveryDetailsPayload({
      deliveryDetails: {
        fullName: 'Mira Demo',
        streetAddress: '11 Spring Street',
        city: 'New York',
        state: 'NY',
        zip: '10012',
        phoneNumber: '212-555-0198',
      },
    });

    expect(details).toEqual({
      recipient: 'Mira Demo',
      address: '11 Spring Street',
      city: 'New York',
      state: 'NY',
      postalCode: '10012',
      phone: '212-555-0198',
    });
    expect(isDeliveryDetailsComplete(details)).toBe(true);
  });

  it('maps LiveKit assistant states to the visible Mira voice state', () => {
    expect(voiceStateFromAgentState('listening')).toBe('listening');
    expect(voiceStateFromAgentState('idle')).toBe('listening');
    expect(voiceStateFromAgentState('thinking')).toBe('thinking');
    expect(voiceStateFromAgentState('speaking')).toBe('speaking');
    expect(voiceStateFromAgentState('failed')).toBe('idle');
  });

  it('uses a fallback value when browser camera capture does not resolve quickly', async () => {
    vi.useFakeTimers();

    const capture = withTimeoutFallback(
      new Promise<string>(() => {}),
      50,
      () => 'demo-fallback-frame',
    );

    await vi.advanceTimersByTimeAsync(50);

    await expect(capture).resolves.toBe('demo-fallback-frame');
  });
});
