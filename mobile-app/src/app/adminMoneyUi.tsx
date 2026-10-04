/**
 * Small building blocks shared by the chunk-C admin panels (Moliya, Referral va bonuslar, Platforma sozlamalari):
 * buttons, fields, chips, badges, notes, and the one confirmed-command flow.
 *
 * The confirmed-command flow is the money/flag rule in one place:
 *   1. `ask()` opens a confirmation that restates what will happen; the Idempotency-Key is minted *there*;
 *   2. "Ha, bajarish" runs the command through `useStepUp().run` (ADR-0021): when the server wants a fresh MFA
 *      proof the code prompt appears and the *same* closure, with the *same* key, is replayed (ADR-0005);
 *   3. any other refusal is shown in words, with a retry that again reuses that key.
 * The server decides every permission; this only avoids offering what it would certainly refuse.
 */
import { useState, type ReactNode } from "react";

import { newIdempotencyKey } from "../api/v2/http";
import { useT } from "../i18n/react";
import { v2ErrorMessage } from "../utils/v2Errors";
import { isStepUpCancelled, useStepUp } from "./useStepUp";

export type Tone = "primary" | "danger" | "neutral";
export type BadgeTone = "ok" | "warn" | "err" | "gray" | "blue";

export function Btn(props: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: Tone; label?: string }) {
  const tone = props.tone ?? "neutral";
  const cls =
    tone === "primary"
      ? "border-primary bg-primary text-primary-foreground"
      : tone === "danger"
        ? "border-destructive/25 bg-destructive/10 text-destructive"
        : "border-border bg-card text-secondary-foreground";
  return (
    <button
      type="button"
      aria-label={props.label}
      onClick={props.onClick}
      disabled={props.disabled}
      className={`el-press inline-flex h-9 items-center justify-center rounded-[10px] border px-3 text-sm font-semibold ${cls} disabled:opacity-50`}
    >
      {props.children}
    </button>
  );
}

export function Field(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  type?: "text" | "date" | "datetime-local" | "number";
  inputMode?: "numeric" | "decimal" | "text";
  area?: boolean;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      {props.area ? (
        <textarea
          value={props.value}
          placeholder={props.placeholder}
          aria-label={props.label}
          onChange={(event) => props.onChange(event.target.value)}
          className="min-h-[72px] w-full min-w-0 rounded-[10px] border border-border bg-card px-3 py-2 text-foreground outline-none"
        />
      ) : (
        <input
          type={props.type ?? "text"}
          inputMode={props.inputMode}
          value={props.value}
          placeholder={props.placeholder}
          aria-label={props.label}
          onChange={(event) => props.onChange(event.target.value)}
          className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3 text-foreground outline-none"
        />
      )}
      {props.hint && <span className="text-xs text-muted-foreground">{props.hint}</span>}
    </label>
  );
}

