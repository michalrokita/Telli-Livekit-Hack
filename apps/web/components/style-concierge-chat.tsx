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
  useVoiceAssistant,
} from '@livekit/components-react';
import {
  Camera,
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
  showAttrs?: boolean;
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
  items: TryOnCard[];
};

type CheckoutMessage = {
  id: string;
  kind: 'checkout';
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

const voiceColors: Record<VoiceState, string> = {
  idle: '#9A8C7C',
  connecting: '#B0917C',
  listening: '#5E8C6E',
  thinking: '#C19A45',
  speaking: '#C16A45',
};

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

  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);

  const clearDemoTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];
  }, []);

  const stopDemo = useCallback(() => {
    runningRef.current = false;
    runIdRef.current += 1;
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
      items: selectedProducts.map((product) => ({
        ...product,
        status: 'gen',
        genLabel: 'Styling...',
      })),
    });

    const tryOnJobs = await createLomaTryOnJobs(selectedProducts);
    const jobsByProductId = new Map(tryOnJobs.map((job) => [job.productId, job]));

    await sleep(2300);
    if (!stillRunning()) return;

    patchMsg(tryOnId, (message) => {
      if (message.kind !== 'tryon') {
        return message;
      }

      return {
        ...message,
        items: message.items.map((item, index) =>
          index === 0
            ? {
                ...item,
                status: 'done',
                renderedImageUrl: jobsByProductId.get(item.id)?.imageUrl ?? item.tryOnImageUrl,
              }
            : item,
        ),
      };
    });

    await sleep(1000);
    if (!stillRunning()) return;

    patchMsg(tryOnId, (message) => {
      if (message.kind !== 'tryon') {
        return message;
      }

      return {
        ...message,
        items: message.items.map((item) => ({
          ...item,
          status: 'done',
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
    addMsg({ kind: 'checkout' });
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
                <span className="mira-avatar" aria-hidden="true" />
                <div>
                  <h2>Mira</h2>
                  <span style={{ '--status-color': voiceColors[voiceState] } as CSSProperties}>
                    {statusLabel}
                  </span>
                </div>
              </div>

              <div className="mira-actions">
                {demoStarted ? (
                  <button type="button" aria-label="Replay demo" onClick={replayDemo}>
                    <RefreshCw size={18} aria-hidden="true" />
                  </button>
                ) : null}
                <button type="button" aria-label="Close Mira" onClick={handleClose}>
                  <X size={19} aria-hidden="true" />
                </button>
              </div>
            </header>

            <div className={demoStarted ? 'mira-viz is-compact' : 'mira-viz'}>
              <canvas ref={orbRef} aria-hidden="true" />
              {!demoStarted ? <span>{statusLabel}</span> : null}
            </div>

            <VoiceBridgeStrip bridge={voiceBridge} />

            {voiceBridge.session ? (
              <LiveKitVoiceRoom
                session={voiceBridge.session}
                onConnected={() =>
                  setVoiceBridge((current) => ({
                    ...current,
                    state: 'connected',
                    detail: 'Live voice room connected. Mira is listening.',
                  }))
                }
                onDisconnected={() =>
                  setVoiceBridge((current) => ({
                    ...current,
                    state: 'fallback',
                    detail: 'Live voice room disconnected. Mock demo remains available.',
                  }))
                }
                onError={(error) =>
                  setVoiceBridge((current) => ({
                    ...current,
                    state: 'error',
                    detail: error.message,
                  }))
                }
              />
            ) : null}

            {!demoStarted ? (
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
                  {messages.map((message) => (
                    <MessageFrame key={message.id} message={message} onPayNow={payNow} />
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
  session: {
    serverUrl: string;
    participantToken: string;
  };
  onConnected: () => void;
  onDisconnected: () => void;
  onError: (error: Error) => void;
};

function LiveKitVoiceRoom({
  session,
  onConnected,
  onDisconnected,
  onError,
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
      <LiveKitAssistantStatus />
    </LiveKitRoom>
  );
}

function LiveKitAssistantStatus() {
  const { state, agentTranscriptions } = useVoiceAssistant();
  const latestAgentText = agentTranscriptions.at(-1)?.text;

  return (
    <div className="livekit-agent-state">
      <span>Agent</span>
      <strong>{state}</strong>
      {latestAgentText ? <p>{latestAgentText}</p> : null}
    </div>
  );
}

type MessageFrameProps = {
  message: MiraMessage;
  onPayNow: () => void;
};

function MessageFrame({ message, onPayNow }: MessageFrameProps) {
  const frameClass =
    message.kind === 'text' && message.role === 'user' ? 'message-frame user' : 'message-frame';

  return (
    <motion.div
      className={frameClass}
      initial={{ y: 10, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.28 }}
    >
      {renderMessage(message, onPayNow)}
    </motion.div>
  );
}

function renderMessage(message: MiraMessage, onPayNow: () => void) {
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

    return (
      <div className="camera-card">
        <div className="camera-preview">
          <div aria-hidden="true" />
          {message.status === 'preview' ? (
            <>
              <span className="live-chip">
                <i />
                LIVE
              </span>
              <span className="shutter-dot" aria-hidden="true" />
            </>
          ) : null}
          {isAnalyzing ? <span className="scan-line" aria-hidden="true" /> : null}
          {isCaptured ? (
            <span className="capture-check" aria-label="Captured">
              <Check size={15} aria-hidden="true" />
            </span>
          ) : null}
        </div>

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
        <p>Swipe or tell Mira which you like</p>
      </div>
    );
  }

  if (message.kind === 'tryon') {
    return (
      <div className="tryon-row">
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
    );
  }

  if (message.kind === 'checkout') {
    const selectedProducts = getSelectedDemoProducts();
    const total = selectedProducts.reduce((sum, product) => sum + product.price, 0);

    return (
      <div className="checkout-card">
        <span>Delivery</span>
        <div className="checkout-fields">
          <div>{deliveryDetails.recipient}</div>
          <div>{deliveryDetails.address}</div>
          <div>
            <span>{deliveryDetails.city}</span>
            <span>{deliveryDetails.postalCode}</span>
          </div>
        </div>
        <div className="checkout-total">
          <span>Total</span>
          <strong>{formatPrice(total)}</strong>
        </div>
        <button type="button" onClick={onPayNow}>
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
