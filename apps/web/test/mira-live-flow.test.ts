import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  cameraAttributesFromQualities,
  deliveryDetailsMatchSpeech,
  isDeliveryDetailsComplete,
  normalizeRpcCategory,
  normalizeDeliveryDetailsPayload,
  profileChipsFromQualities,
  resolveLomaProductIdsFromPayload,
  resolveLiveDisplayProducts,
  selectedProductsMatchSpeech,
  speechLooksReady,
  voiceStateFromAgentState,
  withTimeoutFallback,
} from '../lib/mira-live-flow';
import { lomaProducts } from '../lib/demo-script';

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

  it('builds profile chips from analyzed qualities instead of canned labels', () => {
    expect(
      profileChipsFromQualities({
        hairColor: 'light blond',
        skinTone: 'fair cool',
        undertone: 'cool',
        contrast: 'low',
        palette: 'summer',
        styleNotes: [],
        summary: 'Cool summer palette.',
      }),
    ).toEqual([
      { label: '', value: 'Summer palette' },
      { label: '', value: 'Cool undertone' },
      { label: '', value: 'Fair Cool skin' },
      { label: '', value: 'Light Blond hair' },
      { label: '', value: 'Low contrast' },
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

  it('recognizes recent speech that explicitly allows a camera capture', () => {
    expect(speechLooksReady("Okay Mira, I'm ready.")).toBe(true);
    expect(speechLooksReady('What are we buying today?')).toBe(false);
  });

  it('matches selected products only when the user says displayed product names', () => {
    const selected = lomaProducts.filter((product) => ['clay', 'camel'].includes(product.id));

    expect(selectedProductsMatchSpeech(selected, 'I like the Clay Pocket Tee and Camel Cord Cap.')).toBe(true);
    expect(selectedProductsMatchSpeech(selected, 'I like two of them.')).toBe(false);
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

  it('matches delivery details against actual spoken content instead of accepting guessed payloads', () => {
    const details = normalizeDeliveryDetailsPayload({
      recipient: 'Sagar',
      address: '1 Main Street',
      city: 'Boston',
      state: 'MA',
      postalCode: '02111',
      phone: '123-456-7890',
    });

    expect(
      deliveryDetailsMatchSpeech(
        details,
        'Sure, send it to Sagar at 1 Main Street, Boston MA 02111. My phone is 123-456-7890.',
      ),
    ).toBe(true);
    expect(deliveryDetailsMatchSpeech(details, 'Yes, checkout sounds good.')).toBe(false);
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
