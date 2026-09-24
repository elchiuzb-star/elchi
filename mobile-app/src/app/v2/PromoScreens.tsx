/**
 * Referral and bonus screens (referral stage 5, ADR-0023 §19).
 *
 * The server computes every amount; these components only show the server's numbers and send the person's explicit
 * choices. A bonus is a discount right, never money: nothing here says "balance", "withdraw" or "cash out" about it.
 * The client never sees a commission, a credit or a rate (Q16, Q103).
 */
import qrcode from "qrcode-generator";
import { useEffect, useMemo, useState } from "react";

import {
  attributeReferral,
  confirmProposalPromo,
  enrollInCampaign,
  listingPromoPreview,
  myPromoBalance,
  myReferralCode,
  myReferrals,
  referralOffers,
  type EnrollmentDTO,
  type EnrollmentOfferDTO,
  type ProposalPromoClientDTO,
  type ReferralCodeDTO,
} from "../../api/v2/promo.api";
import { newIdempotencyKey } from "../../api/v2/http";
import { translate } from "../../i18n";
import { formatUzs } from "../../utils/money";
import { v2ErrorMessage } from "../../utils/v2Errors";
import {
  ENROLLMENT_LABELS,
  INSTRUMENT_LABELS,
  parcelPayerRule,
  QUALIFICATION_LABELS,
  actionKey,
  bucketRows,
  clientMoneyLines,
  disclosureText,
  driverMoneyLines,
  finishAction,
  forgetCode,
  noDiscountText,
  normalizeCode,
  pendingCode,
  progressRows,
  withPreview,
  type BookingPromoClientDTO,
  type BookingPromoDriverDTO,
  type ConsentChoice,
  type MoneyLine,
  type ProposalPromoDriverDTO,
} from "../promo";
import { Card, EmptyState, ErrorNote, Field, InlineButton, PrimaryButton, SectionLabel, SkeletonCard, TopBar, WarningNote } from "../ui/mobile";
import { Info, Tag } from "../ui/icons";
import { useAsync } from "./useAsync";

/** An amount never breaks across lines ("197 000 so'm" stays one piece on a narrow screen). */
function soum(minor: number): string {
  return formatUzs(minor / 100).replace(/ /g, "\u00a0");
}

/** Promotions switched off (production default, Q101): a plain sentence, not an error to retry. */
function programOff(error: unknown): boolean {
  return (error as { code?: string } | null)?.code === "FEATURE_DISABLED";
}

