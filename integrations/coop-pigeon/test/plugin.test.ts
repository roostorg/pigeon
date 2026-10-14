import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  assertModelCardHasRequiredSections,
  type CatalogRefreshContext,
  type PluginSignalDescriptor,
  type SignalEvaluationContext,
} from '@roostorg/coop-types';

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import plugin, {
  createPlugin,
  manifest,
  PigeonError,
  SIGNAL_TYPE_ID,
} from '../src/index.js';
import { PACKAGE_VERSION } from '../src/constants.js';

const ENV = { PIGEON_ALLOWED_HOSTS: 'api.example.com' };
const CREDENTIAL = {
  apiKey: 'test-api-key',
  baseUrl: 'https://api.example.com',
};
const VALID_INPUTS = new Set([
  'STRING',
  'IMAGE',
  'VIDEO',
  'AUDIO',
  'MEDIA',
  'URL',
  'USER_ID',
  'ID',
  'GEOHASH',
  'NUMBER',
  'BOOLEAN',
  'DATETIME',
  'RELATED_ITEM',
  'POLICY_ID',
  'IP_ADDRESS',
  'EMAIL_ADDRESS',
  'FULL_ITEM',
]);

type Call = { url: string; init: RequestInit };
type Reply = { status?: number; body: unknown };

function mockFetch(reply: Reply | ((call: Call) => Reply)) {
  const calls: Call[] = [];
  const fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    const { status = 200, body } =
      typeof reply === 'function' ? reply(call) : reply;
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof globalThis.fetch;
  return { fetch, calls };
}

const POLICIES = {
  policies: [
    { id: 'spam', version: '1', base: 'cope-b', display: 'Spam' },
    { id: 'harassment', version: '2', base: 'cope-b', display: 'Harassment' },
  ],
};

function refreshContext(
  credential: Record<string, unknown> = CREDENTIAL,
): CatalogRefreshContext {
  return {
    integrationId: 'PIGEON',
    orgId: 'test-org',
    getCredential: async () => credential,
    abortSignal: new AbortController().signal,
  };
}

function setup(
  credential: Record<string, unknown> = CREDENTIAL,
  reply: Reply | ((call: Call) => Reply) = { body: POLICIES },
) {
  const mock = mockFetch(reply);
  const instance = createPlugin({ fetch: mock.fetch, env: ENV });
  const [entry] = instance.createSignals!({
    integrationId: 'PIGEON',
    getCredential: async () => credential,
  });
  return { mock, instance, signal: entry!.signal };
}

async function refreshedSignal(
  credential: Record<string, unknown> = CREDENTIAL,
  reply?: Reply | ((call: Call) => Reply),
) {
  const { mock, instance } = setup(credential, reply);
  const catalog = await instance.refreshCatalog!(refreshContext(credential));
  const signal = instance.createCatalogSignal!(catalog.signals[0]!, {
    integrationId: 'PIGEON',
    getCredential: async () => credential,
  });
  return { mock, catalog, signal, instance };
}

async function rejectsWith(
  action: () => Promise<unknown>,
  code: string,
): Promise<PigeonError> {
  try {
    await action();
  } catch (error) {
    assert.ok(
      error instanceof PigeonError,
      `expected PigeonError, got ${String(error)}`,
    );
    assert.equal(error.code, code);
    assert.ok(!error.message.includes('test-api-key'));
    return error;
  }
  assert.fail(`expected ${code}`);
}

function textInput(
  text: string,
  subcategory: string | null = 'harassment',
  context?: SignalEvaluationContext,
) {
  return {
    value: { type: 'STRING', value: text },
    orgId: 'test-org',
    ...(subcategory === null ? {} : { subcategory }),
    ...(context === undefined ? {} : { context }),
  };
}

function checkDescriptor(signalTypeId: string, signal: PluginSignalDescriptor) {
  assert.match(signalTypeId, /^[A-Z][A-Z0-9_]{0,99}$/);
  assert.equal(signal.id.type, signalTypeId);
  assert.ok(signal.eligibleInputs.length > 0);
  for (const input of signal.eligibleInputs)
    assert.ok(VALID_INPUTS.has(input), input);
  assert.deepEqual(signal.outputType, { scalarType: 'NUMBER' });
  assert.equal(signal.integration, manifest.id);
}

