import { describe, expect, it, vi } from 'vitest';

import {
  getLiveKitReadiness,
  requestLiveKitSession,
  type LiveKitSessionFetch,
} from '../lib/livekit-session';

describe('livekit session wiring', () => {
  it('detects client-side LiveKit readiness from the public URL only', () => {
    expect(getLiveKitReadiness('wss://demo.livekit.cloud')).toEqual({
      configured: true,
      serverUrl: 'wss://demo.livekit.cloud',
      label: 'Voice room available',
      detail: 'LiveKit URL is configured; request a room token before connecting.',
    });

    expect(getLiveKitReadiness('')).toEqual({
      configured: false,
      serverUrl: null,
      label: 'Demo fallback',
      detail: 'Set NEXT_PUBLIC_LIVEKIT_URL for client voice controls.',
    });
  });

  it('requests a LiveKit token using the existing token API body shape', async () => {
    const fetchMock = vi.fn<LiveKitSessionFetch>(async (url, init) => {
      expect(url).toBe('/api/token');
      expect(JSON.parse(String(init?.body))).toEqual({
        room_name: 'style-concierge-demo',
        participant_identity: 'shopper-123',
        participant_name: 'Mia',
        participant_metadata: 'demo-user',
        participant_attributes: {
          category: 'hats',
        },
        room_config: {
          agents: [{ agentName: 'style-concierge' }],
        },
      });

      return new Response(
        JSON.stringify({
          server_url: 'wss://demo.livekit.cloud',
          participant_token: 'signed-token',
        }),
        {
          status: 201,
          headers: { 'content-type': 'application/json' },
        },
      );
    });

    await expect(
      requestLiveKitSession(
        {
          participantIdentity: 'shopper-123',
          participantName: 'Mia',
          participantMetadata: 'demo-user',
          participantAttributes: {
            category: 'hats',
          },
          roomConfig: {
            agents: [{ agentName: 'style-concierge' }],
          },
        },
        { fetch: fetchMock },
      ),
    ).resolves.toEqual({
      configured: true,
      serverUrl: 'wss://demo.livekit.cloud',
      participantToken: 'signed-token',
    });
  });

  it('maps missing server-side LiveKit env to a fallback result', async () => {
    const fetchMock = vi.fn<LiveKitSessionFetch>(async () => {
      return new Response(
        JSON.stringify({
          error: 'LiveKit environment is missing.',
          missing: ['LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'],
        }),
        {
          status: 503,
          headers: { 'content-type': 'application/json' },
        },
      );
    });

    await expect(requestLiveKitSession({}, { fetch: fetchMock })).resolves.toEqual({
      configured: false,
      missing: ['LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'],
      error: 'LiveKit environment is missing.',
    });
  });
});