export function Select<T extends string>(props: { label: string; value: T; onChange: (v: T) => void; options: Array<[T, string]> }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="font-medium text-secondary-foreground">{props.label}</span>
      <select
        value={props.value}
        aria-label={props.label}
        onChange={(event) => props.onChange(event.target.value as T)}
        className="h-10 w-full min-w-0 rounded-[10px] border border-border bg-card px-3"
      >
        {props.options.map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Loading() {
  const t = useT();
  return (
    <p className="text-sm text-muted-foreground" aria-busy="true">
      {t("common.loading")}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export function Note({ children, tone = "muted", title }: { children: ReactNode; tone?: "muted" | "info" | "warning" | "success" | "danger"; title?: string }) {
  const cls =
    tone === "warning"
      ? "bg-warning/10 text-warning"
      : tone === "success"
        ? "bg-success/10 text-success"
        : tone === "danger"
          ? "bg-destructive/10 text-destructive"
          : tone === "info"
            ? "bg-accent text-primary"
            : "bg-muted/60 text-secondary-foreground";
  return (
    <div className={`rounded-[10px] px-3 py-2 text-sm ${cls}`}>
      {title && <p className="font-semibold">{title}</p>}
      <div>{children}</div>
    </div>
  );
}

const BADGE: Record<BadgeTone, string> = {
  ok: "bg-success/12 text-success",
  warn: "bg-warning/14 text-warning",
  err: "bg-destructive/10 text-destructive",
  gray: "bg-muted text-secondary-foreground",
  blue: "bg-accent text-primary",
};

export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${BADGE[tone]}`}>{children}</span>;
}

/** Design `A.chips`: a single-choice filter row. `role="radiogroup"` so tests and screen readers see one choice. */
export function Chips<T extends string>(props: { label: string; value: T; onChange: (v: T) => void; options: Array<[T, string]> }) {
  return (
    <div role="radiogroup" aria-label={props.label} className="flex flex-wrap items-center gap-2">
      {props.options.map(([value, text]) => {
        const on = value === props.value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => props.onChange(value)}
            className={`el-press h-8 shrink-0 whitespace-nowrap rounded-full px-3 text-sm font-semibold ${on ? "bg-foreground text-background" : "border border-border bg-card text-foreground"}`}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

/** Design `A.cards`: title + badge, meta lines, actions. */
export function Card(props: { title: ReactNode; badge?: ReactNode; children?: ReactNode; highlight?: boolean; testId?: string; label?: string }) {
  return (
    <section
      aria-label={props.label}
      data-testid={props.testId}
      className={`min-w-0 space-y-2 rounded-[12px] bg-card p-3 text-sm ${props.highlight ? "border-2 border-primary" : "border border-border"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 break-words font-semibold text-foreground">{props.title}</p>
        {props.badge}
      </div>
      {props.children}
    </section>
  );
}

export function Tabs<T extends string>(props: { value: T | null; onChange: (v: T) => void; options: Array<[T, string]> }) {
  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-1" role="tablist">
      {props.options.map(([id, text]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={props.value === id}
          onClick={() => props.onChange(id)}
          className={`el-press h-9 shrink-0 whitespace-nowrap rounded-full px-4 text-sm font-semibold ${props.value === id ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function Section(props: { title: string; sub?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-base font-bold text-foreground">{props.title}</h3>
          {props.sub && <p className="text-xs text-muted-foreground">{props.sub}</p>}
        </div>
        {props.actions}
      </div>
      {props.children}
    </section>
  );
}

type Pending = {
  title: string;
  lines: string[];
  tone?: "primary" | "danger";
  /** Confirm button text; default "Ha, bajarish" (flags use "Tasdiqlayman", as in the design). */
  confirmLabel?: string;
  work: (key: string) => Promise<void>;
};

/**
 * One confirmed staff command at a time (see the file comment). `explain` turns a domain refusal into words;
 * returning null falls back to the shared v2 message. `danger` marks refusals (the Q48 gate) that are not bugs.
 */
export function useConfirmedCommand(
  options: { explain?: (error: unknown) => string | null; calm?: (error: unknown) => boolean; confirmLabel?: string } = {},
) {
  const t = useT();
  const stepUp = useStepUp();
  const [pending, setPending] = useState<(Pending & { key: string }) | null>(null);
  const [running, setRunning] = useState<(Pending & { key: string }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  function ask(next: Pending) {
    setError(null);
    setDone(null);
    setPending({ ...next, key: newIdempotencyKey() });
  }

  async function run(action: Pending & { key: string }) {
    setBusy(true);
    setError(null);
    setRunning(action);
    try {
      await stepUp.run(() => action.work(action.key));
      setRunning(null);
    } catch (cause) {
      if (isStepUpCancelled(cause)) setRunning(null);
      else setError(cause);
    } finally {
      setBusy(false);
    }
  }

  function confirm() {
    if (!pending) return;
    const action = pending;
    setPending(null);
    void run(action);
  }

  const message = (cause: unknown) => options.explain?.(cause) ?? v2ErrorMessage(cause);
  const calm = error !== null && (options.calm?.(error) ?? false);

  const view = (
    <>
      {pending && (
        <div role="dialog" aria-label={t("common.confirm")} className="space-y-2 rounded-[12px] border border-warning/40 bg-warning/8 p-3 text-sm">
          <p className="font-semibold text-foreground">{pending.title}</p>
          {pending.lines.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-secondary-foreground">
              {pending.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <Btn tone={pending.tone ?? "primary"} disabled={busy} onClick={confirm}>
              {pending.confirmLabel ?? options.confirmLabel ?? t("admin.money.yesRun")}
            </Btn>
            <Btn disabled={busy} onClick={() => setPending(null)}>
              {t("common.cancel")}
            </Btn>
          </div>
        </div>
      )}
      {stepUp.prompt}
      {done && <Note tone="success">{done}</Note>}
      {error !== null && (
        <div className="flex flex-wrap items-center gap-2" role="alert">
          <Note tone={calm ? "warning" : "danger"}>{message(error)}</Note>
          {running && !calm && (
            <Btn disabled={busy} onClick={() => void run(running)}>
              {t("common.retry")}
            </Btn>
          )}
        </div>
      )}
    </>
  );
  return { ask, busy: busy || pending !== null || stepUp.waiting, view, setDone };
}

/** The server's staff refs carry only `id` today; a name is shown when the backend adds one (TopupAdminDTO driver). */
export function refName(ref: { id?: string | null } | null | undefined): string {
  if (!ref) return "-";
  const named = ref as { full_name?: string | null; name?: string | null; display_name?: string | null };
  return named.full_name || named.name || named.display_name || ref.id || "-";
}
