import { describe, expect, it } from "vitest";

import { inboxBody, inboxTitle, parseInboxLink, unreadCount } from "./inbox";
import { translateDynamic } from "../i18n";

describe("parseInboxLink", () => {
  it("reads the links communications.recipients writes", () => {
    expect(parseInboxLink("/bookings/bkg_1")).toEqual({ kind: "booking", id: "bkg_1", chat: false });
    expect(parseInboxLink("/bookings/bkg_1/messages")).toEqual({ kind: "booking", id: "bkg_1", chat: true });
    expect(parseInboxLink("/listings/lst_2")).toEqual({ kind: "listing", id: "lst_2" });
    expect(parseInboxLink("/proposals/prp_3")).toEqual({ kind: "proposal", id: "prp_3" });
    expect(parseInboxLink("/proposals/prp_3/messages")).toEqual({ kind: "proposal", id: "prp_3" });
    expect(parseInboxLink("/trips/trp_4")).toEqual({ kind: "trip", id: "trp_4" });
    expect(parseInboxLink("/support-threads/sth_5")).toEqual({ kind: "support_thread", id: "sth_5" });
    expect(parseInboxLink("/disputes/dsp_5")).toBeNull(); // ADR-0026: no dispute screen any more
  });

  it("tolerates an absolute or prefixed link and ignores what it has no screen for", () => {
    expect(parseInboxLink("https://api.example/api/v2/bookings/bkg_1")).toEqual({ kind: "booking", id: "bkg_1", chat: false });
    expect(parseInboxLink("/wallet")).toBeNull();
    expect(parseInboxLink(null)).toBeNull();
    expect(parseInboxLink("")).toBeNull();
  });
});

describe("inbox text", () => {
  it("counts unread items for the bell", () => {
    expect(unreadCount([{ is_read: false }, { is_read: true }, { is_read: false }])).toBe(2);
  });

  it("never shows a raw key for a known event", () => {
    const item = { type: "booking.accepted", title_key: "notification.booking.accepted.title", body_key: "notification.booking.accepted.body" };
    expect(inboxTitle(item, translateDynamic)).not.toContain("notification.");
    expect(inboxBody(item, translateDynamic)).not.toContain("notification.");
  });

  it("falls back to a plain title for an event it does not know", () => {
    const item = { type: "something.new", title_key: "notification.something.new.title", body_key: "notification.something.new.body" };
    expect(inboxTitle(item, translateDynamic)).toBe(translateDynamic("notification.fallback.title"));
    expect(inboxBody(item, translateDynamic)).toBe("");
  });
});
