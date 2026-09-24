/**
 * K5 recipient tracking links and O1 listing share links.
 *
 * Both links carry a secret token that the server returns **once** (only its hash is stored, ADR-0018): the screen
 * keeps it for this session and says so; there is no list endpoint to read it back. The tracking TTL stays inside
 * the Q83 pilot bounds (15 min - 24 h); the server re-checks them. Nothing is posted anywhere on the person's behalf.
 */
import { useState } from "react";

import {
  SHARE_LINK_MAX_HOURS,
  TRACKING_GRANT_MAX_MINUTES,
  TRACKING_GRANT_MIN_MINUTES,
  createShareLink,
  createTrackingGrant,
  revokeShareLink,
  revokeTrackingGrant,
  type ShareLinkChannel,
  type ShareLinkDTO,
  type TrackingGrantDTO,
} from "../../api/v2/safety.api";
import { newIdempotencyKey } from "../../api/v2/http";
import { formatDateTime } from "../../utils/v2Format";
import { v2ErrorMessage } from "../../utils/v2Errors";
import { Card, ErrorNote, InlineButton, PrimaryButton, SelectField } from "../ui/mobile";
import { translate } from "../../i18n";

/**
 * A `[value, label]` option whose label is looked up on every read, so a language switch reaches lists built once at
 * import. Destructuring (`[value, label]`) and `option[1]` both go through the getter.
 */
function option(value: number, label: () => string): [number, string] {
  const entry = [value, ""] as [number, string];
  Object.defineProperty(entry, 1, { get: label, enumerable: true });
  return entry;
}

/** Tracking link lifetimes offered to the person, all within Q83 (15 min - 24 h). */
export const TRACKING_TTL_OPTIONS: Array<[number, string]> = ([
  option(15, () => translate("trackingShare.ttlMinutes", { count: 15 })),
  option(60, () => translate("trackingShare.ttlHours", { count: 1 })),
  option(180, () => translate("trackingShare.ttlHours", { count: 3 })),
  option(360, () => translate("trackingShare.ttlHours", { count: 6 })),
  option(720, () => translate("trackingShare.ttlHours", { count: 12 })),
  option(1440, () => translate("trackingShare.ttlHours", { count: 24 })),
] as Array<[number, string]>).filter(
  ([minutes]) => minutes >= TRACKING_GRANT_MIN_MINUTES && minutes <= TRACKING_GRANT_MAX_MINUTES,
);

export const SHARE_TTL_OPTIONS: Array<[number, string]> = [
  option(24, () => translate("trackingShare.ttlDays", { count: 1 })),
  option(48, () => translate("trackingShare.ttlDays", { count: 2 })),
  option(72, () => translate("trackingShare.ttlDays", { count: 3 })),
  option(168, () => translate("trackingShare.ttlDays", { count: 7 })),
  option(SHARE_LINK_MAX_HOURS, () => translate("trackingShare.ttlDays", { count: 14 })),
];

/**
 * The link a recipient opens. The server's default template points at the JSON endpoint
 * (`/api/v2/public/tracking/<token>`); a person needs the page, so such a link is turned into `/t/<token>` on this
 * app's origin. A configured absolute page URL is kept as it is.
 */
export function trackingPageUrl(url: string, origin: string = window.location.origin): string {
  const marker = "/public/tracking/";
  const at = url.indexOf(marker);
  if (at >= 0) return `${origin}/t/${url.slice(at + marker.length)}`;
  if (url.startsWith("/")) return `${origin}${url}`;
  return url;
}