function Lines({ lines }: { lines: MoneyLine[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      {lines.map((line) => (
        <div key={line.label} className="flex items-baseline justify-between gap-3">
          <span className="text-[13px] text-muted-foreground">{line.label}</span>
          <span className={(line.emphasis ? "text-[15px] font-semibold" : "text-[14px]") + " shrink-0 whitespace-nowrap text-foreground"}>
            {line.negative && line.minor > 0 ? "− " : ""}
            {soum(line.minor)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Money of a discounted booking or offer, in the reader's role. `null` promo -> nothing is rendered. */
export function PromoMoneyCard({
  promo,
  title = translate("promoScreen.moneyTitle"),
  agreed = true,
}: {
  promo: BookingPromoClientDTO | BookingPromoDriverDTO | ProposalPromoClientDTO | ProposalPromoDriverDTO | null | undefined;
  title?: string;
  /** A booking (true) or an offer nobody has accepted yet (false). */
  agreed?: boolean;
}) {
  if (!promo) return null;
  return (
    <Card>
      <p className="flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
        <Tag size={15} color="var(--primary)" /> {title}
      </p>
      {promo.view === "client" ? <Lines lines={clientMoneyLines(promo, agreed)} /> : <Lines lines={driverMoneyLines(promo, agreed)} />}
      {promo.view === "client" ? (
        <p className="text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.clientCovers")}</p>
      ) : (
        <p className="text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.driverCovers")}</p>
      )}
    </Card>
  );
}

/**
 * Before sending an offer or a counter: what the person's own bonus does to the price they typed.
 * The box starts **unticked**; a new price clears the tick (a new amount is a new agreement).
 */
export function BonusConsentPanel({
  listingId,
  unitPriceMinor,
  quantity,
  choice,
  onChoice,
  refreshToken = 0,
}: {
  listingId: string;
  unitPriceMinor: number;
  quantity: number;
  choice: ConsentChoice;
  onChoice: (choice: ConsentChoice) => void;
  /** Bump to re-read after a PROMO_QUOTE_STALE refusal. */
  refreshToken?: number;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    if (!listingId || unitPriceMinor <= 0) {
      onChoice(withPreview(choice, null));
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      listingPromoPreview(listingId, unitPriceMinor, quantity)
        .then((preview) => {
          if (cancelled) return;
          setReason(preview.quote ? null : (preview.no_discount_reason ?? null));
          onChoice(withPreview(choice, preview.quote ?? null));
        })
        .catch((cause) => {
          if (!cancelled) {
            setError(v2ErrorMessage(cause));
            onChoice(withPreview(choice, null));
          }
        })
        .finally(() => !cancelled && setLoading(false));
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // choice is read, not a trigger: re-quoting on every tick would clear the person's choice
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listingId, unitPriceMinor, quantity, refreshToken]);

  if (loading && !choice.shown) return <SkeletonCard lines={2} />;
  if (error) return <ErrorNote message={translate("promoScreen.quoteFailed", { error })} />;
  const shown = choice.shown;
  if (!shown) return <NoDiscountNote reason={reason} />; // the offer is sent without a bonus; say why, plainly
  return (
    <Card>
      <Lines lines={clientMoneyLines(shown, false)} />
      <label className="mt-1 flex items-start gap-2.5 text-[14px] text-foreground">
        <input
          type="checkbox"
          className="mt-1 h-5 w-5 shrink-0"
          checked={choice.useBonus}
          onChange={(event) => onChoice({ ...choice, useBonus: event.target.checked })}
        />
        <span>
          {translate("promoScreen.useBonusLine", {
            bonus: soum(shown.passenger_discount_minor),
            cash: soum(shown.cash_due_minor),
          })}
        </span>
      </label>
      <p className="text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.consentNote")}</p>
    </Card>
  );
}

/** Accepting a driver's version: the version's own client quote and an explicit tick. */
export function AcceptConsentPanel({
  quote,
  choice,
  onChoice,
}: {
  quote: ProposalPromoClientDTO | null | undefined;
  choice: ConsentChoice;
  onChoice: (choice: ConsentChoice) => void;
}) {
  useEffect(() => {
    onChoice(withPreview(choice, quote ?? null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quote?.fare_minor, quote?.passenger_discount_minor, quote?.cash_due_minor]);
  if (!quote) return null;
  return (
    <div className="rounded-[12px] border border-border bg-muted/40 p-3">
      <Lines lines={clientMoneyLines(quote, false)} />
      <label className="mt-2 flex items-start gap-2.5 text-[13px] text-foreground">
        <input
          type="checkbox"
          className="mt-0.5 h-5 w-5 shrink-0"
          checked={choice.useBonus}
          onChange={(event) => onChoice({ ...choice, useBonus: event.target.checked })}
        />
        <span>{translate("promoScreen.useBonusShort", { amount: soum(quote.passenger_discount_minor) })}</span>
      </label>
    </div>
  );
}

/** "Why is there no discount?" - a plain category from the server; nothing about rates, limits or checks. */
export function NoDiscountNote({ reason }: { reason: string | null | undefined }) {
  const text = noDiscountText(reason);
  if (!text) return null;
  return (
    <p className="flex items-start gap-2 rounded-[12px] bg-muted px-3 py-2.5 text-[12px] leading-5 text-muted-foreground">
      <Info size={14} className="mt-0.5 shrink-0" />
      <span>
        <span className="font-semibold text-secondary-foreground">{translate("promoScreen.whyNoDiscount")}{" "}</span>
        {text}
      </span>
    </p>
  );
}

/**
 * Q126: the author of an open offer whose promo confirmation went stale (it logged out, its app changed) confirms it
 * again from this session. The client repeats exactly the numbers shown now; the offer - price, places, times - is
 * not touched. Only the author ever gets `promo_confirmation`, so this renders nothing for anyone else.
 */
export function StaleConfirmation({
  threadId,
  side,
  version,
  onDone,
}: {
  threadId: string;
  /** The author's side: the client repeats its bonus numbers, the driver only re-declares its app. */
  side: "client" | "driver";
  version: {
    id: string;
    promo_confirmation?: "valid" | "stale" | null;
    promo_quote?: ProposalPromoClientDTO | ProposalPromoDriverDTO | null;
  };
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (version.promo_confirmation !== "stale") return null;
  const clientQuote = side === "client" && version.promo_quote?.view === "client" ? version.promo_quote : null;
  const isDriver = side === "driver";
  const scope = `promo-confirm:${threadId}:${version.id}`;
  return (
    <div className="rounded-[12px] border border-warning/40 bg-warning/5 p-3">
      <p className="text-[13px] font-semibold text-foreground">{translate("promoScreen.staleTitle")}</p>
      <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.staleNote")}</p>
      {clientQuote && <Lines lines={clientMoneyLines(clientQuote, false)} />}
      {!clientQuote && !isDriver && (
        <p className="mt-1 text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.staleNoBonus")}</p>
      )}
      <ErrorNote message={error} />
      {clientQuote || isDriver ? (
        <PrimaryButton
          busy={busy}
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            const consent = clientQuote
              ? { passenger_bonus_minor: clientQuote.passenger_discount_minor, cash_due_minor: clientQuote.cash_due_minor }
              : undefined;
            confirmProposalPromo(threadId, version.id, consent, actionKey(scope, newIdempotencyKey))
              .then(() => {
                finishAction(scope);
                onDone();
              })
              .catch((cause) => {
                finishAction(scope);
                setError(v2ErrorMessage(cause));
              })
              .finally(() => setBusy(false));
          }}
        >
          {clientQuote ? translate("promoScreen.agreeQuote") : translate("common.confirm")}
        </PrimaryButton>
      ) : null}
    </div>
  );
}