describe('manifest and descriptors', () => {
  it('keeps PACKAGE_VERSION aligned with package.json', () => {
    // Test file lives at test/ (or build-test/test/); package.json is two levels up from build-test/test.
    const here = dirname(fileURLToPath(import.meta.url));
    const candidates = [join(here, '..', 'package.json'), join(here, '..', '..', 'package.json')];
    const pkgPath = candidates.find((path) => {
      try {
        readFileSync(path);
        return true;
      } catch {
        return false;
      }
    });
    assert.ok(pkgPath, 'package.json not found');
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as { version: string };
    assert.equal(PACKAGE_VERSION, pkg.version);
    assert.equal(manifest.version, pkg.version);
  });

  it('has a valid manifest and model card', () => {
    assert.match(manifest.id, /^[A-Z][A-Z0-9_]*$/);
    assert.equal(manifest.requiresConfig, true);
    assert.deepEqual(manifest.signalTypeIds, [SIGNAL_TYPE_ID]);
    const apiKey = manifest.configurationFields?.find(
      (field) => field.key === 'apiKey',
    );
    assert.equal(apiKey?.inputType, 'password');
    assert.equal(apiKey?.required, true);
    const configKeys = (manifest.configurationFields ?? []).map(
      (field) => field.key,
    );
    assert.ok(!configKeys.includes('threadContext'));
    assert.ok(!configKeys.includes('threadMaxMessages'));
    assert.deepEqual(manifest.contextOptions, {
      thread: { default: 'off', defaultMaxMessages: 10, maxMessagesLimit: 100 },
      parent: { default: 'include' },
    });
    assert.doesNotThrow(() =>
      assertModelCardHasRequiredSections(manifest.modelCard!),
    );
    assert.equal(plugin.manifest, manifest);
  });

  it('createSignals returns one bootstrap signal with no subcategories', () => {
    const entries = plugin.createSignals!({
      integrationId: 'PIGEON',
      getCredential: async () => ({}),
    });
    assert.equal(entries.length, 1);
    const [entry] = entries;
    assert.equal(entry!.signalTypeId, 'PIGEON_POLICY_SCORE');
    checkDescriptor(entry!.signalTypeId, entry!.signal);
    assert.deepEqual(entry!.signal.eligibleSubcategories, []);
    assert.equal('contextNeeds' in entry!.signal, false);
  });

  it('refreshCatalog returns a data-only catalog entry', async () => {
    const { catalog } = await refreshedSignal();
    assert.equal(catalog.signals.length, 1);
    const entry = catalog.signals[0]!;
    assert.equal(entry.signalTypeId, SIGNAL_TYPE_ID);
    assert.deepEqual(entry.eligibleSubcategories, [
      {
        id: 'harassment',
        label: 'Harassment',
        description: 'Pigeon policy harassment (base model cope-b, version 2)',
        childrenIds: [],
      },
      {
        id: 'spam',
        label: 'Spam',
        description: 'Pigeon policy spam (base model cope-b, version 1)',
        childrenIds: [],
      },
    ]);
    for (const value of Object.values(entry))
      assert.notEqual(typeof value, 'function');
  });
});

describe('refreshCatalog', () => {
  it('maps Pigeon policies to subcategories with the org key and abort signal', async () => {
    const { mock, instance } = setup();
    const context = refreshContext();
    const catalog = await instance.refreshCatalog!(context);
    assert.deepEqual(
      catalog.signals[0]!.eligibleSubcategories.map(
        ({ id, label, childrenIds }) => ({ id, label, childrenIds }),
      ),
      [
        { id: 'harassment', label: 'Harassment', childrenIds: [] },
        { id: 'spam', label: 'Spam', childrenIds: [] },
      ],
    );
    assert.equal(mock.calls.length, 1);
    assert.equal(mock.calls[0]!.url, 'https://api.example.com/v1/policies');
    assert.equal(
      (mock.calls[0]!.init.headers as Record<string, string>)['Authorization'],
      'Bearer test-api-key',
    );
    assert.equal(mock.calls[0]!.init.signal, context.abortSignal);
    assert.match(catalog.version, /^sha256:[0-9a-f]{64}$/);
  });

  it('rebuilds a catalog signal from data and context', async () => {
    const { instance, catalog, mock } = await refreshedSignal(
      CREDENTIAL,
      (call) =>
        call.url.endsWith('/v1/classify')
          ? { body: { results: [{ label: 'verdict', score: 0.91 }] } }
          : { body: POLICIES },
    );
    const signal = instance.createCatalogSignal!(catalog.signals[0]!, {
      integrationId: 'PIGEON',
      getCredential: async () => CREDENTIAL,
    });
    assert.equal(
      (
        (await signal.run(textInput('content to score', 'spam'))) as {
          score: number;
        }
      ).score,
      0.91,
    );
    assert.equal(
      JSON.parse(String(mock.calls.at(-1)!.init.body)).model,
      'spam',
    );
    assert.deepEqual(await signal.getDisabledInfo('test-org'), {
      disabled: false,
    });
  });

  it('produces a stable version that changes with the policy set', async () => {
    const version = async (policies: unknown[]) =>
      (await refreshedSignal(CREDENTIAL, { body: { policies } })).catalog
        .version;
    const [a, b] = POLICIES.policies;
    const base = await version([a, b]);
    assert.equal(await version([b, a]), base);
    assert.notEqual(await version([a]), base);
    assert.notEqual(await version([a, { ...b, version: '3' }]), base);
  });

  it('caps subcategories and label length', async () => {
    const policies = Array.from({ length: 1200 }, (_, i) => ({
      id: `policy-${i}`,
      version: '1',
      base: 'cope-b',
      display: 'x'.repeat(300),
    }));
    const { signal } = await refreshedSignal(CREDENTIAL, {
      body: { policies },
    });
    assert.equal(signal.eligibleSubcategories.length, 1000);
    assert.ok(
      signal.eligibleSubcategories.every((sub) => sub.label.length <= 200),
    );
  });

  it('throws on auth failures and missing or disallowed config', async () => {
    const { instance } = setup(CREDENTIAL, {
      status: 401,
      body: { detail: 'invalid or missing bearer token' },
    });
    await rejectsWith(
      () => instance.refreshCatalog!(refreshContext()),
      'AUTH_FAILED',
    );
    await rejectsWith(
      () => setup({}).instance.refreshCatalog!(refreshContext({})),
      'NOT_CONFIGURED',
    );
    const evil = { ...CREDENTIAL, baseUrl: 'https://evil.example.net' };
    await rejectsWith(
      () => setup(evil).instance.refreshCatalog!(refreshContext(evil)),
      'INVALID_CONFIG',
    );
    const http = { ...CREDENTIAL, baseUrl: 'http://api.example.com' };
    await rejectsWith(
      () => setup(http).instance.refreshCatalog!(refreshContext(http)),
      'INVALID_CONFIG',
    );
  });
});

