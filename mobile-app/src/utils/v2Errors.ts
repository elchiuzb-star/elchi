/**
 * What a person reads when a v2 request is refused, and what they read when it succeeded with a caveat.
 *
 * Same contract as the v1 map (`utils/errors.ts`): the server sends a code, this file chooses the sentence in
 * the reader's language. An unknown code falls back to the server's own `message`, which at least carries the
 * reason, rather than to a generic "try again" that carries nothing.
 */
import { ApiError, counterpartyStale } from "../types/api";
import { translate, translateDynamic } from "../i18n";

/** `true` when the request never reached the server (offline / DNS / CORS), so the UI can say exactly that. */
export function isOffline(error: unknown): boolean {
  return error instanceof TypeError || (typeof navigator !== "undefined" && navigator.onLine === false);
}

export function v2ErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "PROMO_CONSENT_REQUIRED"
      && (error.details as { party?: string } | undefined)?.party === "driver") {
    return translate("promoNotice.driverAckRequired"); // Q125: the driver confirms its own numbers
  }
  if (error instanceof ApiError && counterpartyStale(error)) {
    // Q126: the other side's confirmation went stale - requoting here would not help; say who has to act
    return translate("promoNotice.counterpartyStale");
  }
  if (error instanceof ApiError) {
    return translateDynamic(`error.${error.code}`) ?? error.message ?? translate("error.fallback");
  }
  if (isOffline(error)) return translate("error.offline");
  if (error instanceof Error && error.message) return error.message;
  return translate("error.fallback");
}

/**
 * Server warnings shown next to a successful action (Q43, Q90).
 *
 * A warning is not a failure: the thing the person asked for happened. Unknown codes fall through to the code
 * itself, which is ugly on purpose - it is a bug to be fixed in the dictionary, not a state to design for.
 */
export function warningMessage(code: string): string {
  return translateDynamic(`warning.${code}`) ?? code;
}
