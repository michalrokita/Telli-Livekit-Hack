export type LiveKitSessionFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type LiveKitReadiness =
  | {
      configured: true;
      serverUrl: string;
      label: 'Voice room available';
      detail: string;
    }
  | {
      configured: false;
      serverUrl: null;
      label: 'Demo fallback';
      detail: string;
    };

export type LiveKitSessionRequest = {
  roomName?: string;
  participantIdentity?: string;
  participantName?: string;
  participantMetadata?: string;
  participantAttributes?: Record<string, string>;
  roomConfig?: unknown;
};

export type LiveKitSessionResult =
  | {
      configured: true;
      serverUrl: string;
      participantToken: string;
    }
  | {
      configured: false;
      missing: string[];
      error: string;
    };

export type LiveKitSessionClientOptions = {
  baseUrl?: string;
  fetch?: LiveKitSessionFetch;
  tokenEndpoint?: string;
};

type LiveKitTokenApiBody = {
  room_name: string;
  participant_identity: string;
  participant_name?: string;
  participant_metadata?: string;
  participant_attributes?: Record<string, string>;
  room_config?: unknown;
};

type LiveKitTokenApiResponse = {
  server_url?: unknown;
  participant_token?: unknown;
  error?: unknown;
  missing?: unknown;
};

const DEFAULT_TOKEN_ENDPOINT = '/api/token';
const DEFAULT_ROOM_NAME = 'style-concierge-demo';
const DEFAULT_PARTICIPANT_IDENTITY = 'style-shopper-demo';

export class LiveKitSessionError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly payload: unknown,
  ) {
    super(message);
    this.name = 'LiveKitSessionError';
  }
}

export function getLiveKitReadiness(publicLiveKitUrl?: string | null): LiveKitReadiness {
  const serverUrl = normalizeString(publicLiveKitUrl);

  if (serverUrl) {
    return {
      configured: true,
      serverUrl,
      label: 'Voice room available',
      detail: 'LiveKit URL is configured; request a room token before connecting.',
    };
  }

  return {
    configured: false,
    serverUrl: null,
    label: 'Demo fallback',
    detail: 'Set NEXT_PUBLIC_LIVEKIT_URL for client voice controls.',
  };
}

export async function requestLiveKitSession(
  input: LiveKitSessionRequest = {},
  options: LiveKitSessionClientOptions = {},
): Promise<LiveKitSessionResult> {
  const fetcher = getFetch(options.fetch);
  const response = await fetcher(resolveEndpoint(options.tokenEndpoint ?? DEFAULT_TOKEN_ENDPOINT, options.baseUrl), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(toTokenApiBody(input)),
  });
  const payload = (await readJson(response)) as LiveKitTokenApiResponse | null;

  if (response.status === 503) {
    return {
      configured: false,
      missing: readStringList(payload?.missing),
      error: readErrorMessage(payload, 'LiveKit environment is missing.'),
    };
  }

  if (!response.ok) {
    throw new LiveKitSessionError(response.status, readErrorMessage(payload, 'LiveKit token request failed.'), payload);
  }

  if (typeof payload?.server_url !== 'string' || typeof payload.participant_token !== 'string') {
    throw new LiveKitSessionError(response.status, 'LiveKit token response was incomplete.', payload);
  }

  return {
    configured: true,
    serverUrl: payload.server_url,
    participantToken: payload.participant_token,
  };
}

function toTokenApiBody(input: LiveKitSessionRequest): LiveKitTokenApiBody {
  return {
    room_name: normalizeString(input.roomName) ?? DEFAULT_ROOM_NAME,
    participant_identity: normalizeString(input.participantIdentity) ?? DEFAULT_PARTICIPANT_IDENTITY,
    participant_name: normalizeString(input.participantName) ?? undefined,
    participant_metadata: normalizeString(input.participantMetadata) ?? undefined,
    participant_attributes: input.participantAttributes,
    room_config: input.roomConfig,
  };
}

function getFetch(fetcher?: LiveKitSessionFetch): LiveKitSessionFetch {
  const resolved = fetcher ?? globalThis.fetch?.bind(globalThis);

  if (!resolved) {
    throw new Error('fetch is required to request a LiveKit session.');
  }

  return resolved;
}

function resolveEndpoint(endpoint: string, baseUrl?: string): string {
  return baseUrl ? new URL(endpoint, baseUrl).toString() : endpoint;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function normalizeString(value: string | null | undefined): string | null {
  if (typeof value !== 'string') {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function readErrorMessage(payload: LiveKitTokenApiResponse | null, fallback: string): string {
  return typeof payload?.error === 'string' && payload.error.trim().length > 0 ? payload.error : fallback;
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}
