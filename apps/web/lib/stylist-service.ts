import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import {
  analyzeCustomerImage,
  createTryOnJobs,
  type AnalyzeCustomerImageInput,
  type CustomerQualities,
  type ProductRecommendation,
  type ShopperCategory,
  type TryOnJob,
} from './shopper-flow';

const GENERATED_AT = '2026-06-27T00:00:00.000Z';

type StylistRequestBase = {
  imagePath: string;
};

export type StylistAnalyzeRequest = StylistRequestBase & {
  kind: 'analyze';
};

export type StylistTryOnRequest = StylistRequestBase & {
  kind: 'tryon';
  optionIds: string[];
  catalog?: Record<string, string>;
};

export type StylistPythonRequest = StylistAnalyzeRequest | StylistTryOnRequest;

export type StylistPythonResult = {
  ok: boolean;
  stdout: string;
  stderr?: string;
};

export type StylistPythonRunner = (request: StylistPythonRequest) => StylistPythonResult;

type TryOnResult = {
  image_url?: unknown;
  image_data_url?: unknown;
  status?: unknown;
  rendered_option_ids?: unknown;
  retry_count?: unknown;
  critic_report?: unknown;
};

type TryOnInput = {
  customerImageId: string;
  customerImageDataUrl?: string;
  products: ProductRecommendation[];
  selectedProductIds: string[];
  runner?: StylistPythonRunner;
};

const REPO_ROOT = process.env.STYLIST_REPO_ROOT ?? resolve(process.cwd(), '..', '..');
const REPO_VENV_PYTHON = resolve(REPO_ROOT, 'apps', 'agent', '.venv', 'bin', 'python');

export function resolveStylistRuntimeEnv(
  source: Record<string, string | undefined>,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env, ...source };

  if (!env.STYLIST_LIVE && env.OPENAI_API_KEY) {
    env.STYLIST_LIVE = '1';
  }

  return env;
}

function isLiveStylistMode() {
  return resolveStylistRuntimeEnv(process.env).STYLIST_LIVE === '1';
}

function parseDataUrl(dataUrl: string): { buffer: Buffer; extension: string } | null {
  const match = /^data:([^;,]+)?(;base64)?,(.*)$/s.exec(dataUrl);
  if (!match) {
    return null;
  }

  const mime = match[1] ?? 'image/png';
  const isBase64 = Boolean(match[2]);
  const payload = match[3] ?? '';
  const extension = mime.includes('jpeg') || mime.includes('jpg') ? 'jpg' : 'png';

  try {
    return {
      buffer: isBase64 ? Buffer.from(payload, 'base64') : Buffer.from(decodeURIComponent(payload)),
      extension,
    };
  } catch {
    return null;
  }
}

