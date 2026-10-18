import { createHash } from 'node:crypto';
import type { PigeonPolicy } from './client.js';
import {
  MAX_CATALOG_VERSION_LENGTH,
  MAX_DESCRIPTION_LENGTH,
  MAX_LABEL_LENGTH,
  MAX_SUBCATEGORIES,
} from './constants.js';

function truncate(value: string, max: number): string {
  return value.length <= max ? value : value.slice(0, max);
}

export function policiesToSubcategories(
  policies: readonly PigeonPolicy[],
): ReadonlyArray<{
  id: string;
  label: string;
  description?: string;
  childrenIds: readonly string[];
}> {
  return policies
    .slice(0, MAX_SUBCATEGORIES)
    .map((policy) => {
      const label = truncate(policy.display || policy.id, MAX_LABEL_LENGTH);
      const details = [
        ...(policy.base ? [`base model ${policy.base}`] : []),
        `version ${policy.version}`,
      ].join(', ');
      const description = truncate(`Pigeon policy ${policy.id} (${details})`, MAX_DESCRIPTION_LENGTH);
      return {
        id: policy.id,
        label: label || policy.id,
        description,
        childrenIds: [],
      };
    })
    .sort((left, right) => left.label.localeCompare(right.label, 'en') || left.id.localeCompare(right.id, 'en'));
}

export function catalogVersion(policies: readonly PigeonPolicy[]): string {
  const input = policies
    .map((policy) => `${policy.id}@${policy.version}`)
    .sort()
    .join('\n');
  return `sha256:${createHash('sha256').update(input, 'utf8').digest('hex')}`.slice(
    0,
    MAX_CATALOG_VERSION_LENGTH,
  );
}
