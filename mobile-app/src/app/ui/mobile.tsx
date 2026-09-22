/**
 * The mobile design system of the Elchi client app.
 *
 * **One design language, one file.** The reference is the frozen client in `frontend/` - `App.tsx` for the
 * components and `styles/theme.css` for the palette - which is where this product's visual language was
 * actually designed and which no agent may edit. Everything here is ported from it.
 *
 * Geometry is not decoration, it is the contract: a 52px/14px button, a 52px/12px field with a 1.5px border
 * that turns primary on focus, a 16px card on a 1px line, a 56px top bar with a 36px round back button, a
 * 72px bottom bar, an 11px pill badge. Screens that re-draw those by hand drift apart within a wave, which is
 * exactly what happened before this file became the only source.
 *
 * Colour is never a literal here. Everything resolves through `styles/theme.css` tokens and the
 * `styles/motion.css` grammar, so a change to a colour or a transition lands on every screen at once - and so
 * that dark mode works at all, which it could not while screens held their own hex values.
 *
 * What is deliberately *not* here: anything that knows about bookings, proposals or money. These are shapes.
 */
import { useState } from "react";
import type { CSSProperties, ElementType, ReactNode } from "react";
import { AlertTriangle, ArrowLeft, Check, ChevronDown, ChevronRight, Loader2, Monitor, Moon, Send, Sun } from "./icons";

import { translateDynamic } from "../../i18n";
import { useThemeMode, type ThemeMode } from "./theme";

// --- tokens -------------------------------------------------------------------------------------------------

/**
 * The palette, as CSS variables rather than literals.
 *
 * These feed inline `style` objects and icon `color` props, and a `var()` resolves in both, so a screen that
 * reaches for `COLORS.muted` follows the theme - including dark mode - without knowing the theme exists. The
 * one place this does not work is a canvas or map SDK, which needs a real colour: `cssColor()` below resolves
 * a token for those.
 */
export const COLORS = {
  primary: "var(--primary)",
  primarySoft: "var(--accent)",
  onPrimary: "var(--primary-foreground)",
  surface: "var(--card)",
  canvas: "var(--background)",
  text: "var(--foreground)",
  label: "var(--secondary-foreground)",
  muted: "var(--muted-foreground)",
  faint: "color-mix(in srgb, var(--foreground) 42%, var(--background))",
  line: "var(--border)",
  lineSoft: "var(--muted)",
  disabled: "color-mix(in srgb, var(--foreground) 42%, var(--background))",
  danger: "var(--destructive)",
  dangerSoft: "color-mix(in srgb, var(--destructive) 12%, transparent)",
  ok: "var(--success)",
  okSoft: "color-mix(in srgb, var(--success) 14%, transparent)",
  warn: "var(--warning)",
  warnSoft: "color-mix(in srgb, var(--warning) 14%, transparent)",
  info: "var(--info)",
  infoSoft: "color-mix(in srgb, var(--primary) 14%, var(--background))",
} as const;

/** Radii and heights the prototype uses; named so a screen never invents a ninth radius. */
export const SHAPE = {
  button: 14,
  control: 12,
  card: 16,
  sheet: 24,
  tile: 14,
  buttonHeight: 52,
  controlHeight: 52,
  barHeight: 56,
  navHeight: 72,
} as const;

