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

// Catalog mirrors the `stylist` brain catalog (stylist/catalog/sample_catalog.json):
// same product IDs + flat-garment images (served from /public/catalog), so what the UI
// shows, what `recommend` scores, and what `tryon` renders all key off one identity.
export const lomaProducts: LomaProduct[] = [
  {
    id: 'TEE-OLIVE-001',
    shopperCategory: 'tshirts',
    name: "Heavyweight Olive Crew Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 29.9,
    color: '#556b2f',
    textColor: '#ffffff',
    sub: "Crew Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-olive-001.png',
    tryOnImageUrl: '/catalog/tee-olive-001.png',
    recommendationReason: "Olive is a warm tone with a streetwear, minimal vibe.",
  },
  {
    id: 'TEE-RUST-002',
    shopperCategory: 'tshirts',
    name: "Garment-Dyed Rust Pocket Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 32.0,
    color: '#9a4521',
    textColor: '#ffffff',
    sub: "Pocket Crew Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-rust-002.png',
    tryOnImageUrl: '/catalog/tee-rust-002.png',
    recommendationReason: "Rust is a warm tone with a casual, heritage vibe.",
  },
  {
    id: 'TEE-NAVY-003',
    shopperCategory: 'tshirts',
    name: "Classic Navy Crew Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 24.9,
    color: '#1f2d4d',
    textColor: '#ffffff',
    sub: "Crew Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-navy-003.png',
    tryOnImageUrl: '/catalog/tee-navy-003.png',
    recommendationReason: "Navy is a cool tone with a classic, minimal vibe.",
  },
  {
    id: 'TEE-CHARCOAL-004',
    shopperCategory: 'tshirts',
    name: "Charcoal Slub V-Neck Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 27.5,
    color: '#36393b',
    textColor: '#ffffff',
    sub: "V-neck Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-charcoal-004.png',
    tryOnImageUrl: '/catalog/tee-charcoal-004.png',
    recommendationReason: "Charcoal is a neutral tone with a minimal, modern vibe.",
  },
  {
    id: 'TEE-CREAM-005',
    shopperCategory: 'tshirts',
    name: "Vintage Cream Boxy Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 34.9,
    color: '#efe6d2',
    textColor: '#2a2622',
    sub: "Crew Boxy",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-cream-005.png',
    tryOnImageUrl: '/catalog/tee-cream-005.png',
    recommendationReason: "Cream is a warm tone with a vintage, relaxed vibe.",
  },
  {
    id: 'TEE-TEAL-006',
    shopperCategory: 'tshirts',
    name: "Teal Ringer Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 26.0,
    color: '#128a86',
    textColor: '#ffffff',
    sub: "Ringer Crew Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-teal-006.png',
    tryOnImageUrl: '/catalog/tee-teal-006.png',
    recommendationReason: "Teal is a cool tone with a retro, streetwear vibe.",
  },
  {
    id: 'TEE-BLACK-007',
    shopperCategory: 'tshirts',
    name: "Midnight Black Crew Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 25.0,
    color: '#17181a',
    textColor: '#ffffff',
    sub: "Crew Fitted",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-black-007.png',
    tryOnImageUrl: '/catalog/tee-black-007.png',
    recommendationReason: "Black is a neutral tone with a minimal, versatile vibe.",
  },
  {
    id: 'TEE-WHITE-008',
    shopperCategory: 'tshirts',
    name: "Essential White Crew Tee",
    brand: 'LOMA',
    kind: 'TEE',
    price: 22.9,
    color: '#f4f4f1',
    textColor: '#2a2622',
    sub: "Crew Regular",
    material: "Heavyweight cotton jersey",
    fitNotes: "straight body, ribbed crew neck",
    imageUrl: '/catalog/tee-white-008.png',
    tryOnImageUrl: '/catalog/tee-white-008.png',
    recommendationReason: "White is a neutral tone with a essential, minimal vibe.",
  },
  {
    id: 'HAT-CAP-009',
    shopperCategory: 'hats',
    name: "Olive 6-Panel Cap",
    brand: 'LOMA',
    kind: 'CAP',
    price: 28.0,
    color: '#5b6230',
    textColor: '#ffffff',
    sub: "6-panel Cap",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-cap-009.png',
    tryOnImageUrl: '/catalog/hat-cap-009.png',
    recommendationReason: "Olive is a warm tone with a streetwear, outdoor vibe.",
  },
  {
    id: 'HAT-FEDORA-010',
    shopperCategory: 'hats',
    name: "Charcoal Short-Brim Fedora",
    brand: 'LOMA',
    kind: 'CAP',
    price: 59.9,
    color: '#3a3d40',
    textColor: '#ffffff',
    sub: "Short-brim Fedora",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-fedora-010.png',
    tryOnImageUrl: '/catalog/hat-fedora-010.png',
    recommendationReason: "Charcoal is a neutral tone with a smart-casual, classic vibe.",
  },
  {
    id: 'HAT-BEANIE-011',
    shopperCategory: 'hats',
    name: "Navy Ribbed Beanie",
    brand: 'LOMA',
    kind: 'CAP',
    price: 21.0,
    color: '#20304f',
    textColor: '#ffffff',
    sub: "Ribbed Beanie",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-beanie-011.png',
    tryOnImageUrl: '/catalog/hat-beanie-011.png',
    recommendationReason: "Navy is a cool tone with a casual, winter vibe.",
  },
  {
    id: 'HAT-BUCKET-012',
    shopperCategory: 'hats',
    name: "Rust Cotton Bucket Hat",
    brand: 'LOMA',
    kind: 'CAP',
    price: 33.0,
    color: '#a04b27',
    textColor: '#ffffff',
    sub: "Bucket Hat",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-bucket-012.png',
    tryOnImageUrl: '/catalog/hat-bucket-012.png',
    recommendationReason: "Rust is a warm tone with a streetwear, retro vibe.",
  },
  {
    id: 'HAT-CAP-013',
    shopperCategory: 'hats',
    name: "Black 5-Panel Cap",
    brand: 'LOMA',
    kind: 'CAP',
    price: 26.5,
    color: '#18191b',
    textColor: '#ffffff',
    sub: "5-panel Cap",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-cap-013.png',
    tryOnImageUrl: '/catalog/hat-cap-013.png',
    recommendationReason: "Black is a neutral tone with a streetwear, minimal vibe.",
  },
  {
    id: 'HAT-BEANIE-014',
    shopperCategory: 'hats',
    name: "Cream Cuffed Beanie",
    brand: 'LOMA',
    kind: 'CAP',
    price: 23.5,
    color: '#ece2cd',
    textColor: '#2a2622',
    sub: "Cuffed Beanie",
    material: "Structured cotton",
    fitNotes: "adjustable fit, structured crown",
    imageUrl: '/catalog/hat-beanie-014.png',
    tryOnImageUrl: '/catalog/hat-beanie-014.png',
    recommendationReason: "Cream is a warm tone with a casual, cozy vibe.",
  },
];

export const selectedDemoProductIds = ['TEE-OLIVE-001', 'HAT-CAP-009'];

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
