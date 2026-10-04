/**
 * Staff MFA screen (ADR-0021, wave 9). The service and the routes exist; this is where a person uses them.
 *
 * What the screen refuses to pretend:
 * * it never says "your account is protected" while the rollout is `audit_only` or while a single super_admin
 *   makes enforcement impossible - it says which of the two it is (spec §9.2 spirit);
 * * the secret and the recovery codes are shown once, in state, and the screen says so before it hides them;
 * * activation and reset are somebody else's buttons: the panel shows them only with `staff.mfa_approve`, and
 *   the server refuses self-approval anyway (`ck_staff_mfa_factors_two_person`).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import qrcode from "qrcode-generator";
import { AlertTriangle, Check, KeyRound, Loader2, RefreshCw, Search, ShieldCheck, ShieldOff } from "./ui/icons";

import { getAdminUsers } from "../api/admin-users.api";
import {
  activateStaffMfa,
  enrollMfa,
  mfaState,
  resetStaffMfa,
  stepUp,
  useRecoveryCode,
  type StaffMfaEnrollmentDTO,
  type StaffMfaStateDTO,
} from "../api/v2/mfa.api";
import { capabilities, type CapabilitiesDTO } from "../api/v2/ops.api";
import { translate, type MessageKey } from "../i18n";
import { useT } from "../i18n/react";
import type { AdminStaffUser } from "../types/admin-user";
import { adminRoleLabel } from "../utils/adminUserLabels";
import { formatDateTime } from "../utils/v2Format";
import { v2ErrorMessage } from "../utils/v2Errors";

function Spinner() {
  return <Loader2 size={16} className="animate-spin text-slate-400" />;
}

function Notice({ tone, children }: { tone: "info" | "warn" | "ok"; children: React.ReactNode }) {
  const styles = {
    info: "border-border bg-slate-50 text-secondary-foreground",
    warn: "border-warning/28 bg-warning/14 text-warning",
    ok: "border-success/25 bg-success/12 text-success",
  }[tone];
  return <p className={`rounded-[10px] border px-3 py-2 text-sm font-medium ${styles}`}>{children}</p>;
}

function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
      {v2ErrorMessage(error)}
    </p>
  );
}

const BUTTON = "el-press inline-flex h-10 items-center gap-2 rounded-[10px] bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50";
const SECONDARY = "el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50";
const DANGER = "el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 text-sm font-semibold text-destructive hover:bg-destructive/25 disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-border bg-card px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-blue-100";

/** One honest sentence about what MFA is doing for this account right now. */
export function statusLine(state: StaffMfaStateDTO): { tone: "info" | "warn" | "ok"; text: string } {
  if (!state.enrolled) return { tone: "warn", text: translate("admin.mfa.noFactor") };
  if (!state.active) return { tone: "warn", text: translate("admin.mfa.notApproved") };
  if (!state.enforced) {
    return {
      tone: "info",
      text: state.mode === "audit_only"
        ? translate("admin.mfa.auditOnly")
        : translate("admin.mfa.singleSuper", { count: state.active_super_admin_count }),
    };
  }
  return { tone: "ok", text: translate("admin.mfa.enforced") };
}

function factorState(state: StaffMfaStateDTO): MessageKey {
  if (state.active) return "admin.common.active";
  if (state.pending_activation) return "status.pending";
  return "common.none";
}

/** The provisioning URI as a QR code, drawn locally (qrcode-generator, no network): the secret never leaves the page. */
export function ProvisioningQr({ uri, size = 184 }: { uri: string; size?: number }) {
  const t = useT();
  const cells = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(uri, "Byte");
    qr.make();
    const count = qr.getModuleCount();
    const dark: string[] = [];
    for (let row = 0; row < count; row += 1) {
      for (let col = 0; col < count; col += 1) {
        if (qr.isDark(row, col)) dark.push(`M${col + 4} ${row + 4}h1v1h-1z`);
      }
    }
    return { count: count + 8, path: dark.join("") };
  }, [uri]);
  return (
    <svg role="img" aria-label={t("admin.mfa.qrAria")} width={size} height={size} viewBox={`0 0 ${cells.count} ${cells.count}`} shapeRendering="crispEdges" className="rounded-[8px]">
      <rect width={cells.count} height={cells.count} fill="var(--qr-light)" />
      <path d={cells.path} fill="var(--qr-dark)" />
    </svg>
  );
}

/**
 * "Xodim (qidiruv)": the staff list now carries the v2 `public_id` (contract §5.1), so the approver picks a person
 * by name or phone instead of typing `usr_...`. A typed `usr_...` id still works.
 */
