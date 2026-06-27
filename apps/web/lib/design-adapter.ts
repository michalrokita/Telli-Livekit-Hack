import {
  getCartSummary,
  isShopperCategory,
  type CartSummary,
  type CustomerQualities,
  type ProductRecommendation,
  type ShopperCategory,
  type TryOnJob,
} from './shopper-flow';

export type ShopperFlowFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type DesignCategoryId = 'hats' | 'tshirts';

export type DesignCategoryChoice =
  | {
      category: ShopperCategory;
      label: string;
      styleGoal: string;
      supported: true;
    }
  | {
      category: null;
      label: string;
      styleGoal: string;
      supported: false;
    };

export type DesignVoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking';

export type DesignDemoFlowInput = {
  category: DesignCategoryId | ShopperCategory | string;
  imageDataUrl: string;
  customerImageId?: string;
  selectedProductIds?: string[];
  selectedCount?: number;
  styleGoal?: string;
};

export type ShopperDemoFlowResult = {
  category: ShopperCategory;
  customerImageId: string;
  analysis: CustomerQualities;
  products: ProductRecommendation[];
  selectedProductIds: string[];
  tryOnJobs: TryOnJob[];
  cartSummary: CartSummary;
};

export type ShopperFlowClientOptions = {
  baseUrl?: string;
  fetch?: ShopperFlowFetch;
};

type AnalyzeImageResponse = {
  analysis: CustomerQualities;
};

type SearchProductsResponse = {
  products: ProductRecommendation[];
};

type GenerateTryOnResponse = {
  jobs: TryOnJob[];
};

const DEFAULT_CUSTOMER_IMAGE_ID = 'customer-design-demo';

export const DESIGN_VOICE_STATES: readonly DesignVoiceState[] = [
  'idle',
  'connecting',
  'listening',
  'thinking',
  'speaking',
] as const;

export const DESIGN_CATEGORY_CHOICES: readonly (DesignCategoryChoice & { id: DesignCategoryId })[] = [
  {
    id: 'hats',
    category: 'hats',
    label: 'Hats',
    styleGoal: 'finish the look',
    supported: true,
  },
  {
    id: 'tshirts',
    category: 'tshirts',
    label: 'T-shirts',
    styleGoal: 'clean summer basics',
    supported: true,
  },
] as const;

export class ShopperFlowApiError extends Error {
  constructor(
    readonly endpoint: string,
    readonly status: number,
    message: string,
    readonly payload: unknown,
  ) {
    super(message);
    this.name = 'ShopperFlowApiError';
  }
}

export function getDesignCategoryChoice(value: unknown): DesignCategoryChoice {
  const choice = DESIGN_CATEGORY_CHOICES.find((item) => item.id === value);

  if (choice) {
    return {
      category: choice.category,
      label: choice.label,
      styleGoal: choice.styleGoal,
      supported: choice.supported,
    } as DesignCategoryChoice;
  }

  if (isShopperCategory(value)) {
    return {
      category: value,
      label: value === 'hats' ? 'Hats' : 'T-shirts',
      styleGoal: value === 'hats' ? 'finish the look' : 'clean summer basics',
      supported: true,
    };
  }

  return {
    category: null,
    label: 'Looks',
    styleGoal: '',
    supported: false,
  };
}

export async function analyzeShopperImage(
  input: { imageDataUrl: string; category: ShopperCategory },
  options: ShopperFlowClientOptions = {},
): Promise<CustomerQualities> {
  const response = await postJson<AnalyzeImageResponse>('/api/mock/analyze-image', input, options);
  return response.analysis;
}

export async function searchShopperProducts(
  input: { category: ShopperCategory; styleGoal?: string; qualities: CustomerQualities },
  options: ShopperFlowClientOptions = {},
): Promise<ProductRecommendation[]> {
  const response = await postJson<SearchProductsResponse>('/api/mock/search-products', input, options);
  return response.products;
}

export async function generateShopperTryOns(
  input: {
    customerImageId: string;
    customerImageDataUrl?: string;
    products: ProductRecommendation[];
    selectedProductIds: string[];
  },
  options: ShopperFlowClientOptions = {},
): Promise<TryOnJob[]> {
  const response = await postJson<GenerateTryOnResponse>('/api/mock/generate-tryon', input, options);
  return response.jobs;
}

export async function runShopperDemoFlow(
  input: DesignDemoFlowInput,
  options: ShopperFlowClientOptions = {},
): Promise<ShopperDemoFlowResult> {
  const choice = getDesignCategoryChoice(input.category);

  if (!choice.supported) {
    throw new Error(`Unsupported shopper category: ${String(input.category)}`);
  }

  const customerImageId = input.customerImageId ?? DEFAULT_CUSTOMER_IMAGE_ID;
  const analysis = await analyzeShopperImage(
    {
      imageDataUrl: input.imageDataUrl,
      category: choice.category,
    },
    options,
  );
  const products = await searchShopperProducts(
    {
      category: choice.category,
      styleGoal: input.styleGoal ?? choice.styleGoal,
      qualities: analysis,
    },
    options,
  );
  const selectedProductIds =
    input.selectedProductIds ?? products.slice(0, input.selectedCount ?? 2).map((product) => product.id);
  const tryOnJobs = await generateShopperTryOns(
    {
      customerImageId,
      customerImageDataUrl: input.imageDataUrl,
      products,
      selectedProductIds,
    },
    options,
  );
  const cartSummary = getCartSummary(
    tryOnJobs.map((job) => ({
      productId: job.productId,
      quantity: 1,
    })),
  );

  return {
    category: choice.category,
    customerImageId,
    analysis,
    products,
    selectedProductIds,
    tryOnJobs,
    cartSummary,
  };
}

async function postJson<T>(
  endpoint: string,
  body: unknown,
  options: ShopperFlowClientOptions,
): Promise<T> {
  const fetcher = getFetch(options.fetch);
  const url = resolveEndpoint(endpoint, options.baseUrl);
  const response = await fetcher(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const payload = await readJson(response);

  if (!response.ok) {
    throw new ShopperFlowApiError(endpoint, response.status, getErrorMessage(payload), payload);
  }

  return payload as T;
}

function getFetch(fetcher?: ShopperFlowFetch): ShopperFlowFetch {
  const resolved = fetcher ?? globalThis.fetch?.bind(globalThis);

  if (!resolved) {
    throw new Error('fetch is required to call shopper-flow endpoints.');
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

function getErrorMessage(payload: unknown): string {
  if (payload && typeof payload === 'object' && 'error' in payload) {
    const error = (payload as { error?: unknown }).error;

    if (typeof error === 'string' && error.trim().length > 0) {
      return error;
    }
  }

  return 'Shopper flow request failed.';
}