function withTempImage<T>(dataUrl: string, run: (imagePath: string) => T): T | null {
  const decoded = parseDataUrl(dataUrl);
  if (!decoded || decoded.buffer.length === 0) {
    return null;
  }

  const dir = mkdtempSync(join(tmpdir(), 'stylist-web-'));
  const imagePath = join(dir, `input.${decoded.extension}`);

  try {
    writeFileSync(imagePath, decoded.buffer);
    return run(imagePath);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

async function withTempTryOnImages<T>(
  imageDataUrl: string,
  products: ProductRecommendation[],
  selectedProductIds: string[],
  run: (imagePath: string, catalog: Record<string, string>) => T,
): Promise<T | null> {
  const decoded = parseDataUrl(imageDataUrl);
  if (!decoded || decoded.buffer.length === 0) {
    return null;
  }

  const dir = mkdtempSync(join(tmpdir(), 'stylist-web-'));
  const imagePath = join(dir, `input.${decoded.extension}`);

  try {
    writeFileSync(imagePath, decoded.buffer);

    const productsById = new Map(products.map((product) => [product.id, product]));
    const catalog: Record<string, string> = {};

    for (const productId of selectedProductIds) {
      const product = productsById.get(productId);
      if (!product) {
        continue;
      }

      const productPath = await writeRemoteImage(product.imageUrl, dir, product.id);
      if (productPath) {
        catalog[product.id] = productPath;
      }
    }

    return run(imagePath, catalog);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

async function writeRemoteImage(url: string, dir: string, id: string): Promise<string | null> {
  if (url.startsWith('data:image/')) {
    const decoded = parseDataUrl(url);
    if (!decoded || decoded.buffer.length === 0) {
      return null;
    }
    const path = join(dir, `${id}.${decoded.extension}`);
    writeFileSync(path, decoded.buffer);
    return path;
  }

  if (!url.startsWith('https://') && !url.startsWith('http://')) {
    return null;
  }

  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }

    const contentType = response.headers.get('content-type') ?? '';
    const extension = contentType.includes('jpeg') || contentType.includes('jpg') ? 'jpg' : 'png';
    const path = join(dir, `${id}.${extension}`);
    writeFileSync(path, Buffer.from(await response.arrayBuffer()));
    return path;
  } catch {
    return null;
  }
}

function parseJsonObject(stdout: string): unknown | null {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

function normalizeWords(value: unknown, fallback: string): string {
  if (typeof value !== 'string') {
    return fallback;
  }

  const normalized = value.replace(/_/g, ' ').trim();
  return normalized.length > 0 ? normalized : fallback;
}

function normalizeContrast(value: unknown): CustomerQualities['contrast'] {
  return value === 'low' || value === 'medium' || value === 'high' ? value : 'medium';
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function readableCategory(category: ShopperCategory): string {
  return category === 'hats' ? 'hats' : 't-shirts';
}

export function mapStyleProfileToCustomerQualities(profile: unknown, category: ShopperCategory): CustomerQualities {
  const root = profile && typeof profile === 'object' ? (profile as Record<string, unknown>) : {};
  const coloring =
    root.coloring && typeof root.coloring === 'object' ? (root.coloring as Record<string, unknown>) : {};
  const currentStyle =
    root.current_style && typeof root.current_style === 'object'
      ? (root.current_style as Record<string, unknown>)
      : {};

  const hairColor = normalizeWords(coloring.hair_color, 'natural hair color');
  const skinDepth = normalizeWords(coloring.skin_depth, 'medium');
  const undertone = normalizeWords(coloring.skin_undertone, 'neutral');
  const contrast = normalizeContrast(coloring.contrast_level);
  const palette = normalizeWords(coloring.season, 'balanced');
  const cues = stringList(coloring.undertone_cues);
  const vibes = stringList(currentStyle.detected_vibe);
  const currentlyWearing = normalizeWords(currentStyle.currently_wearing, '');
  const styleNotes = [
    `palette: ${palette}`,
    ...cues,
    ...(vibes.length > 0 ? [vibes.join(', ')] : []),
    ...(currentlyWearing ? [`currently wearing: ${currentlyWearing}`] : []),
  ].filter((note) => note.trim().length > 0);

  return {
    hairColor,
    skinTone: `${skinDepth} ${undertone}`.trim(),
    contrast,
    undertone,
    palette,
    styleNotes:
      styleNotes.length > 0
        ? styleNotes
        : ['warm neutrals and clean contrast will keep the look camera-ready'],
    summary: `For ${readableCategory(category)}, lean into a ${palette} palette, ${contrast} contrast, and ${undertone} undertones.`,
  };
}

function defaultPythonRunner(request: StylistPythonRequest): StylistPythonResult {
  const env = resolveStylistRuntimeEnv(process.env);
  const python = env.STYLIST_PYTHON ?? (existsSync(REPO_VENV_PYTHON) ? REPO_VENV_PYTHON : 'python3');

  if (request.kind === 'analyze') {
    const cassette = env.STYLIST_ANALYZE_CASSETTE ?? (env.STYLIST_LIVE === '1' ? '' : 'analyze_good');
    const script = [
      'import json, os, sys',
      'from stylist.analyze import analyze',
      'cassette = os.environ.get("STYLIST_ANALYZE_CASSETTE") or None',
      'profile = analyze(sys.argv[1], cassette=cassette)',
      'print(json.dumps(profile.to_dict()))',
    ].join('; ');

    if (cassette) {
      env.STYLIST_ANALYZE_CASSETTE = cassette;
    }

    const result = spawnSync(python, ['-c', script, request.imagePath], {
      cwd: REPO_ROOT,
      env,
      encoding: 'utf8',
      timeout: 120_000,
    });

    return {
      ok: result.status === 0,
      stdout: result.stdout ?? '',
      stderr: result.stderr ?? result.error?.message,
    };
  }

  const cassette = env.STYLIST_TRYON_CASSETTE ?? (env.STYLIST_LIVE === '1' ? '' : 'tryon_hat');
  // The brain writes the rendered PNG to a local path the browser can't read, so we
  // inline it as a base64 data URL the UI can show directly.
  const script = [
    'import json, os, sys, base64',
    'from stylist.tryon import tryon',
    'cassette = os.environ.get("STYLIST_TRYON_CASSETTE") or None',
    'catalog = json.loads(os.environ.get("STYLIST_TRYON_CATALOG") or "{}") or None',
    'result = tryon(sys.argv[1], sys.argv[2:], catalog=catalog, cassette=cassette)',
    'data = result.to_dict()',
    'path = data.get("image_url")',
    'if isinstance(path, str) and os.path.exists(path):',
    '    with open(path, "rb") as handle:',
    '        data["image_data_url"] = "data:image/png;base64," + base64.b64encode(handle.read()).decode("ascii")',
    'print(json.dumps(data))',
  ].join('\n');

  if (cassette) {
    env.STYLIST_TRYON_CASSETTE = cassette;
  }
  if (request.catalog && Object.keys(request.catalog).length > 0) {
    env.STYLIST_TRYON_CATALOG = JSON.stringify(request.catalog);
  }

  const result = spawnSync(python, ['-c', script, request.imagePath, ...request.optionIds], {
    cwd: REPO_ROOT,
    env,
    encoding: 'utf8',
    timeout: 180_000,
    maxBuffer: 64 * 1024 * 1024,
  });

  return {
    ok: result.status === 0,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? result.error?.message,
  };
}

export type StylistAnalysis = { qualities: CustomerQualities; profile: unknown };

export async function tryAnalyzeWithStylist({
  imageDataUrl,
  category,
  runner = defaultPythonRunner,
}: AnalyzeCustomerImageInput & { runner?: StylistPythonRunner }): Promise<StylistAnalysis | null> {
  try {
    return withTempImage(imageDataUrl, (imagePath) => {
      const result = runner({ kind: 'analyze', imagePath });
      if (!result.ok) {
        return null;
      }

      const profile = parseJsonObject(result.stdout);
      if (!profile || typeof profile !== 'object') {
        return null;
      }

      // The raw StyleProfile dict is threaded to the voice agent so it can run the
      // brain's `recommend` over the same profile (not a lossy re-derivation).
      return { qualities: mapStyleProfileToCustomerQualities(profile, category), profile };
    });
  } catch {
    return null;
  }
}

function isBrowserReadableUrl(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    (value.startsWith('https://') ||
      value.startsWith('http://') ||
      (value.startsWith('/') && !value.startsWith('/tmp/') && !value.startsWith('/var/') && !value.startsWith('/Users/')) ||
      value.startsWith('data:image/'))
  );
}

function mapTryOnResultToJobs(input: TryOnInput, result: TryOnResult): TryOnJob[] | null {
  const productsById = new Map(input.products.map((product) => [product.id, product]));
  const renderedIds = stringList(result.rendered_option_ids);
  const renderedSet = new Set(renderedIds);
  // Prefer the inlined render (data URL); fall back to a browser-readable image_url.
  const imageUrl = isBrowserReadableUrl(result.image_data_url)
    ? (result.image_data_url as string)
    : isBrowserReadableUrl(result.image_url)
      ? (result.image_url as string)
      : null;

  return input.selectedProductIds.flatMap((productId, index) => {
    const product = productsById.get(productId);
    if (!product) {
      return [];
    }

    return [
      {
        id: `tryon-${input.customerImageId}-${product.id}-${index + 1}`,
        customerImageId: input.customerImageId,
        productId: product.id,
        productName: product.name,
        status: 'complete',
        imageUrl: imageUrl && renderedSet.has(product.id) ? imageUrl : product.tryOnImageUrl,
        generatedAt: GENERATED_AT,
      },
    ];
  });
}

export async function tryCreateTryOnJobsWithStylist(input: TryOnInput): Promise<TryOnJob[] | null> {
  if (!input.customerImageDataUrl) {
    return null;
  }

  try {
    return await withTempTryOnImages(
      input.customerImageDataUrl,
      input.products,
      input.selectedProductIds,
      (imagePath, catalog) => {
        const result = (input.runner ?? defaultPythonRunner)({
          kind: 'tryon',
          imagePath,
          optionIds: input.selectedProductIds,
          catalog,
        });

        if (!result.ok) {
          return null;
        }

        const parsed = parseJsonObject(result.stdout);
        if (!parsed || typeof parsed !== 'object') {
          return null;
        }

        return mapTryOnResultToJobs(input, parsed as TryOnResult);
      },
    );
  } catch {
    return null;
  }
}

export const createTryOnJobsWithStylistFallback = {
  async analyze(
    input: AnalyzeCustomerImageInput & { runner?: StylistPythonRunner },
  ): Promise<{ analysis: CustomerQualities; profile: unknown | null }> {
    const analysis = await tryAnalyzeWithStylist(input);

    if (analysis) {
      return { analysis: analysis.qualities, profile: analysis.profile };
    }

    if (isLiveStylistMode()) {
      throw new Error('Live stylist image analysis failed.');
    }

    return { analysis: await analyzeCustomerImage(input), profile: null };
  },

  async tryOns(input: TryOnInput): Promise<TryOnJob[]> {
    const jobs = await tryCreateTryOnJobsWithStylist(input);

    if (jobs) {
      return jobs;
    }

    if (isLiveStylistMode()) {
      throw new Error('Live stylist try-on generation failed.');
    }

    return createTryOnJobs({
      customerImageId: input.customerImageId,
      products: input.products,
      selectedProductIds: input.selectedProductIds,
    });
  },
};