function StaffPicker(props: { value: string; onChange: (publicId: string) => void }) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<AdminStaffUser[]>([]);
  const [label, setLabel] = useState("");
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || q.startsWith("usr_")) {
      setOptions([]);
      return;
    }
    const handle = window.setTimeout(() => {
      getAdminUsers({ search: q, limit: 10 })
        .then((page) => setOptions((page.items ?? []).filter((item) => item.public_id)))
        .catch(() => setOptions([]));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [query]);
  return (
    <label className="relative grid gap-1.5 text-sm font-medium text-secondary-foreground">
      {t("admin.mfa.staff")}
      <span className="relative">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          className={`${INPUT} pl-9`}
          value={label || query}
          placeholder={t("admin.mfa.staffPh")}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onChange={(event) => {
            const next = event.target.value;
            setLabel("");
            setQuery(next);
            setOpen(true);
            props.onChange(next.trim().startsWith("usr_") ? next.trim() : "");
          }}
        />
      </span>
      {props.value && <span className="font-mono text-xs text-muted-foreground">{props.value}</span>}
      {open && options.length > 0 && (
        <div className="absolute left-0 right-0 top-[68px] z-30 max-h-56 overflow-y-auto rounded-[10px] border border-border bg-card py-1 shadow-lg">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                props.onChange(option.public_id ?? "");
                setLabel(`${option.full_name || option.phone} · ${adminRoleLabel(option.role)}`);
                setOpen(false);
              }}
              className="block w-full px-3 py-2 text-left text-sm hover:bg-accent"
            >
              <span className="block font-semibold">{option.full_name || option.phone}</span>
              <span className="block text-xs text-muted-foreground">{option.phone} · {adminRoleLabel(option.role)}</span>
            </button>
          ))}
        </div>
      )}
    </label>
  );
}