export function cls(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

// --- buttons ------------------------------------------------------------------------------------------------

/**
 * The one button a screen is really asking for.
 *
 * `icon` and `busy` come from the reference client, where the primary action carries its verb *and* its
 * gesture - a paper plane on "send the code", an arrow on "continue" - and swaps both for a spinner while
 * the request is in flight. Without that, a slow network looks like a button that did nothing, and the
 * person taps again.
 */
export function PrimaryButton(props: {
  children: string;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  icon?: ElementType;
  /** Put the icon after the label, the way an arrow reads as "and then". */
  iconAfter?: boolean;
  busy?: boolean;
}) {
  const Icon = props.icon;
  return (
    <button
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      aria-busy={props.busy || undefined}
      className="el-press flex h-[52px] w-full items-center justify-center gap-2 rounded-[14px] bg-primary px-4 text-[16px] font-semibold text-primary-foreground disabled:bg-slate-400"
    >
      {props.busy ? (
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-primary-foreground/30 border-t-[var(--primary-foreground)]" />
      ) : (
        <>
          {Icon && !props.iconAfter && <Icon size={17} />}
          {props.children}
          {Icon && props.iconAfter && <Icon size={17} />}
        </>
      )}
    </button>
  );
}

export function SecondaryButton(props: { children: string; onClick?: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={cls(
        "el-press flex h-[52px] w-full items-center justify-center rounded-[14px] px-4 text-[15px] font-semibold disabled:opacity-60",
        props.danger ? "bg-destructive/10 text-destructive" : "bg-accent text-primary",
      )}
    >
      {props.children}
    </button>
  );
}

/** The prototype's third weight: a text action that must not compete with the primary one (skip, resend). */
export function GhostButton(props: { children: string; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className="el-press flex h-[52px] w-full items-center justify-center px-4 text-[15px] font-medium text-muted-foreground disabled:opacity-50"
    >
      {props.children}
    </button>
  );
}

/**
 * A primary action sitting **on** the primary colour (the splash screen).
 *
 * A solid blue button on a blue field is invisible, which is why the prototype draws this one translucent with
 * a light border instead of reusing `PrimaryButton`.
 */
export function OnPrimaryButton(props: { children: string; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className="el-press flex h-[52px] w-full items-center justify-center rounded-[14px] border-[1.5px] border-primary-foreground/35 bg-primary-foreground/20 px-4 text-[16px] font-semibold text-primary-foreground disabled:opacity-50"
    >
      {props.children}
    </button>
  );
}

/** A compact action inside a card or a row, where a full-width button would break the rhythm. */
export function InlineButton(props: {
  children: string;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "primary" | "soft" | "danger";
}) {
  const tone = props.tone ?? "soft";
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={cls(
        "el-press flex h-10 items-center justify-center rounded-[10px] px-4 text-[14px] font-semibold disabled:opacity-50",
        tone === "primary" && "bg-primary text-primary-foreground",
        tone === "soft" && "bg-accent text-primary",
        tone === "danger" && "bg-destructive/10 text-destructive",
      )}
    >
      {props.children}
    </button>
  );
}

// --- inputs -------------------------------------------------------------------------------------------------

const CONTROL =
  "el-focus w-full rounded-[12px] border-[1.5px] border-border bg-card text-[15px] text-foreground outline-none placeholder:text-slate-400";

export function Field(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  type?: string;
  hint?: string;
  disabled?: boolean;
  /** Passed straight to the input - `datetime-local` uses it to refuse a date in the past. */
  min?: string;
  max?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span>
      {props.multiline ? (
        <textarea
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          placeholder={props.placeholder}
          disabled={props.disabled}
          rows={3}
          className={cls(CONTROL, "resize-none px-4 py-3 disabled:bg-slate-50")}
        />
      ) : (
        <input
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
          placeholder={props.placeholder}
          type={props.type ?? "text"}
          disabled={props.disabled}
          min={props.min}
          max={props.max}
          className={cls(CONTROL, "h-[52px] px-4 disabled:bg-slate-50")}
        />
      )}
      {props.hint ? <span className="text-[12px] leading-4 text-muted-foreground">{props.hint}</span> : null}
    </label>
  );
}

export function SelectField(props: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span>
      <select
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value)}
        className={cls(CONTROL, "h-[52px] px-4 disabled:bg-slate-50 disabled:text-slate-400")}
      >
        {props.children}
      </select>
      {props.hint ? <span className="text-[12px] leading-4 text-muted-foreground">{props.hint}</span> : null}
    </label>
  );
}

/**
 * The phone field of the reference design: a fixed `+998` block, a hairline divider and then the digits.
 *
 * The country code is not typed, so it cannot be mistyped; the caller receives digits only.
 */
export function PhoneField(props: {
  label?: string;
  value: string;
  onChange: (digits: string) => void;
  maxDigits?: number;
  /** Enter submits, because a phone field is the only thing on its screen. */
  onSubmit?: () => void;
}) {
  const max = props.maxDigits ?? 9;
  // A real <label> element, not a styled span: the span looked identical and left the input unlabelled for a
  // screen reader, and a tap on the text did not focus the field.
  return (
    <label className="flex flex-col gap-1.5">
      {props.label ? <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span> : null}
      <div className="el-focus flex h-[52px] items-center gap-3 rounded-[12px] border-[1.5px] border-border bg-card px-4">
        <div className="flex items-center gap-2 border-r border-border pr-3">
          <span className="text-[16px] leading-none">🇺🇿</span>
          <span className="text-[15px] font-semibold text-foreground">+998</span>
        </div>
        <input
          type="tel"
          inputMode="numeric"
          // The label prop is optional (the sign-in screen shows its own heading instead), and without it the
          // wrapping <label> has no text - so the field falls back to naming itself.
          aria-label={props.label ?? "Telefon raqami"}
          placeholder="__ ___ __ __"
          value={props.value}
          onChange={(event) => props.onChange(event.target.value.replace(/\D/g, "").slice(0, max))}
          onKeyDown={(event) => {
            if (event.key === "Enter" && props.value.length >= max) props.onSubmit?.();
          }}
          className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none placeholder:text-slate-400"
        />
      </div>
    </label>
  );
}

