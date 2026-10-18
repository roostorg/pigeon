import type { PigeonOrgConfig } from './config.js';
import {
  MAX_CLASSIFY_TEXT_LENGTH,
  MAX_POLICY_ID_LENGTH,
  MAX_RESPONSE_BYTES,
} from './constants.js';
import { PigeonError } from './errors.js';

export type FetchLike = typeof fetch;

/** One entry of `GET /v1/policies`, after validation. */
export type PigeonPolicy = Readonly<{
  id: string;
  version: string;
  base: string;
  display: string;
}>;

export type RequestOptions = Readonly<{
  signal: AbortSignal;
  fetch?: FetchLike;
}>;

/** `GET /v1/policies`. */
export async function listPolicies(
  config: PigeonOrgConfig,
  options: RequestOptions,
): Promise<readonly PigeonPolicy[]> {
  const response = await request(config, options, '/v1/policies', 'GET');
  if (!response.ok) {
    await discardBody(response);
    throw listError(response.status);
  }
  const body = await readJson(response, options.signal);
  if (!isRecord(body) || !Array.isArray(body['policies'])) throw invalidResponse();

  const policies: PigeonPolicy[] = [];
  const seen = new Set<string>();
  for (const item of body['policies']) {
    if (!isRecord(item)) continue;
    const rawId = item['id'];
    const rawVersion = item['version'];
    const rawBase = item['base'];
    const rawDisplay = item['display'];
    if (
      typeof rawId !== 'string' ||
      rawId === '' ||
      rawId !== rawId.trim() ||
      rawId.length > MAX_POLICY_ID_LENGTH ||
      hasControlCharacters(rawId) ||
      !isValidVersion(rawVersion) ||
      (rawBase !== undefined && typeof rawBase !== 'string') ||
      (rawDisplay !== undefined && typeof rawDisplay !== 'string')
    ) continue;
    const id = rawId;
    if (seen.has(id)) continue;
    seen.add(id);
    const display = typeof rawDisplay === 'string' && rawDisplay.trim() !== ''
      ? stripControlCharacters(rawDisplay)
      : id;
    policies.push({
      id,
      version: typeof rawVersion === 'number' ? String(rawVersion) : rawVersion,
      base: typeof rawBase === 'string' ? rawBase : '',
      display: display === '' ? id : display,
    });
  }
  return policies;
}

/** `POST /v1/classify` for a bound policy; resolves to `results[0].score`. */
export async function classifyPolicy(
  config: PigeonOrgConfig,
  requestData: Readonly<{ policyId: string; text: string }>,
  options: RequestOptions,
): Promise<number> {
  const policyId = requestData.policyId.trim();
  if (policyId === '') {
    throw new PigeonError('POLICY_REQUIRED', 'Select a Pigeon policy before classifying content.');
  }
  if (requestData.text.length > MAX_CLASSIFY_TEXT_LENGTH) {
    throw new PigeonError('INVALID_REQUEST', 'The text is too long for Pigeon to classify.');
  }
  const response = await request(
    config,
    options,
    '/v1/classify',
    'POST',
    JSON.stringify({ model: policyId, input: { text: requestData.text } }),
  );
  if (!response.ok) {
    await discardBody(response);
    throw classifyError(response.status, policyId);
  }
  const body = await readJson(response, options.signal);
  if (!isRecord(body) || !Array.isArray(body['results']) || body['results'].length === 0) {
    throw invalidResponse();
  }
  const first = body['results'][0];
  if (!isRecord(first) || typeof first['score'] !== 'number' || !Number.isFinite(first['score'])) {
    throw invalidResponse();
  }
  return Math.min(1, Math.max(0, first['score']));
}

type Method = 'GET' | 'POST';

async function request(
  config: PigeonOrgConfig,
  options: RequestOptions,
  path: string,
  method: Method,
  body?: string,
): Promise<Response> {
  const url = new URL(path, config.baseUrl);
  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.apiKey}`,
    Accept: 'application/json',
  };
  if (method === 'POST') headers['Content-Type'] = 'application/json';
  try {
    return await (options.fetch ?? globalThis.fetch)(url, {
      method,
      headers,
      ...(body === undefined ? {} : { body }),
      signal: options.signal,
      redirect: 'error',
    });
  } catch (cause) {
    if (options.signal.aborted || isAbortError(cause)) {
      throw new PigeonError('TIMEOUT', 'Pigeon did not respond in time.', { cause });
    }
    throw new PigeonError(
      'NETWORK_ERROR',
      `Could not reach Pigeon at ${new URL(config.baseUrl).origin}.`,
      { cause },
    );
  }
}

async function discardBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // The status code is all we report for error responses.
  }
}

async function readJson(response: Response, signal: AbortSignal): Promise<unknown> {
  const contentLength = response.headers.get('content-length');
  if (contentLength !== null && Number.isFinite(Number(contentLength)) &&
      Number(contentLength) > MAX_RESPONSE_BYTES) {
    throw invalidResponse();
  }
  let text: string;
  try {
    if (response.body === null) {
      text = await response.text();
      if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
        throw invalidResponse();
      }
    } else {
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > MAX_RESPONSE_BYTES) throw invalidResponse();
          chunks.push(part.value);
        }
      } finally {
        reader.releaseLock();
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      text = new TextDecoder().decode(bytes);
    }
  } catch (cause) {
    if (cause instanceof PigeonError) throw cause;
    if (signal.aborted || isAbortError(cause)) {
      throw new PigeonError('TIMEOUT', 'Pigeon did not respond in time.', { cause });
    }
    throw invalidResponse(cause);
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (cause) {
    throw invalidResponse(cause);
  }
}

function listError(status: number): PigeonError {
  if (status === 401 || status === 403) return authError(status);
  if (status === 404) {
    return new PigeonError(
      'UPSTREAM_ERROR',
      'The Pigeon policies endpoint was not found. Check the configured base URL.',
      { status },
    );
  }
  return upstreamError(status);
}

function classifyError(status: number, policyId: string): PigeonError {
  if (status === 401 || status === 403) return authError(status);
  if (status === 404) {
    return new PigeonError(
      'UNKNOWN_POLICY',
      `Pigeon policy "${policyId.slice(0, MAX_POLICY_ID_LENGTH)}" was not found. It may have been deleted or renamed; refresh the Pigeon catalog and update rules that use it.`,
      { status },
    );
  }
  if (status === 422) {
    return new PigeonError('INVALID_REQUEST', 'Pigeon rejected the classification request.', { status });
  }
  return upstreamError(status);
}

function authError(status: number): PigeonError {
  return new PigeonError(
    'AUTH_FAILED',
    `Pigeon rejected the API key (HTTP ${status}). Check the API key on the Pigeon integration page.`,
    { status },
  );
}

function upstreamError(status: number): PigeonError {
  return new PigeonError('UPSTREAM_ERROR', `Pigeon returned an unexpected response (HTTP ${status}).`, { status });
}

function invalidResponse(cause?: unknown): PigeonError {
  return new PigeonError(
    'INVALID_RESPONSE',
    'Pigeon returned an invalid response.',
    cause === undefined ? {} : { cause },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isValidVersion(value: unknown): value is string | number {
  return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value));
}

function hasControlCharacters(value: string): boolean {
  return /[\u0000-\u001F\u007F-\u009F]/u.test(value);
}

function stripControlCharacters(value: string): string {
  return value.replace(/[\u0000-\u001F\u007F-\u009F]/gu, '');
}

function isAbortError(value: unknown): boolean {
  return value instanceof Error && (value.name === 'AbortError' || value.name === 'TimeoutError');
}