export function AdminSecurityPanel() {
  const t = useT();
  const [state, setState] = useState<StaffMfaStateDTO | null>(null);
  const [caps, setCaps] = useState<CapabilitiesDTO | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(true);
  const [enrollment, setEnrollment] = useState<StaffMfaEnrollmentDTO | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [subjectCode, setSubjectCode] = useState("");
  const [resetReason, setResetReason] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [next, capabilitiesDto] = await Promise.all([mfaState(), capabilities()]);
      setState(next);
      setCaps(capabilitiesDto);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<string>) => {
    setWorking(true);
    setError(null);
    setMessage(null);
    try {
      setMessage(await action());
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setWorking(false);
    }
  };

  const mayApprove = (caps?.capabilities ?? []).includes("staff.mfa_approve");
  const status = state ? statusLine(state) : null;

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.security")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("admin.mfa.subtitle")}</p>
        </div>
        <button type="button" className={SECONDARY} onClick={() => void load()} disabled={busy}>
          <RefreshCw size={14} /> {t("support.refresh")}
        </button>
      </div>

      <ErrorLine error={error} />
      {message && <Notice tone="ok">{message}</Notice>}
      {busy && !state ? (
        <Spinner />
      ) : !state ? null : (
        <>
          {status && <Notice tone={status.tone}>{status.text}</Notice>}

          <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <h3 className="flex items-center gap-2 text-base font-semibold text-foreground">
              {state.active ? <ShieldCheck size={16} className="text-success" /> : <ShieldOff size={16} className="text-warning" />}
              {t("admin.mfa.myFactor")}
            </h3>
            <dl className="grid gap-3 text-sm text-secondary-foreground sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-[10px] border border-border p-3">
                <dt className="text-xs text-muted-foreground">{t("admin.common.status")}</dt>
                <dd className="mt-1 font-bold text-foreground">{t(factorState(state))}</dd>
              </div>
              <div className="rounded-[10px] border border-border p-3">
                <dt className="text-xs text-muted-foreground">{t("admin.mfa.mode")}</dt>
                <dd className="mt-1 font-mono font-bold text-foreground">{state.mode}</dd>
              </div>
              <div className="rounded-[10px] border border-border p-3">
                <dt className="text-xs text-muted-foreground">{t("admin.mfa.lastStepUp")}</dt>
                <dd className="mt-1 font-bold text-foreground">{state.stepped_up_at ? formatDateTime(state.stepped_up_at) : "—"}</dd>
              </div>
              <div className="rounded-[10px] border border-border p-3">
                <dt className="text-xs text-muted-foreground">{t("admin.mfa.recoveryLeft")}</dt>
                <dd className="mt-1 font-bold text-foreground">{state.recovery_codes_remaining}</dd>
              </div>
            </dl>
            {state.failed_attempts_in_window > 0 && (
              <Notice tone="warn">{t("admin.mfa.failedAttempts", { count: state.failed_attempts_in_window, max: state.max_failed_attempts })}</Notice>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={SECONDARY}
                disabled={working}
                onClick={() =>
                  void run(async () => {
                    const created = await enrollMfa();
                    setEnrollment(created);
                    return t("admin.mfa.secretCreated");
                  })
                }
              >
                <KeyRound size={14} /> {t(state.enrolled ? "admin.mfa.enrollNew" : "admin.mfa.enroll")}
              </button>
            </div>
            {state.active && state.pending_activation && <Notice tone="info">{t("admin.mfa.oldStillWorks")}</Notice>}
          </div>

          {enrollment && (
            <div className="grid gap-3 rounded-[12px] border border-blue-200 bg-accent/60 p-4">
              <h3 className="flex items-center gap-2 text-base font-semibold text-foreground">
                <AlertTriangle size={16} className="text-warning" /> {t("admin.mfa.enrolledTitle")}
              </h3>
              <p className="text-sm text-secondary-foreground">{t("admin.mfa.onceOnly")} {t("admin.mfa.onceOnlyDetail")}</p>
              <div className="flex flex-wrap items-start gap-4">
                <ProvisioningQr uri={enrollment.provisioning_uri} />
                <div className="grid min-w-0 flex-1 gap-2">
                  <p className="font-mono text-sm text-foreground">{enrollment.secret}</p>
                  <p className="break-all font-mono text-xs text-muted-foreground">{enrollment.provisioning_uri}</p>
                  <ul className="grid grid-cols-2 gap-1 font-mono text-xs text-foreground sm:grid-cols-5">
                    {enrollment.recovery_codes.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
              <div>
                <button type="button" className={SECONDARY} onClick={() => setEnrollment(null)}>
                  <Check size={14} /> {t("admin.mfa.savedHide")}
                </button>
              </div>
            </div>
          )}

          <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <h3 className="text-base font-semibold text-foreground">{t("admin.mfa.stepUpTitle")}</h3>
            <p className="text-sm text-muted-foreground">{t("admin.mfa.stepUpHint", { minutes: Math.round(state.step_up_max_age_seconds / 60) })}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                {t("admin.common.authCode")}
                <input className={INPUT} value={code} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" onChange={(event) => setCode(event.target.value)} />
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                {t("admin.mfa.recoveryCode")}
                <input className={INPUT} value={recovery} autoComplete="off" placeholder="ABCD1234" onChange={(event) => setRecovery(event.target.value)} />
              </label>
            </div>
            <p className="text-xs text-muted-foreground">{t("admin.mfa.recoveryHint")}</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={BUTTON}
                disabled={working || code.trim().length < 4}
                onClick={() =>
                  void run(async () => {
                    const proved = await stepUp(code.trim());
                    setCode("");
                    return t("admin.mfa.stepUpDone", { until: formatDateTime(proved.expires_at) });
                  })
                }
              >
                {t("common.confirm")}
              </button>
              <button
                type="button"
                className={SECONDARY}
                disabled={working || recovery.trim().length < 4}
                onClick={() =>
                  void run(async () => {
                    const used = await useRecoveryCode(recovery.trim());
                    setRecovery("");
                    return t("admin.mfa.recoveryUsed", { count: used.recovery_codes_remaining });
                  })
                }
              >
                {t("admin.mfa.use")}
              </button>
            </div>
          </div>

          {mayApprove && (
            <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
              <h3 className="text-base font-semibold text-foreground">{t("admin.mfa.otherTitle")}</h3>
              <p className="text-sm text-muted-foreground">{t("admin.mfa.otherHint")}</p>
              <div className="grid gap-3 sm:grid-cols-3">
                <StaffPicker value={subjectId} onChange={setSubjectId} />
                <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                  {t("admin.mfa.liveCode")}
                  <input className={INPUT} value={subjectCode} inputMode="numeric" placeholder="123456" onChange={(event) => setSubjectCode(event.target.value)} />
                </label>
                <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
                  {t("common.reason")}
                  <input className={INPUT} value={resetReason} placeholder={t("admin.mfa.resetReasonPh")} onChange={(event) => setResetReason(event.target.value)} />
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={BUTTON}
                  disabled={working || !subjectId.trim() || subjectCode.trim().length < 4}
                  onClick={() =>
                    void run(async () => {
                      const factor = await activateStaffMfa(subjectId.trim(), subjectCode.trim());
                      setSubjectCode("");
                      return t("admin.mfa.activated", { status: factor.status });
                    })
                  }
                >
                  {t("admin.mfa.activate")}
                </button>
                <button
                  type="button"
                  className={DANGER}
                  disabled={working || !subjectId.trim() || resetReason.trim().length < 3}
                  onClick={() =>
                    void run(async () => {
                      const done = await resetStaffMfa(subjectId.trim(), resetReason.trim());
                      setResetReason("");
                      return t("admin.mfa.resetDone", { count: done.factors_revoked });
                    })
                  }
                >
                  {t("admin.mfa.reset")}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
