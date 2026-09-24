export type ApiErrorBody = {
  code: string;
  message: string;
  details?: unknown;
};

export type ApiSuccess<T> = {
  success: true;
  data: T;
  message?: string;
};

export type ApiFailure = {
  success: false;
  error: ApiErrorBody;
};

export type ApiEnvelope<T> = ApiSuccess<T> | ApiFailure;

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(status: number, error: ApiErrorBody) {
    super(error.message);
    this.name = "ApiError";
    this.code = error.code;
    this.status = status;
    this.details = error.details;
  }
}

export type Paginated<T> = {
  items: T[];
  pagination?: {
    page: number;
    limit: number;
    total: number;
    total_pages: number;
  };
};

/** Referral Q126: a PROMO_QUOTE_STALE whose cause is the *other* side's confirmation (it must confirm again). */
export function counterpartyStale(error: ApiError): boolean {
  if (error.code !== "PROMO_QUOTE_STALE") return false;
  const reasons = (error.details as { reasons?: unknown } | undefined)?.reasons;
  return Array.isArray(reasons) && reasons.some((r) => r === "counterparty_confirmation_stale" || r === "counterparty_client_outdated");
}
