import { NextResponse } from 'next/server';
import { AccessToken, RoomConfiguration, type AccessTokenOptions, type VideoGrant } from 'livekit-server-sdk';

export const runtime = 'nodejs';

type TokenRequestBody = {
  room_name?: unknown;
  participant_identity?: unknown;
  participant_name?: unknown;
  participant_metadata?: unknown;
  participant_attributes?: unknown;
  room_config?: unknown;
};

type JsonRecord = Record<string, unknown>;

const DEFAULT_ROOM_NAME = 'style-concierge-demo';
const DEFAULT_PARTICIPANT_IDENTITY = 'style-shopper-demo';

async function readJsonBody(request: Request): Promise<TokenRequestBody | null> {
  try {
    return (await request.json()) as TokenRequestBody;
  } catch {
    return {};
  }
}

function getMissingLiveKitEnv() {
  return [
    ['LIVEKIT_URL', process.env.LIVEKIT_URL],
    ['LIVEKIT_API_KEY', process.env.LIVEKIT_API_KEY],
    ['LIVEKIT_API_SECRET', process.env.LIVEKIT_API_SECRET],
  ]
    .filter(([, value]) => !value)
    .map(([key]) => key);
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : fallback;
}

function optionalStringValue(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function attributesValue(value: unknown): Record<string, string> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }

  return Object.fromEntries(
    Object.entries(value as JsonRecord)
      .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
      .map(([key, entryValue]) => [key, entryValue]),
  );
}

function snakeToCamel(value: string): string {
  return value.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

function normalizeRoomConfigJson(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(normalizeRoomConfigJson);
  }

  if (!value || typeof value !== 'object') {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value as JsonRecord).map(([key, entryValue]) => [
      snakeToCamel(key),
      normalizeRoomConfigJson(entryValue),
    ]),
  );
}

function roomConfigurationValue(value: unknown): RoomConfiguration | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return undefined;
  }

  return new RoomConfiguration(normalizeRoomConfigJson(value) as ConstructorParameters<typeof RoomConfiguration>[0]);
}

export async function POST(request: Request) {
  const missing = getMissingLiveKitEnv();

  if (missing.length > 0) {
    return NextResponse.json(
      {
        error: 'LiveKit environment is missing. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET on the server.',
        missing,
      },
      { status: 503 },
    );
  }

  const body = await readJsonBody(request);

  if (!body) {
    return NextResponse.json({ error: 'Expected a JSON request body.' }, { status: 400 });
  }

  const serverUrl = process.env.LIVEKIT_URL!;
  const roomName = stringValue(body.room_name, DEFAULT_ROOM_NAME);
  const participantIdentity = stringValue(body.participant_identity, DEFAULT_PARTICIPANT_IDENTITY);
  const tokenOptions: AccessTokenOptions = {
    identity: participantIdentity,
    name: optionalStringValue(body.participant_name),
    metadata: optionalStringValue(body.participant_metadata),
    attributes: attributesValue(body.participant_attributes),
  };

  const accessToken = new AccessToken(process.env.LIVEKIT_API_KEY!, process.env.LIVEKIT_API_SECRET!, tokenOptions);
  const videoGrant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };

  accessToken.addGrant(videoGrant);

  const roomConfig = roomConfigurationValue(body.room_config);

  if (roomConfig) {
    accessToken.roomConfig = roomConfig;
  }

  const participantToken = await accessToken.toJwt();

  return NextResponse.json(
    {
      server_url: serverUrl,
      participant_token: participantToken,
    },
    { status: 201 },
  );
}
