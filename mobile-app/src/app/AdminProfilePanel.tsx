import { useEffect, useState } from "react";
import { LogOut, Percent, RefreshCw, Save, ShieldCheck, UserRound } from "lucide-react";

import { getAdminMe, updateAdminMe } from "../api/admin.api";
import { getAdminSystemSettings, updateDriverCommission } from "../api/admin-settings.api";
import type { AuthUser } from "../types/auth";
import { adminRoleLabel, adminStatusLabel, adminUserStatusClass } from "../utils/adminUserLabels";
import { saveAdminUser } from "../auth/adminTokenStorage";

export function AdminProfilePanel({ user, onUserUpdate, onLogout }: { user: AuthUser; onUserUpdate: (user: AuthUser) => void; onLogout: () => void }) {
  const [busy, setBusy] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [commissionPercent, setCommissionPercent] = useState("15");
  const canEditSettings = user.role === "admin" || user.role === "super_admin";

  useEffect(() => {
    setFullName(user.full_name ?? "");
  }, [user.full_name]);

  useEffect(() => {
    let ignore = false;
    async function loadSettings() {
      setSettingsBusy(true);
      try {
        const settings = await getAdminSystemSettings();
        if (!ignore) setCommissionPercent(String(settings.driver_commission_percent));
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "Sozlamalarni yuklab bo'lmadi");
      } finally {
        if (!ignore) setSettingsBusy(false);
      }
    }
    void loadSettings();
    return () => {
      ignore = true;
    };
  }, []);

  async function refreshProfile() {
    setBusy(true);
    setError(null);
    try {
      const nextUser = await getAdminMe();
      saveAdminUser(nextUser);
      onUserUpdate(nextUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profilni yangilab bo'lmadi");
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
      setProfileMessage("Profil ma'lumotlari saqlandi.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Profilni saqlab bo'lmadi");
    } finally {
      setProfileBusy(false);
    }
  }

  async function saveCommission() {
    setSettingsBusy(true);
    setError(null);
    setSettingsMessage(null);
    try {
      const value = Number(commissionPercent);
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        setError("Tizim solig'i 0 dan 100 foizgacha bo'lishi kerak");
        return;
      }
      const settings = await updateDriverCommission(value);
      setCommissionPercent(String(settings.driver_commission_percent));
      setSettingsMessage("Tizim solig'i saqlandi. O'zgarish faqat yangi qabul qilinadigan buyurtmalarga qo'llanadi.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tizim solig'ini saqlab bo'lmadi");
    } finally {
      setSettingsBusy(false);
    }
  }

  return (
    <div className="grid max-w-3xl min-w-0 gap-5">
      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">{error}</div>}
      {profileMessage && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">{profileMessage}</div>}
      {settingsMessage && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">{settingsMessage}</div>}
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-50 text-blue-700"><UserRound size={26} /></div>
            <div>
              <h2 className="text-xl font-bold">{user.full_name || "Xodim akkaunti"}</h2>
              <p className="text-sm text-slate-500">{user.phone}</p>
            </div>
          </div>
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${adminUserStatusClass(user.status)}`}>{adminStatusLabel(user.status)}</span>
        </div>
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <label className="grid gap-1.5 rounded-md border border-slate-200 p-4 md:col-span-2">
            <span className="text-xs font-semibold uppercase text-slate-500">Ism familiya</span>
            <div className="flex flex-wrap gap-2">
              <input
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                maxLength={255}
                placeholder="Masalan: Ali Valiyev"
                className="h-10 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
              <button
                type="button"
                onClick={() => void saveProfile()}
                disabled={profileBusy || fullName.trim() === (user.full_name ?? "")}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                <Save size={16} /> Saqlash
              </button>
            </div>
          </label>
          <div className="rounded-md border border-slate-200 p-4">
            <p className="text-xs font-semibold uppercase text-slate-500">Rol</p>
            <p className="mt-1 font-bold">{adminRoleLabel(user.role)}</p>
          </div>
          <div className="rounded-md border border-slate-200 p-4">
            <p className="text-xs font-semibold uppercase text-slate-500">Telefon tasdiqlangan</p>
            <p className="mt-1 font-bold">{user.is_phone_verified ? "Ha" : "Yo'q"}</p>
          </div>
          <div className="rounded-md border border-slate-200 p-4 md:col-span-2">
            <div className="flex items-center gap-2 font-bold"><ShieldCheck size={18} /> Xavfsizlik</div>
            <p className="mt-2 text-sm text-slate-600">Admin panel OTP orqali kirish va backenddagi rol tekshiruvlaridan foydalanadi. Parol va to'lov sozlamalari xodim akkauntlariga kirmaydi.</p>
          </div>
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            onClick={() => void refreshProfile()}
            disabled={busy}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw size={16} /> Profilni yangilash
          </button>
          <button
            onClick={onLogout}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-4 text-sm font-semibold text-rose-700 hover:bg-rose-100"
          >
            <LogOut size={16} /> Chiqish
          </button>
        </div>
      </section>
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 font-bold text-slate-900"><Percent size={18} /> Driver tizim solig'i</div>
            <p className="mt-2 text-sm text-slate-600">Foiz o'zgargandan keyin faqat yangi qabul qilingan buyurtmalarga qo'llanadi. Eski buyurtmalarning narxi va soliq hisobi o'zgarmaydi.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={commissionPercent}
                onChange={(event) => setCommissionPercent(event.target.value)}
                disabled={!canEditSettings || settingsBusy}
                className="h-10 w-28 rounded-md border border-slate-200 bg-white px-3 pr-8 text-right text-sm font-bold text-slate-900 outline-none focus:border-blue-500 disabled:bg-slate-50 disabled:text-slate-400"
              />
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-slate-500">%</span>
            </div>
            <button
              onClick={() => void saveCommission()}
              disabled={!canEditSettings || settingsBusy}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <Save size={16} /> Saqlash
            </button>
          </div>
        </div>
        {!canEditSettings && <p className="mt-3 text-xs font-semibold text-amber-700">Bu sozlamani faqat admin yoki super admin o'zgartira oladi.</p>}
      </section>
    </div>
  );
}
