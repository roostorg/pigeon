import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { parseOrgConfig, validateBaseUrl } from '../src/config.js';
import { PigeonError } from '../src/errors.js';

const env = { PIGEON_ALLOWED_HOSTS: 'api.example.com, *.pigeon.example.com' };
const base = { apiKey: 'test-api-key', baseUrl: 'https://api.example.com' };

function assertCode(fn: () => unknown, code: string) {
  assert.throws(fn, (error: unknown) => {
    assert.ok(error instanceof PigeonError);
    assert.equal(error.code, code);
    assert.ok(!error.message.includes('test-api-key'));
    return true;
  });
}

describe('parseOrgConfig', () => {
  it('parses a valid config', () => {
    assert.deepEqual(parseOrgConfig(base, env), {
      apiKey: 'test-api-key',
      baseUrl: 'https://api.example.com',
    });
  });

  it('requires an API key', () => {
    assertCode(() => parseOrgConfig({ baseUrl: base.baseUrl }, env), 'NOT_CONFIGURED');
    assertCode(() => parseOrgConfig({ ...base, apiKey: '   ' }, env), 'NOT_CONFIGURED');
  });

  it('rejects malformed API keys', () => {
    assertCode(() => parseOrgConfig({ ...base, apiKey: 'test api key' }, env), 'INVALID_CONFIG');
    assertCode(() => parseOrgConfig({ ...base, apiKey: 'test-key\r\nX: y' }, env), 'INVALID_CONFIG');
    assertCode(() => parseOrgConfig({ ...base, apiKey: 42n as unknown as string }, env), 'INVALID_CONFIG');
  });

  it('falls back to PIGEON_DEFAULT_BASE_URL and requires one of them', () => {
    const withDefault = { ...env, PIGEON_DEFAULT_BASE_URL: 'https://api.example.com' };
    assert.equal(parseOrgConfig({ apiKey: 'test-api-key', baseUrl: '' }, withDefault).baseUrl, 'https://api.example.com');
    assertCode(() => parseOrgConfig({ apiKey: 'test-api-key' }, env), 'NOT_CONFIGURED');
  });

  it('ignores legacy thread config fields (Coop owns Evaluation context)', () => {
    assert.deepEqual(
      parseOrgConfig({ ...base, threadContext: 'flatten', threadMaxMessages: '25' }, env),
      { apiKey: 'test-api-key', baseUrl: 'https://api.example.com' },
    );
  });
});

describe('validateBaseUrl', () => {
  it('accepts allowlisted https origins and normalizes them', () => {
    assert.equal(validateBaseUrl('https://API.example.com/', env), 'https://api.example.com');
    assert.equal(validateBaseUrl('https://eu.pigeon.example.com', env), 'https://eu.pigeon.example.com');
  });

  it('rejects hosts outside the allowlist', () => {
    assertCode(() => validateBaseUrl('https://evil.example.net', env), 'INVALID_CONFIG');
    assertCode(() => validateBaseUrl('https://pigeon.example.com', env), 'INVALID_CONFIG');
    assertCode(() => validateBaseUrl('https://api.example.com.evil.net', env), 'INVALID_CONFIG');
    assertCode(() => validateBaseUrl('https://api.example.com', {}), 'INVALID_CONFIG');
  });

  it('matches host:port allowlist entries', () => {
    const portEnv = { PIGEON_ALLOWED_HOSTS: 'api.example.com:8443' };
    assert.equal(validateBaseUrl('https://api.example.com:8443', portEnv), 'https://api.example.com:8443');
    assertCode(() => validateBaseUrl('https://api.example.com:9443', portEnv), 'INVALID_CONFIG');
  });

  it('requires https except loopback with the insecure-localhost flag', () => {
    assertCode(() => validateBaseUrl('http://api.example.com', env), 'INVALID_CONFIG');
    const localEnv = { PIGEON_ALLOWED_HOSTS: '127.0.0.1:8900,api.example.com' };
    assertCode(() => validateBaseUrl('http://127.0.0.1:8900', localEnv), 'INVALID_CONFIG');
    const devEnv = { ...localEnv, PIGEON_ALLOW_INSECURE_LOCALHOST: 'true' };
    assert.equal(validateBaseUrl('http://127.0.0.1:8900', devEnv), 'http://127.0.0.1:8900');
    assertCode(() => validateBaseUrl('http://api.example.com', devEnv), 'INVALID_CONFIG');
  });

  it('rejects credentials, paths, queries, fragments, and other schemes', () => {
    for (const bad of [
      'https://user:pass@api.example.com',
      'https://api.example.com/v1',
      'https://api.example.com?x=1',
      'https://api.example.com#frag',
      'ftp://api.example.com',
      'file:///etc/passwd',
      'not a url',
    ]) {
      assertCode(() => validateBaseUrl(bad, env), 'INVALID_CONFIG');
    }
  });
});
