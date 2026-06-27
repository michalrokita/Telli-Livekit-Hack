import {
  getSelectedDemoProducts,
  lomaProducts,
  type LomaProduct,
  type VoiceState,
} from './demo-script';
import {
  isShopperCategory,
  type CustomerQualities,
  type ShopperCategory,
} from './shopper-flow';

export type CheckoutDeliveryDetails = {
  recipient: string;
  address: string;
  city: string;
  state: string;
  postalCode: string;
  phone: string;
};

type CategoryPayload = {
  category?: unknown;
};

type ProductPayload = CategoryPayload & {
  products?: unknown;
  selectedProductIds?: unknown;
  selectedProducts?: unknown;
  selectedProductNames?: unknown;
  productIds?: unknown;
  product_ids?: unknown;
  productNames?: unknown;
  names?: unknown;
};

export function normalizeRpcCategory(payload: CategoryPayload | unknown): ShopperCategory {
  const category = typeof payload === 'object' && payload ? (payload as CategoryPayload).category : payload;

  if (isShopperCategory(category)) {
    return category;
  }

  if (typeof category === 'string') {
    const normalized = category.trim().toLowerCase().replace(/[-_\s]/g, '');

    if (['hat', 'hats', 'cap', 'caps'].includes(normalized)) {
      return 'hats';
    }

    if (['tshirt', 'tshirts', 'tee', 'tees', 'shirt', 'shirts'].includes(normalized)) {
      return 'tshirts';
    }
  }

  return 'tshirts';
}

export function cameraAttributesFromQualities(qualities: CustomerQualities) {
  return [
    { label: 'Hair', value: qualities.hairColor },
    { label: 'Skin tone', value: qualities.skinTone },
    { label: 'Undertone', value: qualities.undertone },
    { label: 'Contrast', value: qualities.contrast },
  ];
}

export function profileChipsFromQualities(qualities: CustomerQualities) {
  const chips = [
    qualities.palette ? `${toTitleCase(qualities.palette)} palette` : '',
    `${toTitleCase(qualities.undertone)} undertone`,
    `${toTitleCase(qualities.skinTone)} skin`,
    `${toTitleCase(qualities.hairColor)} hair`,
    `${toTitleCase(qualities.contrast)} contrast`,
  ].filter((value) => value.trim().length > 0);

  return [...new Set(chips)].slice(0, 5).map((value) => ({ label: '', value }));
}

export function speechLooksReady(value: string): boolean {
  const normalized = normalizeSpeech(value);

  return [
    'ready',
    'im ready',
    'i am ready',
    'take it',
    'take the photo',
    'take a photo',
    'snap it',
    'go ahead',
  ].some((phrase) => normalized.includes(phrase));
}

export function selectedProductsMatchSpeech(products: LomaProduct[], speech: string): boolean {
  const normalized = normalizeSpeech(speech);

  if (products.length === 0 || normalized.length < 3) {
    return false;
  }

  return products.every((product) => {
    const fullName = normalizeSpeech(product.name);
    if (fullName && normalized.includes(fullName)) {
      return true;
    }

    return productSpeechTokens(product).some((token) => normalized.includes(token));
  });
}

export function deliveryDetailsMatchSpeech(details: CheckoutDeliveryDetails, speech: string): boolean {
  const normalized = normalizeSpeech(speech);
  const digits = onlyDigits(speech);

  if (normalized.split(' ').length < 5) {
    return false;
  }

  const recipientToken = normalizeSpeech(details.recipient).split(' ').find((token) => token.length > 1);
  const addressTokens = normalizeSpeech(details.address)
    .split(' ')
    .filter((token) => token.length > 2 && !['street', 'st', 'avenue', 'ave', 'road', 'rd'].includes(token));
  const postalDigits = onlyDigits(details.postalCode);
  const phoneDigits = onlyDigits(details.phone);

  return Boolean(
    recipientToken &&
      normalized.includes(recipientToken) &&
      addressTokens.some((token) => normalized.includes(token)) &&
      (!postalDigits || digits.includes(postalDigits)) &&
      (!phoneDigits || digits.includes(phoneDigits.slice(-4))),
  );
}

export function createEmptyDeliveryDetails(): CheckoutDeliveryDetails {
  return {
    recipient: '',
    address: '',
    city: '',
    state: '',
    postalCode: '',
    phone: '',
  };
}

export function normalizeDeliveryDetailsPayload(payload: unknown): CheckoutDeliveryDetails {
  const source = readDeliverySource(payload);

  return {
    recipient: readFirstString(source, ['recipient', 'name', 'fullName', 'full_name']),
    address: readFirstString(source, ['address', 'street', 'streetAddress', 'street_address']),
    city: readFirstString(source, ['city']),
    state: readFirstString(source, ['state', 'region', 'province']),
    postalCode: readFirstString(source, ['postalCode', 'postal_code', 'zip', 'zipCode', 'zip_code']),
    phone: readFirstString(source, ['phone', 'phoneNumber', 'phone_number']),
  };
}

export function isDeliveryDetailsComplete(details: CheckoutDeliveryDetails): boolean {
  // State, postal code, and phone are optional — never block checkout on them, and any
  // value (real or not) is accepted. Only a name + street + city are needed to enable Pay.
  return [details.recipient, details.address, details.city].every((value) => value.trim().length > 0);
}

export function resolveLiveDisplayProducts(payload: ProductPayload): LomaProduct[] {
  const selectedIds = readSelectedProductIds(payload);

  if (selectedIds.length > 0) {
    const selected = selectedIds
      .map((productId) => lomaProducts.find((product) => product.id === productId))
      .filter((product): product is LomaProduct => Boolean(product));

    return selected.length > 0 ? selected : getSelectedDemoProducts();
  }

  const agentProductIds = readProductIds(payload.products);
  const matchingAgentProducts = agentProductIds
    .map((productId) => lomaProducts.find((product) => product.id === productId))
    .filter((product): product is LomaProduct => Boolean(product));

  if (matchingAgentProducts.length > 0) {
    return matchingAgentProducts;
  }

  return lomaProducts;
}

