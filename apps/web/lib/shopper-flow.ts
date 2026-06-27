export const SHOPPER_CATEGORIES = ['hats', 'tshirts'] as const;

export type ShopperCategory = (typeof SHOPPER_CATEGORIES)[number];

export type CustomerQualities = {
  hairColor: string;
  skinTone: string;
  contrast: 'low' | 'medium' | 'high';
  undertone: string;
  palette?: string;
  styleNotes: string[];
  summary: string;
};

export type AnalyzeCustomerImageInput = {
  imageDataUrl: string;
  category: ShopperCategory;
};

export type ProductRecommendation = {
  id: string;
  category: ShopperCategory;
  name: string;
  brand: string;
  price: number;
  currency: 'USD';
  imageUrl: string;
  tryOnImageUrl: string;
  colorStory: string;
  material: string;
  fitNotes: string;
  recommendationReason: string;
};

export type RecommendProductsInput = {
  category: ShopperCategory;
  styleGoal?: string;
  qualities: CustomerQualities;
};

export type TryOnJob = {
  id: string;
  customerImageId: string;
  productId: string;
  productName: string;
  status: 'complete';
  imageUrl: string;
  generatedAt: string;
};

export type CreateTryOnJobsInput = {
  customerImageId: string;
  products: ProductRecommendation[];
  selectedProductIds: string[];
};

export type CartItem = {
  productId: string;
  quantity: number;
};

export type CartSummary = {
  itemCount: number;
  justAddedCount: number;
  isEmpty: boolean;
};

const GENERATED_AT = '2026-06-27T00:00:00.000Z';

const image = (photoId: string) =>
  `https://images.unsplash.com/${photoId}?auto=format&fit=crop&w=1200&q=85`;

const HAT_PRODUCTS: ProductRecommendation[] = [
  {
    id: 'hat-1',
    category: 'hats',
    name: 'Marseille Straw Panama',
    brand: 'Atelier Cove',
    price: 84,
    currency: 'USD',
    imageUrl: image('photo-1521369909029-2afed882baee'),
    tryOnImageUrl: image('photo-1514327605112-b887c0e61c0a'),
    colorStory: 'honey straw with a matte black ribbon',
    material: 'woven palm straw',
    fitNotes: 'structured crown, medium brim, lightweight summer feel',
    recommendationReason: 'Brightens warm undertones while keeping the silhouette polished.',
  },
  {
    id: 'hat-2',
    category: 'hats',
    name: 'Noir Felt Fedora',
    brand: 'Northline Studio',
    price: 112,
    currency: 'USD',
    imageUrl: image('photo-1506629905607-d9f297d96d6d'),
    tryOnImageUrl: image('photo-1496747611176-843222e1e57c'),
    colorStory: 'soft black felt with charcoal grosgrain',
    material: 'brushed wool felt',
    fitNotes: 'pinched crown, clean brim edge, city-ready structure',
    recommendationReason: 'Adds crisp contrast and frames darker hair without looking severe.',
  },
  {
    id: 'hat-3',
    category: 'hats',
    name: 'Olive Canvas Cap',
    brand: 'Field Theory',
    price: 42,
    currency: 'USD',
    imageUrl: image('photo-1542291026-7eec264c27ff'),
    tryOnImageUrl: image('photo-1529139574466-a303027c1d8b'),
    colorStory: 'muted olive with tonal stitching',
    material: 'washed cotton canvas',
    fitNotes: 'low profile, curved brim, adjustable back strap',
    recommendationReason: 'A relaxed option that pairs naturally with golden and olive skin tones.',
  },
  {
    id: 'hat-4',
    category: 'hats',
    name: 'Ivory Boucle Bucket',
    brand: 'Maison Relay',
    price: 58,
    currency: 'USD',
    imageUrl: image('photo-1534215754734-18e55d13e346'),
    tryOnImageUrl: image('photo-1503342217505-b0a15ec3261c'),
    colorStory: 'warm ivory with soft boucle texture',
    material: 'cotton boucle blend',
    fitNotes: 'soft crown, relaxed brim, packable shape',
    recommendationReason: 'Soft texture keeps the look premium while lifting the face.',
  },
  {
    id: 'hat-5',
    category: 'hats',
    name: 'Cocoa Suede Baseball Hat',
    brand: 'Kindred Goods',
    price: 66,
    currency: 'USD',
    imageUrl: image('photo-1515886657613-9f3515b0c78f'),
    tryOnImageUrl: image('photo-1524504388940-b1c1722653e1'),
    colorStory: 'rich cocoa suede with antique brass adjuster',
    material: 'vegan suede',
    fitNotes: 'six-panel shape, gently curved brim, tailored casual finish',
    recommendationReason: 'Warmer than black and more elevated than a basic cotton cap.',
  },
];

