export const INTEGRATION_ID = 'PIGEON';
export const SIGNAL_TYPE_ID = 'PIGEON_POLICY_SCORE';
/** Keep in sync with package.json `version` (asserted in tests). */
export const PACKAGE_VERSION = '0.1.0';

export const SIGNAL_ID_PATTERN = /^[A-Z][A-Z0-9_]{0,99}$/;

/** Coop rejects catalogs with more than this many subcategories per signal. */
export const MAX_SUBCATEGORIES = 1000;
/** Coop limits display strings (names, labels) to 200 characters. */
export const MAX_LABEL_LENGTH = 200;
/** Coop limits descriptions to 2,000 characters. */
export const MAX_DESCRIPTION_LENGTH = 2000;
/** Coop limits catalog versions to 200 characters. */
export const MAX_CATALOG_VERSION_LENGTH = 200;
/** Upper bound on a policy id we accept from Pigeon. */
export const MAX_POLICY_ID_LENGTH = 200;
/** Upper bound on text sent to Pigeon's classify endpoint (UTF-16 code units). */
export const MAX_CLASSIFY_TEXT_LENGTH = 100_000;
/** Upper bound on a Pigeon response body we will parse. */
export const MAX_RESPONSE_BYTES = 1_000_000;

export const RUN_TIMEOUT_MS = 8_000;
