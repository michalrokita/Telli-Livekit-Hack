import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEB_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_DIR = resolve(WEB_DIR, '../..');

for (const filename of ['.env.local', '.env']) {
  loadRootEnvFile(resolve(REPO_DIR, filename));
}

function loadRootEnvFile(path) {
  if (!existsSync(path)) {
    return;
  }

  for (const rawLine of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }

    const separatorIndex = line.indexOf('=');
    if (separatorIndex <= 0) {
      continue;
    }

    const key = line.slice(0, separatorIndex).trim();
    const value = stripEnvQuotes(line.slice(separatorIndex + 1).trim());
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

function stripEnvQuotes(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'images.unsplash.com',
      },
    ],
  },
};

export default nextConfig;
