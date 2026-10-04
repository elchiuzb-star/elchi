/**
 * Small building blocks shared by the v2 operations and trust panels of the admin ("Elchi Admin" design, chunk B):
 * chips with a count, toned badges, a key-value grid, the loading/empty/error lines and a tiny loader hook.
 *
 * Kept apart from the panels so the queue page, the trust page and the booking drawer render the same pieces the
 * same way. Words come from `i18n/screens/adminMarket.ts`.
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { translate } from "../i18n";
import { v2ErrorMessage } from "../utils/v2Errors";
import { Inbox, Loader2 } from "./ui/icons";

export const INPUT = "h-9 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground";
export const TEXTAREA = "h-20 rounded-[10px] border border-border bg-card px-3 py-2 text-sm text-foreground";

export type BtnTone = "primary" | "danger" | "neutral" | "soft";

function btnClass(tone: BtnTone): string {
  if (tone === "primary") return "border-primary bg-primary text-primary-foreground";
  if (tone === "danger") return "border-destructive/25 bg-destructive/10 text-destructive";
  if (tone === "soft") return "border-transparent bg-accent text-primary";
  return "border-border bg-card text-secondary-foreground";
}

export function Btn(props: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: BtnTone; label?: string }) {
  return (
    <button
      type="button"
      aria-label={props.label}
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-9 items-center justify-center gap-2 rounded-[10px] border px-3 text-sm font-semibold ${btnClass(props.tone ?? "neutral")} disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

export function Spinner() {
  return <Loader2 size={16} className="animate-spin text-slate-400" aria-busy="true" />;
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
      {typeof error === "string" ? error : v2ErrorMessage(error)}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
      <Inbox size={18} className="mx-auto mb-2 text-slate-400" />
      {children}
    </div>
  );
}

export type NoteTone = "info" | "warn" | "gray" | "ok";

export function Note({ tone = "gray", title, children }: { tone?: NoteTone; title?: string; children: ReactNode }) {
  const cls =
    tone === "warn"
      ? "border-warning/30 bg-warning/8 text-foreground"
      : tone === "info"
        ? "border-primary/20 bg-accent text-foreground"
        : tone === "ok"
          ? "border-success/30 bg-success/10 text-foreground"
          : "border-border bg-slate-50 text-secondary-foreground";
  return (
    <div className={`rounded-[10px] border px-3 py-2 text-sm ${cls}`}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div>{children}</div>
    </div>
  );
}

export type BadgeTone = "gray" | "blue" | "warn" | "ok" | "err";

const BADGE: Record<BadgeTone, string> = {
  gray: "border-border bg-slate-50 text-secondary-foreground",
  blue: "border-primary/20 bg-accent text-primary",
  warn: "border-warning/30 bg-warning/14 text-warning",
  ok: "border-success/25 bg-success/12 text-success",
  err: "border-destructive/25 bg-destructive/10 text-destructive",
};

export function Badge({ tone = "gray", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold ${BADGE[tone]}`}>
      {children}
    </span>
  );
}

/**
 * How many rows a capped list holds. A list that came back full may have more behind it, so it reads "50+"
 * instead of claiming an exact count the server never gave (DESIGN-ADMIN-DIFF 3.5).
 */
export function countText(count: number | null | undefined, cap?: number): string {
  if (count === null || count === undefined) return "";
  return cap !== undefined && count >= cap ? `${cap}+` : String(count);
}