describe('run', () => {
  const scoreReply = (call: Call): Reply =>
    call.url.endsWith('/v1/classify')
      ? {
          body: {
            model: 'harassment@2',
            results: [{ label: 'verdict', score: 0.91 }],
          },
        }
      : { body: POLICIES };

  it('sends the selected policy and text and returns the score', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, scoreReply);
    const result = await signal.run(textInput('content to score'));
    assert.deepEqual(result, {
      outputType: { scalarType: 'NUMBER' },
      score: 0.91,
    });
    const call = mock.calls.at(-1)!;
    assert.equal(call.url, 'https://api.example.com/v1/classify');
    assert.deepEqual(JSON.parse(String(call.init.body)), {
      model: 'harassment',
      input: { text: 'content to score' },
    });
    assert.ok(call.init.signal instanceof AbortSignal);
    assert.equal(
      (call.init.headers as Record<string, string>)['Authorization'],
      'Bearer test-api-key',
    );
  });

  it('works from the bootstrap signal too', async () => {
    const { signal } = setup(CREDENTIAL, scoreReply);
    assert.equal(
      ((await signal.run(textInput('hi'))) as { score: number }).score,
      0.91,
    );
  });

  it('throws clear errors for unknown policies and auth failures', async () => {
    const unknown = setup(CREDENTIAL, {
      status: 404,
      body: { detail: "unknown model 'gone'" },
    });
    const error = await rejectsWith(
      () => unknown.signal.run(textInput('secret text', 'gone')),
      'UNKNOWN_POLICY',
    );
    assert.match(error.message, /"gone" was not found/);
    assert.ok(!error.message.includes('secret text'));
    const auth = setup(CREDENTIAL, {
      status: 401,
      body: { detail: 'invalid or missing bearer token' },
    });
    await rejectsWith(() => auth.signal.run(textInput('x')), 'AUTH_FAILED');
  });

  it('requires a policy and text input without calling Pigeon', async () => {
    const { signal, mock } = setup(CREDENTIAL, scoreReply);
    await rejectsWith(
      () => signal.run(textInput('x', null)),
      'POLICY_REQUIRED',
    );
    await rejectsWith(
      () => signal.run(textInput('x', '  ')),
      'POLICY_REQUIRED',
    );
    await rejectsWith(
      () =>
        signal.run({
          value: {
            type: 'IMAGE',
            value: { url: 'https://api.example.com/a.png' },
          },
          orgId: 'test-org',
          subcategory: 'harassment',
        }),
      'UNSUPPORTED_INPUT',
    );
    assert.equal(mock.calls.length, 0);
  });

  it('throws NOT_CONFIGURED when the org has no key', async () => {
    const { signal } = setup({}, scoreReply);
    await rejectsWith(() => signal.run(textInput('x')), 'NOT_CONFIGURED');
  });
});

