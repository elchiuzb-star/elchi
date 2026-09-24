/**
 * The v2 in-app inbox (N4), read without React.
 *
 * In the pilot the inbox is the only delivery channel (Q82: no push provider), so two things have to be right:
 * the unread count on the bell, and where tapping an item takes the person. The server sends a `link` such as
 * `/bookings/bkg_…` or `/proposals/prp_…/messages` (`communications.recipients`) and message *keys*, never text -
 * the words are the client's, in the reader's language.
 */

export type InboxTarget =
  | { kind: "booking"; id: string; chat: boolean }
  | { kind: "listing"; id: string }
  | { kind: "proposal"; id: string }
  | { kind: "trip"; id: string }
  | { kind: "dispute"; id: string };

const PATTERNS: Array<[RegExp, (match: RegExpMatchArray) => InboxTarget]> = [
  [/^\/bookings\/([^/?#]+)(\/messages)?\/?$/, (m) => ({ kind: "booking", id: m[1], chat: Boolean(m[2]) })],
  [/^\/listings\/([^/?#]+)\/?$/, (m) => ({ kind: "listing", id: m[1] })],
  // A proposal's own chat is not opened by this client (Q100): the negotiation is the thread itself.
  [/^\/proposals\/([^/?#]+)(\/messages)?\/?$/, (m) => ({ kind: "proposal", id: m[1] })],
  [/^\/trips\/([^/?#]+)\/?$/, (m) => ({ kind: "trip", id: m[1] })],
  [/^\/disputes\/([^/?#]+)\/?$/, (m) => ({ kind: "dispute", id: m[1] })],
];

/** Where an item leads, or null when it leads nowhere this app has a screen for. */
export function parseInboxLink(link: string | null | undefined): InboxTarget | null {
  if (!link) return null;
  const path = link.trim().replace(/^https?:\/\/[^/]+/, "").replace(/^\/api\/v2/, "");
  for (const [pattern, build] of PATTERNS) {
    const match = path.match(pattern);
    if (match) return build(match);
  }
  return null;
}

export function unreadCount(items: ReadonlyArray<{ is_read: boolean }>): number {
  return items.filter((item) => !item.is_read).length;
}

/**
 * The title of an item: the server's key when the dictionary knows it, the event's generic key next, and a plain
 * "new notification" last - never the raw key, which reads like a bug.
 *
 * @param lookup `translateDynamic`, passed in so this stays testable without the dictionary
 */
export function inboxTitle(
  item: { title_key: string; type: string },
  lookup: (key: string) => string | undefined,
): string {
  return lookup(item.title_key) ?? lookup(`notification.${item.type}.title`) ?? lookup("notification.fallback.title") ?? item.type;
}

export function inboxBody(item: { body_key: string; type: string }, lookup: (key: string) => string | undefined): string {
  return lookup(item.body_key) ?? lookup(`notification.${item.type}.body`) ?? "";
}
