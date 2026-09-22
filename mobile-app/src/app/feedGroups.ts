/**
 * Splitting a feed page into what the driver asked for and what is merely close to it.
 *
 * The server can already answer a wider question than "my exact route at my exact hour": with
 * `include_alternatives=true` it also returns matches that sit within the corridor's search radius of the
 * stop, or within three hours of the window, and marks each one `group: "alternative"` (ADR/§6.4, §8.2). That
 * group is deliberately ranked *below* every primary match and never scored against them - an alternative is
 * a suggestion, not a result.
 *
 * Which is exactly why the split cannot be done by eye on the screen. The two groups arrive in one ordered
 * page, and a list that renders them together tells the driver a match at 06:00 and a match at 09:00 are the
 * same kind of answer. So the page is cut here, once, into `primary` and `alternative`, and each alternative
 * carries the one reason it is one.
 *
 * Pure on purpose - no React, no API, no formatting - so the rule is testable without a browser, the way
 * `auction.ts` is.
 */
import type { Schemas } from "../api/v2/http";

type MatchGroup = Schemas["MatchGroup"];

/** Both feed surfaces the driver meets carry the same two fields, so both can be split by this. */
export interface GroupedItem {
  group: MatchGroup;
  match: { reasons: string[] };
}

export interface FeedGroups<T> {
  /** `exact` and `on_route`: the question the driver actually asked. */
  primary: T[];
  /** Close, but not what was asked - shown under its own heading, never mixed in. */
  alternative: T[];
}

export function splitFeedGroups<T extends GroupedItem>(items: readonly T[]): FeedGroups<T> {
  const primary: T[] = [];
  const alternative: T[] = [];
  for (const item of items) {
    // Anything the server did not call an alternative is a primary result. Defaulting the *other* way would
    // quietly demote a real match if a new group were ever added.
    (item.group === "alternative" ? alternative : primary).push(item);
  }
  return { primary, alternative };
}

/**
 * Why this one is only a suggestion, in the driver's words.
 *
 * "Muqobil" on its own is not actionable: the driver has to know whether to look at the clock or at the map.
 * `time_differs` is checked first because it is the one that costs the driver a decision - a nearby stop is a
 * few minutes' driving, a different hour can mean the trip does not work at all.
 *
 * Returns null when the server sent no reason we can explain, so the caller shows the bare label rather than
 * inventing one.
 */
export function alternativeReason(reasons: readonly string[]): "time_differs" | "nearby_stop" | null {
  if (reasons.includes("time_differs")) return "time_differs";
  if (reasons.includes("nearby_stop")) return "nearby_stop";
  return null;
}