/**
 * The confirmation code, as separate beads rather than one letter-spaced box.
 *
 * Ported from the reference client. One transparent input lies over the whole row and takes every keystroke,
 * paste and the platform's SMS autofill; the circles under it are only a drawing of that input's value. That
 * is what keeps `autocomplete="one-time-code"` working - a row of real per-digit inputs is exactly what
 * breaks it, and is also where backspace stops behaving.
 *
 * The count comes from the server's OTP length (four today, six with the Android v2 client - Q8), so the grid
 * is sized from `length` rather than fixed at five, which is what the reference client hard-coded.
 */
export function CodeField(props: {
  label: string;
  value: string;
  onChange: (digits: string) => void;
  length: number;
  error?: boolean;
  onComplete?: () => void;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <label className="flex flex-col gap-2">
      <span className="text-[14px] font-medium text-secondary-foreground">{props.label}</span>
      <span className="relative block">
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={props.value}
          onChange={(event) => props.onChange(event.target.value.replace(/\D/g, "").slice(0, props.length))}
          onKeyDown={(event) => {
            if (event.key === "Enter" && props.value.length === props.length) props.onComplete?.();
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
        />
        <span
          className="grid gap-2.5"
          style={{ gridTemplateColumns: `repeat(${props.length}, minmax(0, 1fr))` }}
          aria-hidden="true"
        >
          {Array.from({ length: props.length }).map((_, index) => {
            const char = props.value[index] ?? "";
            const current = focused && index === props.value.length;
            return (
              <span
                key={index}
                style={
                  props.error
                    ? {
                        borderColor: "color-mix(in srgb, var(--destructive) 60%, transparent)",
                        background: "color-mix(in srgb, var(--destructive) 5%, transparent)",
                      }
                    : undefined
                }
                className={cls(
                  "flex aspect-square items-center justify-center rounded-full font-mono text-[18px] font-bold transition-all duration-150",
                  props.error
                    ? "border-2 text-foreground"
                    : char
                      ? "border-2 border-primary bg-primary/10 text-foreground"
                      : current
                        ? "border-2 border-primary bg-input-background"
                        : "border border-border bg-input-background",
                )}
              >
                {char || (current ? <span className="h-5 w-0.5 animate-pulse rounded-full bg-primary" /> : "")}
              </span>
            );
          })}
        </span>
      </span>
    </label>
  );
}

// --- structure ----------------------------------------------------------------------------------------------

export function TopBar(props: { title: string; back?: () => void; right?: ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-5">
      {props.back && (
        <button
          type="button"
          onClick={props.back}
          aria-label="Orqaga"
          className="el-press flex h-9 w-9 items-center justify-center rounded-full bg-muted"
        >
          <ArrowLeft size={18} color={COLORS.text} />
        </button>
      )}
      <h1 className="flex-1 truncate text-[17px] font-semibold text-foreground">{props.title}</h1>
      {props.right}
    </header>
  );
}

/** The scrollable body of a screen. `stagger` lets its direct children arrive one after another. */
export function ScreenBody(props: { children: ReactNode; stagger?: boolean; className?: string }) {
  return (
    <section
      className={cls(
        "el-enter flex flex-1 flex-col gap-3 overflow-y-auto px-5 py-4",
        props.stagger && "el-stagger",
        props.className,
      )}
    >
      {props.children}
    </section>
  );
}

export function Card(props: { children: ReactNode; onClick?: () => void; className?: string }) {
  if (props.onClick) {
    return (
      <button
        type="button"
        onClick={props.onClick}
        className={cls(
          "el-press-soft flex w-full flex-col gap-2 rounded-[16px] border border-border bg-card p-4 text-left",
          props.className,
        )}
      >
        {props.children}
      </button>
    );
  }
  return (
    <div className={cls("flex flex-col gap-2 rounded-[16px] border border-border bg-card p-4", props.className)}>
      {props.children}
    </div>
  );
}

/** One label/value line inside a card - the shape agreements and money are read in. */
export function Row(props: { label: string; value: ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[13px] text-muted-foreground">{props.label}</span>
      <span className={cls("text-right text-[14px] text-foreground", props.strong && "font-semibold")}>
        {props.value}
      </span>
    </div>
  );
}

/** A rounded icon tile - the prototype's way of giving a row or an empty state a subject. */
/**
 * One quiet container for an icon, in one of five tones.
 *
 * The reference client made this the replacement for multi-coloured icon chips: a row of rows reads as one
 * system when every icon sits in the same tile, and the tone carries the only meaning there is. `feruza` and
 * `success` are mixed inline because `color-mix()` does not survive Tailwind's arbitrary-value parser.
 */
export function IconTile(props: {
  icon: ElementType;
  tone?: "primary" | "muted" | "danger" | "feruza" | "success";
  size?: number;
}) {
  const Icon = props.icon;
  const tone = props.tone ?? "primary";
  const box = props.size ?? 40;
  const style: CSSProperties = { width: box, height: box };
  if (tone === "feruza" || tone === "success") {
    const token = tone === "feruza" ? "var(--feruza)" : "var(--success)";
    style.color = token;
    style.background = `color-mix(in srgb, ${token} 14%, transparent)`;
  }
  return (
    <span
      style={style}
      className={cls(
        "flex shrink-0 items-center justify-center rounded-[14px]",
        tone === "primary" && "bg-accent text-primary",
        tone === "muted" && "bg-secondary text-muted-foreground",
        tone === "danger" && "bg-destructive/10 text-destructive",
      )}
    >
      <Icon size={Math.round(box * 0.475)} />
    </span>
  );
}

export function ProfileActionRow(props: {
  icon: ElementType;
  label: string;
  description?: string;
  onClick: () => void;
  danger?: boolean;
}) {
  const Icon = props.icon;
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="el-press-soft flex min-h-[64px] w-full items-center gap-3 rounded-[14px] bg-card px-4 py-3 text-left"
    >
      <span
        className={cls(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
          props.danger ? "bg-destructive/10 text-destructive" : "bg-accent text-primary",
        )}
      >
        <Icon size={19} />
      </span>
      <span className="min-w-0 flex-1">
        <span className={cls("block text-[15px] font-semibold", props.danger ? "text-destructive" : "text-foreground")}>
          {props.label}
        </span>
        {props.description && <span className="mt-0.5 block text-[12px] leading-5 text-muted-foreground">{props.description}</span>}
      </span>
      {!props.danger && <ChevronRight size={18} color={COLORS.faint} />}
    </button>
  );
}

// --- status -------------------------------------------------------------------------------------------------

/**
 * Every status this product shows a person, in the language they chose.
 *
 * It was a constant map of Uzbek strings; a constant cannot follow a language change, so the lookup happens per
 * call. An unknown status falls back to the code itself - ugly on purpose, because it is a missing dictionary
 * entry, not a state to design for.
 */
export function statusLabel(status?: string): string {
  const key = status ?? "";
  return translateDynamic(`status.${key}`) ?? key;
}

type Tone = "neutral" | "info" | "progress" | "ok" | "warn" | "danger";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-blue-100 text-info",
  progress: "bg-accent text-info",
  ok: "bg-success/12 text-success",
  warn: "bg-warning/14 text-warning",
  danger: "bg-destructive/10 text-destructive",
};

