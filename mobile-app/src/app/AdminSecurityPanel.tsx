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
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, KeyRound, Loader2, RefreshCw, ShieldCheck, ShieldOff } from "./ui/icons";

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
    <p className="rounded-[10px] border border-destructive/25 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
      {v2ErrorMessage(error)}
    </p>
  );
}

const BUTTON = "inline-flex items-center gap-2 rounded-[10px] bg-foreground px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50";
const SECONDARY = "inline-flex items-center gap-2 rounded-[10px] border border-slate-300 px-3 py-2 text-sm font-semibold text-secondary-foreground disabled:opacity-50";
const INPUT = "w-full rounded-[10px] border border-slate-300 px-3 py-2 text-sm";

/** One honest sentence about what MFA is doing for this account right now. */
function statusLine(state: StaffMfaStateDTO): { tone: "info" | "warn" | "ok"; text: string } {
  if (!state.enrolled) {
    return { tone: "warn", text: "Ikkinchi omil yo'q. Pul va flag buyruqlari hozircha faqat yozib boriladi." };
  }
  if (!state.active) {
    return { tone: "warn", text: "Omil tasdiqlanmagan: boshqa super_admin bitta jonli kodni tasdiqlashi kerak." };
  }
  if (!state.enforced) {
    return {
      tone: "info",
      text:
        state.mode === "audit_only"
          ? "Omil faol, lekin majburlash o'chiq (audit_only) — buyruqlar hozircha rad etilmaydi."
          : `Omil faol, lekin faol super_admin soni ${state.active_super_admin_count} — majburlash yoqilmaydi (yagona operatorni qulflab qo'ymaslik uchun).`,
    };
  }
  return { tone: "ok", text: "Omil faol va majburlash yoqilgan." };
}

