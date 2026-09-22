/**
 * What a person reads when a v1 request is refused.
 *
 * The server sends a machine code; the sentence is chosen here, in the reader's language. That is the whole
 * reason there is no `Accept-Language` negotiation in this app: `message` on the wire is an English developer
 * description, and it was never the text anybody was meant to see.
 *
 * Honest wording (spec §21.2): a refusal says what actually happened - a code has expired, a document is
 * missing, a balance is short - and never blames the network for a business rule. Most of these are things the
 * person can fix, and they can only fix what they are told.
 */
import { ApiError } from "../types/api";
import { translate, translateDynamic } from "../i18n";

/**
 * The message for an error, in the active language.
 *
 * Falls back in three steps: the code's own sentence, then the generic failure, and - when nothing reached the
 * server at all - the offline line, which is the one case where blaming the connection is the truth.
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return translateDynamic(`error.${error.code}`) ?? translate("error.fallback");
  }
  if (error instanceof Error && error.message) {
    return translate("error.fallback");
  }
  return translate("error.offline");
}
