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

// Store catalog = the merchant's real products (sourced from /clothes-images). Product ids
// + images (served from /public/catalog) match catalog-store/store.json, so what the UI
// shows, what `recommend` scores, and what `tryon` renders all key off one identity.
export const lomaProducts: LomaProduct[] = [
  {
    id: 'HAT-NORTHFACE-001',
    shopperCategory: 'hats',
    name: "Classic Cap",
    brand: "The North Face",
    kind: 'CAP',
    price: 27.95,
    color: '#1b1b1d',
    textColor: '#ffffff',
    sub: "6-panel cap",
    material: "Cotton twill",
    fitNotes: "adjustable strap",
    imageUrl: '/catalog/hat-northface-001.png',
    tryOnImageUrl: '/catalog/hat-northface-001.png',
    recommendationReason: "Black neutral tone with a outdoor, minimal, streetwear vibe.",
  },
  {
    id: 'HAT-BOSS-002',
    shopperCategory: 'hats',
    name: "Zed Cap",
    brand: "BOSS",
    kind: 'CAP',
    price: 44.95,
    color: '#2c2c30',
    textColor: '#ffffff',
    sub: "Curved-brim cap",
    material: "Cotton twill",
    fitNotes: "adjustable strap",
    imageUrl: '/catalog/hat-boss-002.png',
    tryOnImageUrl: '/catalog/hat-boss-002.png',
    recommendationReason: "Charcoal neutral tone with a smart casual, minimal vibe.",
  },
  {
    id: 'HAT-DODGERS-003',
    shopperCategory: 'hats',
    name: "LA Dodgers Branson Trucker",
    brand: "'47",
    kind: 'CAP',
    price: 20.95,
    color: '#19191b',
    textColor: '#ffffff',
    sub: "Trucker cap",
    material: "Cotton / mesh",
    fitNotes: "snapback strap",
    imageUrl: '/catalog/hat-dodgers-003.png',
    tryOnImageUrl: '/catalog/hat-dodgers-003.png',
    recommendationReason: "Black neutral tone with a streetwear, sport, casual vibe.",
  },
  {
    id: 'HAT-VONDUTCH-004',
    shopperCategory: 'hats',
    name: "Eye Trucker Cap",
    brand: "Von Dutch",
    kind: 'CAP',
    price: 26.35,
    color: '#161618',
    textColor: '#ffffff',
    sub: "Trucker cap",
    material: "Cotton / mesh",
    fitNotes: "snapback strap",
    imageUrl: '/catalog/hat-vondutch-004.png',
    tryOnImageUrl: '/catalog/hat-vondutch-004.png',
    recommendationReason: "Black neutral tone with a streetwear, retro, bold vibe.",
  },
  {
    id: 'HAT-LYLE-005',
    shopperCategory: 'hats',
    name: "Eagle Baseball Cap",
    brand: "Lyle & Scott",
    kind: 'CAP',
    price: 17.55,
    color: '#141416',
    textColor: '#ffffff',
    sub: "Dad cap",
    material: "Cotton twill",
    fitNotes: "adjustable strap",
    imageUrl: '/catalog/hat-lyle-005.png',
    tryOnImageUrl: '/catalog/hat-lyle-005.png',
    recommendationReason: "Black neutral tone with a minimal, casual, heritage vibe.",
  },
  {
    id: 'TEE-MONOGRAM-001',
    shopperCategory: 'tshirts',
    name: "Monogram AOP Tee",
    brand: "adidas Originals",
    kind: 'TEE',
    price: 33.95,
    color: '#1c1c1e',
    textColor: '#ffffff',
    sub: "All-over monogram",
    material: "Cotton jersey",
    fitNotes: "regular fit, crew neck",
    imageUrl: '/catalog/tee-monogram-001.png',
    tryOnImageUrl: '/catalog/tee-monogram-001.png',
    recommendationReason: "Black neutral tone with a streetwear, bold vibe.",
  },
  {
    id: 'TEE-LUX-002',
    shopperCategory: 'tshirts',
    name: "Lux Color Graphic Tee",
    brand: "adidas Sportswear",
    kind: 'TEE',
    price: 34.95,
    color: '#4a4a4d',
    textColor: '#ffffff',
    sub: "Tie-dye graphic",
    material: "Cotton jersey",
    fitNotes: "regular fit, crew neck",
    imageUrl: '/catalog/tee-lux-002.png',
    tryOnImageUrl: '/catalog/tee-lux-002.png',
    recommendationReason: "Grey neutral tone with a streetwear, graphic vibe.",
  },
  {
    id: 'TEE-CAMO-003',
    shopperCategory: 'tshirts',
    name: "Seasonal Essentials Camo Tee",
    brand: "adidas Sportswear",
    kind: 'TEE',
    price: 34.95,
    color: '#6c6a3b',
    textColor: '#ffffff',
    sub: "Camo logo",
    material: "Cotton jersey",
    fitNotes: "regular fit, crew neck",
    imageUrl: '/catalog/tee-camo-003.png',
    tryOnImageUrl: '/catalog/tee-camo-003.png',
    recommendationReason: "Olive warm tone with a streetwear, military, casual vibe.",
  },
  {
    id: 'TEE-SHAPE-004',
    shopperCategory: 'tshirts',
    name: "Camo Shape Graphic Tee",
    brand: "adidas Sportswear",
    kind: 'TEE',
    price: 24.95,
    color: '#1a1a1c',
    textColor: '#ffffff',
    sub: "Camo shape graphic",
    material: "Cotton jersey",
    fitNotes: "regular fit, crew neck",
    imageUrl: '/catalog/tee-shape-004.png',
    tryOnImageUrl: '/catalog/tee-shape-004.png',
    recommendationReason: "Black neutral tone with a streetwear, sport vibe.",
  },
  {
    id: 'TEE-TIRO-005',
    shopperCategory: 'tshirts',
    name: "House of Tiro Tee",
    brand: "adidas Sportswear",
    kind: 'TEE',
    price: 29.35,
    color: '#efe9da',
    textColor: '#2a2622',
    sub: "Retro graphic",
    material: "Recycled jersey",
    fitNotes: "regular fit, crew neck",
    imageUrl: '/catalog/tee-tiro-005.png',
    tryOnImageUrl: '/catalog/tee-tiro-005.png',
    recommendationReason: "Cream warm tone with a sport, retro, streetwear vibe.",
  },
];

export const selectedDemoProductIds = ['TEE-CAMO-003', 'HAT-LYLE-005'];

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
