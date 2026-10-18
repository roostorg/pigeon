import type { IntegrationManifest } from '@roostorg/coop-types';
import { REQUIRED_MODEL_CARD_SECTION_IDS } from '@roostorg/coop-types';
import { INTEGRATION_ID, PACKAGE_VERSION, SIGNAL_TYPE_ID } from './constants.js';

const sectionTitles: Readonly<Record<string, string>> = {
  trainingData: 'Training Data',
  policyAndTaxonomy: 'Policy and Taxonomy',
  annotationMethodology: 'Annotation Methodology',
  performanceBenchmarks: 'Performance and Benchmarks',
  biasAndLimitations: 'Bias and Limitations',
  implementationGuidance: 'Implementation Guidance',
  relevantLinks: 'Relevant Links',
};

const sectionContent: Readonly<Record<string, string>> = {
  trainingData: 'Pigeon policy scoring makes no training-data claims. Policies are org-authored and bound to BYOP base models.',
  policyAndTaxonomy: 'Scores text against an organization-authored policy bound to a BYOP base model such as cope-b or shieldstral.',
  annotationMethodology: 'No annotation methodology is provided by this integration; policy meaning depends on the organization-authored policy.',
  performanceBenchmarks: 'No benchmark claims are made. Performance depends on the selected base model and policy wording.',
  biasAndLimitations: 'Scores come from a single verdict label in the range [0,1]. Text only; images are not supported. Results may reflect limitations or bias in the selected base model and policy.',
  implementationGuidance:
    'Send text only. Parent and thread context are controlled on the Pigeon integration page under Evaluation context. When Coop includes them, the parent and earlier thread messages are flattened into the text sent to Pigeon.',
  relevantLinks: 'No public documentation links are available beyond the organization’s Pigeon deployment.',
};

export const manifest: IntegrationManifest = {
  id: INTEGRATION_ID,
  name: 'Pigeon',
  version: PACKAGE_VERSION,
  description: 'Scores text with organization-authored Pigeon policies.',
  requiresConfig: true,
  configurationFields: [
    {
      key: 'apiKey',
      label: 'API key',
      required: true,
      inputType: 'password',
      description: 'The Pigeon bearer token.',
    },
    {
      key: 'baseUrl',
      label: 'Base URL',
      required: false,
      inputType: 'text',
      placeholder: 'https://pigeon.example.com',
      description: 'Origin only; must be https and on a host the Coop operator allowed via PIGEON_ALLOWED_HOSTS. Leave blank to use PIGEON_DEFAULT_BASE_URL.',
    },
  ],
  /**
   * Coop owns which context is loaded (Evaluation context on the integration
   * page). The parent is included by default; the thread is opt-in. run()
   * flattens both into the classify text.
   */
  contextOptions: {
    thread: {
      default: 'off',
      defaultMaxMessages: 10,
      maxMessagesLimit: 100,
    },
    parent: { default: 'include' },
  },
  signalTypeIds: [SIGNAL_TYPE_ID],
  modelCard: {
    modelName: 'Pigeon policy classifier',
    version: PACKAGE_VERSION,
    sections: REQUIRED_MODEL_CARD_SECTION_IDS.map((id) => ({
      id,
      title: sectionTitles[id] ?? id,
      fields: [{ label: 'Notes', value: sectionContent[id] ?? 'No additional information is available.' }],
    })),
  },
};