/**
 * Which colour a status earns. The prototype colours these by meaning, not by novelty: waiting is grey,
 * moving is blue, a person has to act is amber, finished is green, broken is red. A single violet pill for
 * every state (what the live app had) tells the reader nothing.
 */
const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  paused: "neutral",
  expired: "neutral",
  published: "info",
  in_transit: "info",
  boarding: "info",
  in_progress: "info",
  bidding: "progress",
  pending: "warn",
  accepted: "warn",
  selected: "warn",
  picked_up: "warn",
  awaiting_pickup: "warn",
  delivered: "ok",
  confirmed: "ok",
  approved: "ok",
  completed: "ok",
  fulfilled: "ok",
  cancelled: "danger",
  rejected: "danger",
  disputed: "danger",
  no_show: "danger",
  interrupted: "danger",
};

/**
 * A status, with a dot in front of it.
 *
 * The dot is not decoration. Colour is the fastest signal here and the slowest one for a reader who cannot
 * separate the hues, so the reference client doubles it with a shape that is present whatever the colour
 * does - the badge still reads as a distinct state in greyscale.
 */
export function StatusBadge({ status }: { status?: string }) {
  const key = status ?? "";
  const tone = STATUS_TONE[key] ?? "neutral";
  return (
    <span
      className={cls(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        TONE_CLASS[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" aria-hidden="true" />
      {statusLabel(key)}
    </span>
  );
}

export function Badge({ text, tone = "progress" }: { text: string; tone?: Tone }) {
  return <span className={cls("rounded-full px-2.5 py-1 text-[12px] font-semibold", TONE_CLASS[tone])}>{text}</span>;
}

// --- feedback -----------------------------------------------------------------------------------------------

export function EmptyState(props: {
  icon: ElementType;
  title: string;
  subtitle?: string;
  action?: string;
  onAction?: () => void;
}) {
  const Icon = props.icon;
  return (
    <div className="el-enter flex flex-1 flex-col items-center justify-center gap-4 px-8 py-12 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
        <Icon size={28} color={COLORS.faint} />
      </div>
      <div>
        <p className="text-[15px] font-semibold text-secondary-foreground">{props.title}</p>
        {props.subtitle && <p className="mt-1.5 text-[13px] leading-5 text-muted-foreground">{props.subtitle}</p>}
      </div>
      {props.action && <InlineButton onClick={props.onAction}>{props.action}</InlineButton>}
    </div>
  );
}

export function Loading({ label = "Yuklanmoqda..." }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-6 text-[13px] text-muted-foreground">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  );
}

/** The shape of an answer that has not arrived yet. Use where the row height is known in advance. */
export function SkeletonCard({ lines = 2 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2.5 rounded-[16px] border border-border bg-card p-4">
      <div className="el-skeleton h-4 w-2/3" />
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className="el-skeleton h-3" style={{ width: index % 2 ? "45%" : "80%" }} />
      ))}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string | null; onRetry?: () => void }) {
  if (!message) return null;
  return (
    <div className="el-fade flex flex-col gap-2 rounded-[12px] border border-destructive/25 bg-destructive/8 px-3 py-2.5">
      <p className="text-[13px] font-medium text-destructive">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="self-start text-[13px] font-semibold text-primary">
          Qayta urinish
        </button>
      ) : null}
    </div>
  );
}