describe('parent and thread context (from Coop Evaluation context → input.context)', () => {
  const context: SignalEvaluationContext = {
    item: {
      itemId: 'item-3',
      itemTypeId: 'post',
      data: { text: 'current message' },
    },
    thread: {
      id: 'thread-1',
      typeId: 'thread',
      truncated: false,
      messages: [
        {
          itemId: 'item-0',
          itemTypeId: 'post',
          data: { text: 'first' },
          creator: { id: 'user-a', typeId: 'user' },
        },
        {
          itemId: 'item-1',
          itemTypeId: 'post',
          data: { body: 'second' },
          creator: { id: 'user-b', typeId: 'user' },
        },
        { itemId: 'item-2', itemTypeId: 'post', data: { text: 'third' } },
        {
          itemId: 'item-3',
          itemTypeId: 'post',
          data: { text: 'current message' },
        },
      ],
    },
  };
  const reply = (call: Call): Reply =>
    call.url.endsWith('/v1/classify')
      ? { body: { results: [{ label: 'verdict', score: 0.5 }] } }
      : { body: POLICIES };

  it('does not set contextNeeds; Coop decides via contextOptions', async () => {
    const { signal } = await refreshedSignal(CREDENTIAL, reply);
    assert.equal('contextNeeds' in signal, false);
  });

  it('flattens when input.context.thread.messages is present', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    await signal.run(textInput('current message', 'harassment', context));
    const sent = JSON.parse(String(mock.calls.at(-1)!.init.body)).input
      .text as string;
    assert.equal(
      sent,
      'Earlier messages in this thread (oldest first):\n[user-a]: first\n[user-b]: second\n[unknown]: third\n\nMessage to evaluate:\ncurrent message',
    );
  });

  const sentText = (mock: { calls: Call[] }) =>
    JSON.parse(String(mock.calls.at(-1)!.init.body)).input.text as string;

  it('puts the parent first and does not repeat it in the thread history', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    await signal.run(
      textInput('current message', 'harassment', {
        ...context,
        parent: context.thread!.messages[1]!,
      }),
    );
    assert.equal(
      sentText(mock),
      'In reply to [user-b]: second\n\nEarlier messages in this thread (oldest first):\n[user-a]: first\n[unknown]: third\n\nMessage to evaluate:\ncurrent message',
    );
  });

  it('includes the parent without a thread', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    await signal.run(
      textInput('current message', 'harassment', {
        parent: {
          itemId: 'p',
          itemTypeId: 'post',
          data: { text: 'original post' },
        },
      }),
    );
    assert.equal(
      sentText(mock),
      'In reply to [unknown]: original post\n\nMessage to evaluate:\ncurrent message',
    );
  });

  it('drops the oldest thread messages first to stay under 100,000 characters', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    const long = 'x'.repeat(99_900);
    await signal.run(
      textInput('current message', 'harassment', {
        parent: { itemId: 'p', itemTypeId: 'post', data: { text: 'parent' } },
        thread: {
          id: 'thread-1',
          typeId: 'thread',
          truncated: false,
          messages: [
            {
              itemId: 'old',
              itemTypeId: 'post',
              data: { text: `old ${long}` },
            },
            { itemId: 'new', itemTypeId: 'post', data: { text: 'newest' } },
          ],
        },
      }),
    );
    const sent = sentText(mock);
    assert.ok(sent.length <= 100_000);
    assert.ok(sent.startsWith('In reply to [unknown]: parent'));
    assert.ok(sent.includes('[unknown]: newest'));
    assert.ok(!sent.includes('old x'));
  });

  it('falls back to the item text when the parent and item alone are too long', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    await signal.run(
      textInput('current message', 'harassment', {
        parent: {
          itemId: 'p',
          itemTypeId: 'post',
          data: { text: 'y'.repeat(100_000) },
        },
      }),
    );
    assert.equal(sentText(mock), 'current message');
  });

  it('scores only the item text when thread context is absent', async () => {
    const { signal, mock } = await refreshedSignal(CREDENTIAL, reply);
    await signal.run(textInput('alone'));
    assert.equal(
      JSON.parse(String(mock.calls.at(-1)!.init.body)).input.text,
      'alone',
    );
    await signal.run(textInput('current message', 'harassment', {}));
    assert.equal(
      JSON.parse(String(mock.calls.at(-1)!.init.body)).input.text,
      'current message',
    );
  });
});

describe('getDisabledInfo', () => {
  it('is disabled until an API key is configured', async () => {
    assert.deepEqual(await setup({}).signal.getDisabledInfo('test-org'), {
      disabled: true,
      disabledMessage:
        'Add your Pigeon API key on the Pigeon integration page.',
    });
    assert.deepEqual(await setup().signal.getDisabledInfo('test-org'), {
      disabled: false,
    });
    const bad = await setup({
      ...CREDENTIAL,
      baseUrl: 'https://evil.example.net',
    }).signal.getDisabledInfo('test-org');
    assert.equal(bad.disabled, true);
  });
});
