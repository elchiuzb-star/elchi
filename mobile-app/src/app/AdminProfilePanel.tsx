/**
 * Profil / Akkaunt (DESIGN-ADMIN-DIFF §26). The person's own staff account, the v1 driver commission percent and
 * the appearance choice.
 *
 * Q2: only super_admin changes the commission (`require_capability(FINANCE_COMMISSION_POLICY_MANAGE)`); admin and
 * operator read it with the field locked. Finance cannot read v1 settings at all (contract §1.2), so the block is
 * not drawn for finance.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { LogOut, Percent, RefreshCw, Save } from "./ui/icons";

import { getAdminMe, updateAdminMe } from "../api/admin.api";
import { getAdminSystemSettings, updateDriverCommission } from "../api/admin-settings.api";
import { useT } from "../i18n/react";
import type { AuthUser } from "../types/auth";
import { adminErrorMessage, adminRoleLabel, adminStatusLabel, yesNo } from "../utils/adminUserLabels";
import { saveAdminUser } from "../auth/adminTokenStorage";
import { AppearancePicker, SectionLabel } from "./ui/mobile";

export function canEditCommission(role: string): boolean {
  return role === "super_admin";
}

export function canReadCommission(role: string): boolean {
  return role === "operator" || role === "admin" || role === "super_admin";
}

function Kv({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-[10px] border border-border p-3">
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <p className="mt-1 break-words font-bold">{children}</p>
    </div>
  );
}

export function AdminProfilePanel({ user, onUserUpdate, onLogout }: { user: AuthUser; onUserUpdate: (user: AuthUser) => void; onLogout: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [commissionPercent, setCommissionPercent] = useState("");
  const readsCommission = canReadCommission(user.role);
  const editsCommission = canEditCommission(user.role);

  useEffect(() => {
    setFullName(user.full_name ?? "");
  }, [user.full_name]);

  useEffect(() => {
    if (!readsCommission) return;
    let ignore = false;
    async function loadSettings() {
      setSettingsBusy(true);
      try {
        const settings = await getAdminSystemSettings();
        if (!ignore) setCommissionPercent(String(settings.driver_commission_percent));
      } catch (err) {
        if (!ignore) setError(adminErrorMessage(err, "admin.profile.settingsFailed"));
      } finally {
        if (!ignore) setSettingsBusy(false);
      }
    }
    void loadSettings();
    return () => {
      ignore = true;
    };
  }, [readsCommission]);

  async function refreshProfile() {
    setBusy(true);
    setError(null);
    try {
      const nextUser = await getAdminMe();
      saveAdminUser(nextUser);
      onUserUpdate(nextUser);
    } catch (err) {
      setError(adminErrorMessage(err, "admin.profile.refreshFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile() {
    setProfileBusy(true);
    setError(null);
    setProfileMessage(null);
    try {
      const nextUser = await updateAdminMe({ full_name: fullName.trim() || null });
      saveAdminUser(nextUser);
      onUserUpdate(nextUser);
      setFullName(nextUser.full_name ?? "");
      setProfileMessage(t("admin.profile.saved"));
    } catch (err) {
      setError(adminErrorMessage(err, "admin.profile.saveFailed"));
    } finally {
      setProfileBusy(false);
    }
  }

  async function saveCommission() {
    setError(null);
    setSettingsMessage(null);
    const value = Number(commissionPercent);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      setError(t("admin.profile.percentRange"));
      return;
    }
    setSettingsBusy(true);
    try {
      const settings = await updateDriverCommission(value);
      setCommissionPercent(String(settings.driver_commission_percent));
      setSettingsMessage(t("admin.profile.commissionSaved"));
    } catch (err) {
      setError(adminErrorMessage(err, "admin.profile.commissionFailed"));
    } finally {
      setSettingsBusy(false);
    }
  }

  return (
    <div className="grid max-w-4xl min-w-0 gap-5">
      <h2 className="text-2xl font-bold text-foreground">{t("admin.nav.profile")}</h2>
      {error && <div role="alert" className="rounded-[12px] border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm font-semibold text-destructive">{error}</div>}
      {profileMessage && <div className="rounded-[12px] border border-success/25 bg-success/12 px-4 py-3 text-sm font-semibold text-success">{profileMessage}</div>}
      {settingsMessage && <div className="rounded-[12px] border border-success/25 bg-success/12 px-4 py-3 text-sm font-semibold text-success">{settingsMessage}</div>}

      <section className="grid gap-4 rounded-[12px] border border-border bg-card p-5 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Kv label={t("admin.profile.name")}>{user.full_name || "-"}</Kv>
          <Kv label={t("admin.common.phone")}>{user.phone}</Kv>
          <Kv label={t("admin.common.status")}>{adminStatusLabel(user.status)}</Kv>
          <Kv label={t("admin.staff.role")}>{adminRoleLabel(user.role)}</Kv>
          <Kv label={t("admin.staff.colPhoneVerified")}>{yesNo(user.is_phone_verified)}</Kv>
        </div>
        <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
          {t("clientProfile.fullName")}
          <div className="flex flex-wrap gap-2">
            <input
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              maxLength={255}
              className="h-10 min-w-0 flex-1 rounded-[10px] border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-blue-100 sm:max-w-sm"
            />
            <button
              type="button"
              onClick={() => void saveProfile()}
              disabled={profileBusy || fullName.trim() === (user.full_name ?? "")}
              className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Save size={16} /> {t("common.save")}
            </button>
          </div>
        </label>
      </section>

      {readsCommission && (
        <section className="rounded-[12px] border border-border bg-card p-5 shadow-sm" data-testid="commission-block">
          <div className="flex items-center gap-2 font-bold text-foreground"><Percent size={18} /> {t("admin.profile.commissionTitle")}</div>
          <p className="mt-2 text-sm text-secondary-foreground">{t("admin.profile.commissionHint")}</p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="grid gap-1.5 text-sm font-medium text-secondary-foreground">
              {t("admin.profile.percent")}
              <span className="relative">
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={commissionPercent}
                  onChange={(event) => setCommissionPercent(event.target.value)}
                  disabled={!editsCommission || settingsBusy}
                  readOnly={!editsCommission}
                  className="h-10 w-32 rounded-[10px] border border-border bg-card px-3 pr-8 text-right text-sm font-bold text-foreground outline-none focus:border-primary disabled:bg-slate-50 disabled:text-slate-400"
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-muted-foreground">%</span>
              </span>
            </label>
            {editsCommission && (
              <button
                type="button"
                onClick={() => void saveCommission()}
                disabled={settingsBusy}
                className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Save size={16} /> {t("common.save")}
              </button>
            )}
          </div>
        </section>
      )}

      {/* An operator works this panel for a whole shift, often at night. The choice is this browser's, not the
          account's, so it is not saved to the server. */}
      <section className="rounded-[14px] border border-border bg-card p-5">
        <SectionLabel>{t("settingsScreen.appearance")}</SectionLabel>
        <AppearancePicker />
      </section>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => void refreshProfile()}
          disabled={busy}
          className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-border bg-card px-4 text-sm font-semibold text-secondary-foreground hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw size={16} /> {t("admin.profile.refresh")}
        </button>
        <button
          type="button"
          onClick={onLogout}
          className="el-press inline-flex h-10 items-center gap-2 rounded-[10px] border border-destructive/25 bg-destructive/10 px-4 text-sm font-semibold text-destructive hover:bg-destructive/25"
        >
          <LogOut size={16} /> {t("nav.logout")}
        </button>
      </div>
    </div>
  );
}