/** Non-fatal server warnings: the action succeeded, but the person must know something (Q43, Q90). */
export function WarningNote({ children }: { children: ReactNode }) {
  return (
    <div className="el-fade flex items-start gap-2 rounded-[12px] border border-warning/28 bg-warning/8 px-3 py-2.5">
      <AlertTriangle size={16} color="var(--warning)" className="mt-0.5 shrink-0" />
      <p className="text-[13px] leading-5 text-warning">{children}</p>
    </div>
  );
}

// --- progress -----------------------------------------------------------------------------------------------

/** The multi-step form indicator: one filled bar per completed step. */
export function StepBar({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex shrink-0 gap-2 px-5 py-3">
      {Array.from({ length: total }).map((_, index) => (
        <div
          key={index}
          className={cls(
            "h-1 flex-1 rounded-full transition-colors duration-300",
            index < step ? "bg-primary" : "bg-border",
          )}
        />
      ))}
    </div>
  );
}

/** The onboarding indicator: the active dot widens rather than merely changing colour (prototype, 300ms). */
export function StepDots({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }).map((_, index) => (
        <span
          key={index}
          className={cls(
            "h-2 rounded-full transition-all duration-300 ease-out",
            index === step ? "w-6 bg-primary" : "w-2 bg-border",
          )}
        />
      ))}
    </div>
  );
}