export function resolveLomaProductIdsFromPayload(payload: unknown): string[] {
  if (!payload || typeof payload !== 'object') {
    return [];
  }

  return readSelectedProductIds(payload as ProductPayload);
}

export function parseRpcPayload(payload: string): unknown {
  if (!payload.trim()) {
    return {};
  }

  try {
    return JSON.parse(payload) as unknown;
  } catch {
    return {};
  }
}

export function voiceStateFromAgentState(agentState: string): VoiceState {
  if (agentState === 'listening' || agentState === 'idle') {
    return 'listening';
  }

  if (agentState === 'thinking') {
    return 'thinking';
  }

  if (agentState === 'speaking') {
    return 'speaking';
  }

  if (agentState === 'connecting' || agentState === 'pre-connect-buffering') {
    return 'connecting';
  }

  return 'idle';
}

export async function withTimeoutFallback<T>(
  task: Promise<T>,
  timeoutMs: number,
  fallback: () => T,
): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const timeout = new Promise<T>((resolve) => {
    timeoutId = setTimeout(() => resolve(fallback()), timeoutMs);
  });

  try {
    return await Promise.race([task, timeout]);
  } finally {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
  }
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function toTitleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizeSpeech(value: string): string {
  return value
    .toLowerCase()
    .replace(/['']/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function onlyDigits(value: string): string {
  return value.replace(/\D/g, '');
}

function productSpeechTokens(product: LomaProduct): string[] {
  const stopWords = new Set(['tee', 'cap', 'hat', 'the', 'and', 'loma']);
  return normalizeSpeech(`${product.name} ${product.kind} ${product.sub}`)
    .split(' ')
    .filter((token) => token.length > 2 && !stopWords.has(token));
}

function readDeliverySource(payload: unknown): Record<string, unknown> {
  if (!payload || typeof payload !== 'object') {
    return {};
  }

  const maybeNested = (payload as { deliveryDetails?: unknown; delivery?: unknown }).deliveryDetails ??
    (payload as { delivery?: unknown }).delivery;

  if (maybeNested && typeof maybeNested === 'object') {
    return maybeNested as Record<string, unknown>;
  }

  return payload as Record<string, unknown>;
}

function readFirstString(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = source[key];

    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }

  return '';
}

function readSelectedProductIds(payload: ProductPayload): string[] {
  const candidates = [
    payload.selectedProductIds,
    payload.selectedProducts,
    payload.selectedProductNames,
    payload.productIds,
    payload.product_ids,
    payload.productNames,
    payload.names,
  ];

  for (const candidate of candidates) {
    const selectors = readProductSelectors(candidate);
    const productIds = resolveProductSelectors(selectors);

    if (productIds.length > 0) {
      return productIds;
    }
  }

  return [];
}

function readProductIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const selectors = value.flatMap((item) => {
    if (typeof item === 'string') {
      return [item];
    }

    if (!item || typeof item !== 'object') {
      return [];
    }

    const source = item as {
      id?: unknown;
      product_id?: unknown;
      name?: unknown;
      productName?: unknown;
      product_name?: unknown;
    };
    const selector = source.id ?? source.product_id ?? source.name ?? source.productName ?? source.product_name;
    return typeof selector === 'string' ? [selector] : [];
  });

  return resolveProductSelectors(selectors);
}

function readProductSelectors(value: unknown): string[] {
  if (typeof value === 'string') {
    return value
      .split(/,|\band\b/gi)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((item) => {
    if (typeof item === 'string') {
      return [item];
    }

    if (!item || typeof item !== 'object') {
      return [];
    }

    const source = item as {
      id?: unknown;
      product_id?: unknown;
      name?: unknown;
      productName?: unknown;
      product_name?: unknown;
    };
    const selector = source.id ?? source.product_id ?? source.name ?? source.productName ?? source.product_name;
    return typeof selector === 'string' ? [selector] : [];
  });
}

function resolveProductSelectors(selectors: string[]): string[] {
  const resolved = selectors
    .map((selector) => resolveProductSelector(selector))
    .filter((product): product is LomaProduct => Boolean(product))
    .map((product) => product.id);

  return Array.from(new Set(resolved));
}

function resolveProductSelector(selector: string): LomaProduct | null {
  const normalized = normalizeProductSelector(selector);

  if (!normalized) {
    return null;
  }

  const byExactIdOrName = lomaProducts.find(
    (product) =>
      normalizeProductSelector(product.id) === normalized ||
      normalizeProductSelector(product.name) === normalized,
  );

  if (byExactIdOrName) {
    return byExactIdOrName;
  }

  const selectorTokens = productSelectorTokens(selector);
  const byTokens = lomaProducts.find((product) => {
    const productTokens = productSelectorTokens(`${product.name} ${product.id} ${product.kind}`);
    return selectorTokens.length > 0 && selectorTokens.every((token) => productTokens.includes(token));
  });

  if (byTokens) {
    return byTokens;
  }

  const ordinal = Number.parseInt(normalized, 10);
  return Number.isInteger(ordinal) && ordinal >= 1 && ordinal <= lomaProducts.length
    ? lomaProducts[ordinal - 1]
    : null;
}

function normalizeProductSelector(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

function productSelectorTokens(value: string): string[] {
  return value
    .toLowerCase()
    .split(/[^a-z0-9]+/g)
    .filter(Boolean);
}
