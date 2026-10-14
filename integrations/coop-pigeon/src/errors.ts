export type PigeonErrorCode =
  | 'NOT_CONFIGURED'
  | 'INVALID_CONFIG'
  | 'AUTH_FAILED'
  | 'POLICY_REQUIRED'
  | 'UNKNOWN_POLICY'
  | 'UNSUPPORTED_INPUT'
  | 'INVALID_REQUEST'
  | 'TIMEOUT'
  | 'NETWORK_ERROR'
  | 'UPSTREAM_ERROR'
  | 'INVALID_RESPONSE';

/**
 * Error thrown by every part of this plugin. Messages are shown to Coop
 * admins, so they must never contain API keys, request bodies, classified
 * content, or raw Pigeon response bodies.
 */
export class PigeonError extends Error {
  override readonly name = 'PigeonError';
  readonly code: PigeonErrorCode;
  readonly status: number | undefined;

  constructor(
    code: PigeonErrorCode,
    message: string,
    options: { status?: number; cause?: unknown } = {},
  ) {
    super(`Pigeon ${code}: ${message}`, { cause: options.cause });
    this.code = code;
    this.status = options.status;
  }
}

export function isPigeonError(value: unknown): value is PigeonError {
  return value instanceof PigeonError;
}
