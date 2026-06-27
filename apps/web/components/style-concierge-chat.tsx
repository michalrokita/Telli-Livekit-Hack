'use client';

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  LiveKitRoom,
  RoomAudioRenderer,
  StartAudio,
  useRoomContext,
  useTranscriptions,
  useVoiceAssistant,
} from '@livekit/components-react';
import {
  Check,
  CreditCard,
  Mic,
  Play,
  RefreshCw,
  SendHorizontal,
  ShoppingBag,
  Sparkles,
  X,
} from 'lucide-react';

import {
  createLomaTryOnJobs,
  deliveryDetails,
  formatPrice,
  getSelectedDemoProducts,
  lomaProducts,
  readDemoCustomerQualities,
  voiceStateLabels,
  type LiveKitReadiness,
  type LomaProduct,
  type VoiceState,
} from '@/lib/demo-script';
import { requestLiveKitSession } from '@/lib/livekit-session';
import {
  cameraAttributesFromQualities,
  createEmptyDeliveryDetails,
  isDeliveryDetailsComplete,
  normalizeRpcCategory,
  normalizeDeliveryDetailsPayload,
  parseRpcPayload,
  profileChipsFromQualities,
  resolveLomaProductIdsFromPayload,
  resolveLiveDisplayProducts,
  selectedProductsMatchSpeech,
  speechLooksReady,
  type CheckoutDeliveryDetails,
  voiceStateFromAgentState,
  withTimeoutFallback,
} from '@/lib/mira-live-flow';
import { analyzeShopperImage, generateShopperTryOns } from '@/lib/design-adapter';
import type { CustomerQualities, ProductRecommendation } from '@/lib/shopper-flow';

type StyleConciergeChatProps = {
  cartCount: number;
  chatOpen: boolean;
  liveKitReadiness: LiveKitReadiness;
  onAddToCart: (products: LomaProduct[], isTryOn?: boolean) => void;
  onClose: () => void;
  onOpen: () => void;
};

type TextMessage = {
  id: string;
  kind: 'text';
  role: 'agent' | 'user';
  text: string;
};

type CameraAttribute = {
  label: string;
  value: string;
  on?: boolean;
};

type CameraMessage = {
  id: string;
  kind: 'camera';
  status: 'preview' | 'captured' | 'analyzing';
  attrs: CameraAttribute[];
  countdown?: number;
  showAttrs?: boolean;
  prompt?: string;
  actionLabel?: string;
  actionBusy?: boolean;
  filter?: 'none' | 'bright' | 'warm';
  photoDataUrl?: string;
  error?: string;
};

type ProfileMessage = {
  id: string;
  kind: 'profile';
  chips: Array<{ label: string; value: string }>;
};

type RecommendationCard = LomaProduct & {
  selected: boolean;
  why: string;
};

type RecommendationsMessage = {
  id: string;
  kind: 'recs';
  cards: RecommendationCard[];
};

type TryOnCard = LomaProduct & {
  status: 'gen' | 'done';
  genLabel: string;
  added?: boolean;
  renderedImageUrl?: string;
};

type TryOnMessage = {
  id: string;
  kind: 'tryon';
  title?: string;
  subtitle?: string;
  items: TryOnCard[];
};

type CheckoutMessage = {
  id: string;
  kind: 'checkout';
  delivery: CheckoutDeliveryDetails;
  deliveryComplete: boolean;
  items: LomaProduct[];
};

type SuccessMessage = {
  id: string;
  kind: 'success';
};

type MiraMessage =
  | TextMessage
  | CameraMessage
  | ProfileMessage
  | RecommendationsMessage
  | TryOnMessage
  | CheckoutMessage
  | SuccessMessage;

type MiraMessageInput =
  | Omit<TextMessage, 'id'>
  | Omit<CameraMessage, 'id'>
  | Omit<ProfileMessage, 'id'>
  | Omit<RecommendationsMessage, 'id'>
  | Omit<TryOnMessage, 'id'>
  | Omit<CheckoutMessage, 'id'>
  | Omit<SuccessMessage, 'id'>;

type VoiceBridgeStatus = {
  state: 'idle' | 'requesting' | 'ready' | 'connected' | 'fallback' | 'error';
  detail: string;
  session?: {
    serverUrl: string;
    participantToken: string;
  };
};

type RecentSpeech = {
  text: string;
  receivedAt: number;
};

type PendingCapture = {
  category: 'hats' | 'tshirts';
  captureStarted: boolean;
  generation: number;
  messageId: string;
  result: Promise<string>;
  resolve: (value: string) => void;
  reject: (reason?: unknown) => void;
};

type CameraController = {
  capture: () => DemoCaptureResult;
};

type MiraRpcHandlers = {
  prepareCustomerCamera: (payload: unknown) => Promise<string>;
  captureCustomerImage: (payload: unknown) => Promise<string>;
  showProductRecommendations: (payload: unknown) => Promise<string>;
  generateTryOns: (payload: unknown) => Promise<string>;
  addToCart: (payload: unknown) => Promise<string>;
  fillCheckoutDelivery: (payload: unknown) => Promise<string>;
};

const voiceColors: Record<VoiceState, string> = {
  idle: '#9A8C7C',
  connecting: '#B0917C',
  listening: '#5E8C6E',
  thinking: '#C19A45',
  speaking: '#C16A45',
};

const CAMERA_PREVIEW_READY_TIMEOUT_MS = 1600;
const READY_SPEECH_WINDOW_MS = 9_000;
const SELECTION_SPEECH_WINDOW_MS = 30_000;
const DELIVERY_SPEECH_WINDOW_MS = 45_000;

