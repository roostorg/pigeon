import type {
  CatalogRefreshContext,
  CatalogSignalEntry,
  CoopIntegrationPlugin,
  PluginSignalContext,
  SignalCatalog,
} from '@roostorg/coop-types';

import { catalogVersion, policiesToSubcategories } from './catalog.js';
import { listPolicies, type FetchLike } from './client.js';
import { parseOrgConfig, type Env } from './config.js';
import {
  INTEGRATION_ID,
  RUN_TIMEOUT_MS,
  SIGNAL_ID_PATTERN,
  SIGNAL_TYPE_ID,
} from './constants.js';
import { PigeonError } from './errors.js';
import { manifest } from './manifest.js';
import { createSignalDescriptor, type SignalDependencies } from './signal.js';

if (!SIGNAL_ID_PATTERN.test(SIGNAL_TYPE_ID)) {
  throw new Error(`Invalid Pigeon signal type id: ${SIGNAL_TYPE_ID}`);
}

export type PluginOptions = Readonly<{
  fetch?: FetchLike;
  env?: Env;
  runTimeoutMs?: number;
}>;

export function createPlugin(
  options: PluginOptions = {},
): CoopIntegrationPlugin {
  const fetch = options.fetch;
  const runTimeoutMs = options.runTimeoutMs ?? RUN_TIMEOUT_MS;
  const dependencies = (
    getCredential: (orgId: string) => Promise<Record<string, unknown>>,
  ): SignalDependencies => ({
    getCredential,
    env: options.env ?? process.env,
    ...(fetch === undefined ? {} : { fetch }),
    runTimeoutMs,
  });

  const createSignals = (context: PluginSignalContext) => {
    return [
      {
        signalTypeId: SIGNAL_TYPE_ID,
        signal: createSignalDescriptor([], dependencies(context.getCredential)),
      },
    ];
  };

  async function refreshCatalog(
    context: CatalogRefreshContext,
  ): Promise<SignalCatalog> {
    const raw = await context.getCredential();
    const env = options.env ?? process.env;
    const config = parseOrgConfig(raw, env);
    const policies = await listPolicies(config, {
      signal: context.abortSignal,
      ...(fetch === undefined ? {} : { fetch }),
    });
    return {
      version: catalogVersion(policies),
      signals: [
        {
          signalTypeId: SIGNAL_TYPE_ID,
          displayName: 'Pigeon policy score',
          description:
            'Scores text against an organization-selected Pigeon policy.',
          docsUrl: null,
          recommendedThresholds: null,
          supportedLanguages: 'ALL',
          pricingStructure: { type: 'SUBSCRIPTION' },
          eligibleInputs: ['STRING'],
          outputType: { scalarType: 'NUMBER' },
          needsMatchingValues: false,
          eligibleSubcategories: policiesToSubcategories(policies),
          needsActionPenalties: false,
          allowedInAutomatedRules: true,
        },
      ],
    };
  }

  function createCatalogSignal(
    entry: CatalogSignalEntry,
    context: PluginSignalContext,
  ) {
    return createSignalDescriptor(
      entry.eligibleSubcategories,
      dependencies(context.getCredential),
      entry,
    );
  }

  return {
    manifest,
    createSignals,
    refreshCatalog,
    createCatalogSignal,
  };
}

export { INTEGRATION_ID, SIGNAL_TYPE_ID, manifest, PigeonError };
export default createPlugin();