/**
 * The referral link as a QR code, drawn here on the device (qrcode-generator, no network): the code never leaves the
 * phone for a QR service. It holds exactly the link the server gave - nothing is added to it.
 */
export function ReferralQr({ url, size = 184 }: { url: string; size?: number }) {
  const cells = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(url, "Byte");
    qr.make();
    const count = qr.getModuleCount();
    const dark: string[] = [];
    for (let row = 0; row < count; row += 1) {
      for (let col = 0; col < count; col += 1) {
        if (qr.isDark(row, col)) dark.push(`M${col + 4} ${row + 4}h1v1h-1z`);
      }
    }
    return { count: count + 8, path: dark.join("") };
  }, [url]);
  return (
    <svg
      role="img"
      aria-label={translate("promoScreen.qrAria")}
      width={size}
      height={size}
      viewBox={`0 0 ${cells.count} ${cells.count}`}
      shapeRendering="crispEdges"
      className="mx-auto rounded-[8px]"
    >
      <rect width={cells.count} height={cells.count} fill="var(--qr-light)" />
      <path d={cells.path} fill="var(--qr-dark)" />
    </svg>
  );
}

function ProgressBlock({ progress }: { progress: NonNullable<EnrollmentDTO["progress"]> }) {
  return (
    <div className="flex flex-col gap-1 rounded-[10px] bg-muted/50 px-3 py-2">
      {progressRows(progress).map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-3">
          <span className="text-[12px] text-muted-foreground">
            {row.label}
            {row.hint && row.kind === "in_review" && progress.in_review > 0 ? (
              <span className="block text-[11px]">{row.hint}</span>
            ) : null}
          </span>
          <span className="shrink-0 whitespace-nowrap text-[13px] font-semibold text-foreground">{row.value}</span>
        </div>
      ))}
      {(progress.milestones ?? []).length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {(progress.milestones ?? []).map((m) => (
            <span
              key={m.threshold}
              className={
                "rounded-full px-2 py-0.5 text-[11px] " +
                (m.reached ? "bg-success/15 text-success" : "bg-card text-muted-foreground")
              }
            >
              {m.reached
                ? translate("promoScreen.milestoneReached", { count: m.threshold })
                : translate("promoScreen.milestone", { count: m.threshold })}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// --- the bonus screen ---------------------------------------------------------------------------------------------

function Offer({ offer, onJoined }: { offer: EnrollmentOfferDTO; onJoined: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scope = `enroll:${offer.campaign_id}:${offer.version_no}`;
  return (
    <Card>
      <p className="text-[15px] font-semibold text-foreground">{offer.campaign_name}</p>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-[13px] leading-5 text-secondary-foreground">
        {offer.disclosures.map((item) => {
          const sentence = disclosureText(item);
          return sentence ? <li key={item.code}>{sentence}</li> : null;
        })}
        {offer.parcel_sender_pays_only && <li>{parcelPayerRule()}</li>}
      </ul>
      <ErrorNote message={error} />
      <PrimaryButton
        busy={busy}
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          enrollInCampaign(offer, actionKey(scope, newIdempotencyKey))
            .then(() => {
              finishAction(scope);
              onJoined();
            })
            .catch((cause) => setError(v2ErrorMessage(cause)))
            .finally(() => setBusy(false));
        }}
      >
        {translate("promoScreen.joinOffer")}
      </PrimaryButton>
    </Card>
  );
}

export function BonusScreen({ role, back }: { role: "client" | "driver"; back: () => void }) {
  const balance = useAsync(() => myPromoBalance(), []);
  const referrals = useAsync(() => myReferrals(), []);
  const offers = useAsync(() => referralOffers(role), [role]);
  const [code, setCode] = useState<ReferralCodeDTO | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [entered, setEntered] = useState(pendingCode() ?? "");
  const [enterBusy, setEnterBusy] = useState(false);
  const [enterError, setEnterError] = useState<string | null>(null);
  const [enterDone, setEnterDone] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const hasAttribution = (referrals.data?.attributions ?? []).some((item) => item.audience === role);
  const normalized = normalizeCode(entered);

  async function showCode() {
    setCodeError(null);
    try {
      setCode(await myReferralCode(actionKey("referral-code", newIdempotencyKey)));
      finishAction("referral-code");
    } catch (cause) {
      setCodeError(programOff(cause) ? translate("promoScreen.programOff") : v2ErrorMessage(cause));
    }
  }

  async function submitCode() {
    if (!normalized) return;
    setEnterBusy(true);
    setEnterError(null);
    const scope = `attribute:${role}:${normalized}`;
    try {
      await attributeReferral(normalized, role, actionKey(scope, newIdempotencyKey));
      finishAction(scope);
      forgetCode();
      setEnterDone(translate("promoScreen.codeAccepted"));
      referrals.reload();
      offers.reload();
    } catch (cause) {
      finishAction(scope);
      setEnterError(programOff(cause) ? translate("promoScreen.programOff") : v2ErrorMessage(cause));
    } finally {
      setEnterBusy(false);
    }
  }

  const title = role === "client" ? translate("promoScreen.titleClient") : translate("promoScreen.titleDriver");
  return (
    <main className="flex min-h-0 flex-1 flex-col bg-background">
      <TopBar title={title} back={back} />
      <section className="el-enter min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-28 pt-5">
        <WarningNote>
          {role === "client"
            ? translate("promoScreen.bonusNotMoney")
            : translate("promoScreen.creditNotMoney")}
        </WarningNote>

        <SectionLabel>{role === "client" ? translate("promoScreen.myBonuses") : translate("promoScreen.myCredit")}</SectionLabel>
        {balance.loading ? (
          <SkeletonCard lines={3} />
        ) : balance.error ? (
          <ErrorNote message={v2ErrorMessage(balance.error)} onRetry={balance.reload} />
        ) : (balance.data?.buckets ?? []).length === 0 ? (
          <EmptyState icon={Tag} title={translate("promoScreen.noBonusTitle")} subtitle={translate("promoScreen.noBonusSubtitle")} />
        ) : (
          balance.data!.buckets.map((bucket) => (
            <Card key={`${bucket.instrument}:${bucket.service_type}`}>
              <p className="text-[14px] font-semibold text-foreground">
                {INSTRUMENT_LABELS[bucket.instrument] ?? bucket.instrument} ·{" "}
                {bucket.service_type === "parcel" ? translate("promoScreen.service.parcel") : translate("promoScreen.service.passenger")}
              </p>
              {bucketRows(bucket).map((row) => (
                <div key={row.label} className="flex items-baseline justify-between gap-3">
                  <span className="text-[13px] text-muted-foreground">
                    {row.label}
                    {row.hint && row.minor > 0 ? <span className="block text-[11px]">{row.hint}</span> : null}
                  </span>
                  <span className="shrink-0 whitespace-nowrap text-[14px] text-foreground">{soum(row.minor)}</span>
                </div>
              ))}
              {bucket.next_expiry_at && (
                <p className="text-[12px] text-muted-foreground">
                  {translate("promoScreen.nextExpiry", { date: new Date(bucket.next_expiry_at).toLocaleDateString("uz-UZ") })}
                </p>
              )}
            </Card>
          ))
        )}

        <SectionLabel>{translate("promoScreen.myCode")}</SectionLabel>
        <Card>
          {code ? (
            <>
              <p className="text-center text-[24px] font-bold tracking-[0.2em] text-foreground">{code.code}</p>
              {code.share_url ? (
                <>
                  {role === "driver" && <ReferralQr url={code.share_url} />}
                  <p className="break-all text-center text-[13px] text-primary">{code.share_url}</p>
                  {role === "driver" && (
                    <p className="text-center text-[11px] leading-4 text-muted-foreground">
                      {translate("promoScreen.qrNote")}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-center text-[12px] leading-5 text-muted-foreground">
                  {translate("promoScreen.linkNotReady")}
                </p>
              )}
              <InlineButton
                onClick={() => {
                  void navigator.clipboard?.writeText(code.share_url ?? code.code).then(() => setCopied(true));
                }}
              >
                {copied ? translate("promoScreen.copied") : translate("promoScreen.copy")}
              </InlineButton>
              <p className="text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.rewardNote")}</p>
            </>
          ) : (
            <>
              <ErrorNote message={codeError} />
              <InlineButton onClick={() => void showCode()}>{translate("promoScreen.showCode")}</InlineButton>
            </>
          )}
        </Card>

        {enterDone && <p className="rounded-[12px] bg-success/10 px-3 py-2.5 text-[13px] text-success">{enterDone}</p>}
        {!hasAttribution && (
          <>
            <SectionLabel>{translate("promoScreen.enterCode")}</SectionLabel>
            <Card>
              <Field
                label={translate("promoScreen.friendCode")}
                value={entered}
                placeholder={translate("promoScreen.codeExample")}
                onChange={setEntered}
              />
              {entered && !normalized && <p className="text-[12px] text-destructive">{translate("promoScreen.codeFormat")}</p>}
              <ErrorNote message={enterError} />
              <PrimaryButton busy={enterBusy} disabled={!normalized || enterBusy} onClick={() => void submitCode()}>
                {translate("promoScreen.confirmCode")}
              </PrimaryButton>
              <p className="text-[12px] leading-5 text-muted-foreground">{translate("promoScreen.codeOnce")}</p>
            </Card>
          </>
        )}

        {(offers.data ?? []).length > 0 && <SectionLabel>{translate("promoScreen.availableCampaigns")}</SectionLabel>}
        {offers.error && programOff(offers.error) ? (
          <p className="flex items-start gap-2 rounded-[12px] bg-muted px-3 py-2.5 text-[13px] text-muted-foreground">
            <Info size={15} className="mt-0.5 shrink-0" /> {translate("promoScreen.programOffWithBalance")}
          </p>
        ) : offers.error ? (
          <ErrorNote message={v2ErrorMessage(offers.error)} onRetry={offers.reload} />
        ) : null}
        {(offers.data ?? []).map((offer) => (
          <Offer
            key={`${offer.campaign_id}:${offer.version_no}`}
            offer={offer}
            onJoined={() => {
              offers.reload();
              referrals.reload();
            }}
          />
        ))}

        <SectionLabel>{translate("promoScreen.myCampaigns")}</SectionLabel>
        {referrals.loading ? (
          <SkeletonCard lines={2} />
        ) : referrals.error ? (
          <ErrorNote message={v2ErrorMessage(referrals.error)} onRetry={referrals.reload} />
        ) : (referrals.data?.enrollments ?? []).length === 0 ? (
          <p className="flex items-start gap-2 text-[13px] text-muted-foreground">
            <Info size={15} className="mt-0.5 shrink-0" /> {translate("promoScreen.noCampaigns")}
          </p>
        ) : (
          referrals.data!.enrollments.map((item) => (
            <Card key={item.id}>
              <p className="text-[14px] font-semibold text-foreground">{item.campaign_name}</p>
              <p className="text-[13px] text-secondary-foreground">
                {item.side === "referee" ? translate("promoScreen.youAreInvited") : translate("promoScreen.youInvited")} ·{" "}
                {(item.qualification_status && QUALIFICATION_LABELS[item.qualification_status]) ??
                  ENROLLMENT_LABELS[item.status] ??
                  item.status}
              </p>
              {item.progress && <ProgressBlock progress={item.progress} />}
              <p className="text-[12px] text-muted-foreground">
                {translate("promoScreen.deadline", { date: new Date(item.qualification_deadline).toLocaleDateString("uz-UZ") })}
              </p>
            </Card>
          ))
        )}
        {referrals.data && (
          <p className="text-[12px] text-muted-foreground">
            {translate("promoScreen.invitedCount", {
              count: Object.values(referrals.data.invited).reduce((a, b) => a + b, 0),
            })}
          </p>
        )}
      </section>
    </main>
  );
}
