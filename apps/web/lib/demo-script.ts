import {
  analyzeCustomerImage,
  createTryOnJobs,
  getCartSummary,
  type CustomerQualities,
  type ProductRecommendation,
  type ShopperCategory,
  type TryOnJob,
} from './shopper-flow';

export type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking';

export type LomaCategory = {
  id: ShopperCategory;
  label: string;
  navLabel: string;
  styleGoal: string;
};

export type LomaProduct = {
  id: string;
  shopperCategory: ShopperCategory;
  name: string;
  brand: string;
  kind: 'TEE' | 'CAP';
  price: number;
  color: string;
  textColor: string;
  sub: string;
  material: string;
  fitNotes: string;
  imageUrl: string;
  tryOnImageUrl: string;
  recommendationReason: string;
};

export type LomaCartItem = LomaProduct & {
  cartId: string;
  isTryOn: boolean;
};

export type LiveKitReadiness = {
  configured: boolean;
  label: string;
  detail: string;
};

const image = (photoId: string) =>
  `https://images.unsplash.com/${photoId}?auto=format&fit=crop&w=1200&q=85`;

export const lomaCategories: LomaCategory[] = [
  {
    id: 'tshirts',
    label: 'Tees',
    navLabel: 'Tees',
    styleGoal: 'clean summer basics',
  },
  {
    id: 'hats',
    label: 'Hats',
    navLabel: 'Hats',
    styleGoal: 'finish the look',
  },
];

export const lomaProducts: LomaProduct[] = [
  {
    id: 'clay',
    shopperCategory: 'tshirts',
    name: 'Clay Pocket Tee',
    brand: 'LOMA',
    kind: 'TEE',
    price: 48,
    color: '#C16A45',
    textColor: '#fff',
    sub: 'Heavyweight cotton',
    material: '240gsm cotton jersey',
    fitNotes: 'straight body, compact sleeve, pocket detail',
    imageUrl: image('photo-1503341455253-b2e723bb3dbb'),
    tryOnImageUrl: image('photo-1496747611176-843222e1e57c'),
    recommendationReason: 'Clay echoes warm golden undertones and makes a simple fit feel styled.',
  },
  {
    id: 'bone',
    shopperCategory: 'tshirts',
    name: 'Bone Boxy Tee',
    brand: 'LOMA',
    kind: 'TEE',
    price: 52,
    color: '#E7DFD2',
    textColor: '#3a3127',
    sub: 'Relaxed crop',
    material: 'washed supima cotton',
    fitNotes: 'boxy shape, soft neckline, relaxed crop',
    imageUrl: image('photo-1521572163474-6864f9cf17ab'),
    tryOnImageUrl: image('photo-1503342217505-b0a15ec3261c'),
    recommendationReason: 'Bone gives the outfit a clean neutral base without going stark white.',
  },
  {
    id: 'olive',
    shopperCategory: 'tshirts',
    name: 'Olive Heavyweight',
    brand: 'LOMA',
    kind: 'TEE',
    price: 54,
    color: '#6E7257',
    textColor: '#fff',
    sub: '240gsm jersey',
    material: 'dense organic cotton',
    fitNotes: 'easy body, soft structure, matte finish',
    imageUrl: image('photo-1503341504253-dff4815485f1'),
    tryOnImageUrl: image('photo-1529139574466-a303027c1d8b'),
    recommendationReason: 'Muted olive supports soft contrast and keeps the palette grounded.',
  },
  {
    id: 'camel',
    shopperCategory: 'hats',
    name: 'Camel Cord Cap',
    brand: 'LOMA',
    kind: 'CAP',
    price: 42,
    color: '#C9A36A',
    textColor: '#3a3127',
    sub: 'Corduroy 6-panel',
    material: 'fine wale cotton corduroy',
    fitNotes: 'low crown, curved brim, brass adjuster',
    imageUrl: image('photo-1542291026-7eec264c27ff'),
    tryOnImageUrl: image('photo-1524504388940-b1c1722653e1'),
    recommendationReason: 'Camel frames the face warmly and never competes with the tee.',
  },
  {
    id: 'char',
    shopperCategory: 'hats',
    name: 'Charcoal 5-Panel',
    brand: 'LOMA',
    kind: 'CAP',
    price: 44,
    color: '#2E2C29',
    textColor: '#fff',
    sub: 'Brushed twill',
    material: 'brushed cotton twill',
    fitNotes: 'structured front, flat side panel, tonal strap',
    imageUrl: image('photo-1506629905607-d9f297d96d6d'),
    tryOnImageUrl: image('photo-1496747611176-843222e1e57c'),
    recommendationReason: 'Charcoal adds quiet structure when the outfit needs more definition.',
  },
];

export const selectedDemoProductIds = ['clay', 'camel'];

export const deliveryDetails = {
  recipient: 'Jordan Avery',
  address: '218 Mercer St, Apt 4',
  city: 'New York, NY',
  postalCode: '10012',
  window: 'Arrives Thu',
  orderNumber: 'LM-4471',
};

export const voiceStateLabels: Record<VoiceState, string> = {
  idle: 'Ready',
  connecting: 'Connecting...',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};

export function formatPrice(price: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(price);
}

export function getLiveKitReadiness(liveKitUrl?: string): LiveKitReadiness {
  if (liveKitUrl?.trim()) {
    return {
      configured: true,
      label: 'LiveKit real mode ready',
      detail: 'Public LiveKit URL is configured. The mock demo still works offline.',
    };
  }

  return {
    configured: false,
    label: 'Mock demo mode',
    detail: 'Set NEXT_PUBLIC_LIVEKIT_URL plus server credentials to enable real voice.',
  };
}

export function getProductsByCategory(category: ShopperCategory) {
  return lomaProducts.filter((product) => product.shopperCategory === category);
}

export function getProductById(productId: string) {
  return lomaProducts.find((product) => product.id === productId) ?? null;
}

export function getSelectedDemoProducts() {
  return selectedDemoProductIds
    .map((productId) => getProductById(productId))
    .filter((product): product is LomaProduct => Boolean(product));
}

export function getCartTotals(items: LomaCartItem[]) {
  const summary = getCartSummary(
    items.map((item) => ({
      productId: item.id,
      quantity: 1,
    })),
  );

  return {
    ...summary,
    subtotal: items.reduce((total, item) => total + item.price, 0),
  };
}

export async function readDemoCustomerQualities(): Promise<CustomerQualities> {
  return analyzeCustomerImage({
    imageDataUrl: 'data:image/jpeg;base64,loma-demo',
    category: 'tshirts',
  });
}

export async function createLomaTryOnJobs(products: LomaProduct[]): Promise<TryOnJob[]> {
  return createTryOnJobs({
    customerImageId: 'loma-demo-shopper',
    products: products.map(toProductRecommendation),
    selectedProductIds: products.map((product) => product.id),
  });
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
