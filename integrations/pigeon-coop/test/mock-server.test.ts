import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';

type MockServer = { url: string; close: () => Promise<void> };
type MockModule = { startMockServer: (options: { port: number }) => Promise<MockServer> };

const { startMockServer } = (await import(
  new URL('../../mock-server/server.mjs', import.meta.url).href
)) as MockModule;

const AUTH = { Authorization: 'Bearer test-api-key' };
const OTHER = { Authorization: 'Bearer other-org-key' };

describe('mock Pigeon server', () => {
  let server: MockServer;
  const call = (path: string, init: RequestInit = {}) => fetch(`${server.url}${path}`, init);
  const classify = (model: string, input: Record<string, unknown>, headers: Record<string, string> = AUTH) =>
    call('/v1/classify', {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, input }),
    });

  before(async () => {
    server = await startMockServer({ port: 0 });
  });
  after(() => server.close());

  it('serves health without auth and rejects missing tokens', async () => {
    assert.deepEqual(await (await call('/health')).json(), { status: 'ok' });
    const denied = await call('/v1/policies');
    assert.equal(denied.status, 401);
    assert.deepEqual(await denied.json(), { detail: 'invalid or missing bearer token' });
  });

  it('lists policies per org', async () => {
    const { policies } = (await (await call('/v1/policies', { headers: AUTH })).json()) as {
      policies: Array<Record<string, string>>;
    };
    assert.deepEqual(policies.map((policy) => policy.id), ['harassment', 'toxicity', 'spam']);
    assert.deepEqual(policies[0], { id: 'harassment', version: '1', base: 'cope-b', display: 'Harassment' });
    assert.deepEqual(await (await call('/v1/policies', { headers: OTHER })).json(), { policies: [] });
    assert.equal((await classify('harassment', { text: 'idiot' }, OTHER)).status, 404);
  });

  it('scores high, medium, and low text deterministically', async () => {
    const scoreOf = async (text: string) =>
      ((await (await classify('harassment', { text })).json()) as { results: Array<{ score: number }> }).results[0]!.score;
    assert.equal(await scoreOf('you idiot'), 0.95);
    assert.equal(await scoreOf('please shut up'), 0.6);
    const low = await scoreOf('have a nice day');
    assert.ok(low >= 0.01 && low <= 0.2);
    assert.equal(await scoreOf('have a nice day'), low);
    const body = await (await classify('harassment@1', { text: 'x' })).json();
    assert.equal((body as { model: string }).model, 'harassment@1');
  });

  it('reports unknown models, images, bad bodies, and oversized bodies', async () => {
    const unknown = await classify('nope', { text: 'x' });
    assert.equal(unknown.status, 404);
    assert.deepEqual(await unknown.json(), { detail: "unknown model 'nope'" });
    assert.equal((await classify('harassment@9', { text: 'x' })).status, 404);
    assert.equal((await classify('harassment', { mediaUrl: 'https://api.example.com/a.png' })).status, 422);
    const bad = await call('/v1/classify', { method: 'POST', headers: AUTH, body: 'not json' });
    assert.equal(bad.status, 422);
    const huge = await call('/v1/classify', { method: 'POST', headers: AUTH, body: 'x'.repeat(1024 * 1024 + 1) });
    assert.equal(huge.status, 413);
  });

  it('creates policies and supports the mock-only delete and reset routes', async () => {
    const created = await call('/v1/policies', {
      method: 'POST',
      headers: { ...AUTH, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'threats', base: 'cope-b', policyText: 'Flag threats.', display: 'Threats' }),
    });
    assert.deepEqual(await created.json(), { id: 'threats', version: '1', base: 'cope-b', display: 'Threats' });

    assert.equal((await call('/__mock/policies/harassment', { method: 'DELETE' })).status, 401);
    assert.equal((await call('/__mock/policies/harassment', { method: 'DELETE', headers: AUTH })).status, 204);
    const { policies } = (await (await call('/v1/policies', { headers: AUTH })).json()) as { policies: Array<{ id: string }> };
    assert.ok(!policies.some((policy) => policy.id === 'harassment'));
    assert.equal((await classify('harassment', { text: 'idiot' })).status, 404);
    assert.equal((await call('/__mock/policies/harassment', { method: 'DELETE', headers: AUTH })).status, 404);

    assert.equal((await call('/__mock/reset', { method: 'POST' })).status, 204);
    assert.equal((await classify('harassment', { text: 'idiot' })).status, 200);
  });
});
