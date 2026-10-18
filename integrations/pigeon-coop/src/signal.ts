import type {
  CatalogSignalEntry,
  PluginSignalDescriptor,
  PluginSignalRunInput,
} from '@roostorg/coop-types';

import { classifyPolicy, type FetchLike } from './client.js';
import { hasApiKey, parseOrgConfig, type Env } from './config.js';
import { INTEGRATION_ID, RUN_TIMEOUT_MS, SIGNAL_TYPE_ID } from './constants.js';
import { PigeonError } from './errors.js';
import { buildClassifyText } from './thread.js';

type CredentialGetter = (orgId: string) => Promise<Record<string, unknown>>;

export type SignalDependencies = Readonly<{
  getCredential: CredentialGetter;
  env: Env;
  fetch?: FetchLike;
  runTimeoutMs: number;
}>;

function output(score: number) {
  return { outputType: { scalarType: 'NUMBER' }, score };
}

function isStringValue(
  value: unknown,
): value is { type: 'STRING'; value: string } {
  if (value === null || typeof value !== 'object' || Array.isArray(value))
    return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate['type'] === 'STRING' && typeof candidate['value'] === 'string'
  );
}

function safeCredentialError(): { disabled: true; disabledMessage: string } {
  return {
    disabled: true,
    disabledMessage: 'Pigeon configuration could not be loaded.',
  };
}

export function createSignalDescriptor(
  eligibleSubcategories: PluginSignalDescriptor['eligibleSubcategories'],
  dependencies: SignalDependencies,
  catalogEntry?: CatalogSignalEntry,
): PluginSignalDescriptor {
  const descriptor = {
    ...(catalogEntry ?? {
      signalTypeId: SIGNAL_TYPE_ID,
      displayName: 'Pigeon policy score',
      description:
        'Scores text against an organization-selected Pigeon policy.',
      docsUrl: null,
      recommendedThresholds: null,
      supportedLanguages: 'ALL' as const,
      pricingStructure: { type: 'SUBSCRIPTION' as const },
      eligibleInputs: ['STRING'],
      outputType: { scalarType: 'NUMBER' },
      needsMatchingValues: false,
      needsActionPenalties: false,
      allowedInAutomatedRules: true,
    }),
    id: { type: catalogEntry?.signalTypeId ?? SIGNAL_TYPE_ID },
    getCost: () => 10,
    eligibleSubcategories,
    integration: INTEGRATION_ID,
    async getDisabledInfo(orgId: string) {
      let raw: Record<string, unknown>;
      try {
        raw = await dependencies.getCredential(orgId);
      } catch {
        return safeCredentialError();
      }
      if (!hasApiKey(raw)) {
        return {
          disabled: true,
          disabledMessage:
            'Add your Pigeon API key on the Pigeon integration page.',
        };
      }
      try {
        parseOrgConfig(raw, dependencies.env);
        return { disabled: false };
      } catch (error) {
        if (error instanceof PigeonError) {
          return { disabled: true, disabledMessage: error.message };
        }
        return safeCredentialError();
      }
    },
    async run(input: PluginSignalRunInput) {
      if (input.subcategory === undefined || input.subcategory.trim() === '') {
        throw new PigeonError(
          'POLICY_REQUIRED',
          'Select a Pigeon policy in this rule condition. Pigeon has no overall score.',
        );
      }
      if (!isStringValue(input.value)) {
        const type =
          input.value !== null &&
          typeof input.value === 'object' &&
          typeof (input.value as Record<string, unknown>)['type'] === 'string'
            ? String((input.value as Record<string, unknown>)['type']).slice(
                0,
                50,
              )
            : typeof input.value;
        throw new PigeonError(
          'UNSUPPORTED_INPUT',
          `Pigeon supports STRING input only (received ${type}).`,
        );
      }
      const config = parseOrgConfig(
        await dependencies.getCredential(input.orgId),
        dependencies.env,
      );
      // Coop loads parent/thread context from the org's Evaluation context
      // settings and passes it as input.context; without it, only the item's text is scored.
      const text = buildClassifyText(input.value.value, input.context);
      const signal = AbortSignal.timeout(dependencies.runTimeoutMs);
      const score = await classifyPolicy(
        config,
        { policyId: input.subcategory, text },
        {
          signal,
          ...(dependencies.fetch === undefined
            ? {}
            : { fetch: dependencies.fetch }),
        },
      );
      return output(score);
    },
  } satisfies PluginSignalDescriptor;
  return descriptor;
}
