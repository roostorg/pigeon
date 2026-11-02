import { PigeonError } from './errors.js';

export type PigeonOrgConfig = Readonly<{
  apiKey: string;
  /** Validated origin, e.g. `https://pigeon.example.com`. No trailing slash. */
  baseUrl: string;
}>;

export type Env = Readonly<Record<string, string | undefined>>;

const MAX_API_KEY_LENGTH = 4096;
const MAX_URL_LENGTH = 2000;
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);
const TRUE_VALUES = new Set(['1', 'true', 'yes']);

function readString(raw: Record<string, unknown>, key: string): string | undefined {
  const value = raw[key];
  if (value == null) return undefined;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value !== 'string') {
    throw new PigeonError('INVALID_CONFIG', `"${key}" must be a string.`);
  }
  const trimmed = value.normalize('NFC').trim();
  if (trimmed.includes('\u0000')) {
    throw new PigeonError('INVALID_CONFIG', `"${key}" contains invalid characters.`);
  }
  return trimmed === '' ? undefined : trimmed;
}

/** True when the org has entered an API key; does not validate the rest. */
export function hasApiKey(raw: Record<string, unknown>): boolean {
  const value = raw['apiKey'];
  return typeof value === 'string' && value.trim() !== '';
}

function parseApiKey(raw: Record<string, unknown>): string {
  const apiKey = readString(raw, 'apiKey');
  if (apiKey === undefined) {
    throw new PigeonError(
      'NOT_CONFIGURED',
      'Add your Pigeon API key on the Pigeon integration page.',
    );
  }
  if (apiKey.length > MAX_API_KEY_LENGTH || /[\s\p{Cc}]/u.test(apiKey)) {
    throw new PigeonError(
      'INVALID_CONFIG',
      'The Pigeon API key is malformed (it must not contain spaces or control characters).',
    );
  }
  return apiKey;
}

/**
 * Parses `PIGEON_ALLOWED_HOSTS`: comma-separated hostnames (with optional
 * port), lowercased. `*.example.com` matches subdomains of example.com but not
 * example.com itself.
 */
export function parseAllowedHosts(env: Env): readonly string[] {
  return (env['PIGEON_ALLOWED_HOSTS'] ?? '')
    .split(',')
    .map((entry) => entry.trim().toLowerCase())
    .filter((entry) => entry !== '');
}

function hostMatches(url: URL, pattern: string): boolean {
  const hostname = url.hostname.toLowerCase();
  const host = url.host.toLowerCase();
  if (pattern.startsWith('*.')) {
    const suffix = pattern.slice(1);
    return hostname.endsWith(suffix) && hostname.length > suffix.length;
  }
  return pattern === hostname || pattern === host;
}

/**
 * Validates a Pigeon base URL against the Coop operator's allowlist. Only
 * `https:` origins are accepted, except `http:` on loopback hosts when
 * `PIGEON_ALLOW_INSECURE_LOCALHOST` is set (local development only).
 */
export function validateBaseUrl(value: string, env: Env): string {
  if (value.length > MAX_URL_LENGTH) {
    throw new PigeonError('INVALID_CONFIG', 'The Pigeon base URL is too long.');
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new PigeonError('INVALID_CONFIG', 'The Pigeon base URL is not a valid URL.');
  }
  if (url.username !== '' || url.password !== '') {
    throw new PigeonError(
      'INVALID_CONFIG',
      'The Pigeon base URL must not contain credentials; put the key in the API key field.',
    );
  }
  if ((url.pathname !== '/' && url.pathname !== '') || url.search !== '' || url.hash !== '') {
    throw new PigeonError(
      'INVALID_CONFIG',
      'The Pigeon base URL must be an origin only, e.g. https://pigeon.example.com (no path, query, or fragment).',
    );
  }
  const isLoopback = LOOPBACK_HOSTS.has(url.hostname.toLowerCase());
  const allowInsecureLocalhost = TRUE_VALUES.has(
    (env['PIGEON_ALLOW_INSECURE_LOCALHOST'] ?? '').trim().toLowerCase(),
  );
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback && allowInsecureLocalhost)) {
    throw new PigeonError('INVALID_CONFIG', 'The Pigeon base URL must use https.');
  }
  const allowedHosts = parseAllowedHosts(env);
  if (!allowedHosts.some((pattern) => hostMatches(url, pattern))) {
    throw new PigeonError(
      'INVALID_CONFIG',
      `The Pigeon host "${url.host}" is not allowed. Ask your Coop operator to add it to PIGEON_ALLOWED_HOSTS.`,
    );
  }
  return url.origin;
}

function parseBaseUrl(raw: Record<string, unknown>, env: Env): string {
  const configured = readString(raw, 'baseUrl') ?? env['PIGEON_DEFAULT_BASE_URL']?.trim();
  if (configured === undefined || configured === '') {
    throw new PigeonError(
      'NOT_CONFIGURED',
      'Set the Pigeon base URL on the Pigeon integration page (or ask your Coop operator to set PIGEON_DEFAULT_BASE_URL).',
    );
  }
  return validateBaseUrl(configured, env);
}

/**
 * Parses an org's stored Coop configuration. Everything in `raw` is untrusted.
 * Throws a PigeonError whose message is safe to show to admins.
 *
 * Thread / evaluation-context settings are NOT here — Coop owns those via
 * `manifest.contextOptions` and passes loaded context as `input.context`.
 */
export function parseOrgConfig(
  raw: Record<string, unknown>,
  env: Env = process.env,
): PigeonOrgConfig {
  return {
    apiKey: parseApiKey(raw),
    baseUrl: parseBaseUrl(raw, env),
  };
}