/** The vertical order/booking ladder: filled dots with a connecting rail. */
export function Timeline({ steps, activeIndex }: { steps: string[]; activeIndex: number }) {
  return (
    <div className="flex flex-col">
      {steps.map((step, index) => {
        const done = index < activeIndex;
        const active = index === activeIndex;
        const last = index === steps.length - 1;
        return (
          <div key={step} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cls(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors duration-300",
                  done || active ? "bg-primary" : "bg-border",
                )}
              >
                {done ? (
                  <Check size={11} color="var(--primary-foreground)" />
                ) : (
                  <span className={cls("h-2 w-2 rounded-full", active ? "bg-primary-foreground" : "bg-slate-400")} />
                )}
              </span>
              {!last && (
                <span className={cls("min-h-[20px] w-0.5 flex-1", done ? "bg-primary" : "bg-border")} />
              )}
            </div>
            <div className="pt-0.5 pb-4">
              <p className={cls("text-[14px] font-medium", done || active ? "text-foreground" : "text-slate-400")}>
                {step}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- overlays -----------------------------------------------------------------------------------------------

/**
 * A bottom sheet. The scrim fades, the panel slides - and a tap on the scrim closes it, which is what a person
 * expects from a sheet and what the prototype's selectors do.
 */
export function Sheet(props: { title?: string; onClose?: () => void; children: ReactNode; maxHeight?: number }) {
  return (
    <div
      className="el-overlay absolute inset-0 z-[70] flex items-end bg-black/45"
      onClick={props.onClose}
      role="presentation"
    >
      <div
        className="el-sheet w-full rounded-t-[24px] bg-card shadow-[0_-8px_30px_rgba(15,23,42,0.18)]"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex justify-center pt-2.5 pb-1">
          <span className="h-1 w-10 rounded-full bg-border" />
        </div>
        {props.title ? (
          <div className="border-b border-border px-5 py-3">
            <p className="text-[16px] font-semibold text-foreground">{props.title}</p>
          </div>
        ) : null}
        <div style={{ maxHeight: props.maxHeight ?? 360 }} className="overflow-y-auto">
          {props.children}
        </div>
        <div className="h-4" />
      </div>
    </div>
  );
}

export function ConfirmSheet(props: {
  title: string;
  text: string;
  confirmText: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="el-overlay absolute inset-0 z-[70] flex items-end bg-black/35" onClick={props.onCancel} role="presentation">
      <div
        className="el-sheet w-full rounded-t-[24px] bg-card p-5 shadow-[0_-8px_30px_rgba(15,23,42,0.18)]"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <p className="text-[18px] font-bold text-foreground">{props.title}</p>
        <p className="mt-2 text-[14px] leading-6 text-muted-foreground">{props.text}</p>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={props.onCancel}
            className="el-press h-[52px] rounded-[14px] bg-muted text-[15px] font-semibold text-muted-foreground"
          >
            {props.cancelText ?? "Bekor qilish"}
          </button>
          <button
            type="button"
            onClick={props.onConfirm}
            className={cls(
              "el-press h-[52px] rounded-[14px] text-[15px] font-semibold text-primary-foreground",
              props.danger ? "bg-destructive" : "bg-primary",
            )}
          >
            {props.confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

// --- selection ----------------------------------------------------------------------------------------------

/** The two-way switch the prototype uses for mode choices (parcel/passenger, requests/offers). */
export function SegmentedControl<T extends string>(props: {
  value: T;
  options: ReadonlyArray<readonly [T, string]>;
  onChange: (value: T) => void;
}) {
  return (
    <div
      className="grid rounded-[14px] bg-muted p-1"
      style={{ gridTemplateColumns: `repeat(${props.options.length}, minmax(0, 1fr))` }}
    >
      {props.options.map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => props.onChange(value)}
          className={cls(
            "el-press h-10 rounded-[11px] text-[14px] font-semibold",
            props.value === value ? "bg-card text-primary shadow-sm" : "text-muted-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * A large pick-one card: an icon tile that inverts, a 2px border and a filled background when chosen.
 *
 * This is the role picker of the prototype, and the same shape works for any "choose one of two or three"
 * question where the choice deserves more than a radio button.
 */
export function ChoiceCard(props: {
  icon: ElementType;
  label: string;
  description?: string;
  active: boolean;
  onClick: () => void;
}) {
  const Icon = props.icon;
  return (
    <button
      type="button"
      onClick={props.onClick}
      aria-pressed={props.active}
      className={cls(
        "el-press-soft flex w-full items-center gap-4 rounded-[16px] border-2 p-5 text-left transition-colors duration-200",
        props.active ? "border-primary bg-accent" : "border-border bg-card",
      )}
    >
      <span
        className={cls(
          "flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px] transition-colors duration-200",
          props.active ? "bg-primary text-primary-foreground" : "bg-muted text-slate-400",
        )}
      >
        <Icon size={22} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold text-foreground">{props.label}</span>
        {props.description ? <span className="block text-[13px] text-muted-foreground">{props.description}</span> : null}
      </span>
      {props.active && (
        <span className="el-pop flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary">
          <Check size={11} color="var(--primary-foreground)" />
        </span>
      )}
    </button>
  );
}

// --- the reference client's signature pieces ------------------------------------------------------------

/**
 * Ported from the frozen reference client (`frontend/src/app/App.tsx`), which is where this product's visual
 * language was designed. They are here rather than inside one screen because each is a *recurring* shape: the
 * thread appears on home, in tracking and on the splash; the section label separates every settings group.
 */

/**
 * The caravan thread - the one drawing this app is recognisable by.
 *
 * A hollow azure origin node, a beaded line, and a filled destination that is a seal rather than a circle: a
 * rounded diamond, three corners soft and one sharp, rotated so the sharp corner points down at the place.
 * It replaces the two stacked inputs with a dead grey rule between them, and it is the same drawing as
 * `JourneySpine` below, which is the point - the route and its progress are one idea.
 */
export function ThreadSpine({ tall = false }: { tall?: boolean }) {
  return (
    <div className="flex flex-col items-center self-stretch pt-1.5" aria-hidden="true">
      <span
        className="w-3.5 h-3.5 rounded-full border-[3px] flex-none"
        style={{
          borderColor: "var(--feruza)",
          background: "var(--card)",
          boxShadow: "0 0 0 4px color-mix(in srgb, var(--feruza) 14%, transparent)",
        }}
      />
      <span
        className={cls("w-0.5 flex-1", tall ? "my-2" : "my-1.5")}
        style={{
          minHeight: tall ? 32 : 20,
          background: "repeating-linear-gradient(to bottom, var(--primary) 0 3px, transparent 3px 8px)",
          opacity: 0.65,
        }}
      />
      <span
        className="w-4 h-4 flex-none"
        style={{
          background: "var(--primary)",
          borderRadius: "50% 50% 50% 3px",
          transform: "rotate(45deg)",
          boxShadow: "0 0 0 4px color-mix(in srgb, var(--primary) 16%, transparent)",
        }}
      />
    </div>
  );
}

/** The two ends of a direction, joined by the thread. Either end may be unset; it then reads as a prompt. */
export function RouteThread(props: {
  from: ReactNode | null;
  to: ReactNode | null;
  fromLabel?: string;
  toLabel?: string;
  placeholder?: string;
  onFrom: () => void;
  onTo: () => void;
}) {
  const placeholder = props.placeholder ?? "Tanlang";
  const end = (label: string, value: ReactNode | null, onClick: () => void) => (
    <button type="button" onClick={onClick} className="el-press flex items-center justify-between text-left py-2.5">
      <span className="min-w-0">
        <span className="block text-[11px] text-muted-foreground">{label}</span>
        <span className={cls("block text-[15px] truncate", value ? "text-foreground font-medium" : "text-muted-foreground/70")}>
          {value ?? placeholder}
        </span>
      </span>
      <ChevronRight size={16} className="text-muted-foreground flex-none ml-2" />
    </button>
  );
  return (
    <div className="flex gap-3">
      <ThreadSpine />
      <div className="flex-1 flex flex-col">
        {end(props.fromLabel ?? "Qayerdan", props.from, props.onFrom)}
        <div className="h-px bg-border" />
        {end(props.toLabel ?? "Qayerga", props.to, props.onTo)}
      </div>
    </div>
  );
}

/**
 * The thread again, now as a progress timeline: a bead per stage, the finished ones filled, the current one a
 * pulsing azure ring, the destination the same seal as above.
 *
 * `Timeline` is the plain version and stays for lists of short steps. Use this one where the steps *are* the
 * journey, because the shared drawing is what tells a person the two screens are about the same trip.
 */
export function JourneySpine({ steps, current }: { steps: { key: string; label: string; time?: string }[]; current: number }) {
  return (
    <div className="flex flex-col">
      {steps.map((step, index) => {
        const done = index < current;
        const now = index === current;
        const last = index === steps.length - 1;
        return (
          <div key={step.key} className="grid grid-cols-[18px_1fr] gap-3">
            <div className="relative flex justify-center">
              {!last && (
                <span
                  className="absolute w-0.5"
                  style={{
                    top: 11,
                    bottom: -4,
                    background: done
                      ? "var(--primary)"
                      : "repeating-linear-gradient(to bottom, color-mix(in srgb, var(--primary) 40%, transparent) 0 3px, transparent 3px 8px)",
                  }}
                />
              )}
              {last ? (
                <span
                  className="relative z-10 w-4 h-4 mt-1 flex-none"
                  style={{
                    background: done ? "var(--primary)" : "var(--card)",
                    border: done ? "none" : "2px solid color-mix(in srgb, var(--primary) 45%, transparent)",
                    borderRadius: "50% 50% 50% 3px",
                    transform: "rotate(45deg)",
                    boxShadow: done ? "0 0 0 4px color-mix(in srgb, var(--primary) 16%, transparent)" : "none",
                  }}
                />
              ) : (
                <span
                  className={cls("relative z-10 w-3.5 h-3.5 mt-1 rounded-full flex-none", now && "anim-pulse")}
                  style={
                    now
                      ? { border: "2px solid var(--feruza)", background: "var(--card)" }
                      : done
                        ? { background: "var(--primary)" }
                        : { background: "var(--card)", border: "2px solid color-mix(in srgb, var(--primary) 45%, transparent)" }
                  }
                >
                  {now && <span className="absolute inset-[3px] rounded-full" style={{ background: "var(--feruza)" }} />}
                </span>
              )}
            </div>
            <div className="pb-4 min-w-0">
              <p className={cls("text-sm leading-tight", now ? "font-semibold text-foreground" : done ? "text-foreground" : "text-muted-foreground")}>
                {step.label}
              </p>
              {step.time && <p className="text-[11px] text-muted-foreground font-mono mt-0.5">{step.time}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The quiet header that separates one group of settings or rows from the next. */
export function SectionLabel(props: { children: ReactNode; className?: string }) {
  return (
    <p className={cls("text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-2 px-1", props.className)}>
      {props.children}
    </p>
  );
}

/**
 * The wordmark: the envoy's seal, and the name in lower case.
 *
 * The inner rule inside the tile is not decoration - it is what makes the shape read as a stamped seal rather
 * than a generic rounded square with an icon in it.
 */
export function ElchiLogo({ size = 40 }: { size?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="rounded-2xl bg-primary flex items-center justify-center relative" style={{ width: size, height: size }}>
        <Send size={Math.round(size * 0.46)} weight="fill" className="text-primary-foreground relative z-10" />
        <span
          className="absolute rounded-xl"
          style={{ inset: size * 0.16, border: "1.5px solid color-mix(in srgb, var(--primary-foreground) 40%, transparent)" }}
        />
      </div>
      <span className="font-display text-[24px] font-extrabold text-foreground leading-none">elchi</span>
    </div>
  );
}

/**
 * Light, dark, or the device's own setting.
 *
 * Three cards rather than a toggle, because "follow the device" is not the opposite of anything and cannot be
 * expressed by a switch. Each card says what it does in the person's own words.
 */
export function AppearancePicker() {
  const { mode, setMode } = useThemeMode();
  const options: { id: ThemeMode; icon: ElementType; label: string; desc: string }[] = [
    { id: "light", icon: Sun, label: "Yorug'", desc: "Doim yorug'" },
    { id: "dark", icon: Moon, label: "Qorong'i", desc: "Doim qorong'i" },
    { id: "system", icon: Monitor, label: "Tizim", desc: "Qurilmaga mos" },
  ];
  return (
    <div className="grid grid-cols-3 gap-2">
      {options.map(({ id, icon: Icon, label, desc }) => {
        const active = mode === id;
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() => setMode(id)}
            className={cls(
              "el-press flex flex-col items-center gap-1.5 rounded-xl py-3 px-2 border",
              active ? "border-primary bg-primary/10" : "border-border bg-secondary/50",
            )}
          >
            <Icon size={20} className={active ? "text-primary" : "text-muted-foreground"} />
            <p className={cls("text-xs font-semibold", active ? "text-primary" : "text-foreground")}>{label}</p>
            <p className="text-[9px] text-muted-foreground leading-tight text-center">{desc}</p>
          </button>
        );
      })}
    </div>
  );
}

/**
 * A question that opens to its answer.
 *
 * Ported from the reference client's help screen. Collapsed by default because a wall of answers is not a
 * help screen, it is a document - the person is looking for one of them.
 */
export function FaqItem(props: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setOpen((value) => !value)}
      aria-expanded={open}
      className="el-press-soft w-full rounded-2xl border border-border bg-card p-4 text-left"
    >
      <span className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-foreground">{props.question}</span>
        <ChevronDown
          size={16}
          className={cls("shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </span>
      {open && <span className="mt-2 block text-xs leading-relaxed text-muted-foreground">{props.answer}</span>}
    </button>
  );
}

/**
 * A small bar chart.
 *
 * The reference client draws its earnings chart with `recharts`. That is roughly three hundred kilobytes for
 * one 140px chart on one screen, so this is the same drawing in CSS: a row of columns scaled against the
 * largest value, the value read out on hover and, for anyone not using a pointer, present in the table that
 * the markup actually is.
 *
 * `formatValue` exists so the caller names its own unit - the axis of a money chart lies if it says "24" and
 * means "24 000 so'm".
 */
export function BarChart(props: {
  data: { label: string; value: number }[];
  height?: number;
  formatValue: (value: number) => string;
  empty?: string;
}) {
  const height = props.height ?? 140;
  const peak = Math.max(0, ...props.data.map((point) => point.value));
  if (!props.data.length || peak <= 0) {
    return (
      <div className="flex items-center justify-center text-xs text-muted-foreground" style={{ height }}>
        {props.empty ?? "Hali ma'lumot yo'q"}
      </div>
    );
  }
  return (
    <div className="flex items-end gap-2" style={{ height }} role="list">
      {props.data.map((point) => {
        // A real but tiny value still gets a visible sliver, because zero height reads as "no data".
        const ratio = point.value <= 0 ? 0 : Math.max(0.04, point.value / peak);
        return (
          <div key={point.label} role="listitem" className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
            <div className="flex w-full flex-1 items-end">
              <div
                className="el-press-soft w-full rounded-t-[6px] bg-primary"
                style={{ height: `${ratio * 100}%` }}
                title={`${point.label}: ${props.formatValue(point.value)}`}
              />
            </div>
            <span className="w-full truncate text-center font-mono text-[10px] text-muted-foreground">
              {point.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
