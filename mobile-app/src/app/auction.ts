/**
 * What either side may do with a negotiation right now.
 *
 * ELCHI is a two-sided auction: both a client and a driver publish listings, both answer with a price, both
 * counter, and a booking exists only once someone accepts a version the *other* side authored. That last rule
 * is AC05, and it is the reason this file exists as its own module: the same six conditions were written inline
 * on three screens, which is three chances to let someone accept their own price.
 *
 * Pure on purpose - no React, no API, no formatting. It takes the thread the server sent and answers what the
 * buttons should be, so the rule can be tested directly instead of through a rendered screen.
 */
import type { Schemas } from "../api/v2/http";
import { translate } from "../i18n";

export type ProposalThreadDTO = Schemas["ProposalThreadDTO"];
export type ActorSide = "client" | "driver";

export interface NegotiationActions {
  /** The thread is live and its current version can still be answered. */
  open: boolean;
  /** The other side spoke last, so the ball is here. */
  theirTurn: boolean;
  /** AC05: never your own version. */
  canAccept: boolean;
  /** A price revision is still left for this side (`price_revisions_left`). */
  canCounter: boolean;
  /** You can take back what you wrote, not what they wrote. */
  canWithdraw: boolean;
  /** You can refuse what they wrote, not what you wrote. */
  canReject: boolean;
  /** How many more times this side may change the price. */
  revisionsLeft: number;
}

const CLOSED: NegotiationActions = {
  open: false,
  theirTurn: false,
  canAccept: false,
  canCounter: false,
  canWithdraw: false,
  canReject: false,
  revisionsLeft: 0,
};

/**
 * @param thread the thread as the server returned it (`current_version` is the only version that can be acted on)
 * @param mySide which side of this negotiation the viewer is
 */
export function negotiationActions(thread: ProposalThreadDTO, mySide: ActorSide): NegotiationActions {
  const version = thread.current_version;
  if (!version) return CLOSED;
  const open = thread.state === "open" && version.status === "active";
  if (!open) return CLOSED;

  const theirTurn = version.author_side !== mySide;
  const revisionsLeft = version.price_revisions_left?.[mySide] ?? 0;
  return {
    open,
    theirTurn,
    // AC05. Accepting your own version would let one person make a booking alone, which is not an agreement.
    canAccept: theirTurn,
    canCounter: revisionsLeft > 0,
    canWithdraw: !theirTurn,
    canReject: theirTurn,
    revisionsLeft,
  };
}

/** The sentence under a thread: whose answer is being waited on. */
export function turnLabel(actions: NegotiationActions, mySide: ActorSide): string {
  if (!actions.open) return translate("negotiation.closed");
  if (!actions.theirTurn) return translate("negotiation.waitingForAnswer");
  return mySide === "client" ? translate("negotiation.driverCountered") : translate("negotiation.clientCountered");
}

/**
 * The total a booking would be made at, in minor units.
 *
 * It is read off the version, never recomputed: the number the two sides agreed on is the number that lands on
 * the booking (Q90). A screen that multiplied a unit price by a quantity of its own would be inventing a fare.
 */
export function agreedTotalMinor(thread: ProposalThreadDTO): number | null {
  return thread.current_version?.total_minor ?? null;
}