/** A row of choice chips; the selected one is dark and may carry a count ("Moliya ko'rigi · 14"). */
export function Chips<T extends string>(props: {
  items: Array<{ value: T; label: string; count?: string | null }>;
  value: T;
  onChange: (value: T) => void;
  label?: string;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={props.label}>
      {props.items.map((item) => {
        const on = item.value === props.value;
        const text = on && item.count ? `${item.label} · ${item.count}` : item.label;
        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={on}
            onClick={() => props.onChange(item.value)}
            className={`el-press inline-flex h-9 items-center whitespace-nowrap rounded-full border px-4 text-sm font-semibold ${
              on ? "border-transparent bg-foreground text-background" : "border-border bg-card text-foreground"
            }`}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

export function Field(props: { label: string; children: ReactNode; hint?: string; hintTone?: "danger" }) {
  return (
    <label className="grid gap-1 text-sm font-medium text-secondary-foreground">
      {props.label}
      {props.children}
      {props.hint ? (
        <span className={`text-xs font-normal ${props.hintTone === "danger" ? "text-destructive" : "text-muted-foreground"}`}>{props.hint}</span>
      ) : null}
    </label>
  );
}

/** A labelled value grid (the design's `kv` block). */
export function Kv({ rows, cols = 3 }: { rows: Array<[string, ReactNode]>; cols?: 1 | 2 | 3 | 4 }) {
  const grid = cols === 4 ? "sm:grid-cols-2 lg:grid-cols-4" : cols === 3 ? "sm:grid-cols-3" : cols === 2 ? "sm:grid-cols-2" : "";
  return (
    <dl className={`grid gap-3 rounded-[12px] border border-border bg-card p-3 text-sm ${grid}`}>
      {rows.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{key}</dt>
          <dd className="break-words text-secondary-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PanelHead(props: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-lg font-bold text-foreground">{props.title}</h2>
        {props.sub ? <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{props.sub}</p> : null}
      </div>
      {props.actions ? <div className="flex flex-wrap items-center gap-2">{props.actions}</div> : null}
    </header>
  );
}

export function useLoader<T>(loader: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(enabled);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(loader, deps);

  useEffect(() => {
    if (!enabled) {
      setBusy(false);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    run()
      .then((value) => !cancelled && setData(value))
      .catch((cause) => !cancelled && setError(cause))
      .finally(() => !cancelled && setBusy(false));
    return () => {
      cancelled = true;
    };
  }, [run, nonce, enabled]);

  return { data, error, busy, reload: () => setNonce((value) => value + 1) };
}

/** "42 daq" / "1 soat 10 daq" / "3 soat" (DESIGN-ADMIN-DIFF 4.4); a day or more reads "4 kun 21 soat". */
export function ageText(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    const h = hours % 24;
    return h === 0 ? translate("admin.queues.ageDay", { d: days }) : translate("admin.queues.ageDayHour", { d: days, h });
  }
  if (hours === 0) return translate("admin.queues.ageMin", { min: rest });
  if (rest === 0) return translate("admin.queues.ageHour", { h: hours });
  return translate("admin.queues.ageHourMin", { h: hours, min: rest });
}

export type LookupOption = { id: string; title: string; sub?: string };

/**
 * An id field that also searches (DESIGN-ADMIN-DIFF 5d.2, 5e.2, 5f.4, 5g.3): typing a full id still works as before,
 * typing a name, phone or code fragment lists matches from the staff search and a click puts that id in the field.
 * The search is a convenience: when it fails, the field keeps working as a plain id input.
 */
export function LookupField(props: {
  label: string;
  ariaLabel: string;
  value: string;
  onChange: (value: string) => void;
  search: (query: string) => Promise<LookupOption[]>;
  min: number;
  hint?: string;
  debounceMs?: number;
}) {
  const [options, setOptions] = useState<LookupOption[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const query = props.value.trim();
  const { search, min } = props;
  const debounceMs = props.debounceMs ?? 300;

  useEffect(() => {
    if (query.length < min || query === picked) {
      setOptions(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      search(query)
        .then((rows) => {
          if (cancelled) return;
          setFailed(false);
          setOptions(rows);
        })
        .catch(() => {
          if (cancelled) return;
          setFailed(true);
          setOptions(null);
        });
    }, debounceMs);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, min, picked, search, debounceMs]);

  return (
    <div className="relative grid gap-1 text-sm font-medium text-secondary-foreground">
      <label className="grid gap-1">
        {props.label}
        <input
          aria-label={props.ariaLabel}
          value={props.value}
          onChange={(event) => {
            setPicked(null);
            props.onChange(event.target.value);
          }}
          placeholder={translate("admin.mk.searchPlaceholder")}
          className={INPUT}
        />
      </label>
      {props.hint ? <span className="text-xs font-normal text-muted-foreground">{props.hint}</span> : null}
      {failed ? <span className="text-xs font-normal text-muted-foreground">{translate("admin.mk.searchUnavailable")}</span> : null}
      {options && options.length === 0 ? (
        <span className="text-xs font-normal text-muted-foreground">{translate("admin.mk.searchEmpty")}</span>
      ) : null}
      {options && options.length > 0 ? (
        <ul className="grid max-h-56 gap-1 overflow-y-auto rounded-[10px] border border-border bg-card p-1" role="listbox" aria-label={props.label}>
          {options.map((option) => (
            <li key={option.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onClick={() => {
                  setPicked(option.id);
                  setOptions(null);
                  props.onChange(option.id);
                }}
                className="w-full rounded-[8px] px-2 py-1.5 text-left hover:bg-muted"
              >
                <span className="block text-sm font-semibold text-foreground">{option.title}</span>
                <span className="block font-mono text-xs text-muted-foreground">
                  {option.id}
                  {option.sub ? ` · ${option.sub}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Capabilities as returned by `/me/capabilities`. */
export function hasCap(caps: { capabilities?: readonly string[] | null } | null | undefined, capability: string): boolean {
  return Boolean(caps?.capabilities?.includes(capability));
}