export function AdminSecurityPanel() {
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
    <section className="grid gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-foreground">Xavfsizlik — ikkinchi omil (MFA)</h2>
        <button type="button" className={SECONDARY} onClick={() => void load()} disabled={busy}>
          <RefreshCw size={14} /> Yangilash
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
              Mening omilim
            </h3>
            <dl className="grid gap-2 text-sm text-secondary-foreground sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Holat</dt>
                <dd>{state.active ? "faol" : state.pending_activation ? "tasdiq kutilmoqda" : "yo'q"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Rejim</dt>
                <dd>{state.mode}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Oxirgi tasdiq (step-up)</dt>
                <dd>{state.stepped_up_at ? formatDateTime(state.stepped_up_at) : "—"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Qolgan tiklash kodlari</dt>
                <dd>{state.recovery_codes_remaining}</dd>
              </div>
            </dl>
            {state.failed_attempts_in_window > 0 && (
              <Notice tone="warn">
                Oynada {state.failed_attempts_in_window} / {state.max_failed_attempts} xato kod. Limitga
                yetilsa akkaunt vaqtincha kod qabul qilmaydi.
              </Notice>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={BUTTON}
                disabled={working}
                onClick={() =>
                  void run(async () => {
                    const created = await enrollMfa();
                    setEnrollment(created);
                    return "Sir yaratildi. Uni hozir saqlang — boshqa ko'rsatilmaydi.";
                  })
                }
              >
                <KeyRound size={14} /> {state.enrolled ? "Yangi qurilmaga ulash" : "Omil ulash"}
              </button>
            </div>
            {state.active && state.pending_activation && (
              <Notice tone="info">
                Yangi qurilma tasdiqlanmaguncha eski omil ishlaydi — hech narsa uzilmaydi.
              </Notice>
            )}
          </div>

          {enrollment && (
            <div className="grid gap-3 rounded-[12px] border border-warning/28 bg-warning/14 p-4">
              <h3 className="flex items-center gap-2 text-base font-semibold text-warning">
                <AlertTriangle size={16} /> Faqat bir marta ko'rsatiladi
              </h3>
              <p className="text-sm text-warning">
                Sirni autentifikator ilovasiga kiriting, tiklash kodlarini esa xavfsiz joyda saqlang. Bu oyna
                yopilgach ular qayta ko'rsatilmaydi. Omil boshqa super_admin tasdiqlagunicha ishlamaydi.
              </p>
              <p className="font-mono text-sm text-warning">{enrollment.secret}</p>
              <p className="break-all font-mono text-xs text-warning">{enrollment.provisioning_uri}</p>
              <ul className="grid grid-cols-2 gap-1 font-mono text-xs text-warning sm:grid-cols-5">
                {enrollment.recovery_codes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <div>
                <button type="button" className={SECONDARY} onClick={() => setEnrollment(null)}>
                  <Check size={14} /> Saqladim, yashir
                </button>
              </div>
            </div>
          )}

          <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <h3 className="text-base font-semibold text-foreground">Kodni tasdiqlash (step-up)</h3>
            <p className="text-sm text-muted-foreground">
              Pul va flag buyruqlari uchun {Math.round(state.step_up_max_age_seconds / 60)} daqiqaga amal qiladi.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className={`${INPUT} max-w-[180px]`}
                value={code}
                inputMode="numeric"
                aria-label="Tasdiqlash kodi"
                placeholder="123456"
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                type="button"
                className={BUTTON}
                disabled={working || code.trim().length < 4}
                onClick={() =>
                  void run(async () => {
                    const proved = await stepUp(code.trim());
                    setCode("");
                    return `Tasdiqlandi, ${formatDateTime(proved.expires_at)} gacha amal qiladi.`;
                  })
                }
              >
                Tasdiqlash
              </button>
            </div>
          </div>

          <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
            <h3 className="text-base font-semibold text-foreground">Tiklash kodi</h3>
            <p className="text-sm text-muted-foreground">
              Tiklash kodi faqat yangi omil ulash huquqini qaytaradi: u step-up ham, moliyaviy tasdiq ham emas.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className={`${INPUT} max-w-[260px]`}
                value={recovery}
                aria-label="Tiklash kodi"
                placeholder="ABCD1234..."
                onChange={(event) => setRecovery(event.target.value)}
              />
              <button
                type="button"
                className={SECONDARY}
                disabled={working || recovery.trim().length < 4}
                onClick={() =>
                  void run(async () => {
                    const used = await useRecoveryCode(recovery.trim());
                    setRecovery("");
                    return `Kod ishlatildi. Qolgan kodlar: ${used.recovery_codes_remaining}. Endi yangi omil ulashingiz mumkin.`;
                  })
                }
              >
                Ishlatish
              </button>
            </div>
          </div>

          {mayApprove && (
            <div className="grid gap-3 rounded-[12px] border border-border bg-card p-4 shadow-sm">
              <h3 className="text-base font-semibold text-foreground">Boshqa xodimning omili</h3>
              <p className="text-sm text-muted-foreground">
                Xodim sizga jonli kodni aytadi — o'z omilingizni o'zingiz tasdiqlay olmaysiz (server ham, baza
                ham rad etadi).
              </p>
              <div className="grid gap-2 sm:grid-cols-3">
                <input
                  className={INPUT}
                  value={subjectId}
                  aria-label="Xodim identifikatori"
                  placeholder="usr_..."
                  onChange={(event) => setSubjectId(event.target.value)}
                />
                <input
                  className={INPUT}
                  value={subjectCode}
                  inputMode="numeric"
                  aria-label="Xodimning tasdiqlash kodi"
                  placeholder="123456"
                  onChange={(event) => setSubjectCode(event.target.value)}
                />
                <button
                  type="button"
                  className={BUTTON}
                  disabled={working || !subjectId.trim() || subjectCode.trim().length < 4}
                  onClick={() =>
                    void run(async () => {
                      const factor = await activateStaffMfa(subjectId.trim(), subjectCode.trim());
                      setSubjectCode("");
                      return `Omil faollashtirildi (${factor.status}).`;
                    })
                  }
                >
                  Faollashtirish
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <input
                  className={INPUT}
                  value={resetReason}
                  aria-label="Tiklash sababi"
                  placeholder="Sabab: telefon yo'qoldi"
                  onChange={(event) => setResetReason(event.target.value)}
                />
                <button
                  type="button"
                  className={`el-press ${SECONDARY} sm:col-span-2 sm:justify-self-start`}
                  disabled={working || !subjectId.trim() || resetReason.trim().length < 3}
                  onClick={() =>
                    void run(async () => {
                      const done = await resetStaffMfa(subjectId.trim(), resetReason.trim());
                      setResetReason("");
                      return `Omil bekor qilindi (${done.factors_revoked} ta) va tiklash kodlari yaroqsiz qilindi.`;
                    })
                  }
                >
                  Omilni bekor qilish (yo'qolgan telefon)
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