export function StyleConciergeChat({
  cartCount,
  chatOpen,
  liveKitReadiness,
  onAddToCart,
  onClose,
  onOpen,
}: StyleConciergeChatProps) {
  const [demoStarted, setDemoStarted] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [voiceBridge, setVoiceBridge] = useState<VoiceBridgeStatus>({
    state: 'idle',
    detail: 'Voice room will start when Mira opens.',
  });
  const [messages, setMessages] = useState<MiraMessage[]>([]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const orbRef = useRef<HTMLCanvasElement | null>(null);
  const voiceStateRef = useRef<VoiceState>('idle');
  const timersRef = useRef<number[]>([]);
  const runningRef = useRef(false);
  const runIdRef = useRef(0);
  const ampRef = useRef(0.16);
  const pendingCaptureRef = useRef<PendingCapture | null>(null);
  const activeCameraMessageIdRef = useRef<string | null>(null);
  const cameraControllersRef = useRef<Map<string, CameraController>>(new Map());
  const cameraReadyWaitersRef = useRef<Map<string, (status: string) => void>>(new Map());
  const captureGenerationRef = useRef(0);
  const recentUserSpeechRef = useRef<RecentSpeech[]>([]);
  const liveRecommendationsIdRef = useRef<string | null>(null);
  const liveTryOnIdRef = useRef<string | null>(null);
  const liveCheckoutIdRef = useRef<string | null>(null);
  const lastCustomerImageRef = useRef<{ imageRef: string; imageDataUrl: string } | null>(null);

  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);

  const noteUserSpeech = useCallback((text: string) => {
    const trimmed = text.trim();

    if (trimmed.length < 2) {
      return;
    }

    const now = Date.now();
    const previous = recentUserSpeechRef.current.at(-1);
    if (previous?.text === trimmed) {
      recentUserSpeechRef.current = [
        ...recentUserSpeechRef.current.slice(0, -1),
        { text: trimmed, receivedAt: now },
      ];
      return;
    }

    recentUserSpeechRef.current = [
      ...recentUserSpeechRef.current.filter((entry) => now - entry.receivedAt < 60_000),
      { text: trimmed, receivedAt: now },
    ].slice(-24);
  }, []);

  const getRecentUserSpeech = useCallback((windowMs: number) => {
    const now = Date.now();
    return recentUserSpeechRef.current
      .filter((entry) => now - entry.receivedAt <= windowMs)
      .map((entry) => entry.text)
      .join(' ');
  }, []);

  const clearDemoTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];
  }, []);

  const stopDemo = useCallback(() => {
    runningRef.current = false;
    runIdRef.current += 1;
    pendingCaptureRef.current?.reject(new Error('Mira chat was closed before capture finished.'));
    pendingCaptureRef.current = null;
    captureGenerationRef.current += 1;
    cameraReadyWaitersRef.current.forEach((resolve) => resolve('cancelled'));
    cameraReadyWaitersRef.current.clear();
    liveCheckoutIdRef.current = null;
    lastCustomerImageRef.current = null;
    recentUserSpeechRef.current = [];
    clearDemoTimers();
  }, [clearDemoTimers]);

  useEffect(() => {
    return () => {
      stopDemo();
    };
  }, [stopDemo]);

  useEffect(() => {
    const el = scrollRef.current;

    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (!chatOpen || !liveKitReadiness.configured) {
      return;
    }

    stopDemo();
    setDemoStarted(true);
    setMessages([]);
    setVoiceState('connecting');
    activeCameraMessageIdRef.current = null;
    cameraControllersRef.current.clear();
    cameraReadyWaitersRef.current.clear();
    captureGenerationRef.current += 1;
    liveRecommendationsIdRef.current = null;
    liveTryOnIdRef.current = null;
    liveCheckoutIdRef.current = null;
  }, [chatOpen, liveKitReadiness.configured, stopDemo]);

  useEffect(() => {
    if (!chatOpen) {
      return;
    }

    if (!liveKitReadiness.configured) {
      setVoiceBridge({
        state: 'fallback',
        detail: 'Mock voice is active. Add LiveKit env to connect the real agent.',
      });
      return;
    }

    let cancelled = false;
    const agentName = process.env.NEXT_PUBLIC_LIVEKIT_AGENT_NAME ?? 'style-concierge';
    const stamp = Date.now().toString(36);

    setVoiceBridge({
      state: 'requesting',
      detail: 'Requesting a short-lived LiveKit room token...',
    });

    requestLiveKitSession({
      roomName: `loma-mira-${stamp}`,
      participantIdentity: `shopper-${stamp}`,
      participantName: 'LOMA shopper',
      participantMetadata: JSON.stringify({ source: 'loma-demo', category: 'tshirts' }),
      participantAttributes: {
        category: 'tshirts',
        demo: 'loma-mira',
      },
      roomConfig: {
        agents: [{ agentName }],
      },
    })
      .then((result) => {
        if (cancelled) {
          return;
        }

        if (result.configured) {
          setVoiceBridge({
            state: 'ready',
            detail: 'Token ready. Connecting browser audio to Mira...',
            session: {
              serverUrl: result.serverUrl,
              participantToken: result.participantToken,
            },
          });
          return;
        }

        setVoiceBridge({
          state: 'fallback',
          detail: `${result.error} Missing: ${result.missing.join(', ') || 'server env'}.`,
        });
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }

        setVoiceBridge({
          state: 'error',
          detail: error instanceof Error ? error.message : 'LiveKit voice room failed to start.',
        });
      });

    return () => {
      cancelled = true;
    };
  }, [chatOpen, liveKitReadiness.configured]);

  useEffect(() => {
    if (!chatOpen) {
      return;
    }

    let animationFrame = 0;

    const drawOrb = () => {
      const canvas = orbRef.current;

      if (canvas) {
        const ctx = canvas.getContext('2d');
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;

        if (ctx && width > 0 && height > 0) {
          const dpr = window.devicePixelRatio || 1;
          const nextWidth = Math.round(width * dpr);
          const nextHeight = Math.round(height * dpr);

          if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
            canvas.width = nextWidth;
            canvas.height = nextHeight;
          }

          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, width, height);

          const t = performance.now() / 1000;
          const state = voiceStateRef.current;
          let target = 0.16 + Math.sin(t * 1.5) * 0.04;

          if (state === 'listening') {
            target =
              0.34 + Math.abs(Math.sin(t * 5)) * 0.42 * (0.6 + 0.4 * Math.sin(t * 12.7));
          } else if (state === 'speaking') {
            target = 0.3 + Math.abs(Math.sin(t * 7.3)) * 0.45;
          } else if (state === 'thinking') {
            target = 0.24 + Math.sin(t * 2.4) * 0.05;
          } else if (state === 'connecting') {
            target = 0.15 + Math.sin(t * 2) * 0.03;
          }

          ampRef.current += (target - ampRef.current) * 0.16;

          const amp = ampRef.current;
          const cx = width / 2;
          const cy = height / 2;
          const base = Math.min(width, height) * 0.21;
          const glow = ctx.createRadialGradient(cx, cy, base * 0.3, cx, cy, base * 2.6);

          glow.addColorStop(0, `rgba(224,160,126,${0.3 + amp * 0.4})`);
          glow.addColorStop(1, 'rgba(224,160,126,0)');
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(cx, cy, base * 2.6, 0, Math.PI * 2);
          ctx.fill();

          for (let i = 0; i < 52; i += 1) {
            const angle = (i / 52) * Math.PI * 2;
            const length =
              state === 'thinking'
                ? base * 0.5 * (0.45 + 0.55 * Math.max(0, Math.sin(t * 3 - i * 0.5)))
                : base *
                  0.6 *
                  (0.35 + amp * 1.25) *
                  (0.55 + 0.45 * Math.sin(t * 4 + i * 0.55));
            const r0 = base * 1.05;
            const r1 = r0 + Math.max(1.5, length);

            ctx.strokeStyle = `rgba(193,106,69,${0.45 + amp * 0.4})`;
            ctx.lineWidth = 2.2;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(angle) * r0, cy + Math.sin(angle) * r0);
            ctx.lineTo(cx + Math.cos(angle) * r1, cy + Math.sin(angle) * r1);
            ctx.stroke();
          }

          const core = ctx.createRadialGradient(
            cx - base * 0.32,
            cy - base * 0.32,
            base * 0.1,
            cx,
            cy,
            base,
          );
          core.addColorStop(0, '#F2C8AC');
          core.addColorStop(0.5, '#D98B63');
          core.addColorStop(1, '#B85F3C');

          ctx.fillStyle = core;
          ctx.beginPath();
          ctx.arc(cx, cy, base * (0.92 + amp * 0.12), 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = 'rgba(255,255,255,0.28)';
          ctx.beginPath();
          ctx.ellipse(
            cx - base * 0.26,
            cy - base * 0.3,
            base * 0.36,
            base * 0.22,
            -0.6,
            0,
            Math.PI * 2,
          );
          ctx.fill();
        }
      }

      animationFrame = window.requestAnimationFrame(drawOrb);
    };

    drawOrb();

    return () => {
      window.cancelAnimationFrame(animationFrame);
    };
  }, [chatOpen]);

  const sleep = useCallback((ms: number) => {
    return new Promise<void>((resolve) => {
      const timer = window.setTimeout(() => {
        timersRef.current = timersRef.current.filter((item) => item !== timer);
        resolve();
      }, ms);
      timersRef.current.push(timer);
    });
  }, []);

  function addMsg(message: MiraMessageInput) {
    const id = `m-${Math.random().toString(36).slice(2)}`;
    setMessages((current) => [...current, { id, ...message } as MiraMessage]);
    return id;
  }

  function patchMsg(id: string, patcher: (message: MiraMessage) => MiraMessage) {
    setMessages((current) =>
      current.map((message) => (message.id === id ? patcher(message) : message)),
    );
  }

  function addTimedVoiceReset(ms: number) {
    const timer = window.setTimeout(() => setVoiceState('idle'), ms);
    timersRef.current.push(timer);
  }

  async function revealCameraAnalysis(messageId: string, qualities: CustomerQualities) {
    const attrs = cameraAttributesFromQualities(qualities);

    setVoiceState('thinking');
    patchMsg(messageId, (message) =>
      message.kind === 'camera'
        ? {
            ...message,
            status: 'analyzing',
            attrs,
            showAttrs: true,
            actionLabel: undefined,
            actionBusy: false,
          }
        : message,
    );

    for (const index of attrs.keys()) {
      await sleep(200);

      patchMsg(messageId, (message) => {
        if (message.kind !== 'camera') {
          return message;
        }

        return {
          ...message,
          attrs: message.attrs.map((attr, attrIndex) =>
            attrIndex === index ? { ...attr, on: true } : attr,
          ),
        };
      });
    }

    await sleep(150);
    setVoiceState('speaking');
    addMsg({
      kind: 'profile',
      chips: profileChipsFromQualities(qualities),
    });
  }

  function isCurrentCapture(pending: PendingCapture) {
    return (
      pendingCaptureRef.current === pending &&
      captureGenerationRef.current === pending.generation
    );
  }

  function claimPendingCapture(messageId: string) {
    const pending = pendingCaptureRef.current;

    if (!pending || pending.messageId !== messageId) {
      return null;
    }

    if (pending.captureStarted) {
      return null;
    }
    pending.captureStarted = true;

    return pending;
  }

  function setCameraController(messageId: string, controller: CameraController | null) {
    if (controller) {
      cameraControllersRef.current.set(messageId, controller);
      cameraReadyWaitersRef.current.get(messageId)?.('controller-ready');
      cameraReadyWaitersRef.current.delete(messageId);
      return;
    }

    cameraControllersRef.current.delete(messageId);
  }

  function captureActiveCameraFrame(messageId: string): DemoCaptureResult {
    const controller = cameraControllersRef.current.get(messageId);

    if (controller) {
      return controller.capture();
    }

    return {
      imageDataUrl: createFallbackSelfieDataUrl(),
      source: 'fallback',
      error: 'Camera preview was not ready, so Mira used a demo frame.',
    };
  }

  async function finishCameraCapture(
    messageId: string,
    pending: PendingCapture,
    capture: DemoCaptureResult,
  ) {
    if (!isCurrentCapture(pending)) {
      return;
    }

    patchMsg(messageId, (message) =>
      message.kind === 'camera'
        ? {
            ...message,
            status: 'captured',
            photoDataUrl: capture.imageDataUrl,
            countdown: undefined,
            filter: capture.source === 'camera' ? 'bright' : 'none',
            prompt:
              capture.source === 'camera'
                ? "Photo captured. If you don't like it, tell Mira to retake it."
                : "Demo capture ready. If you don't like it, tell Mira to retake it.",
            actionLabel: undefined,
            actionBusy: false,
            error: capture.error,
          }
        : message,
    );

    await sleep(520);

    if (!isCurrentCapture(pending)) {
      return;
    }

    let qualities: CustomerQualities;
    let styleProfile: unknown = null;
    try {
      const analyzed = await analyzeShopperImage({
        imageDataUrl: capture.imageDataUrl,
        category: pending.category,
      });
      qualities = analyzed.analysis;
      styleProfile = analyzed.profile;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Image analysis failed.';
      patchMsg(messageId, (currentMessage) =>
        currentMessage.kind === 'camera'
          ? {
              ...currentMessage,
              status: 'captured',
              prompt: 'Image analysis failed. Tell Mira to retake the photo and try again.',
              error: message,
              actionBusy: false,
            }
          : currentMessage,
      );
      pending.reject(new Error(message));
      pendingCaptureRef.current = null;
      activeCameraMessageIdRef.current = messageId;
      setVoiceState('listening');
      return;
    }

    if (!isCurrentCapture(pending)) {
      return;
    }

    const imageRef = `browser-camera-${Date.now().toString(36)}`;
    lastCustomerImageRef.current = {
      imageRef,
      imageDataUrl: capture.imageDataUrl,
    };

    // Resolve the RPC the instant the analysis is ready so Mira speaks in sync with the
    // qualities appearing — the reveal animation plays after, without blocking her turn.
    pending.resolve(
      JSON.stringify({
        status: 'complete',
        imageRef,
        captureSource: capture.source,
        category: pending.category,
        qualities,
        styleProfile,
      }),
    );
    pendingCaptureRef.current = null;
    activeCameraMessageIdRef.current = null;

    void revealCameraAnalysis(messageId, qualities);
  }

  async function runVoiceCaptureCountdown(messageId: string) {
    const pending = claimPendingCapture(messageId);

    if (!pending) {
      return;
    }

    setVoiceState('thinking');

    for (const count of [3, 2, 1]) {
      if (!isCurrentCapture(pending)) {
        return;
      }

      patchMsg(messageId, (message) =>
        message.kind === 'camera'
          ? {
              ...message,
              countdown: count,
              prompt: `Taking it in ${count}...`,
            }
          : message,
      );
      await sleep(650);
    }

    if (!isCurrentCapture(pending)) {
      return;
    }

    patchMsg(messageId, (message) =>
      message.kind === 'camera'
        ? {
            ...message,
            countdown: undefined,
            prompt: 'Snapping now...',
          }
        : message,
    );

    const capture = captureActiveCameraFrame(messageId);
    await finishCameraCapture(messageId, pending, capture);
  }

  async function prepareCustomerCameraRpc(payload: unknown) {
    if (pendingCaptureRef.current) {
      pendingCaptureRef.current.reject(new Error('Camera capture was reset before finishing.'));
      pendingCaptureRef.current = null;
    }

    captureGenerationRef.current += 1;
    const category = normalizeRpcCategory(payload);
    const placeholder: CustomerQualities = {
      hairColor: 'Waiting...',
      skinTone: 'Waiting...',
      undertone: 'Waiting...',
      contrast: 'medium',
      styleNotes: [],
      summary: '',
    };

    setDemoStarted(true);
    setVoiceState('listening');

    const existingMessageId = activeCameraMessageIdRef.current;
    const messageInput = {
      kind: 'camera' as const,
      status: 'preview' as const,
      attrs: cameraAttributesFromQualities(placeholder),
      countdown: undefined,
      showAttrs: false,
      prompt: "Camera is open. Tell Mira \"I'm ready\" when you want the photo.",
      actionLabel: undefined,
      actionBusy: false,
      filter: 'none' as const,
      photoDataUrl: undefined,
      error: undefined,
    };
    const messageId = existingMessageId ?? addMsg(messageInput);

    if (existingMessageId) {
      patchMsg(existingMessageId, (message) =>
        message.kind === 'camera' ? { ...message, ...messageInput } : message,
      );
    }

    activeCameraMessageIdRef.current = messageId;
    const readiness = cameraControllersRef.current.has(messageId)
      ? 'controller-ready'
      : await withTimeoutFallback(
          new Promise<string>((resolve) => {
            cameraReadyWaitersRef.current.set(messageId, resolve);
          }),
          CAMERA_PREVIEW_READY_TIMEOUT_MS,
          () => 'preview-timeout',
        );
    cameraReadyWaitersRef.current.delete(messageId);

    return JSON.stringify({
      status: 'ready',
      readiness,
      cameraSessionId: messageId,
      category,
    });
  }

  async function captureCustomerImageRpc(payload: unknown) {
    if (pendingCaptureRef.current) {
      return pendingCaptureRef.current.result;
    }

    const category = normalizeRpcCategory(payload);
    let messageId = activeCameraMessageIdRef.current;
    const readySpeech = getRecentUserSpeech(READY_SPEECH_WINDOW_MS);

    if (!speechLooksReady(readySpeech)) {
      if (messageId) {
        patchMsg(messageId, (message) =>
          message.kind === 'camera'
            ? {
                ...message,
                prompt: 'Camera is open. Tell Mira "I\'m ready" when you want the photo.',
                actionBusy: false,
              }
            : message,
        );
      }

      throw new Error('Mira is waiting for the shopper to say they are ready before taking the photo.');
    }

    if (!messageId) {
      const prepared = parseRpcPayload(await prepareCustomerCameraRpc(payload));
      messageId =
        typeof prepared === 'object' && prepared
          ? String((prepared as { cameraSessionId?: unknown }).cameraSessionId ?? '')
          : '';
    }

    if (!messageId) {
      throw new Error('Unable to prepare camera capture.');
    }

    let resolveCapture: PendingCapture['resolve'] | undefined;
    let rejectCapture: PendingCapture['reject'] | undefined;
    const result = new Promise<string>((resolve, reject) => {
      resolveCapture = resolve;
      rejectCapture = reject;
    });

    if (!resolveCapture || !rejectCapture) {
      throw new Error('Unable to initialize camera capture.');
    }

    pendingCaptureRef.current = {
      category,
      captureStarted: false,
      generation: captureGenerationRef.current,
      messageId,
      result,
      resolve: resolveCapture,
      reject: rejectCapture,
    };

    const captureTimer = window.setTimeout(() => {
      timersRef.current = timersRef.current.filter((item) => item !== captureTimer);
      void runVoiceCaptureCountdown(messageId);
    }, 150);
    timersRef.current.push(captureTimer);

    return result;
  }

  function handleCameraRetake(messageId: string) {
    if (pendingCaptureRef.current) {
      pendingCaptureRef.current.reject(new Error('Camera capture was retaken before analysis finished.'));
      pendingCaptureRef.current = null;
    }
    captureGenerationRef.current += 1;
    activeCameraMessageIdRef.current = messageId;
    patchMsg(messageId, (message) =>
      message.kind === 'camera'
        ? {
            ...message,
            status: 'preview',
            countdown: undefined,
            photoDataUrl: undefined,
            showAttrs: false,
            prompt: "No problem. Tell Mira \"I'm ready\" when you want the next photo.",
            actionLabel: undefined,
            actionBusy: false,
            error: undefined,
          }
        : message,
    );
    setVoiceState('listening');
  }

  function handleCameraFilter(messageId: string, filter: CameraMessage['filter']) {
    patchMsg(messageId, (message) =>
      message.kind === 'camera' ? { ...message, filter } : message,
    );
  }

  async function showProductRecommendationsRpc(payload: unknown) {
    const products = resolveLiveDisplayProducts(readProductPayload(payload));
    const recsId = addMsg({
      kind: 'recs',
      cards: products.map((product) => ({
        ...product,
        why: product.recommendationReason,
        selected: false,
      })),
    });

    liveRecommendationsIdRef.current = recsId;
    setDemoStarted(true);
    setVoiceState('speaking');
    addTimedVoiceReset(1000);

    return JSON.stringify({
      status: 'shown',
      displayedProductIds: products.map((product) => product.id),
    });
  }

  async function generateTryOnsRpc(payload: unknown) {
    const selectedProductIds = readProductIds(payload);

    if (selectedProductIds.length === 0) {
      throw new Error('Ask the shopper to say the product names they want to preview.');
    }

    const selectedProducts = resolveLiveDisplayProducts({ selectedProductIds });
    const selectionSpeech = getRecentUserSpeech(SELECTION_SPEECH_WINDOW_MS);
    const recsId = liveRecommendationsIdRef.current;

    if (!selectedProductsMatchSpeech(selectedProducts, selectionSpeech)) {
      throw new Error('Ask the shopper to say the product names they want to preview.');
    }

    if (recsId) {
      patchMsg(recsId, (message) => {
        if (message.kind !== 'recs') {
          return message;
        }

        return {
          ...message,
          cards: message.cards.map((card) => ({
            ...card,
            selected: selectedProducts.some((product) => product.id === card.id),
          })),
        };
      });
    }

    setVoiceState('thinking');
    const tryOnId = addMsg({
      kind: 'tryon',
      title: 'Rendering your try-ons',
      subtitle: selectedProducts.map((product) => product.name).join(' + '),
      items: selectedProducts.map((product) => ({
        ...product,
        status: 'gen' as const,
        genLabel: `Rendering ${product.name}`,
      })),
    });
    liveTryOnIdRef.current = tryOnId;

    const customerImage = lastCustomerImageRef.current;
    let tryOnJobs;
    try {
      tryOnJobs = await generateShopperTryOns({
        customerImageId: customerImage?.imageRef ?? 'loma-live-shopper',
        customerImageDataUrl: customerImage?.imageDataUrl,
        products: selectedProducts.map(toProductRecommendation),
        selectedProductIds: selectedProducts.map((product) => product.id),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Try-on generation failed.';
      patchMsg(tryOnId, (currentMessage) =>
        currentMessage.kind === 'tryon'
          ? {
              ...currentMessage,
              title: 'Try-on generation needs a retry',
              subtitle: message,
              items: currentMessage.items.map((item) => ({
                ...item,
                status: 'done' as const,
              })),
            }
          : currentMessage,
      );
      setVoiceState('listening');
      throw new Error(message);
    }
    const jobsByProductId = new Map(tryOnJobs.map((job) => [job.productId, job]));

    for (const [index, product] of selectedProducts.entries()) {
      await sleep(index === 0 ? 1500 : 1050);
      patchMsg(tryOnId, (message) => {
        if (message.kind !== 'tryon') {
          return message;
        }

        const remaining = Math.max(0, selectedProducts.length - index - 1);

        return {
          ...message,
          title: remaining > 0 ? 'Rendering your try-ons' : 'Your try-ons are ready',
          subtitle:
            remaining > 0
              ? `${remaining} preview${remaining === 1 ? '' : 's'} still polishing`
              : 'Tell Mira which product names you want to add.',
          items: message.items.map((item) =>
            item.id === product.id
              ? {
                  ...item,
                  status: 'done' as const,
                  renderedImageUrl: jobsByProductId.get(item.id)?.imageUrl ?? item.tryOnImageUrl,
                }
              : item,
          ),
        };
      });
    }

    patchMsg(tryOnId, (message) => {
      if (message.kind !== 'tryon') {
        return message;
      }

      return {
        ...message,
        title: 'Your try-ons are ready',
        subtitle: 'Tell Mira which product names you want to add.',
        items: message.items.map((item) => ({
          ...item,
          status: 'done' as const,
          renderedImageUrl: jobsByProductId.get(item.id)?.imageUrl ?? item.tryOnImageUrl,
        })),
      };
    });

    setVoiceState('speaking');
    addTimedVoiceReset(1200);

    return JSON.stringify({
      status: 'complete',
      imageCount: tryOnJobs.length,
      selectedProducts: selectedProducts.map((product) => ({ id: product.id, name: product.name })),
    });
  }

  function addCheckoutMessage(items: LomaProduct[]) {
    const checkoutId = addMsg({
      kind: 'checkout',
      items,
      delivery: createEmptyDeliveryDetails(),
      deliveryComplete: false,
    });
    liveCheckoutIdRef.current = checkoutId;
    return checkoutId;
  }

  async function addToCartRpc(payload: unknown) {
    const productIds = readProductIds(payload);

    if (productIds.length === 0) {
      throw new Error('Ask the shopper to say the product names they want to add to cart.');
    }

    const selectedProducts = resolveLiveDisplayProducts({ selectedProductIds: productIds });
    const selectionSpeech = getRecentUserSpeech(SELECTION_SPEECH_WINDOW_MS);

    if (!selectedProductsMatchSpeech(selectedProducts, selectionSpeech)) {
      throw new Error('Ask the shopper to say the product names they want to add to cart.');
    }

    onAddToCart(selectedProducts, true);

    const tryOnId = liveTryOnIdRef.current;
    if (tryOnId) {
      patchMsg(tryOnId, (message) => {
        if (message.kind !== 'tryon') {
          return message;
        }

        return {
          ...message,
          items: message.items.map((item) => ({
            ...item,
            added: selectedProducts.some((product) => product.id === item.id),
          })),
        };
      });
    }

    addCheckoutMessage(selectedProducts);
    setVoiceState('speaking');
    addTimedVoiceReset(1000);

    return JSON.stringify({
      status: 'added',
      addedProductIds: selectedProducts.map((product) => product.id),
      itemCount: cartCount + selectedProducts.length,
      checkout: {
        deliveryStatus: 'waiting_for_details',
      },
    });
  }

  async function fillCheckoutDeliveryRpc(payload: unknown) {
    const delivery = normalizeDeliveryDetailsPayload(payload);
    const deliveryComplete = isDeliveryDetailsComplete(delivery);
    let checkoutId = liveCheckoutIdRef.current;

    if (!checkoutId) {
      checkoutId = addCheckoutMessage(getSelectedDemoProducts());
    }

    // Trust the spoken details and fill what we have (partial is fine — Mira asks for the
    // rest). The old transcript-match guardrail rejected almost every real fill because STT
    // renders postal/phone digits as words and details arrive across multiple turns.
    patchMsg(checkoutId, (message) =>
      message.kind === 'checkout'
        ? {
            ...message,
            delivery,
            deliveryComplete,
          }
        : message,
    );

    setVoiceState('speaking');
    addTimedVoiceReset(1000);

    return JSON.stringify({
      status: deliveryComplete ? 'filled' : 'partial',
      deliveryComplete,
    });
  }

  const playDemo = useCallback(async () => {
    stopDemo();

    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    runningRef.current = true;

    const stillRunning = () => runningRef.current && runIdRef.current === runId;
    const selectedProducts = getSelectedDemoProducts();

    setDemoStarted(true);
    setMessages([]);
    setVoiceState('connecting');

    await sleep(650);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addMsg({
      kind: 'text',
      role: 'agent',
      text: "Hi! I'm Mira, your LOMA stylist. What are we shopping for today?",
    });

    await sleep(1800);
    if (!stillRunning()) return;

    setVoiceState('listening');
    await sleep(850);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'user',
      text: 'Something easy for summer - a tee and a hat.',
    });

    await sleep(1000);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addMsg({
      kind: 'text',
      role: 'agent',
      text: 'Love that. Mind if I take a quick look? Smile for the camera.',
    });

    await sleep(1450);
    if (!stillRunning()) return;

    const qualities = await readDemoCustomerQualities();
    if (!stillRunning()) return;

    const cameraId = addMsg({
      kind: 'camera',
      status: 'preview',
      attrs: [
        { label: 'Hair', value: 'Deep brown' },
        { label: 'Skin tone', value: qualities.skinTone },
        { label: 'Undertone', value: 'Warm / golden' },
        { label: 'Contrast', value: 'Soft' },
      ],
    });
    setVoiceState('idle');

    await sleep(1850);
    if (!stillRunning()) return;

    patchMsg(cameraId, (message) =>
      message.kind === 'camera' ? { ...message, status: 'captured' } : message,
    );

    await sleep(850);
    if (!stillRunning()) return;

    setVoiceState('thinking');
    patchMsg(cameraId, (message) =>
      message.kind === 'camera'
        ? { ...message, status: 'analyzing', showAttrs: true }
        : message,
    );

    for (const index of [0, 1, 2, 3]) {
      await sleep(610);
      if (!stillRunning()) return;

      patchMsg(cameraId, (message) => {
        if (message.kind !== 'camera') {
          return message;
        }

        return {
          ...message,
          attrs: message.attrs.map((attr, attrIndex) =>
            attrIndex === index ? { ...attr, on: true } : attr,
          ),
        };
      });
    }

    await sleep(650);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addMsg({
      kind: 'text',
      role: 'agent',
      text: 'Gorgeous - warm golden undertones and soft contrast. Earthy, muted tones are going to love you.',
    });

    await sleep(1900);
    if (!stillRunning()) return;

    addMsg({
      kind: 'profile',
      chips: [
        { label: '', value: 'Warm undertone' },
        { label: '', value: 'Olive skin' },
        { label: '', value: 'Deep brown hair' },
        { label: '', value: 'Soft contrast' },
        { label: '', value: 'Relaxed fit' },
      ],
    });

    await sleep(1300);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'agent',
      text: "Here are five picks I'd put you in:",
    });

    await sleep(950);
    if (!stillRunning()) return;

    const recsId = addMsg({
      kind: 'recs',
      cards: lomaProducts.map((product) => ({
        ...product,
        why: product.recommendationReason,
        selected: false,
      })),
    });

    await sleep(1800);
    if (!stillRunning()) return;

    setVoiceState('listening');
    await sleep(700);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'user',
      text: 'Ooh - the clay tee and the camel cap.',
    });

    await sleep(850);
    if (!stillRunning()) return;

    patchMsg(recsId, (message) => {
      if (message.kind !== 'recs') {
        return message;
      }

      return {
        ...message,
        cards: message.cards.map((card) => ({
          ...card,
          selected: selectedProducts.some((product) => product.id === card.id),
        })),
      };
    });

    await sleep(850);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addMsg({
      kind: 'text',
      role: 'agent',
      text: 'Amazing taste. Let me show you wearing them - one sec.',
    });

    await sleep(1200);
    if (!stillRunning()) return;

    setVoiceState('thinking');
    const tryOnId = addMsg({
      kind: 'tryon',
      title: 'Rendering your try-ons',
      subtitle: selectedProducts.map((product) => product.name).join(' + '),
      items: selectedProducts.map((product) => ({
        ...product,
        status: 'gen' as const,
        genLabel: `Rendering ${product.name}`,
      })),
    });

    const tryOnJobs = await createLomaTryOnJobs(selectedProducts);
    const jobsByProductId = new Map(tryOnJobs.map((job) => [job.productId, job]));

    for (const [index, product] of selectedProducts.entries()) {
      await sleep(index === 0 ? 2200 : 1100);
      if (!stillRunning()) return;

      patchMsg(tryOnId, (message) => {
        if (message.kind !== 'tryon') {
          return message;
        }

        const remaining = Math.max(0, selectedProducts.length - index - 1);

        return {
          ...message,
          title: remaining > 0 ? 'Rendering your try-ons' : 'Your try-ons are ready',
          subtitle:
            remaining > 0
              ? `${remaining} preview${remaining === 1 ? '' : 's'} still polishing`
              : 'Tell Mira which product names you want to add.',
          items: message.items.map((item) =>
            item.id === product.id
              ? {
                  ...item,
                  status: 'done' as const,
                  renderedImageUrl: jobsByProductId.get(item.id)?.imageUrl ?? item.tryOnImageUrl,
                }
              : item,
          ),
        };
      });
    }

    patchMsg(tryOnId, (message) => {
      if (message.kind !== 'tryon') {
        return message;
      }

      return {
        ...message,
        title: 'Your try-ons are ready',
        subtitle: 'Tell Mira which product names you want to add.',
        items: message.items.map((item) => ({
          ...item,
          status: 'done' as const,
          renderedImageUrl: jobsByProductId.get(item.id)?.imageUrl ?? item.tryOnImageUrl,
        })),
      };
    });

    setVoiceState('speaking');
    await sleep(500);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'agent',
      text: 'That clay-and-camel combo is so you. Want me to bag them?',
    });

    await sleep(1700);
    if (!stillRunning()) return;

    setVoiceState('listening');
    await sleep(650);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'user',
      text: 'Yes - add both.',
    });

    await sleep(650);
    if (!stillRunning()) return;

    onAddToCart(selectedProducts, true);

    patchMsg(tryOnId, (message) => {
      if (message.kind !== 'tryon') {
        return message;
      }

      return {
        ...message,
        items: message.items.map((item) => ({ ...item, added: true })),
      };
    });

    await sleep(500);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addMsg({
      kind: 'text',
      role: 'agent',
      text: 'Done - both in your bag. Ready to check out?',
    });

    await sleep(1700);
    if (!stillRunning()) return;

    setVoiceState('listening');
    await sleep(650);
    if (!stillRunning()) return;

    addMsg({
      kind: 'text',
      role: 'user',
      text: "Let's do it.",
    });

    await sleep(700);
    if (!stillRunning()) return;

    setVoiceState('speaking');
    addCheckoutMessage(selectedProducts);
    await sleep(800);
    if (!stillRunning()) return;

    patchMsg(liveCheckoutIdRef.current ?? '', (message) =>
      message.kind === 'checkout'
        ? {
            ...message,
            delivery: {
              recipient: deliveryDetails.recipient,
              address: deliveryDetails.address,
              city: 'New York',
              state: 'NY',
              postalCode: deliveryDetails.postalCode,
              phone: '(212) 555-0198',
            },
            deliveryComplete: true,
          }
        : message,
    );
    setVoiceState('idle');
    runningRef.current = false;
  }, [onAddToCart, sleep, stopDemo]);

  function replayDemo() {
    void playDemo();
  }

  function payNow() {
    if (messages.some((message) => message.kind === 'success')) {
      return;
    }

    addMsg({ kind: 'success' });
    setVoiceState('speaking');
    addTimedVoiceReset(900);
  }

  function handleClose() {
    stopDemo();
    setVoiceState('idle');
    onClose();
  }

  const statusLabel = voiceStateLabels[voiceState];
  const isLiveMode = liveKitReadiness.configured;
  const rpcHandlers: MiraRpcHandlers = {
    prepareCustomerCamera: prepareCustomerCameraRpc,
    captureCustomerImage: captureCustomerImageRpc,
    showProductRecommendations: showProductRecommendationsRpc,
    generateTryOns: generateTryOnsRpc,
    addToCart: addToCartRpc,
    fillCheckoutDelivery: fillCheckoutDeliveryRpc,
  };

  return (
    <>
      <AnimatePresence>
        {!chatOpen ? (
          <motion.button
            className="chat-launcher"
            type="button"
            aria-label="Open Mira style concierge"
            onClick={onOpen}
            initial={{ scale: 0.82, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.86, opacity: 0 }}
            whileHover={{ y: -4 }}
            whileTap={{ scale: 0.96 }}
          >
            <span className="launcher-ripple" aria-hidden="true" />
            <span className="launcher-ripple delay" aria-hidden="true" />
            <span className="launcher-bars" aria-hidden="true">
              <i />
              <i />
              <i />
              <i />
            </span>
          </motion.button>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {chatOpen ? (
          <motion.aside
            className="mira-panel"
            aria-label="Mira style concierge"
            initial={{ y: 26, scale: 0.97, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ y: 26, scale: 0.97, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 330, damping: 32 }}
          >
            <header className="mira-head">
              <div className="mira-identity">
                <canvas ref={orbRef} className="mira-orb" aria-hidden="true" />
                <div>
                  <h2>Mira</h2>
                  <span style={{ '--status-color': voiceColors[voiceState] } as CSSProperties}>
                    {statusLabel}
                  </span>
                </div>
              </div>

              <div className="mira-actions">
                {demoStarted && !isLiveMode ? (
                  <button type="button" aria-label="Replay demo" onClick={replayDemo}>
                    <RefreshCw size={18} aria-hidden="true" />
                  </button>
                ) : null}
                <button type="button" aria-label="Close Mira" onClick={handleClose}>
                  <X size={19} aria-hidden="true" />
                </button>
              </div>
            </header>

            <VoiceBridgeStrip bridge={voiceBridge} />

            {voiceBridge.session ? (
              <LiveKitVoiceRoom
                rpcHandlers={rpcHandlers}
                session={voiceBridge.session}
                onUserSpeech={noteUserSpeech}
                onConnected={() =>
                  {
                    setVoiceState('listening');
                    setVoiceBridge((current) => ({
                      ...current,
                      state: 'connected',
                      detail: 'Live voice room connected. Mira is listening.',
                    }));
                  }
                }
                onDisconnected={() => {
                  setVoiceState('idle');
                  setVoiceBridge((current) => ({
                    ...current,
                    state: 'fallback',
                    detail: 'Live voice room disconnected. Mock demo remains available.',
                  }));
                }}
                onError={(error) => {
                  setVoiceState('idle');
                  setVoiceBridge((current) => ({
                    ...current,
                    state: 'error',
                    detail: error.message,
                  }));
                }}
                onAgentVoiceStateChange={(nextVoiceState) => {
                  setVoiceState((current) => {
                    if (voiceBridge.state === 'connected' && nextVoiceState === 'connecting') {
                      return current === 'connecting' ? 'listening' : current;
                    }

                    return nextVoiceState;
                  });
                }}
              />
            ) : null}

            {!demoStarted && !isLiveMode ? (
              <div className="mira-intro">
                <h3>Hey - I'm Mira.</h3>
                <p>
                  I'll take a quick look at you and style a fit in about a minute.
                  Hands-free, with camera and mic simulated for this fallback.
                </p>
                <button type="button" onClick={() => void playDemo()}>
                  <Play size={15} aria-hidden="true" />
                  Play the demo
                </button>
                <span>
                  {liveKitReadiness.configured
                    ? 'Real voice readiness detected'
                    : 'Voice-first / mock camera and mic'}
                </span>
              </div>
            ) : (
              <>
                <div className="mira-thread loma-scroll" ref={scrollRef}>
                  {messages.length === 0 && isLiveMode ? <LiveThreadEmptyState /> : null}
                  {messages.map((message) => (
                    <MessageFrame
                      key={message.id}
                      message={message}
                      onCameraController={setCameraController}
                      onCameraFilter={handleCameraFilter}
                      onCameraRetake={handleCameraRetake}
                      onPayNow={payNow}
                    />
                  ))}
                </div>

                <footer className="mira-compose">
                  <div>Type a message...</div>
                  <span
                    className={voiceState === 'listening' ? 'compose-mic is-listening' : 'compose-mic'}
                    aria-label={`${statusLabel}; cart has ${cartCount} items`}
                    role="img"
                  >
                    <Mic size={17} aria-hidden="true" />
                  </span>
                  <button type="button" aria-label="Send message">
                    <SendHorizontal size={17} aria-hidden="true" />
                  </button>
                </footer>
              </>
            )}
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </>
  );
}

type VoiceBridgeStripProps = {
  bridge: VoiceBridgeStatus;
};

function VoiceBridgeStrip({ bridge }: VoiceBridgeStripProps) {
  const labelByState: Record<VoiceBridgeStatus['state'], string> = {
    idle: 'Voice ready',
    requesting: 'Starting voice',
    ready: 'Joining room',
    connected: 'Live voice',
    fallback: 'Mock voice',
    error: 'Voice paused',
  };

  return (
    <div className={`voice-bridge ${bridge.state}`}>
      <span aria-hidden="true" />
      <div>
        <strong>{labelByState[bridge.state]}</strong>
        <p>{bridge.detail}</p>
      </div>
    </div>
  );
}

type LiveKitVoiceRoomProps = {
  rpcHandlers: MiraRpcHandlers;
  session: {
    serverUrl: string;
    participantToken: string;
  };
  onConnected: () => void;
  onDisconnected: () => void;
  onError: (error: Error) => void;
  onAgentVoiceStateChange: (voiceState: VoiceState) => void;
  onUserSpeech: (text: string) => void;
};

function LiveKitVoiceRoom({
  rpcHandlers,
  session,
  onConnected,
  onDisconnected,
  onError,
  onAgentVoiceStateChange,
  onUserSpeech,
}: LiveKitVoiceRoomProps) {
  return (
    <LiveKitRoom
      className="livekit-voice-room"
      serverUrl={session.serverUrl}
      token={session.participantToken}
      connect
      audio={{ echoCancellation: true, noiseSuppression: true }}
      video={false}
      onConnected={onConnected}
      onDisconnected={onDisconnected}
      onError={onError}
    >
      <RoomAudioRenderer />
      <StartAudio className="livekit-start-audio" label="Enable voice" />
      <LiveKitBrowserRpcBridge handlers={rpcHandlers} />
      <LiveKitUserSpeechBridge onUserSpeech={onUserSpeech} />
      <LiveKitAssistantStatus onVoiceStateChange={onAgentVoiceStateChange} />
    </LiveKitRoom>
  );
}

type LiveKitBrowserRpcBridgeProps = {
  handlers: MiraRpcHandlers;
};

function LiveKitBrowserRpcBridge({ handlers }: LiveKitBrowserRpcBridgeProps) {
  const room = useRoomContext();
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  useEffect(() => {
    const methods = [
      'prepareCustomerCamera',
      'captureCustomerImage',
      'showProductRecommendations',
      'generateTryOns',
      'addToCart',
      'fillCheckoutDelivery',
    ] as const;

    methods.forEach((method) => {
      room.registerRpcMethod(method, async (data) =>
        handlersRef.current[method](parseRpcPayload(data.payload)),
      );
    });

    return () => {
      methods.forEach((method) => room.unregisterRpcMethod(method));
    };
  }, [room]);

  return null;
}

type LiveKitUserSpeechBridgeProps = {
  onUserSpeech: (text: string) => void;
};

function LiveKitUserSpeechBridge({ onUserSpeech }: LiveKitUserSpeechBridgeProps) {
  const room = useRoomContext();
  const transcriptions = useTranscriptions({
    room,
    participantIdentities: [room.localParticipant.identity],
  });
  const seenTextByIdRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    for (const transcription of transcriptions) {
      const previous = seenTextByIdRef.current.get(transcription.streamInfo.id);

      if (previous === transcription.text) {
        continue;
      }

      seenTextByIdRef.current.set(transcription.streamInfo.id, transcription.text);
      onUserSpeech(transcription.text);
    }
  }, [onUserSpeech, transcriptions]);

  return null;
}

type LiveKitAssistantStatusProps = {
  onVoiceStateChange: (voiceState: VoiceState) => void;
};

function LiveKitAssistantStatus({ onVoiceStateChange }: LiveKitAssistantStatusProps) {
  const { state, agentTranscriptions } = useVoiceAssistant();
  const latestAgentText = agentTranscriptions.at(-1)?.text;

  useEffect(() => {
    onVoiceStateChange(voiceStateFromAgentState(state));
  }, [onVoiceStateChange, state]);

  return (
    <div className="livekit-agent-state">
      <span>Agent</span>
      <strong>{state}</strong>
      {latestAgentText ? <p>{latestAgentText}</p> : null}
    </div>
  );
}

function LiveThreadEmptyState() {
  return (
    <div className="live-thread-empty">
      <span aria-hidden="true" />
      <div>
        <strong>Mira is listening</strong>
        <p>Say hats or t-shirts to begin the camera styling flow.</p>
      </div>
    </div>
  );
}

type MessageFrameProps = {
  message: MiraMessage;
  onCameraController: (messageId: string, controller: CameraController | null) => void;
  onCameraFilter: (messageId: string, filter: CameraMessage['filter']) => void;
  onCameraRetake: (messageId: string) => void;
  onPayNow: () => void;
};

function MessageFrame({
  message,
  onCameraController,
  onCameraFilter,
  onCameraRetake,
  onPayNow,
}: MessageFrameProps) {
  const frameClass =
    message.kind === 'text' && message.role === 'user' ? 'message-frame user' : 'message-frame';

  return (
    <motion.div
      className={frameClass}
      initial={{ y: 10, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.28 }}
    >
      {renderMessage(message, onCameraController, onCameraFilter, onCameraRetake, onPayNow)}
    </motion.div>
  );
}

function renderMessage(
  message: MiraMessage,
  onCameraController: (messageId: string, controller: CameraController | null) => void,
  onCameraFilter: (messageId: string, filter: CameraMessage['filter']) => void,
  onCameraRetake: (messageId: string) => void,
  onPayNow: () => void,
) {
  if (message.kind === 'text') {
    return (
      <div className={message.role === 'user' ? 'text-bubble user' : 'text-bubble'}>
        {message.text}
      </div>
    );
  }

  if (message.kind === 'camera') {
    const isAnalyzing = message.status === 'analyzing';
    const isCaptured = message.status === 'captured' || message.status === 'analyzing';
    const canEditCapture = Boolean(message.photoDataUrl && message.status === 'captured');

    return (
      <div className="camera-card">
        <div className="camera-preview">
          {message.photoDataUrl ? (
            <img
              className={`camera-photo ${message.filter ? `filter-${message.filter}` : 'filter-none'}`}
              src={message.photoDataUrl}
              alt="Captured customer"
            />
          ) : message.status === 'preview' ? (
            <LiveCameraPreview messageId={message.id} onController={onCameraController} />
          ) : (
            <div aria-hidden="true" />
          )}
          {message.countdown ? (
            <span className="camera-countdown" aria-live="polite">
              {message.countdown}
            </span>
          ) : null}
          {message.status === 'preview' ? (
            <span className="live-chip">
              <i />
              LIVE
            </span>
          ) : null}
          {isAnalyzing ? <span className="scan-line" aria-hidden="true" /> : null}
          {isCaptured ? (
            <span className="capture-check" aria-label="Captured">
              <Check size={15} aria-hidden="true" />
            </span>
          ) : null}
        </div>

        {message.prompt ? (
          <div className="camera-prompt">
            <p>{message.prompt}</p>
            {message.actionLabel ? (
              <button
                type="button"
                disabled={Boolean(message.actionBusy)}
              >
                {message.actionBusy ? 'Opening...' : message.actionLabel}
              </button>
            ) : null}
            {message.error ? <small>{message.error}</small> : null}
            {canEditCapture ? (
              <div className="camera-edit-bar">
                <button type="button" onClick={() => onCameraFilter(message.id, 'bright')}>
                  Brighten
                </button>
                <button type="button" onClick={() => onCameraFilter(message.id, 'warm')}>
                  Warm
                </button>
                <button type="button" onClick={() => onCameraRetake(message.id)}>
                  Retake
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {message.showAttrs ? (
          <div className="attribute-readout">
            <span>Reading your features</span>
            {message.attrs.map((attr) => (
              <div className={attr.on ? 'attribute-row is-on' : 'attribute-row'} key={attr.label}>
                <span>{attr.label}</span>
                <strong>{attr.value}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  if (message.kind === 'profile') {
    return (
      <div className="profile-card">
        <div className="profile-title">
          <Sparkles size={18} aria-hidden="true" />
          <span>Your style profile</span>
        </div>
        <div className="profile-chips">
          {message.chips.map((chip) => (
            <span key={chip.value}>
              {chip.label ? <small>{chip.label}</small> : null}
              <strong>{chip.value}</strong>
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (message.kind === 'recs') {
    return (
      <div className="recommendation-carousel">
        <div className="recs-strip loma-scroll">
          {message.cards.map((card) => (
            <div
              className={card.selected ? 'rec-card is-selected' : 'rec-card'}
              key={card.id}
              style={
                {
                  '--rec-color': card.color,
                  '--rec-text': card.textColor,
                } as CSSProperties
              }
            >
              <div className="rec-art">
                <img src={card.imageUrl} alt={card.name} />
                <div aria-hidden="true" />
                {card.selected ? (
                  <span aria-label="Selected">
                    <Check size={14} aria-hidden="true" />
                  </span>
                ) : null}
              </div>
              <div className="rec-copy">
                <div>
                  <strong>{card.name}</strong>
                  <span>{formatPrice(card.price)}</span>
                </div>
                <p>{card.why}</p>
              </div>
            </div>
          ))}
        </div>
        <p>Swipe or tell Mira the product names you like</p>
      </div>
    );
  }

  if (message.kind === 'tryon') {
    return (
      <div className="tryon-group">
        <div className="tryon-status">
          <Sparkles size={15} aria-hidden="true" />
          <div>
            <strong>{message.title ?? 'Rendering your try-ons'}</strong>
            {message.subtitle ? <span>{message.subtitle}</span> : null}
          </div>
        </div>
        <div className="tryon-row loma-scroll">
          {message.items.map((item) => (
            <div
              className="tryon-card"
              key={item.id}
              style={
                {
                  '--tryon-color': item.color,
                  '--tryon-text': item.textColor,
                } as CSSProperties
              }
            >
              <div className={item.status === 'gen' ? 'tryon-art is-generating' : 'tryon-art'}>
                {item.status === 'done' ? (
                  <>
                    <img src={item.renderedImageUrl ?? item.tryOnImageUrl} alt={`${item.name} try-on`} />
                    <span>YOU / AI TRY-ON</span>
                  </>
                ) : (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    <strong>{item.genLabel}</strong>
                  </>
                )}
              </div>
              {item.status === 'done' ? (
                <div className="tryon-copy">
                  <strong>{item.name}</strong>
                  <div>
                    <span>{formatPrice(item.price)}</span>
                    <button className={item.added ? 'is-added' : ''} type="button">
                      {item.added ? 'Added' : 'Add'}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (message.kind === 'checkout') {
    const total = message.items.reduce((sum, product) => sum + product.price, 0);
    const deliveryCityLine = [message.delivery.city, message.delivery.state]
      .filter(Boolean)
      .join(', ');

    return (
      <div className={message.deliveryComplete ? 'checkout-card is-filled' : 'checkout-card'}>
        <span>{message.deliveryComplete ? 'Delivery ready' : 'Delivery'}</span>
        <div className="checkout-fields">
          <div className={message.delivery.recipient ? 'checkout-field is-filled' : 'checkout-field is-empty'}>
            {message.delivery.recipient || 'Recipient name'}
          </div>
          <div className={message.delivery.address ? 'checkout-field is-filled' : 'checkout-field is-empty'}>
            {message.delivery.address || 'Street address'}
          </div>
          <div className="checkout-field-row">
            <span className={deliveryCityLine ? 'checkout-field is-filled' : 'checkout-field is-empty'}>
              {deliveryCityLine || 'City, state'}
            </span>
            <span className={message.delivery.postalCode ? 'checkout-field is-filled' : 'checkout-field is-empty'}>
              {message.delivery.postalCode || 'Postal'}
            </span>
          </div>
          <div className={message.delivery.phone ? 'checkout-field is-filled' : 'checkout-field is-empty'}>
            {message.delivery.phone || 'Phone number'}
          </div>
        </div>
        <p className="checkout-hint">
          {message.deliveryComplete ? 'Details filled from your voice reply.' : 'Tell Mira your delivery details.'}
        </p>
        <div className="checkout-total">
          <span>Total</span>
          <strong>{formatPrice(total)}</strong>
        </div>
        <button type="button" onClick={onPayNow} disabled={!message.deliveryComplete}>
          <CreditCard size={17} aria-hidden="true" />
          Pay
        </button>
      </div>
    );
  }

  return (
    <div className="success-card">
      <span>
        <Check size={27} aria-hidden="true" />
      </span>
      <strong>Order placed</strong>
      <p>2 pieces on the way. I had a blast styling you - come back anytime.</p>
      <small>
        ORDER #{deliveryDetails.orderNumber} / {deliveryDetails.window.toUpperCase()}
      </small>
    </div>
  );
}

type LiveCameraPreviewProps = {
  messageId: string;
  onController: (messageId: string, controller: CameraController | null) => void;
};

function LiveCameraPreview({ messageId, onController }: LiveCameraPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const errorRef = useRef<string | undefined>(undefined);
  const onControllerRef = useRef(onController);
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    onControllerRef.current = onController;
  }, [onController]);

  useEffect(() => {
    let cancelled = false;
    errorRef.current = undefined;
    setIsLive(false);

    const stopStream = () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };

    const controller: CameraController = {
      capture: () => {
        const video = videoRef.current;

        if (video && isVideoReady(video)) {
          return {
            imageDataUrl: captureVideoElementFrame(video),
            source: 'camera',
          };
        }

        return {
          imageDataUrl: createFallbackSelfieDataUrl(),
          source: 'fallback',
          error: errorRef.current ?? 'Camera preview was not ready yet.',
        };
      },
    };

    onControllerRef.current(messageId, controller);

    const startCamera = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error('Camera is not available in this browser.');
        }

        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: 'user',
            width: { ideal: 720 },
            height: { ideal: 960 },
          },
          audio: false,
        });

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        const video = videoRef.current;

        if (!video) {
          throw new Error('Camera preview is not ready.');
        }

        video.srcObject = stream;
        await video.play();

        if (cancelled) {
          return;
        }

        setIsLive(true);
      } catch (error) {
        errorRef.current = error instanceof Error ? error.message : 'Camera unavailable.';
        setIsLive(false);
      }
    };

    void startCamera();

    return () => {
      cancelled = true;
      onControllerRef.current(messageId, null);
      stopStream();
    };
  }, [messageId]);

  return (
    <>
      <video
        ref={videoRef}
        className={isLive ? 'camera-video is-live' : 'camera-video'}
        autoPlay
        muted
        playsInline
      />
      {!isLive ? <div aria-hidden="true" /> : null}
    </>
  );
}

type DemoCaptureResult = {
  imageDataUrl: string;
  source: 'camera' | 'fallback';
  error?: string;
};

function captureVideoElementFrame(video: HTMLVideoElement): string {
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth || 720;
  canvas.height = video.videoHeight || 960;
  const ctx = canvas.getContext('2d');

  if (!ctx) {
    throw new Error('Unable to capture camera frame.');
  }

  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
}

function isVideoReady(video: HTMLVideoElement): boolean {
  return video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0;
}

function createFallbackSelfieDataUrl(): string {
  const canvas = document.createElement('canvas');
  canvas.width = 720;
  canvas.height = 960;
  const ctx = canvas.getContext('2d');

  if (!ctx) {
    return 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  }

  const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
  gradient.addColorStop(0, '#f6d0b5');
  gradient.addColorStop(0.45, '#b66a46');
  gradient.addColorStop(1, '#2e2925');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = 'rgba(255,255,255,0.18)';
  ctx.beginPath();
  ctx.ellipse(360, 310, 140, 170, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = 'rgba(255,255,255,0.72)';
  ctx.font = '600 42px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Camera preview', 360, 820);

  return canvas.toDataURL('image/jpeg', 0.82);
}

function readProductPayload(payload: unknown) {
  return typeof payload === 'object' && payload ? payload : {};
}

function readProductIds(payload: unknown): string[] {
  return resolveLomaProductIdsFromPayload(payload);
}

function toProductRecommendation(product: LomaProduct): ProductRecommendation {
  return {
    id: product.id,
    category: product.shopperCategory,
    name: product.name,
    brand: product.brand,
    price: product.price,
    currency: 'USD',
    imageUrl: product.imageUrl,
    tryOnImageUrl: product.tryOnImageUrl,
    colorStory: product.sub,
    material: product.material,
    fitNotes: product.fitNotes,
    recommendationReason: product.recommendationReason,
  };
}
