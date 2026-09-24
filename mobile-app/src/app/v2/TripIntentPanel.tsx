/**
 * ADR-0025: the client's saved trip/parcel request on screen - the one-line summary with its actions, and the
 * edit form. State lives in ConnectedApp; these only draw it and report taps.
 */
import { useState } from "react";

import type { TripIntentDTO, TripIntentFitDTO } from "../../api/v2/tripIntents.api";
import { Field, PrimaryButton, SecondaryButton, cls } from "../ui/mobile";
import { translate, type MessageKey } from "../../i18n";
import {
  fitNotes,
  intentSummary,
  isExpired,
  isoToLocalInput,
  priceLine,
  type ParcelFields,
} from "../tripIntent";

const PARCEL_TYPES: Array<[string, MessageKey]> = [
  ["documents", "tripIntent.parcelType.documents"],
  ["box", "tripIntent.parcelType.box"],
  ["bag", "tripIntent.parcelType.bag"],
  ["electronics", "tripIntent.parcelType.electronics"],
  ["clothing", "tripIntent.parcelType.clothing"],
  ["other", "tripIntent.parcelType.other"],
];

export function TripIntentSummary(props: {
  intent: TripIntentDTO | null;
  others: TripIntentDTO[];
  loading: boolean;
  error: string | null;
  busy?: boolean;
  onEdit: () => void;
  onNew: () => void;
  onReopen: () => void;
  onRetry: () => void;
  onSelect: (intent: TripIntentDTO) => void;
}) {
  const { intent } = props;
  if (props.loading && !intent) {
    return (
      <div className="rounded-[16px] border border-border bg-card p-4" aria-busy="true">
        <div className="el-skeleton h-4 w-3/4" />
        <div className="el-skeleton mt-2 h-3 w-1/2" />
      </div>
    );
  }
  if (props.error && !intent) {
    return (
      <div className="rounded-[16px] border border-destructive/30 bg-destructive/5 p-4">
        <p className="text-[13px] leading-5 text-destructive">{translate("tripIntent.loadFailed", { error: props.error })}</p>
        <button type="button" onClick={props.onRetry} className="el-press mt-2 text-[13px] font-semibold text-primary">
          {translate("common.retry")}
        </button>
      </div>
    );
  }
  if (!intent) {
    return (
      <div className="rounded-[16px] border border-dashed border-border bg-card p-4">
        <p className="text-[14px] font-semibold text-foreground">{translate("tripIntent.emptyTitle")}</p>
        <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
          {translate("tripIntent.emptyHint")}
        </p>
        <button type="button" onClick={props.onNew} className="el-press mt-3 h-10 w-full rounded-[10px] bg-primary text-[14px] font-semibold text-primary-foreground">
          {translate("tripIntent.new")}
        </button>
      </div>
    );
  }
  const expired = intent.expired || isExpired(intent);
  const booked = intent.status === "booked";
  const v = intent.current_version;
  const others = props.others.filter((item) => item.id !== intent.id && item.status !== "closed");
  return (
    <div className={cls("rounded-[16px] border bg-card p-4", expired ? "border-warning/50" : "border-primary/30")}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
        {intent.service_type === "passenger" ? translate("tripIntent.passengerTitle") : translate("tripIntent.parcelTitle")}
      </p>
      <p className="mt-1 text-[15px] font-semibold leading-6 text-foreground" data-testid="intent-summary">
        {intentSummary(intent)}
      </p>
      {v.price_basis && v.unit_price_minor ? (
        <p className="mt-0.5 text-[12px] text-muted-foreground">
          {translate("tripIntent.yourPrice", { price: priceLine(v.price_basis, v.unit_price_minor, v.quantity) })}
        </p>
      ) : null}
      {intent.open_offers > 0 && !booked && (
        <p className="mt-0.5 text-[12px] text-muted-foreground">{translate("tripIntent.openOffers", { count: intent.open_offers })}</p>
      )}
      {expired && !booked && (
        <p className="mt-2 rounded-[10px] bg-warning/14 px-3 py-2 text-[12px] leading-5 text-warning">
          {translate("tripIntent.expiredHint")}
        </p>
      )}
      {booked && (
        <p className="mt-2 rounded-[10px] bg-accent px-3 py-2 text-[12px] leading-5 text-primary">
          {props.intent?.can_reopen
            ? translate("tripIntent.bookingCancelledHint")
            : translate("tripIntent.bookedHint")}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        {booked ? (
          props.intent?.can_reopen ? (
            <button type="button" disabled={props.busy} onClick={props.onReopen} className="el-press min-h-10 flex-1 rounded-[10px] px-2 py-2 leading-tight bg-primary text-[13px] font-semibold text-primary-foreground disabled:opacity-60">
              {translate("bookingCancel.searchAgain")}
            </button>
          ) : null
        ) : (
          <button type="button" disabled={props.busy} onClick={props.onEdit} className={cls("el-press min-h-10 flex-1 rounded-[10px] px-2 py-2 leading-tight text-[13px] font-semibold disabled:opacity-60", expired ? "bg-primary text-primary-foreground" : "border border-primary text-primary")}>
            {expired ? translate("tripIntent.updateTime") : translate("listingOwner.edit")}
          </button>
        )}
        <button type="button" disabled={props.busy} onClick={props.onNew} className="el-press min-h-10 flex-1 rounded-[10px] px-2 py-2 leading-tight border border-border text-[13px] font-semibold text-foreground disabled:opacity-60">
          {translate("tripIntent.new")}
        </button>
      </div>
      {others.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="text-[11px] font-semibold text-muted-foreground">{translate("tripIntent.others")}</p>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {others.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => props.onSelect(item)}
                className="el-press truncate rounded-[10px] bg-background px-3 py-2 text-left text-[12px] text-foreground"
              >
                {intentSummary(item)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** The differences between the request and this driver's offer. The request is never changed to fit. */
export function TripIntentFitNotes({ fit, loading }: { fit: TripIntentFitDTO | null; loading: boolean }) {
  if (loading && !fit) return <div className="el-skeleton h-10 w-full rounded-[12px]" aria-busy="true" />;
  if (!fit) return null;
  const notes = fitNotes(fit);
  if (!notes.length) {
    return (
      <p className="rounded-[12px] bg-accent px-3 py-2.5 text-[12px] leading-5 text-primary">
        {translate("tripIntent.fits")}
      </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {notes.map((note) => (
        <li
          key={note.text}
          className={cls(
            "rounded-[12px] px-3 py-2 text-[12px] leading-5",
            note.tone === "block" ? "bg-destructive/10 text-destructive" : "bg-warning/14 text-warning",
          )}
        >
          {note.text}
        </li>
      ))}
    </ul>
  );
}

export type IntentEditForm = ParcelFields & {
  windowStart: string;
  windowEnd: string;
  quantity: number;
  price: string;
};

export function intentEditForm(intent: TripIntentDTO): IntentEditForm {
  const v = intent.current_version;
  const parcel = v.parcel;
  return {
    windowStart: isoToLocalInput(v.window_start),
    windowEnd: isoToLocalInput(v.window_end),
    quantity: v.quantity,
    price: v.unit_price_minor ? String(Math.round(v.unit_price_minor / 100)) : "",
    parcelType: parcel?.parcel_type ?? "box",
    weightKg: parcel?.weight_g ? String(parcel.weight_g / 1000) : "",
    lengthCm: parcel?.length_cm ? String(parcel.length_cm) : "",
    widthCm: parcel?.width_cm ? String(parcel.width_cm) : "",
    heightCm: parcel?.height_cm ? String(parcel.height_cm) : "",
    receiverName: parcel?.receiver?.name ?? "",
    receiverPhone: parcel?.receiver?.phone ?? "",
  };
}

export function editProblems(form: IntentEditForm, now: Date = new Date()): string[] {
  const problems: string[] = [];
  const start = new Date(form.windowStart);
  const end = new Date(form.windowEnd);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) problems.push(translate("tripIntent.problem.windowIncomplete"));
  else {
    if (end <= start) problems.push(translate("tripIntent.problem.endBeforeStart"));
    if (end <= now) problems.push(translate("tripIntent.problem.past"));
  }
  return problems;
}

export function TripIntentEditor(props: {
  intent: TripIntentDTO;
  busy: boolean;
  onSave: (form: IntentEditForm) => void;
  onChangeRoute: () => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<IntentEditForm>(() => intentEditForm(props.intent));
  const passenger = props.intent.service_type === "passenger";
  const problems = editProblems(form);
  const priceMinor = Math.round(Number(form.price) * 100);
  const set = (patch: Partial<IntentEditForm>) => setForm((current) => ({ ...current, ...patch }));
  return (
    <section className="el-enter flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-5">
      <div className="rounded-[14px] bg-background p-4">
        <p className="text-[12px] font-semibold text-muted-foreground">{translate("tripIntent.route")}</p>
        <p className="mt-1 text-[15px] font-semibold text-foreground">{intentSummary(props.intent).split(" · ")[0]}</p>
        <button type="button" onClick={props.onChangeRoute} className="el-press mt-2 text-[13px] font-semibold text-primary">
          {translate("tripIntent.changeRoute")}
        </button>
      </div>
      <Field label={translate("tripIntent.windowStart")} type="datetime-local" value={form.windowStart} onChange={(v) => set({ windowStart: v })} />
      <Field label={translate("tripIntent.windowEnd")} type="datetime-local" min={form.windowStart} value={form.windowEnd} onChange={(v) => set({ windowEnd: v })} />
      {passenger && (
        <Field
          label={translate("tripIntent.people")}
          type="number"
          value={String(form.quantity)}
          onChange={(v) => set({ quantity: Math.max(1, Math.min(8, Number(v) || 1)) })}
        />
      )}
      <Field
        label={passenger ? translate("tripIntent.pricePerPerson") : translate("tripIntent.priceTotal")}
        type="number"
        value={form.price}
        onChange={(v) => set({ price: v })}
        placeholder="190000"
      />
      {priceMinor > 0 && (
        <p className="-mt-2 text-[12px] leading-5 text-muted-foreground">
          {priceLine(passenger ? "per_seat" : "total", priceMinor, form.quantity)}
        </p>
      )}
      {!passenger && (
        <>
          <label className="flex flex-col gap-1.5">
            <span className="text-[14px] font-medium text-secondary-foreground">{translate("tripIntent.parcelTypeLabel")}</span>
            <select
              value={form.parcelType}
              onChange={(event) => set({ parcelType: event.target.value })}
              className="h-12 rounded-[12px] border border-border bg-card px-4 text-[15px] text-foreground"
            >
              {PARCEL_TYPES.map(([value, label]) => (
                <option key={value} value={value}>{translate(label)}</option>
              ))}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-2">
            <Field label={translate("tripIntent.weight")} type="number" value={form.weightKg} onChange={(v) => set({ weightKg: v })} />
            <Field label={translate("tripIntent.length")} type="number" value={form.lengthCm} onChange={(v) => set({ lengthCm: v })} />
            <Field label={translate("tripIntent.width")} type="number" value={form.widthCm} onChange={(v) => set({ widthCm: v })} />
            <Field label={translate("tripIntent.height")} type="number" value={form.heightCm} onChange={(v) => set({ heightCm: v })} />
          </div>
          <Field label={translate("tripIntent.receiverName")} value={form.receiverName} onChange={(v) => set({ receiverName: v })} />
          <Field label={translate("tripIntent.receiverPhone")} value={form.receiverPhone} onChange={(v) => set({ receiverPhone: v })} placeholder="+998..." />
          <p className="-mt-2 text-[12px] leading-5 text-muted-foreground">
            {translate("tripIntent.receiverHint")}
          </p>
        </>
      )}
      {props.intent.open_offers > 0 && (
        <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">
          {translate("tripIntent.openOffersWarning", { count: props.intent.open_offers })}
        </p>
      )}
      {problems.length > 0 && (
        <ul className="space-y-1">
          {problems.map((problem) => (
            <li key={problem} className="text-[12px] leading-5 text-destructive">{problem}</li>
          ))}
        </ul>
      )}
      <div className="mt-auto space-y-2">
        <PrimaryButton disabled={props.busy || problems.length > 0} onClick={() => props.onSave(form)}>
          {translate("common.save")}
        </PrimaryButton>
        <SecondaryButton danger disabled={props.busy} onClick={props.onClose}>
          {translate("tripIntent.close")}
        </SecondaryButton>
      </div>
    </section>
  );
}