const TSHIRT_PRODUCTS: ProductRecommendation[] = [
  {
    id: 'tshirt-1',
    category: 'tshirts',
    name: 'Cloud Supima Crew',
    brand: 'Common Form',
    price: 46,
    currency: 'USD',
    imageUrl: image('photo-1521572163474-6864f9cf17ab'),
    tryOnImageUrl: image('photo-1503342217505-b0a15ec3261c'),
    colorStory: 'soft white with a warm cast',
    material: 'supima cotton jersey',
    fitNotes: 'clean crew neck, easy body, sleeves that sit mid-bicep',
    recommendationReason: 'A premium basic that keeps summer looks bright without stark contrast.',
  },
  {
    id: 'tshirt-2',
    category: 'tshirts',
    name: 'Sage Mercer Tee',
    brand: 'Palette House',
    price: 54,
    currency: 'USD',
    imageUrl: image('photo-1503341504253-dff4815485f1'),
    tryOnImageUrl: image('photo-1529139574466-a303027c1d8b'),
    colorStory: 'dusty sage green',
    material: 'mercerized cotton',
    fitNotes: 'slim shoulder, straight body, subtle sheen',
    recommendationReason: 'Echoes olive undertones and reads refined in natural light.',
  },
  {
    id: 'tshirt-3',
    category: 'tshirts',
    name: 'Washed Black Box Tee',
    brand: 'Loom Archive',
    price: 62,
    currency: 'USD',
    imageUrl: image('photo-1562157873-818bc0726f68'),
    tryOnImageUrl: image('photo-1496747611176-843222e1e57c'),
    colorStory: 'sun-faded black',
    material: 'heavyweight organic cotton',
    fitNotes: 'boxy cut, dropped shoulder, dense drape',
    recommendationReason: 'Creates definition for medium contrast styling without looking flat.',
  },
  {
    id: 'tshirt-4',
    category: 'tshirts',
    name: 'Terracotta Rib Baby Tee',
    brand: 'Soft Signal',
    price: 38,
    currency: 'USD',
    imageUrl: image('photo-1554568218-0f1715e72254'),
    tryOnImageUrl: image('photo-1517841905240-472988babdf9'),
    colorStory: 'warm terracotta',
    material: 'ribbed cotton modal',
    fitNotes: 'close fit, slight crop, soft neckline',
    recommendationReason: 'Adds warmth near the face and works especially well with gold jewelry.',
  },
  {
    id: 'tshirt-5',
    category: 'tshirts',
    name: 'Ink Stripe Relaxed Tee',
    brand: 'Harbor Mark',
    price: 49,
    currency: 'USD',
    imageUrl: image('photo-1581655353564-df123a1eb820'),
    tryOnImageUrl: image('photo-1524504388940-b1c1722653e1'),
    colorStory: 'cream base with ink navy stripe',
    material: 'combed cotton',
    fitNotes: 'relaxed torso, open crew, easy tuck length',
    recommendationReason: 'Gives a styled point of view while staying in clean basic territory.',
  },
];

const PRODUCTS_BY_CATEGORY: Record<ShopperCategory, ProductRecommendation[]> = {
  hats: HAT_PRODUCTS,
  tshirts: TSHIRT_PRODUCTS,
};

export function isShopperCategory(value: unknown): value is ShopperCategory {
  return typeof value === 'string' && SHOPPER_CATEGORIES.includes(value as ShopperCategory);
}

export async function analyzeCustomerImage({
  category,
}: AnalyzeCustomerImageInput): Promise<CustomerQualities> {
  const categoryLabel = category === 'hats' ? 'hat' : 't-shirt';

  return {
    hairColor: 'dark brown with soft espresso highlights',
    skinTone: 'warm olive',
    contrast: 'medium',
    undertone: 'golden',
    styleNotes: [
      'warm neutrals and muted earth tones will look expensive on camera',
      'soft structure keeps the outfit polished without feeling formal',
      'matte textures will flatter the complexion more than high shine',
      `${categoryLabel} picks should frame the face with clean, intentional contrast`,
    ],
    summary: `The selected ${categoryLabel} category should lean warm, softly structured, and camera-ready for a premium shopping demo.`,
  };
}

export async function recommendProducts({
  category,
  styleGoal,
  qualities,
}: RecommendProductsInput): Promise<ProductRecommendation[]> {
  const products = PRODUCTS_BY_CATEGORY[category].slice(0, 5);
  const goal = styleGoal?.trim();

  return products.map((product) => ({
    ...product,
    recommendationReason: goal
      ? `${product.recommendationReason} It also fits the requested "${goal}" direction for ${qualities.skinTone} coloring.`
      : product.recommendationReason,
  }));
}

export async function createTryOnJobs({
  customerImageId,
  products,
  selectedProductIds,
}: CreateTryOnJobsInput): Promise<TryOnJob[]> {
  const productsById = new Map(products.map((product) => [product.id, product]));

  return selectedProductIds.flatMap((productId, index) => {
    const product = productsById.get(productId);

    if (!product) {
      return [];
    }

    return [
      {
        id: `tryon-${customerImageId}-${product.id}-${index + 1}`,
        customerImageId,
        productId: product.id,
        productName: product.name,
        status: 'complete',
        imageUrl: product.tryOnImageUrl,
        generatedAt: GENERATED_AT,
      },
    ];
  });
}

export function getCartSummary(items: CartItem[]): CartSummary {
  const activeItems = items.filter((item) => item.quantity > 0);
  const itemCount = activeItems.reduce((total, item) => total + item.quantity, 0);

  return {
    itemCount,
    justAddedCount: activeItems.length,
    isEmpty: itemCount === 0,
  };
}