/** Same for a listing share link: the JSON path `/api/v2/public/listings/<token>` becomes the `/e/<token>` page. */
export function sharePageUrl(url: string, origin: string = window.location.origin): string {
  const marker = "/public/listings/";
  const at = url.indexOf(marker);
  if (at >= 0) return `${origin}/e/${url.slice(at + marker.length)}`;
  if (url.startsWith("/")) return `${origin}${url}`;
  return url;
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function LinkBox(props: { url: string; testId: string }) {
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  return (
    <div className="flex flex-col gap-2">
      <input
        readOnly
        value={props.url}
        data-testid={props.testId}
        onFocus={(event) => event.target.select()}
        className="h-10 w-full rounded-[10px] border border-border bg-background px-3 text-[13px] text-foreground"
      />
      <InlineButton tone="primary" onClick={async () => setCopied((await copyText(props.url)) ? "yes" : "no")}>
        {copied === "yes" ? translate("trackingShare.copied") : translate("trackingShare.copy")}
      </InlineButton>
      {copied === "no" && (
        <p className="text-[12px] text-muted-foreground">{translate("trackingShare.copyFailed")}</p>
      )}
    </div>
  );
}

// --- K5 tracking grant ---------------------------------------------------------------------------------------------

type IssuedGrant = TrackingGrantDTO & { revoked?: boolean };

export function TrackingGrantPanel(props: { bookingId: string; now?: () => Date }) {
  const [ttl, setTtl] = useState(TRACKING_TTL_OPTIONS[1]?.[0] ?? TRACKING_GRANT_MIN_MINUTES);
  const [grants, setGrants] = useState<IssuedGrant[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key, setKey] = useState(newIdempotencyKey);
  const now = props.now ?? (() => new Date());

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const grant = await createTrackingGrant(props.bookingId, ttl, key);
      setKey(newIdempotencyKey());
      setGrants((current) => [grant, ...current]);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(grantId: string) {
    setBusy(true);
    setError(null);
    try {
      await revokeTrackingGrant(props.bookingId, grantId);
      setGrants((current) => current.map((item) => (item.id === grantId ? { ...item, revoked: true } : item)));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <strong className="text-[15px]">{translate("trackingShare.trackingTitle")}</strong>
      <p className="text-[12px] leading-5 text-muted-foreground">
        {translate("trackingShare.trackingHint")}
      </p>
      <SelectField label={translate("trackingShare.ttlLabel")} value={String(ttl)} onChange={(value) => setTtl(Number(value))}>
        {TRACKING_TTL_OPTIONS.map(([minutes, label]) => (
          <option key={minutes} value={minutes}>{label}</option>
        ))}
      </SelectField>
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      <PrimaryButton disabled={busy} busy={busy} onClick={create}>{translate("trackingShare.create")}</PrimaryButton>
      {grants.map((grant) => {
        const expired = new Date(grant.expires_at).getTime() <= now().getTime();
        return (
          <div key={grant.id} className="flex flex-col gap-2 rounded-[12px] bg-background p-3" data-testid="tracking-grant">
            <p className="text-[12px] text-muted-foreground">
              {grant.revoked
                ? translate("trackingShare.revoked")
                : expired
                  ? translate("trackingShare.expiredAt", { time: formatDateTime(grant.expires_at) })
                  : translate("trackingShare.validUntil", { time: formatDateTime(grant.expires_at) })}
            </p>
            {!grant.revoked && !expired && grant.url ? <LinkBox url={trackingPageUrl(grant.url)} testId="tracking-url" /> : null}
            {!grant.revoked && !expired && !grant.url ? (
              <p className="text-[12px] text-muted-foreground">
                {translate("trackingShare.urlOnce")}
              </p>
            ) : null}
            {!grant.revoked && !expired ? (
              <InlineButton tone="danger" disabled={busy} onClick={() => revoke(grant.id)}>{translate("common.cancel")}</InlineButton>
            ) : null}
          </div>
        );
      })}
    </Card>
  );
}

// --- O1 listing share link -----------------------------------------------------------------------------------------

type IssuedShare = ShareLinkDTO & { revoked?: boolean };

export function ShareLinkPanel(props: { listingId: string }) {
  const [hours, setHours] = useState(48);
  const [channel, setChannel] = useState<ShareLinkChannel>("generic");
  const [links, setLinks] = useState<IssuedShare[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [key, setKey] = useState(newIdempotencyKey);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const link = await createShareLink(props.listingId, { ttl_hours: hours, channel }, key);
      setKey(newIdempotencyKey());
      setLinks((current) => [link, ...current]);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    setBusy(true);
    setError(null);
    try {
      await revokeShareLink(id);
      setLinks((current) => current.map((item) => (item.id === id ? { ...item, revoked: true } : item)));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <strong className="text-[15px]">{translate("trackingShare.shareTitle")}</strong>
      <p className="text-[12px] leading-5 text-muted-foreground">
        {translate("trackingShare.shareHint")}
      </p>
      <SelectField label={translate("trackingShare.ttlLabel")} value={String(hours)} onChange={(value) => setHours(Number(value))}>
        {SHARE_TTL_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </SelectField>
      <SelectField label={translate("trackingShare.channelLabel")} value={channel} onChange={(value) => setChannel(value as ShareLinkChannel)}>
        <option value="generic">{translate("trackingShare.channelGeneric")}</option>
        <option value="telegram">Telegram</option>
      </SelectField>
      <ErrorNote message={error ? v2ErrorMessage(error) : null} />
      <PrimaryButton disabled={busy} busy={busy} onClick={create}>{translate("trackingShare.create")}</PrimaryButton>
      {links.map((link) => (
        <div key={link.id} className="flex flex-col gap-2 rounded-[12px] bg-background p-3" data-testid="share-link">
          <p className="text-[12px] text-muted-foreground">
            {link.revoked ? translate("trackingShare.revoked") : translate("trackingShare.validUntil", { time: formatDateTime(link.expires_at) })}
          </p>
          {!link.revoked ? (
            <>
              <p className="whitespace-pre-line text-[13px] text-foreground">{link.share_text.split(link.url).join(sharePageUrl(link.url))}</p>
              <LinkBox url={sharePageUrl(link.url)} testId="share-url" />
              <InlineButton tone="danger" disabled={busy} onClick={() => revoke(link.id)}>{translate("common.cancel")}</InlineButton>
            </>
          ) : null}
        </div>
      ))}
    </Card>
  );
}

/** Both panels; each part only appears when its id is given. */
export function TrackingSharePanel(props: { bookingId?: string; listingId?: string }) {
  return (
    <div className="flex flex-col gap-3">
      {props.bookingId ? <TrackingGrantPanel bookingId={props.bookingId} /> : null}
      {props.listingId ? <ShareLinkPanel listingId={props.listingId} /> : null}
    </div>
  );
}
