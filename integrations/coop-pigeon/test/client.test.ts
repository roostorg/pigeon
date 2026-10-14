import assert from 'node:assert/strict';
import test from 'node:test';
import { classifyPolicy, listPolicies } from '../src/client.js';
import { MAX_RESPONSE_BYTES } from '../src/constants.js';
import { PigeonError } from '../src/errors.js';

const config = {
  apiKey: 'test-api-key',
  baseUrl: 'https://api.example.com',
  threadContext: { mode: 'skip' as const },
};

function mockFetch(body: unknown, status = 200): {
  fetch: typeof fetch;
  calls: RequestInit[];
  urls: string[];
} {
  const calls: RequestInit[] = [];
  const urls: string[] = [];
  return {
    calls,
    urls,
    fetch: async (input, init) => {
      urls.push(String(input));
      calls.push(init ?? {});
      return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });
    },
  };
}

function options(mock: ReturnType<typeof mockFetch>, signal = new AbortController().signal) {
  return { fetch: mock.fetch, signal };
}

async function errorOf(action: Promise<unknown>): Promise<PigeonError> {
  try {
    await action;
  } catch (error) {
    assert.ok(error instanceof PigeonError);
    return error;
  }
  assert.fail('Expected a PigeonError');
}

test('lists policies with the documented request and validation', async () => {
  const mock = mockFetch({
    policies: [
      { id: 'one', version: 1, base: 'cope-b', display: 'One' },
      { id: 'one', version: '2', base: 'ignored', display: 'Duplicate' },
      { id: 'two', version: '2' },
      { id: '', version: '3' },
      { id: ' padded ', version: '1' },
      { id: 'bad', version: 'x', base: 4 },
    ],
  });
  const result = await listPolicies(config, options(mock));
  assert.deepEqual(result, [
    { id: 'one', version: '1', base: 'cope-b', display: 'One' },
    { id: 'two', version: '2', base: '', display: 'two' },
  ]);
  assert.equal(mock.urls[0], 'https://api.example.com/v1/policies');
  assert.equal(mock.calls[0]?.method, 'GET');
  assert.equal((mock.calls[0]?.headers as Record<string, string>).Authorization, 'Bearer test-api-key');
  assert.equal((mock.calls[0]?.headers as Record<string, string>).Accept, 'application/json');
  assert.equal(mock.calls[0]?.redirect, 'error');
});

test('classifies with model/input and clamps the score', async () => {
  const mock = mockFetch({ model: 'one@1', results: [{ label: 'verdict', score: 4 }] });
  const controller = new AbortController();
  const score = await classifyPolicy(config, { policyId: 'one', text: 'hello' }, options(mock, controller.signal));
  assert.equal(score, 1);
  assert.equal(mock.urls[0], 'https://api.example.com/v1/classify');
  assert.equal(mock.calls[0]?.method, 'POST');
  assert.equal(mock.calls[0]?.redirect, 'error');
  assert.equal(mock.calls[0]?.signal, controller.signal);
  assert.deepEqual(JSON.parse(String(mock.calls[0]?.body)), { model: 'one', input: { text: 'hello' } });
  assert.equal((mock.calls[0]?.headers as Record<string, string>)['Content-Type'], 'application/json');
});

test('maps HTTP errors without exposing the API key', async () => {
  for (const [status, expected] of [[401, 'AUTH_FAILED'], [500, 'UPSTREAM_ERROR']] as const) {
    const error = await errorOf(listPolicies(config, options(mockFetch({ detail: 'secret' }, status))));
    assert.equal(error.code, expected);
    assert.equal(error.message.includes(config.apiKey), false);
  }
  const unknown = await errorOf(classifyPolicy(
    config,
    { policyId: 'gone-policy', text: 'secret text' },
    options(mockFetch({ detail: 'unknown model' }, 404)),
  ));
  assert.equal(unknown.code, 'UNKNOWN_POLICY');
  assert.match(unknown.message, /gone-policy/);
  assert.equal(unknown.message.includes('secret text'), false);
  const invalid = await errorOf(classifyPolicy(
    config,
    { policyId: 'one', text: 'hello' },
    options(mockFetch({ detail: 'unsupported' }, 422)),
  ));
  assert.equal(invalid.code, 'INVALID_REQUEST');
  const hugeAuth = await errorOf(listPolicies(
    config,
    options(mockFetch('x'.repeat(MAX_RESPONSE_BYTES + 1), 401)),
  ));
  assert.equal(hugeAuth.code, 'AUTH_FAILED');
});

test('rejects malformed and oversized responses', async () => {
  const malformed = await errorOf(listPolicies(config, options(mockFetch('not-json'))));
  assert.equal(malformed.code, 'INVALID_RESPONSE');
  const wrongShape = await errorOf(listPolicies(config, options(mockFetch({ policies: 'no' }))));
  assert.equal(wrongShape.code, 'INVALID_RESPONSE');
  const oversized = await errorOf(listPolicies(config, options(mockFetch('x'.repeat(MAX_RESPONSE_BYTES + 1)))));
  assert.equal(oversized.code, 'INVALID_RESPONSE');
  const badScore = await errorOf(classifyPolicy(
    config,
    { policyId: 'one', text: 'hello' },
    options(mockFetch({ results: [{}] })),
  ));
  assert.equal(badScore.code, 'INVALID_RESPONSE');
});

test('maps aborts and network failures', async () => {
  const controller = new AbortController();
  controller.abort();
  const aborted = await errorOf(listPolicies(config, {
    signal: controller.signal,
    fetch: async () => { throw new DOMException('aborted', 'AbortError'); },
  }));
  assert.equal(aborted.code, 'TIMEOUT');

  const network = await errorOf(listPolicies(config, {
    signal: new AbortController().signal,
    fetch: async () => { throw new TypeError('network'); },
  }));
  assert.equal(network.code, 'NETWORK_ERROR');
  assert.match(network.message, /https:\/\/api\.example\.com/);
});

test('validates required and oversized classify input locally', async () => {
  const mock = mockFetch({ results: [{ score: 0.5 }] });
  const required = await errorOf(classifyPolicy(config, { policyId: ' ', text: 'x' }, options(mock)));
  assert.equal(required.code, 'POLICY_REQUIRED');
  const oversized = await errorOf(classifyPolicy(
    config,
    { policyId: 'one', text: 'x'.repeat(100_001) },
    options(mock),
  ));
  assert.equal(oversized.code, 'INVALID_REQUEST');
  assert.equal(mock.calls.length, 0);
});
