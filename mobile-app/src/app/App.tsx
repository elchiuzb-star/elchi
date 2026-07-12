import { useState } from "react";
import { ConnectedApp } from "./ConnectedApp";
import {
  Home, Package, Bell, User, ArrowLeft, ChevronRight,
  Star, Upload, Truck, MapPin, Phone, FileText,
  CheckCircle, XCircle, AlertCircle, Camera, Navigation,
  Plus, Check, X,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Screen =
  | "splash" | "onboarding" | "role-select" | "phone-login" | "otp"
  | "c-home" | "c-order-1" | "c-order-2" | "c-order-3" | "c-review"
  | "c-success" | "c-orders" | "c-order-nobids" | "c-order-bids"
  | "c-order-selected" | "c-confirm" | "c-rating" | "c-notifications" | "c-profile"
  | "d-home" | "d-profile-form" | "d-documents" | "d-routes" | "d-add-route"
  | "d-feed" | "d-bid" | "d-orders" | "d-order-detail" | "d-profile";

type Role = "client" | "driver" | null;
type Go = (screen: Screen) => void;

// ─── Primitives ───────────────────────────────────────────────────────────────

function PrimaryBtn({
  label, onClick, disabled,
}: { label: string; onClick?: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      className="w-full flex items-center justify-center font-semibold text-base transition-opacity"
      style={{
        height: 52, borderRadius: 14,
        background: disabled ? "#9CA3AF" : "#1B4FD8",
        color: "#fff", cursor: disabled ? "not-allowed" : "pointer", border: "none",
      }}
    >
      {label}
    </button>
  );
}

function SecondaryBtn({ label, onClick }: { label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center font-semibold text-base"
      style={{ height: 52, borderRadius: 14, background: "#EEF2FF", color: "#1B4FD8", border: "none" }}
    >
      {label}
    </button>
  );
}

function GhostBtn({ label, onClick }: { label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center font-medium text-base"
      style={{ height: 52, color: "#6B7280", background: "none", border: "none" }}
    >
      {label}
    </button>
  );
}

function InputField({
  label, placeholder, value, onChange, type = "text", multiline,
}: {
  label?: string; placeholder?: string; value?: string;
  onChange?: (v: string) => void; type?: string; multiline?: boolean;
}) {
  const baseStyle: React.CSSProperties = {
    border: "1.5px solid #E5E7EB", background: "#fff",
    color: "#111827", borderRadius: 12, fontFamily: "inherit", fontSize: 15,
  };
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <span className="text-sm font-medium" style={{ color: "#374151" }}>{label}</span>
      )}
      {multiline ? (
        <textarea
          placeholder={placeholder}
          value={value}
          onChange={e => onChange?.(e.target.value)}
          rows={3}
          className="px-4 py-3 outline-none resize-none"
          style={baseStyle}
        />
      ) : (
        <input
          type={type}
          placeholder={placeholder}
          value={value}
          onChange={e => onChange?.(e.target.value)}
          className="px-4 outline-none"
          style={{ ...baseStyle, height: 52 }}
        />
      )}
    </div>
  );
}

function TopBar({
  title, onBack, right,
}: { title: string; onBack?: () => void; right?: React.ReactNode }) {
  return (
    <div
      className="flex items-center gap-3 px-5"
      style={{ height: 56, background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}
    >
      {onBack && (
        <button
          onClick={onBack}
          className="w-9 h-9 flex items-center justify-center rounded-full"
          style={{ background: "#F3F4F6" }}
        >
          <ArrowLeft size={18} color="#111827" />
        </button>
      )}
      <span className="flex-1 text-[17px] font-semibold" style={{ color: "#111827" }}>{title}</span>
      {right}
    </div>
  );
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

const STATUS: Record<string, { label: string; bg: string; color: string }> = {
  draft:     { label: "Qoralama",           bg: "#F3F4F6", color: "#6B7280" },
  announced: { label: "E'lon qilingan",     bg: "#DBEAFE", color: "#1D4ED8" },
  has_bids:  { label: "Takliflar bor",      bg: "#EDE9FE", color: "#6D28D9" },
  selected:  { label: "Haydovchi tanlangan",bg: "#FEF3C7", color: "#92400E" },
  picked_up: { label: "Olib ketildi",       bg: "#FEF3C7", color: "#92400E" },
  in_transit:{ label: "Yo'lda",             bg: "#DBEAFE", color: "#1D4ED8" },
  delivered: { label: "Yetkazildi",         bg: "#DCFCE7", color: "#15803D" },
  confirmed: { label: "Tasdiqlandi",        bg: "#DCFCE7", color: "#15803D" },
  cancelled: { label: "Bekor qilingan",     bg: "#FEE2E2", color: "#DC2626" },
  disputed:  { label: "Nizo ochilgan",      bg: "#FFE4E6", color: "#BE123C" },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.draft;
  return (
    <span
      className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

// ─── Order Card ───────────────────────────────────────────────────────────────

function OrderCard({
  from, to, status, price, bids, date, onClick,
}: { from: string; to: string; status: string; price: string; bids?: number; date: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-[16px] p-4 mb-3"
      style={{ background: "#fff", border: "1px solid #E5E7EB" }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <MapPin size={13} color="#1B4FD8" />
          <span className="font-semibold text-[14px]" style={{ color: "#111827" }}>
            {from} → {to}
          </span>
        </div>
        <StatusBadge status={status} />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[12px]" style={{ color: "#9CA3AF" }}>{date}</span>
        <div className="flex items-center gap-3">
          {bids !== undefined && (
            <span className="text-[12px]" style={{ color: "#6B7280" }}>{bids} taklif</span>
          )}
          <span className="font-semibold text-[13px]" style={{ color: "#111827" }}>{price}</span>
        </div>
      </div>
    </button>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({
  icon: Icon, title, subtitle, action, onAction,
}: { icon: React.ElementType; title: string; subtitle?: string; action?: string; onAction?: () => void }) {
  return (
    <div className="flex flex-col items-center py-12 px-8 gap-4">
      <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ background: "#F3F4F6" }}>
        <Icon size={28} color="#9CA3AF" />
      </div>
      <div className="text-center">
        <p className="font-semibold text-[15px]" style={{ color: "#374151" }}>{title}</p>
        {subtitle && (
          <p className="text-[13px] mt-1.5 leading-5" style={{ color: "#6B7280" }}>{subtitle}</p>
        )}
      </div>
      {action && (
        <button
          onClick={onAction}
          className="px-5 h-9 rounded-[10px] text-sm font-semibold"
          style={{ background: "#EEF2FF", color: "#1B4FD8" }}
        >
          {action}
        </button>
      )}
    </div>
  );
}

// ─── Timeline ────────────────────────────────────────────────────────────────

function Timeline({ steps, activeStep }: { steps: string[]; activeStep: number }) {
  return (
    <div className="flex flex-col">
      {steps.map((step, i) => {
        const done = i < activeStep;
        const active = i === activeStep;
        const last = i === steps.length - 1;
        return (
          <div key={step} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                style={{ background: done || active ? "#1B4FD8" : "#E5E7EB" }}
              >
                {done
                  ? <Check size={11} color="#fff" />
                  : <div className="w-2 h-2 rounded-full" style={{ background: active ? "#fff" : "#9CA3AF" }} />
                }
              </div>
              {!last && (
                <div className="w-0.5 min-h-[20px] flex-1" style={{ background: done ? "#1B4FD8" : "#E5E7EB" }} />
              )}
            </div>
            <div className="pb-4 pt-0.5">
              <p className="text-[14px] font-medium" style={{ color: done || active ? "#111827" : "#9CA3AF" }}>
                {step}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── City Selector ────────────────────────────────────────────────────────────

const CITIES = [
  "Toshkent","Samarqand","Buxoro","Andijon","Namangan",
  "Farg'ona","Qo'qon","Qarshi","Navoiy","Jizzax",
  "Termiz","Urganch","Nukus","Guliston",
];

function CitySelector({
  selected, onSelect, onClose,
}: { selected: string; onSelect: (c: string) => void; onClose: () => void }) {
  return (
    <div
      className="absolute inset-0 flex items-end z-50"
      style={{ background: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
    >
      <div
        className="w-full rounded-t-[24px]"
        style={{ background: "#fff" }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid #E5E7EB" }}>
          <span className="font-semibold text-[16px]" style={{ color: "#111827" }}>Shaharni tanlang</span>
          <button onClick={onClose}><X size={20} color="#6B7280" /></button>
        </div>
        <div style={{ maxHeight: 300, overflowY: "auto" }}>
          {CITIES.map(city => (
            <button
              key={city}
              onClick={() => { onSelect(city); onClose(); }}
              className="w-full flex items-center justify-between px-5 py-3.5"
              style={{ borderBottom: "1px solid #F3F4F6" }}
            >
              <span className="text-[15px]" style={{ color: "#111827" }}>{city}</span>
              {selected === city && <Check size={16} color="#1B4FD8" />}
            </button>
          ))}
        </div>
        <div style={{ height: 20 }} />
      </div>
    </div>
  );
}

// ─── Bottom Navs ──────────────────────────────────────────────────────────────

function ClientBottomNav({ active, navigate }: { active: string; navigate: Go }) {
  const tabs = [
    { id: "c-home" as Screen, icon: Home, label: "Bosh sahifa" },
    { id: "c-orders" as Screen, icon: Package, label: "Buyurtmalar" },
    { id: "c-notifications" as Screen, icon: Bell, label: "Bildirishnomalar" },
    { id: "c-profile" as Screen, icon: User, label: "Profil" },
  ];
  return (
    <div
      className="flex"
      style={{ background: "#fff", borderTop: "1px solid #E5E7EB", height: 72, flexShrink: 0 }}
    >
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => navigate(t.id)}
          className="flex-1 flex flex-col items-center justify-center gap-1"
        >
          <t.icon size={22} color={active === t.id ? "#1B4FD8" : "#9CA3AF"} />
          <span className="text-[10px] font-medium" style={{ color: active === t.id ? "#1B4FD8" : "#9CA3AF" }}>
            {t.label}
          </span>
        </button>
      ))}
    </div>
  );
}

function DriverBottomNav({ active, navigate }: { active: string; navigate: Go }) {
  const tabs = [
    { id: "d-home" as Screen, icon: Home, label: "Bosh sahifa" },
    { id: "d-routes" as Screen, icon: Navigation, label: "Yo'nalishlar" },
    { id: "d-orders" as Screen, icon: Package, label: "Buyurtmalar" },
    { id: "d-profile" as Screen, icon: User, label: "Profil" },
  ];
  return (
    <div
      className="flex"
      style={{ background: "#fff", borderTop: "1px solid #E5E7EB", height: 72, flexShrink: 0 }}
    >
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => navigate(t.id)}
          className="flex-1 flex flex-col items-center justify-center gap-1"
        >
          <t.icon size={22} color={active === t.id ? "#1B4FD8" : "#9CA3AF"} />
          <span className="text-[10px] font-medium" style={{ color: active === t.id ? "#1B4FD8" : "#9CA3AF" }}>
            {t.label}
          </span>
        </button>
      ))}
    </div>
  );
}

// ─── Step Progress ────────────────────────────────────────────────────────────

function StepBar({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex gap-2 px-5 py-3" style={{ flexShrink: 0 }}>
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className="flex-1 rounded-full"
          style={{ height: 4, background: i < step ? "#1B4FD8" : "#E5E7EB" }}
        />
      ))}
    </div>
  );
}

// ─── Auth Screens ─────────────────────────────────────────────────────────────

function SplashScreen({ navigate }: { navigate: Go }) {
  return (
    <div
      className="flex flex-col items-center justify-between py-12 flex-1"
      style={{ background: "#1B4FD8" }}
    >
      <div />
      <div className="flex flex-col items-center gap-6">
        <div
          className="w-24 h-24 rounded-[28px] flex items-center justify-center"
          style={{ background: "rgba(255,255,255,0.15)" }}
        >
          <Truck size={46} color="#fff" />
        </div>
        <div className="text-center">
          <h1 className="text-[38px] font-bold tracking-tight" style={{ color: "#fff" }}>Elchi</h1>
          <p className="text-[16px] mt-2 leading-6" style={{ color: "rgba(255,255,255,0.75)" }}>
            Shaharlararo posilka<br />yetkazish xizmati
          </p>
        </div>
      </div>
      <div className="px-5 w-full">
        <button
          onClick={() => navigate("onboarding")}
          className="w-full flex items-center justify-center font-semibold text-base"
          style={{
            height: 52, borderRadius: 14,
            background: "rgba(255,255,255,0.2)",
            color: "#fff", border: "1.5px solid rgba(255,255,255,0.35)",
          }}
        >
          Boshlash
        </button>
      </div>
    </div>
  );
}

function OnboardingScreen({ navigate }: { navigate: Go }) {
  const [step, setStep] = useState(0);
  const steps = [
    {
      Icon: MapPin, bg: "#EEF2FF", color: "#1B4FD8",
      title: "Posilkangizni shahardan shaharga yuboring",
      sub: "Yo'nalishni tanlang, manzillarni kiriting va haydovchilardan taklif oling.",
    },
    {
      Icon: FileText, bg: "#F0FDF4", color: "#16A34A",
      title: "Haydovchilar narx taklif qiladi",
      sub: "Sizga mos narx va haydovchini o'zingiz tanlaysiz.",
    },
    {
      Icon: CheckCircle, bg: "#FFFBEB", color: "#D97706",
      title: "Yetkazildi — tasdiqlang va baholang",
      sub: "Posilka yetib borgach, buyurtmani tasdiqlang va haydovchiga baho bering.",
    },
  ];
  const cur = steps[step];
  const last = step === 2;
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff" }}>
      <div className="flex-1 flex flex-col items-center justify-center px-8">
        <div
          className="w-32 h-32 rounded-[36px] flex items-center justify-center mb-10"
          style={{ background: cur.bg }}
        >
          <cur.Icon size={60} color={cur.color} />
        </div>
        <div className="flex gap-2 mb-8">
          {steps.map((_, i) => (
            <div
              key={i}
              className="rounded-full transition-all duration-300"
              style={{ width: i === step ? 24 : 8, height: 8, background: i === step ? "#1B4FD8" : "#E5E7EB" }}
            />
          ))}
        </div>
        <h2 className="text-[22px] font-bold text-center leading-[30px] mb-3" style={{ color: "#111827" }}>
          {cur.title}
        </h2>
        <p className="text-[15px] text-center leading-6" style={{ color: "#6B7280" }}>{cur.sub}</p>
      </div>
      <div className="px-5 pb-6 flex flex-col gap-2">
        <PrimaryBtn
          label={last ? "Boshlash" : "Keyingisi"}
          onClick={() => last ? navigate("role-select") : setStep(s => s + 1)}
        />
        {!last && <GhostBtn label="O'tkazib yuborish" onClick={() => navigate("role-select")} />}
      </div>
    </div>
  );
}

function RoleSelectScreen({ navigate, setRole }: { navigate: Go; setRole: (r: Role) => void }) {
  const [sel, setSel] = useState<Role>(null);
  const roles = [
    { role: "client" as Role, label: "Men mijozman", sub: "Posilka yuborish", Icon: Package },
    { role: "driver" as Role, label: "Men haydovchiman", sub: "Buyurtmalar qabul qilish", Icon: Truck },
  ];
  return (
    <div className="flex flex-col flex-1 px-5" style={{ background: "#fff" }}>
      <div className="pt-8 pb-6">
        <h1 className="text-[26px] font-bold mb-1.5" style={{ color: "#111827" }}>Elchiga xush kelibsiz</h1>
        <p className="text-[15px]" style={{ color: "#6B7280" }}>Davom etish uchun rolingizni tanlang</p>
      </div>
      <div className="flex flex-col gap-4 mb-8">
        {roles.map(({ role, label, sub, Icon }) => {
          const active = sel === role;
          return (
            <button
              key={role}
              onClick={() => setSel(role)}
              className="flex items-center gap-4 p-5 rounded-[16px] text-left transition-all"
              style={{ border: `2px solid ${active ? "#1B4FD8" : "#E5E7EB"}`, background: active ? "#EEF2FF" : "#fff" }}
            >
              <div
                className="w-12 h-12 rounded-[14px] flex items-center justify-center"
                style={{ background: active ? "#1B4FD8" : "#F3F4F6" }}
              >
                <Icon size={22} color={active ? "#fff" : "#9CA3AF"} />
              </div>
              <div className="flex-1">
                <p className="font-semibold text-[15px]" style={{ color: "#111827" }}>{label}</p>
                <p className="text-[13px]" style={{ color: "#6B7280" }}>{sub}</p>
              </div>
              {active && (
                <div className="w-5 h-5 rounded-full flex items-center justify-center" style={{ background: "#1B4FD8" }}>
                  <Check size={11} color="#fff" />
                </div>
              )}
            </button>
          );
        })}
      </div>
      <PrimaryBtn
        label="Davom etish"
        disabled={!sel}
        onClick={() => { setRole(sel); navigate("phone-login"); }}
      />
    </div>
  );
}

function PhoneLoginScreen({ navigate }: { navigate: Go }) {
  const [phone, setPhone] = useState("");
  return (
    <div className="flex flex-col flex-1 px-5" style={{ background: "#fff" }}>
      <div className="pt-8 pb-6">
        <h1 className="text-[24px] font-bold mb-1.5" style={{ color: "#111827" }}>Telefon raqamingizni kiriting</h1>
        <p className="text-[15px]" style={{ color: "#6B7280" }}>Tasdiqlash kodi SMS orqali yuboriladi</p>
      </div>
      <div className="mb-8">
        <div
          className="flex items-center px-4 gap-3"
          style={{ height: 52, borderRadius: 12, border: "1.5px solid #1B4FD8", background: "#fff" }}
        >
          <div className="flex items-center gap-2 pr-3" style={{ borderRight: "1px solid #E5E7EB" }}>
            <span className="text-base">🇺🇿</span>
            <span className="text-[15px] font-semibold" style={{ color: "#111827" }}>+998</span>
          </div>
          <input
            type="tel"
            placeholder="__ ___ __ __"
            value={phone}
            onChange={e => setPhone(e.target.value)}
            className="flex-1 text-[15px] outline-none"
            style={{ color: "#111827", background: "transparent", fontFamily: "inherit" }}
          />
        </div>
      </div>
      <PrimaryBtn label="Kod olish" onClick={() => navigate("otp")} disabled={phone.length < 9} />
    </div>
  );
}

function OtpScreen({ navigate, role }: { navigate: Go; role: Role }) {
  const [code, setCode] = useState("");
  const dest: Screen = role === "driver" ? "d-home" : "c-home";
  return (
    <div className="flex flex-col flex-1 px-5" style={{ background: "#fff" }}>
      <button
        onClick={() => navigate("phone-login")}
        className="mt-3 w-9 h-9 flex items-center justify-center rounded-full"
        style={{ background: "#F3F4F6" }}
      >
        <ArrowLeft size={18} color="#111827" />
      </button>
      <div className="pt-5 pb-6">
        <h1 className="text-[24px] font-bold mb-1.5" style={{ color: "#111827" }}>Tasdiqlash kodi</h1>
        <p className="text-[15px]" style={{ color: "#6B7280" }}>Raqamingizga yuborilgan 5 xonali kodni kiriting</p>
      </div>
      <div className="mb-2">
        <label className="text-sm font-medium block mb-1.5" style={{ color: "#374151" }}>5 xonali kod</label>
        <input
          type="number"
          placeholder="12345"
          value={code}
          onChange={e => setCode(e.target.value.slice(0, 9))}
          className="w-full outline-none text-center font-semibold tracking-[8px]"
          style={{
            height: 56, borderRadius: 12, border: "1.5px solid #1B4FD8",
            fontSize: 22, color: "#111827", fontFamily: "inherit",
          }}
        />
      </div>
      <div className="flex justify-between items-center mb-8 mt-2">
        <span className="text-[13px]" style={{ color: "#6B7280" }}>Kod amal qilish vaqti:</span>
        <span className="text-[13px] font-semibold" style={{ color: "#1B4FD8" }}>01:59</span>
      </div>
      <PrimaryBtn label="Tasdiqlash" onClick={() => navigate(dest)} disabled={code.length < 9} />
      <div className="mt-2">
        <GhostBtn label="Kodni qayta yuborish" />
      </div>
    </div>
  );
}

// ─── Client Screens ───────────────────────────────────────────────────────────

function ClientHomeScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px]" style={{ color: "#9CA3AF" }}>Assalomu alaykum</p>
            <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Yuk yuborish</h2>
          </div>
          <div className="relative">
            <Bell size={22} color="#6B7280" />
            <span
              className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-[9px] font-bold flex items-center justify-center"
              style={{ background: "#DC2626", color: "#fff" }}
            >3</span>
          </div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* Create order card */}
        <div className="rounded-[18px] p-5 mb-4" style={{ background: "#1B4FD8" }}>
          <h3 className="text-[17px] font-bold mb-1" style={{ color: "#fff" }}>Buyurtma yaratish</h3>
          <p className="text-[13px] mb-4" style={{ color: "rgba(255,255,255,0.7)" }}>Posilkangizni yuboring</p>
          <div className="flex flex-col gap-2 mb-4">
            {["Qayerdan?", "Qayerga?"].map(p => (
              <div
                key={p}
                className="flex items-center gap-3 px-4"
                style={{ height: 46, borderRadius: 11, background: "rgba(255,255,255,0.13)" }}
              >
                <MapPin size={15} color="rgba(255,255,255,0.6)" />
                <span className="text-[14px]" style={{ color: "rgba(255,255,255,0.65)" }}>{p}</span>
              </div>
            ))}
          </div>
          <button
            onClick={() => navigate("c-order-1")}
            className="w-full flex items-center justify-center gap-1.5 font-semibold text-[15px]"
            style={{ height: 46, borderRadius: 11, background: "#fff", color: "#1B4FD8" }}
          >
            Buyurtma yaratish <ChevronRight size={16} />
          </button>
        </div>
        {/* Stats */}
        <div className="grid grid-cols-3 gap-2.5 mb-4">
          {[
            { label: "Faol buyurtmalar", value: "2" },
            { label: "Yangi takliflar", value: "5" },
            { label: "Yetkazilgan", value: "14" },
          ].map(s => (
            <div
              key={s.label}
              className="rounded-[14px] p-3 text-center"
              style={{ background: "#fff", border: "1px solid #E5E7EB" }}
            >
              <p className="text-[20px] font-bold" style={{ color: "#1B4FD8" }}>{s.value}</p>
              <p className="text-[10px] mt-0.5 leading-4" style={{ color: "#6B7280" }}>{s.label}</p>
            </div>
          ))}
        </div>
        {/* Recent */}
        <h3 className="text-[14px] font-semibold mb-3" style={{ color: "#374151" }}>So'nggi buyurtmalar</h3>
        <OrderCard from="Toshkent" to="Samarqand" status="has_bids" price="60 000 so'm" bids={3} date="18 Jun" onClick={() => navigate("c-order-bids")} />
        <OrderCard from="Andijon" to="Namangan" status="in_transit" price="45 000 so'm" date="15 Jun" onClick={() => navigate("c-order-selected")} />
      </div>
      <ClientBottomNav active="c-home" navigate={navigate} />
    </div>
  );
}

function CreateOrder1({ navigate }: { navigate: Go }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [showFrom, setShowFrom] = useState(false);
  const [showTo, setShowTo] = useState(false);
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff", position: "relative" }}>
      <TopBar title="Yo'nalishni tanlang" onBack={() => navigate("c-home")} />
      <StepBar step={1} total={3} />
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="flex flex-col gap-4 mb-5">
          {[
            { label: "Qayerdan", val: from, open: () => setShowFrom(true) },
            { label: "Qayerga", val: to, open: () => setShowTo(true) },
          ].map(f => (
            <div key={f.label}>
              <label className="text-sm font-medium block mb-1.5" style={{ color: "#374151" }}>{f.label}</label>
              <button
                onClick={f.open}
                className="w-full flex items-center gap-3 px-4 text-left"
                style={{
                  height: 52, borderRadius: 12,
                  border: `1.5px solid ${f.val ? "#1B4FD8" : "#E5E7EB"}`,
                  background: "#fff",
                }}
              >
                <MapPin size={17} color={f.val ? "#1B4FD8" : "#9CA3AF"} />
                <span className="text-[15px]" style={{ color: f.val ? "#111827" : "#9CA3AF" }}>
                  {f.val || "Shaharni tanlang"}
                </span>
              </button>
            </div>
          ))}
        </div>
        {from && to && (
          <div className="rounded-[14px] p-4" style={{ background: "#F0FDF4", border: "1px solid #DCFCE7" }}>
            <p className="text-[13px] font-medium mb-1" style={{ color: "#15803D" }}>Tavsiya etilgan narx</p>
            <p className="text-[22px] font-bold" style={{ color: "#111827" }}>60 000 so'm</p>
            <p className="text-[12px] mt-0.5" style={{ color: "#6B7280" }}>Narx haydovchi bilan kelishiladi</p>
          </div>
        )}
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Davom etish" onClick={() => navigate("c-order-2")} disabled={!from || !to} />
      </div>
      {showFrom && <CitySelector selected={from} onSelect={setFrom} onClose={() => setShowFrom(false)} />}
      {showTo && <CitySelector selected={to} onSelect={setTo} onClose={() => setShowTo(false)} />}
    </div>
  );
}

function CreateOrder2({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff" }}>
      <TopBar title="Manzil ma'lumotlari" onBack={() => navigate("c-order-1")} />
      <StepBar step={2} total={3} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
        <InputField label="Olib ketish manzili" placeholder="Masalan: Chilonzor, 12-mavze, 45-uy" multiline />
        <InputField label="Yetkazish manzili" placeholder="Masalan: Samarqand shahar, Registon ko'chasi" multiline />
        <InputField label="Yuboruvchi telefon raqami" placeholder="+998 90 123 45 67" type="tel" />
        <InputField label="Qabul qiluvchi telefon raqami" placeholder="+998 91 234 56 78" type="tel" />
        <InputField label="Izoh" placeholder="Qo'shimcha ma'lumot (ixtiyoriy)" multiline />
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Davom etish" onClick={() => navigate("c-order-3")} />
      </div>
    </div>
  );
}

function CreateOrder3({ navigate }: { navigate: Go }) {
  const [hasPhoto, setHasPhoto] = useState(false);
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff" }}>
      <TopBar title="Posilka rasmi" onBack={() => navigate("c-order-2")} />
      <StepBar step={3} total={3} />
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <button
          onClick={() => setHasPhoto(h => !h)}
          className="w-full flex flex-col items-center justify-center gap-3 mb-5"
          style={{
            height: 180, borderRadius: 16,
            border: `2px dashed ${hasPhoto ? "#1B4FD8" : "#D1D5DB"}`,
            background: hasPhoto ? "#EEF2FF" : "#F9FAFB",
          }}
        >
          {hasPhoto ? (
            <>
              <CheckCircle size={36} color="#1B4FD8" />
              <span className="text-[14px] font-semibold" style={{ color: "#1B4FD8" }}>Rasm yuklandi</span>
            </>
          ) : (
            <>
              <Camera size={34} color="#9CA3AF" />
              <span className="text-[15px] font-semibold" style={{ color: "#374151" }}>Rasm yuklash</span>
              <span className="text-[12px] text-center px-6" style={{ color: "#6B7280" }}>
                Posilkani haydovchi ko'rishi uchun bitta rasm yuklang
              </span>
            </>
          )}
        </button>
        <InputField label="Izoh" placeholder="Posilka haqida qo'shimcha ma'lumot" multiline />
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Buyurtmani ko'rib chiqish" onClick={() => navigate("c-review")} />
      </div>
    </div>
  );
}

function ReviewScreen({ navigate }: { navigate: Go }) {
  const sections = [
    { title: "YO'NALISH", rows: [["Qayerdan","Toshkent"],["Qayerga","Samarqand"]] },
    { title: "MANZILLAR", rows: [["Olib ketish","Chilonzor, 12-mavze, 45-uy"],["Yetkazish","Registon ko'chasi, 5-uy"]] },
    { title: "TELEFON RAQAMLAR", rows: [["Yuboruvchi","+998 90 123 45 67"],["Qabul qiluvchi","+998 91 234 56 78"]] },
    { title: "NARX", rows: [["Tavsiya etilgan","60 000 so'm"]] },
  ];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <TopBar title="Buyurtmani tekshiring" onBack={() => navigate("c-order-3")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        {sections.map(sec => (
          <div key={sec.title} className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
            <p className="text-[10px] font-bold tracking-widest mb-3" style={{ color: "#9CA3AF" }}>{sec.title}</p>
            {sec.rows.map(([l, v]) => (
              <div key={l} className="flex justify-between py-2" style={{ borderBottom: "1px solid #F3F4F6" }}>
                <span className="text-[13px]" style={{ color: "#6B7280" }}>{l}</span>
                <span className="text-[13px] font-medium" style={{ color: "#111827" }}>{v}</span>
              </div>
            ))}
          </div>
        ))}
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[10px] font-bold tracking-widest mb-3" style={{ color: "#9CA3AF" }}>POSILKA RASMI</p>
          <div className="w-full h-[100px] rounded-[10px] flex items-center justify-center" style={{ background: "#F3F4F6" }}>
            <Camera size={24} color="#9CA3AF" />
          </div>
        </div>
      </div>
      <div className="px-5 pb-5 flex flex-col gap-2.5" style={{ background: "#F7F8FA", flexShrink: 0 }}>
        <PrimaryBtn label="Buyurtmani e'lon qilish" onClick={() => navigate("c-success")} />
        <SecondaryBtn label="Tahrirlash" onClick={() => navigate("c-order-1")} />
      </div>
    </div>
  );
}

function SuccessScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1 items-center justify-center px-8" style={{ background: "#fff" }}>
      <div className="w-24 h-24 rounded-full flex items-center justify-center mb-6" style={{ background: "#DCFCE7" }}>
        <CheckCircle size={48} color="#16A34A" />
      </div>
      <h2 className="text-[22px] font-bold text-center mb-3" style={{ color: "#111827" }}>Buyurtma e'lon qilindi</h2>
      <p className="text-[15px] text-center leading-6 mb-10" style={{ color: "#6B7280" }}>
        Haydovchilardan takliflar kelganda sizga xabar beramiz
      </p>
      <div className="w-full flex flex-col gap-3">
        <PrimaryBtn label="Buyurtmalarni ko'rish" onClick={() => navigate("c-orders")} />
        <SecondaryBtn label="Bosh sahifaga" onClick={() => navigate("c-home")} />
      </div>
    </div>
  );
}

function ClientOrdersScreen({ navigate }: { navigate: Go }) {
  const [tab, setTab] = useState(0);
  const tabs = ["Faol", "Takliflar", "Yakunlangan", "Bekor qilingan"];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold mb-3" style={{ color: "#111827" }}>Buyurtmalar</h2>
        <div className="flex gap-0 overflow-x-auto">
          {tabs.map((t, i) => (
            <button
              key={t}
              onClick={() => setTab(i)}
              className="px-3 py-2.5 text-[13px] font-medium whitespace-nowrap"
              style={{
                color: tab === i ? "#1B4FD8" : "#6B7280",
                borderBottom: `2px solid ${tab === i ? "#1B4FD8" : "transparent"}`,
              }}
            >{t}</button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === 0 && <>
          <OrderCard from="Toshkent" to="Samarqand" status="has_bids" price="60 000 so'm" bids={3} date="18 Jun" onClick={() => navigate("c-order-bids")} />
          <OrderCard from="Andijon" to="Namangan" status="in_transit" price="45 000 so'm" date="15 Jun" onClick={() => navigate("c-order-selected")} />
        </>}
        {tab === 1 && <OrderCard from="Toshkent" to="Samarqand" status="has_bids" price="60 000 so'm" bids={3} date="18 Jun" onClick={() => navigate("c-order-bids")} />}
        {tab === 2 && <OrderCard from="Toshkent" to="Buxoro" status="confirmed" price="80 000 so'm" date="10 Jun" onClick={() => navigate("c-order-nobids")} />}
        {tab === 3 && <EmptyState icon={XCircle} title="Bekor qilingan buyurtmalar yo'q" />}
      </div>
      <ClientBottomNav active="c-orders" navigate={navigate} />
    </div>
  );
}

function ClientOrderNoBids({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <TopBar title="Buyurtma tafsilotlari" onBack={() => navigate("c-orders")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <div className="flex items-center justify-between mb-3">
            <span className="font-semibold text-[15px]" style={{ color: "#111827" }}>Toshkent → Samarqand</span>
            <StatusBadge status="announced" />
          </div>
          {[["Olib ketish","Chilonzor, 12-mavze, 45-uy"],["Yetkazish","Registon ko'chasi, 5-uy"],["Tavsiya narx","60 000 so'm"]].map(([l,v]) => (
            <div key={l} className="flex justify-between py-2" style={{ borderBottom: "1px solid #F3F4F6" }}>
              <span className="text-[13px]" style={{ color: "#6B7280" }}>{l}</span>
              <span className="text-[13px] font-medium" style={{ color: "#111827" }}>{v}</span>
            </div>
          ))}
        </div>
        <EmptyState
          icon={Package}
          title="Hozircha takliflar yo'q"
          subtitle="Haydovchilar taklif yuborishi bilan shu yerda ko'rasiz"
        />
      </div>
      <div className="px-5 pb-5" style={{ flexShrink: 0 }}>
        <button
          className="w-full flex items-center justify-center font-semibold text-[15px]"
          style={{ height: 52, borderRadius: 14, background: "#FEE2E2", color: "#DC2626", border: "none" }}
        >
          Buyurtmani bekor qilish
        </button>
      </div>
    </div>
  );
}

function ClientOrderBids({ navigate }: { navigate: Go }) {
  const [modal, setModal] = useState(false);
  const bids = [
    { name: "Jasur Toshmatov", car: "Cobalt", plate: "01 A 123 AA", rating: 4.8, price: "55 000 so'm" },
    { name: "Alisher Karimov", car: "Lacetti", plate: "78 B 456 BB", rating: 4.5, price: "60 000 so'm" },
    { name: "Bobur Rahimov", car: "Nexia 3", plate: "30 C 789 CC", rating: 4.2, price: "50 000 so'm" },
  ];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA", position: "relative" }}>
      <TopBar title="Haydovchi takliflari" onBack={() => navigate("c-orders")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-[12px] mb-1" style={{ background: "#EEF2FF" }}>
          <MapPin size={14} color="#1B4FD8" />
          <span className="text-[13px] font-medium" style={{ color: "#1B4FD8" }}>Toshkent → Samarqand</span>
        </div>
        {bids.map((bid, i) => (
          <div key={i} className="rounded-[16px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full flex items-center justify-center" style={{ background: "#EEF2FF" }}>
                <User size={20} color="#1B4FD8" />
              </div>
              <div className="flex-1">
                <p className="font-semibold text-[14px]" style={{ color: "#111827" }}>{bid.name}</p>
                <p className="text-[12px]" style={{ color: "#6B7280" }}>{bid.car} · {bid.plate}</p>
              </div>
              <div className="flex items-center gap-0.5">
                <Star size={13} color="#F59E0B" fill="#F59E0B" />
                <span className="text-[13px] font-semibold" style={{ color: "#111827" }}>{bid.rating}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[19px] font-bold" style={{ color: "#111827" }}>{bid.price}</span>
              <button
                onClick={() => setModal(true)}
                className="flex items-center font-semibold text-[13px]"
                style={{ height: 36, paddingInline: 12, borderRadius: 10, background: "#1B4FD8", color: "#fff", border: "none" }}
              >
                Shu haydovchini tanlash
              </button>
            </div>
          </div>
        ))}
      </div>
      {modal && (
        <div className="absolute inset-0 flex items-center justify-center z-50 px-5" style={{ background: "rgba(0,0,0,0.5)" }}>
          <div className="w-full rounded-[20px] p-6" style={{ background: "#fff" }}>
            <h3 className="text-[19px] font-bold mb-2" style={{ color: "#111827" }}>Haydovchini tanlaysizmi?</h3>
            <p className="text-[14px] leading-6 mb-6" style={{ color: "#6B7280" }}>
              Tanlaganingizdan keyin boshqa takliflar yopiladi.
            </p>
            <div className="flex flex-col gap-2.5">
              <PrimaryBtn label="Tanlash" onClick={() => { setModal(false); navigate("c-order-selected"); }} />
              <SecondaryBtn label="Bekor qilish" onClick={() => setModal(false)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ClientOrderSelected({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <TopBar title="Buyurtma tafsilotlari" onBack={() => navigate("c-orders")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[10px] font-bold tracking-widest mb-3" style={{ color: "#9CA3AF" }}>HAYDOVCHI</p>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-12 h-12 rounded-full flex items-center justify-center" style={{ background: "#EEF2FF" }}>
              <User size={24} color="#1B4FD8" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-[15px]" style={{ color: "#111827" }}>Jasur Toshmatov</p>
              <p className="text-[12px]" style={{ color: "#6B7280" }}>Cobalt · 01 A 123 AA</p>
            </div>
            <div className="flex items-center gap-0.5">
              <Star size={13} color="#F59E0B" fill="#F59E0B" />
              <span className="font-semibold text-[13px]" style={{ color: "#111827" }}>4.8</span>
            </div>
          </div>
          <div className="flex items-center justify-between px-3 py-2.5 rounded-[10px]" style={{ background: "#F7F8FA" }}>
            <span className="text-[13px]" style={{ color: "#6B7280" }}>Yakuniy narx</span>
            <span className="font-bold text-[17px]" style={{ color: "#111827" }}>55 000 so'm</span>
          </div>
        </div>
        <div className="flex items-center justify-between px-4 py-3.5 rounded-[14px]" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <span className="text-[13px]" style={{ color: "#6B7280" }}>Holat</span>
          <StatusBadge status="in_transit" />
        </div>
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[10px] font-bold tracking-widest mb-4" style={{ color: "#9CA3AF" }}>JARAYON</p>
          <Timeline
            steps={["Haydovchi tanlandi","Olib ketildi","Yo'lda","Yetkazildi","Tasdiqlandi"]}
            activeStep={2}
          />
        </div>
        <div className="rounded-[14px] p-4" style={{ background: "#DCFCE7", border: "1px solid #BBF7D0" }}>
          <p className="text-[13px] font-medium" style={{ color: "#15803D" }}>
            Posilka yetkazilganda "Yetkazilganini tasdiqlash" tugmasini bosing
          </p>
        </div>
      </div>
      <div className="px-5 pb-5" style={{ flexShrink: 0 }}>
        <PrimaryBtn label="Yetkazilganini tasdiqlash" onClick={() => navigate("c-confirm")} />
      </div>
    </div>
  );
}

function ConfirmScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1 items-center justify-center px-8" style={{ background: "#fff" }}>
      <div className="w-20 h-20 rounded-full flex items-center justify-center mb-5" style={{ background: "#DCFCE7" }}>
        <CheckCircle size={40} color="#16A34A" />
      </div>
      <h1 className="text-[22px] font-bold text-center mb-2" style={{ color: "#111827" }}>Buyurtmani tasdiqlang</h1>
      <p className="text-[15px] text-center leading-6 mb-10" style={{ color: "#6B7280" }}>
        Posilka yetib kelgan bo'lsa, buyurtmani tasdiqlang.
      </p>
      <div className="w-full flex flex-col gap-3">
        <PrimaryBtn label="Tasdiqlash" onClick={() => navigate("c-rating")} />
        <GhostBtn label="Bekor qilish" />
      </div>
    </div>
  );
}

function RatingScreen({ navigate }: { navigate: Go }) {
  const [stars, setStars] = useState(0);
  const [note, setNote] = useState("");
  return (
    <div className="flex flex-col flex-1 px-5" style={{ background: "#fff" }}>
      <div className="pt-8 flex flex-col items-center gap-5 mb-8">
        <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ background: "#EEF2FF" }}>
          <User size={30} color="#1B4FD8" />
        </div>
        <div className="text-center">
          <h1 className="text-[22px] font-bold mb-0.5" style={{ color: "#111827" }}>Haydovchini baholang</h1>
          <p className="text-[14px]" style={{ color: "#6B7280" }}>Jasur Toshmatov</p>
        </div>
        <div className="flex gap-3">
          {[1,2,3,4,5].map(s => (
            <button key={s} onClick={() => setStars(s)}>
              <Star size={34} color="#F59E0B" fill={s <= stars ? "#F59E0B" : "none"} strokeWidth={1.5} />
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <InputField label="Izoh qoldiring" placeholder="Haydovchi haqida fikringiz..." value={note} onChange={setNote} multiline />
        <PrimaryBtn label="Bahoni yuborish" onClick={() => navigate("c-home")} disabled={stars === 0} />
      </div>
    </div>
  );
}

function ClientNotifications({ navigate }: { navigate: Go }) {
  const items = [
    { title: "Yangi taklif keldi", sub: "Jasur Toshmatov: 55 000 so'm", time: "5 daqiqa oldin", type: "info" },
    { title: "Posilka yo'lda", sub: "Toshkent → Samarqand", time: "2 soat oldin", type: "success" },
    { title: "Buyurtma tasdiqlandi", sub: "Andijon → Namangan", time: "Kecha", type: "success" },
    { title: "Buyurtma bekor qilindi", sub: "Farg'ona → Toshkent", time: "3 kun oldin", type: "error" },
  ];
  const tc: Record<string,string> = { info: "#DBEAFE", success: "#DCFCE7", error: "#FEE2E2" };
  const ic: Record<string,string> = { info: "#1D4ED8", success: "#16A34A", error: "#DC2626" };
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Bildirishnomalar</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        {items.map((n, i) => (
          <div key={i} className="rounded-[14px] p-4 flex items-start gap-3" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
            <div className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0" style={{ background: tc[n.type] }}>
              <Bell size={16} color={ic[n.type]} />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-[14px]" style={{ color: "#111827" }}>{n.title}</p>
              <p className="text-[12px] mt-0.5" style={{ color: "#6B7280" }}>{n.sub}</p>
              <p className="text-[11px] mt-1" style={{ color: "#9CA3AF" }}>{n.time}</p>
            </div>
          </div>
        ))}
      </div>
      <ClientBottomNav active="c-notifications" navigate={navigate} />
    </div>
  );
}

function ClientProfileScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Profil</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <div className="flex flex-col items-center mb-6">
          <div className="w-20 h-20 rounded-full flex items-center justify-center mb-3" style={{ background: "#EEF2FF" }}>
            <User size={34} color="#1B4FD8" />
          </div>
          <p className="font-semibold text-[17px]" style={{ color: "#111827" }}>+998 90 123 45 67</p>
          <span className="mt-2 px-3 py-1 rounded-full text-[12px] font-semibold" style={{ background: "#EEF2FF", color: "#1B4FD8" }}>Mijoz</span>
        </div>
        <div className="rounded-[16px] overflow-hidden mb-4" style={{ border: "1px solid #E5E7EB" }}>
          {[["Telefon raqam","+998 90 123 45 67"],["Rol","Mijoz"],["Ro'yxatdan o'tgan","Iyun 2024"]].map(([l,v],i,arr) => (
            <div key={l} className="flex items-center justify-between px-4 py-3.5" style={{ background: "#fff", borderBottom: i < arr.length-1 ? "1px solid #F3F4F6" : "none" }}>
              <span className="text-[14px]" style={{ color: "#6B7280" }}>{l}</span>
              <span className="text-[14px] font-medium" style={{ color: "#111827" }}>{v}</span>
            </div>
          ))}
        </div>
        <button
          onClick={() => navigate("role-select")}
          className="w-full flex items-center justify-center font-semibold text-[15px]"
          style={{ height: 52, borderRadius: 14, background: "#FEE2E2", color: "#DC2626", border: "none" }}
        >
          Chiqish
        </button>
      </div>
      <ClientBottomNav active="c-profile" navigate={navigate} />
    </div>
  );
}

// ─── Driver Screens ───────────────────────────────────────────────────────────

function DriverHomeScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4 flex items-center justify-between" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Bosh sahifa</h2>
        <Bell size={22} color="#6B7280" />
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="rounded-[16px] p-5 mb-4" style={{ background: "#FEF3C7", border: "1px solid #FDE68A" }}>
          <div className="flex items-start gap-3">
            <AlertCircle size={20} color="#D97706" className="flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold text-[15px] mb-1" style={{ color: "#92400E" }}>Profilni to'ldiring</p>
              <p className="text-[13px] leading-5 mb-4" style={{ color: "#78350F" }}>
                Buyurtmalarni ko'rish uchun avval profil va hujjatlaringizni yuboring.
              </p>
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => navigate("d-profile-form")}
                  className="flex items-center font-semibold text-[13px]"
                  style={{ height: 36, paddingInline: 14, borderRadius: 10, background: "#D97706", color: "#fff", border: "none" }}
                >Profilni to'ldirish</button>
                <button
                  onClick={() => navigate("d-documents")}
                  className="flex items-center font-semibold text-[13px]"
                  style={{ height: 36, paddingInline: 14, borderRadius: 10, background: "rgba(217,119,6,0.12)", color: "#D97706", border: "none" }}
                >Hujjatlarni yuklash</button>
              </div>
            </div>
          </div>
        </div>
        <div className="rounded-[16px] p-4 mb-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[13px] font-semibold mb-3" style={{ color: "#374151" }}>Faollik holati</p>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-[14px]" style={{ color: "#111827" }}>Faolman</p>
              <p className="text-[12px] mt-0.5" style={{ color: "#DC2626" }}>Tasdiqlanmaguncha faol bo'la olmaysiz</p>
            </div>
            <div className="w-12 h-7 rounded-full flex items-center px-0.5" style={{ background: "#E5E7EB" }}>
              <div className="w-6 h-6 rounded-full" style={{ background: "#9CA3AF" }} />
            </div>
          </div>
        </div>
        <EmptyState
          icon={Package}
          title="Hozircha mos buyurtmalar yo'q"
          subtitle="Profil tasdiqlangandan keyin buyurtmalarni ko'rasiz"
        />
      </div>
      <DriverBottomNav active="d-home" navigate={navigate} />
    </div>
  );
}

function DriverProfileFormScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff" }}>
      <TopBar title="Haydovchi profili" onBack={() => navigate("d-home")} />
      <div className="flex-1 overflow-y-auto px-5 py-5 flex flex-col gap-4">
        <InputField label="Ism familiya" placeholder="Masalan: Jasur Toshmatov" />
        <InputField label="Avtomobil modeli" placeholder="Masalan: Cobalt" />
        <InputField label="Avtomobil rangi" placeholder="Masalan: Oq" />
        <InputField label="Davlat raqami" placeholder="Masalan: 01 A 123 AA" />
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Saqlash" onClick={() => navigate("d-documents")} />
      </div>
    </div>
  );
}

function DriverDocumentsScreen({ navigate }: { navigate: Go }) {
  const [docs, setDocs] = useState<Record<string,string>>({
    "Pasport": "Yuklanmagan",
    "Selfi": "Yuklanmagan",
    "Haydovchilik guvohnomasi": "Ko'rib chiqilmoqda",
    "Avtomobil hujjati": "Rad etildi",
    "Avtomobil rasmi": "Yuklanmagan",
  });
  const st: Record<string,{bg:string;color:string}> = {
    "Yuklanmagan":       { bg:"#F3F4F6", color:"#6B7280" },
    "Yuklandi":          { bg:"#DCFCE7", color:"#16A34A" },
    "Ko'rib chiqilmoqda":{ bg:"#FEF3C7", color:"#D97706" },
    "Rad etildi":        { bg:"#FEE2E2", color:"#DC2626" },
  };
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <TopBar title="Hujjatlar" onBack={() => navigate("d-profile-form")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        {Object.entries(docs).map(([doc, state]) => {
          const s = st[state];
          const canUpload = state === "Yuklanmagan" || state === "Rad etildi";
          return (
            <div key={doc} className="rounded-[14px] p-4 flex items-center gap-3" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
              <div className="w-10 h-10 rounded-[10px] flex items-center justify-center flex-shrink-0" style={{ background: s.bg }}>
                <FileText size={19} color={s.color} />
              </div>
              <div className="flex-1">
                <p className="font-medium text-[14px]" style={{ color: "#111827" }}>{doc}</p>
                <span className="text-[12px] font-semibold" style={{ color: s.color }}>{state}</span>
              </div>
              {canUpload && (
                <button
                  onClick={() => setDocs(d => ({ ...d, [doc]: "Ko'rib chiqilmoqda" }))}
                  className="flex items-center gap-1 font-semibold text-[13px]"
                  style={{ height: 34, paddingInline: 12, borderRadius: 8, background: "#1B4FD8", color: "#fff", border: "none" }}
                >
                  <Upload size={13} /> Yuklash
                </button>
              )}
            </div>
          );
        })}
        <div className="rounded-[12px] p-3 text-center" style={{ background: "#DBEAFE" }}>
          <p className="text-[13px]" style={{ color: "#1D4ED8" }}>Hujjatlar ko'rib chiqishga yuborildi</p>
        </div>
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Saqlash" onClick={() => navigate("d-home")} />
      </div>
    </div>
  );
}

function DriverRoutesScreen({ navigate }: { navigate: Go }) {
  const routes = [
    { from: "Toshkent", to: "Samarqand" },
    { from: "Samarqand", to: "Toshkent" },
  ];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4 flex items-center justify-between" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Yo'nalishlarim</h2>
        <button
          onClick={() => navigate("d-add-route")}
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ background: "#1B4FD8" }}
        >
          <Plus size={18} color="#fff" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        {routes.map((r, i) => (
          <div key={i} className="rounded-[14px] p-4 flex items-center gap-3" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
            <div className="w-10 h-10 rounded-[10px] flex items-center justify-center" style={{ background: "#EEF2FF" }}>
              <Navigation size={18} color="#1B4FD8" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-[14px]" style={{ color: "#111827" }}>{r.from} → {r.to}</p>
              <span className="text-[12px] font-semibold" style={{ color: "#16A34A" }}>Faol</span>
            </div>
            <button><X size={18} color="#9CA3AF" /></button>
          </div>
        ))}
        <button
          onClick={() => navigate("d-add-route")}
          className="w-full flex items-center justify-center gap-2"
          style={{ height: 52, borderRadius: 14, border: "2px dashed #D1D5DB", background: "#F9FAFB" }}
        >
          <Plus size={17} color="#6B7280" />
          <span className="text-[14px] font-medium" style={{ color: "#6B7280" }}>Yo'nalish qo'shish</span>
        </button>
      </div>
      <DriverBottomNav active="d-routes" navigate={navigate} />
    </div>
  );
}

function AddRouteScreen({ navigate }: { navigate: Go }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [showFrom, setShowFrom] = useState(false);
  const [showTo, setShowTo] = useState(false);
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff", position: "relative" }}>
      <TopBar title="Yo'nalish qo'shish" onBack={() => navigate("d-routes")} />
      <div className="flex-1 px-5 py-5 flex flex-col gap-4">
        {[
          { label: "Qayerdan", val: from, open: () => setShowFrom(true) },
          { label: "Qayerga", val: to, open: () => setShowTo(true) },
        ].map(f => (
          <div key={f.label}>
            <label className="text-sm font-medium block mb-1.5" style={{ color: "#374151" }}>{f.label}</label>
            <button
              onClick={f.open}
              className="w-full flex items-center gap-3 px-4 text-left"
              style={{ height: 52, borderRadius: 12, border: `1.5px solid ${f.val ? "#1B4FD8" : "#E5E7EB"}`, background: "#fff" }}
            >
              <MapPin size={17} color={f.val ? "#1B4FD8" : "#9CA3AF"} />
              <span className="text-[15px]" style={{ color: f.val ? "#111827" : "#9CA3AF" }}>
                {f.val || "Shaharni tanlang"}
              </span>
            </button>
          </div>
        ))}
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Saqlash" onClick={() => navigate("d-routes")} disabled={!from || !to} />
      </div>
      {showFrom && <CitySelector selected={from} onSelect={setFrom} onClose={() => setShowFrom(false)} />}
      {showTo && <CitySelector selected={to} onSelect={setTo} onClose={() => setShowTo(false)} />}
    </div>
  );
}

function DriverFeedScreen({ navigate }: { navigate: Go }) {
  const orders = [
    { from: "Toshkent", to: "Samarqand", pickup: "Chilonzor tumani", dropoff: "Registon maydon", price: "60 000 so'm" },
    { from: "Toshkent", to: "Samarqand", pickup: "Yunusobod tumani", dropoff: "Mirzo Ulug'bek ko'ch.", price: "55 000 so'm" },
  ];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Mos buyurtmalar</h2>
        <p className="text-[12px] mt-0.5" style={{ color: "#6B7280" }}>Toshkent → Samarqand yo'nalishi</p>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
        {orders.map((o, i) => (
          <div key={i} className="rounded-[16px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
            <div className="flex items-center gap-2 mb-3">
              <MapPin size={13} color="#1B4FD8" />
              <span className="font-semibold text-[14px]" style={{ color: "#111827" }}>{o.from} → {o.to}</span>
            </div>
            <div className="flex flex-col gap-1.5 mb-3 pb-3" style={{ borderBottom: "1px solid #F3F4F6" }}>
              {[["Olib ketish",o.pickup],["Yetkazish",o.dropoff]].map(([l,v]) => (
                <div key={l} className="flex gap-2">
                  <span className="text-[11px] w-16 flex-shrink-0 mt-0.5" style={{ color: "#9CA3AF" }}>{l}</span>
                  <span className="text-[13px]" style={{ color: "#374151" }}>{v}</span>
                </div>
              ))}
            </div>
            <div className="w-14 h-14 rounded-[10px] mb-3" style={{ background: "#F3F4F6" }} />
            <div className="flex items-center justify-between">
              <span className="text-[19px] font-bold" style={{ color: "#111827" }}>{o.price}</span>
              <div className="flex gap-2">
                <button style={{ height: 36, paddingInline: 10, borderRadius: 10, background: "#FEE2E2", color: "#DC2626", border: "none", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                  Rad etish
                </button>
                <button
                  onClick={() => navigate("d-bid")}
                  style={{ height: 36, paddingInline: 10, borderRadius: 10, background: "#1B4FD8", color: "#fff", border: "none", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
                >
                  Taklif yuborish
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
      <DriverBottomNav active="d-home" navigate={navigate} />
    </div>
  );
}

function DriverBidScreen({ navigate }: { navigate: Go }) {
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");
  const invalid = !price || parseInt(price) <= 0;
  return (
    <div className="flex flex-col flex-1" style={{ background: "#fff" }}>
      <TopBar title="Narx taklif qiling" onBack={() => navigate("d-feed")} />
      <div className="flex-1 overflow-y-auto px-5 py-5 flex flex-col gap-4">
        <div className="rounded-[14px] p-4" style={{ background: "#F7F8FA", border: "1px solid #E5E7EB" }}>
          <div className="flex items-center gap-2 mb-1.5">
            <MapPin size={13} color="#1B4FD8" />
            <span className="font-semibold text-[14px]" style={{ color: "#111827" }}>Toshkent → Samarqand</span>
          </div>
          <p className="text-[12px]" style={{ color: "#6B7280" }}>Tavsiya narx: 60 000 so'm</p>
        </div>
        <div>
          <label className="text-sm font-medium block mb-1.5" style={{ color: "#374151" }}>Taklif narxi (so'm)</label>
          <input
            type="number"
            placeholder="Masalan: 55000"
            value={price}
            onChange={e => setPrice(e.target.value)}
            className="w-full outline-none text-center font-bold"
            style={{ height: 56, borderRadius: 12, border: "1.5px solid #E5E7EB", fontSize: 22, color: "#111827", fontFamily: "inherit" }}
          />
          {price && invalid && (
            <p className="text-[12px] mt-1" style={{ color: "#DC2626" }}>Narx 0 dan katta bo'lishi kerak</p>
          )}
        </div>
        <InputField label="Izoh" placeholder="Qo'shimcha ma'lumot (ixtiyoriy)" value={note} onChange={setNote} multiline />
      </div>
      <div className="px-5 pb-5">
        <PrimaryBtn label="Taklif yuborish" onClick={() => navigate("d-feed")} disabled={invalid} />
      </div>
    </div>
  );
}

function DriverOrdersScreen({ navigate }: { navigate: Go }) {
  const [tab, setTab] = useState(0);
  const tabs = ["Faol", "Yakunlangan", "Bekor qilingan"];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold mb-3" style={{ color: "#111827" }}>Buyurtmalar</h2>
        <div className="flex gap-0">
          {tabs.map((t, i) => (
            <button
              key={t}
              onClick={() => setTab(i)}
              className="px-3 py-2.5 text-[13px] font-medium"
              style={{ color: tab===i?"#1B4FD8":"#6B7280", borderBottom:`2px solid ${tab===i?"#1B4FD8":"transparent"}` }}
            >{t}</button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === 0 && <OrderCard from="Toshkent" to="Samarqand" status="in_transit" price="55 000 so'm" date="18 Jun" onClick={() => navigate("d-order-detail")} />}
        {tab === 1 && <OrderCard from="Andijon" to="Namangan" status="confirmed" price="45 000 so'm" date="10 Jun" onClick={() => navigate("d-order-detail")} />}
        {tab === 2 && <EmptyState icon={XCircle} title="Bekor qilingan buyurtmalar yo'q" />}
      </div>
      <DriverBottomNav active="d-orders" navigate={navigate} />
    </div>
  );
}

function DriverOrderDetailScreen({ navigate }: { navigate: Go }) {
  const [statusStep, setStatusStep] = useState(0);
  const actions = [
    "Olib ketildi deb belgilash",
    "Yo'lga chiqdi deb belgilash",
    "Yetkazildi deb belgilash",
  ];
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <TopBar title="Buyurtma tafsilotlari" onBack={() => navigate("d-orders")} />
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3">
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <div className="flex items-center justify-between mb-3">
            <span className="font-semibold text-[15px]" style={{ color: "#111827" }}>Toshkent → Samarqand</span>
            <span className="font-bold text-[16px]" style={{ color: "#1B4FD8" }}>55 000 so'm</span>
          </div>
          {[
            ["Olib ketish","Chilonzor, 12-mavze, 45-uy"],
            ["Yetkazish","Registon ko'chasi, 5-uy"],
            ["Yuboruvchi tel.","+998 90 123 45 67"],
            ["Qabul qiluvchi tel.","+998 91 234 56 78"],
          ].map(([l,v]) => (
            <div key={l} className="flex justify-between py-2" style={{ borderBottom: "1px solid #F3F4F6" }}>
              <span className="text-[12px]" style={{ color: "#6B7280" }}>{l}</span>
              <span className="text-[12px] font-medium" style={{ color: "#111827" }}>{v}</span>
            </div>
          ))}
        </div>
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[10px] font-bold tracking-widest mb-3" style={{ color: "#9CA3AF" }}>POSILKA RASMI</p>
          <div className="w-full h-[100px] rounded-[10px] flex items-center justify-center" style={{ background: "#F3F4F6" }}>
            <Camera size={24} color="#9CA3AF" />
          </div>
        </div>
        <div className="rounded-[14px] p-4" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
          <p className="text-[10px] font-bold tracking-widest mb-4" style={{ color: "#9CA3AF" }}>JARAYON</p>
          <Timeline
            steps={["Haydovchi tanlandi","Olib ketildi","Yo'lda","Yetkazildi","Tasdiqlandi"]}
            activeStep={statusStep}
          />
        </div>
      </div>
      {statusStep < 3 && (
        <div className="px-5 pb-5" style={{ flexShrink: 0 }}>
          <PrimaryBtn
            label={actions[statusStep]}
            onClick={() => setStatusStep(s => s + 1)}
          />
        </div>
      )}
    </div>
  );
}

function DriverProfileScreen({ navigate }: { navigate: Go }) {
  return (
    <div className="flex flex-col flex-1" style={{ background: "#F7F8FA" }}>
      <div className="px-5 pt-3 pb-4" style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", flexShrink: 0 }}>
        <h2 className="text-[20px] font-bold" style={{ color: "#111827" }}>Profil</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-5">
        <div className="flex flex-col items-center mb-5">
          <div className="w-20 h-20 rounded-full flex items-center justify-center mb-3" style={{ background: "#EEF2FF" }}>
            <Truck size={32} color="#1B4FD8" />
          </div>
          <p className="font-semibold text-[17px]" style={{ color: "#111827" }}>Jasur Toshmatov</p>
          <p className="text-[13px] mt-0.5" style={{ color: "#6B7280" }}>+998 90 123 45 67</p>
          <div className="flex gap-2 mt-2">
            <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold" style={{ background: "#EEF2FF", color: "#1B4FD8" }}>Haydovchi</span>
            <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold" style={{ background: "#FEF3C7", color: "#D97706" }}>Ko'rib chiqilmoqda</span>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2.5 mb-4">
          {[["Reyting","—"],["Bajarilgan","0"],["Bekor qilingan","0"]].map(([l,v]) => (
            <div key={l} className="rounded-[12px] p-3 text-center" style={{ background: "#fff", border: "1px solid #E5E7EB" }}>
              <p className="text-[18px] font-bold" style={{ color: "#111827" }}>{v}</p>
              <p className="text-[10px] mt-0.5" style={{ color: "#6B7280" }}>{l}</p>
            </div>
          ))}
        </div>
        <div className="rounded-[14px] overflow-hidden mb-4" style={{ border: "1px solid #E5E7EB" }}>
          {[["Avtomobil","Cobalt · Oq"],["Raqam","01 A 123 AA"],["Tasdiqlash holati","Ko'rib chiqilmoqda"],["Faollik","Nofaol"]].map(([l,v],i,arr) => (
            <div key={l} className="flex items-center justify-between px-4 py-3.5" style={{ background: "#fff", borderBottom: i<arr.length-1?"1px solid #F3F4F6":"none" }}>
              <span className="text-[13px]" style={{ color: "#6B7280" }}>{l}</span>
              <span className="text-[13px] font-medium" style={{ color: "#111827" }}>{v}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-2.5">
          <SecondaryBtn label="Profilni tahrirlash" onClick={() => navigate("d-profile-form")} />
          <SecondaryBtn label="Hujjatlar" onClick={() => navigate("d-documents")} />
          <button
            onClick={() => navigate("role-select")}
            className="w-full flex items-center justify-center font-semibold text-[15px]"
            style={{ height: 52, borderRadius: 14, background: "#FEE2E2", color: "#DC2626", border: "none" }}
          >Chiqish</button>
        </div>
      </div>
      <DriverBottomNav active="d-profile" navigate={navigate} />
    </div>
  );
}

// ─── Screen Router ────────────────────────────────────────────────────────────

function ScreenRouter({ screen, navigate, role, setRole }: {
  screen: Screen; navigate: Go; role: Role; setRole: (r: Role) => void;
}) {
  switch (screen) {
    case "splash":            return <SplashScreen navigate={navigate} />;
    case "onboarding":        return <OnboardingScreen navigate={navigate} />;
    case "role-select":       return <RoleSelectScreen navigate={navigate} setRole={setRole} />;
    case "phone-login":       return <PhoneLoginScreen navigate={navigate} />;
    case "otp":               return <OtpScreen navigate={navigate} role={role} />;
    case "c-home":            return <ClientHomeScreen navigate={navigate} />;
    case "c-order-1":         return <CreateOrder1 navigate={navigate} />;
    case "c-order-2":         return <CreateOrder2 navigate={navigate} />;
    case "c-order-3":         return <CreateOrder3 navigate={navigate} />;
    case "c-review":          return <ReviewScreen navigate={navigate} />;
    case "c-success":         return <SuccessScreen navigate={navigate} />;
    case "c-orders":          return <ClientOrdersScreen navigate={navigate} />;
    case "c-order-nobids":    return <ClientOrderNoBids navigate={navigate} />;
    case "c-order-bids":      return <ClientOrderBids navigate={navigate} />;
    case "c-order-selected":  return <ClientOrderSelected navigate={navigate} />;
    case "c-confirm":         return <ConfirmScreen navigate={navigate} />;
    case "c-rating":          return <RatingScreen navigate={navigate} />;
    case "c-notifications":   return <ClientNotifications navigate={navigate} />;
    case "c-profile":         return <ClientProfileScreen navigate={navigate} />;
    case "d-home":            return <DriverHomeScreen navigate={navigate} />;
    case "d-profile-form":    return <DriverProfileFormScreen navigate={navigate} />;
    case "d-documents":       return <DriverDocumentsScreen navigate={navigate} />;
    case "d-routes":          return <DriverRoutesScreen navigate={navigate} />;
    case "d-add-route":       return <AddRouteScreen navigate={navigate} />;
    case "d-feed":            return <DriverFeedScreen navigate={navigate} />;
    case "d-bid":             return <DriverBidScreen navigate={navigate} />;
    case "d-orders":          return <DriverOrdersScreen navigate={navigate} />;
    case "d-order-detail":    return <DriverOrderDetailScreen navigate={navigate} />;
    case "d-profile":         return <DriverProfileScreen navigate={navigate} />;
    default:                  return <SplashScreen navigate={navigate} />;
  }
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

const GROUPS = [
  { title: "KIRISH", screens: [
    { id: "splash",       label: "Splash" },
    { id: "onboarding",   label: "Onboarding" },
    { id: "role-select",  label: "Rol tanlash" },
    { id: "phone-login",  label: "Telefon kirish" },
    { id: "otp",          label: "OTP tasdiqlash" },
  ]},
  { title: "MIJOZ", screens: [
    { id: "c-home",           label: "Bosh sahifa" },
    { id: "c-order-1",        label: "Buyurtma 1/3 – Yo'nalish" },
    { id: "c-order-2",        label: "Buyurtma 2/3 – Manzil" },
    { id: "c-order-3",        label: "Buyurtma 3/3 – Rasm" },
    { id: "c-review",         label: "Ko'rib chiqish" },
    { id: "c-success",        label: "Muvaffaqiyat" },
    { id: "c-orders",         label: "Buyurtmalar ro'yxati" },
    { id: "c-order-nobids",   label: "Taklif yo'q" },
    { id: "c-order-bids",     label: "Takliflar bor" },
    { id: "c-order-selected", label: "Haydovchi tanlangan" },
    { id: "c-confirm",        label: "Tasdiqlash" },
    { id: "c-rating",         label: "Baholash" },
    { id: "c-notifications",  label: "Bildirishnomalar" },
    { id: "c-profile",        label: "Profil" },
  ]},
  { title: "HAYDOVCHI", screens: [
    { id: "d-home",         label: "Bosh sahifa" },
    { id: "d-profile-form", label: "Profil to'ldirish" },
    { id: "d-documents",    label: "Hujjatlar" },
    { id: "d-routes",       label: "Yo'nalishlar" },
    { id: "d-add-route",    label: "Yo'nalish qo'shish" },
    { id: "d-feed",         label: "Buyurtmalar tasmasi" },
    { id: "d-bid",          label: "Taklif yuborish" },
    { id: "d-orders",       label: "Buyurtmalar" },
    { id: "d-order-detail", label: "Buyurtma tafsilotlari" },
    { id: "d-profile",      label: "Profil" },
  ]},
] as const;

function Sidebar({ current, onNavigate }: { current: Screen; onNavigate: Go }) {
  return (
    <div
      className="flex-shrink-0 overflow-y-auto"
      style={{ width: 220, background: "#161E2D", height: "100%" }}
    >
      <div className="px-4 py-5" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
        <div className="flex items-center gap-2.5 mb-1">
          <div className="w-7 h-7 rounded-[8px] flex items-center justify-center" style={{ background: "#1B4FD8" }}>
            <Truck size={14} color="#fff" />
          </div>
          <span className="font-bold text-[15px]" style={{ color: "#fff" }}>Elchi</span>
        </div>
        <p className="text-[10px]" style={{ color: "rgba(255,255,255,0.35)" }}>UI Prototype · 29 screens</p>
      </div>
      {GROUPS.map(group => (
        <div key={group.title} className="py-3">
          <p
            className="px-4 text-[9px] font-bold tracking-widest mb-1"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >{group.title}</p>
          {group.screens.map(s => {
            const active = current === s.id;
            return (
              <button
                key={s.id}
                onClick={() => onNavigate(s.id as Screen)}
                className="w-full text-left px-4 py-2 text-[12px]"
                style={{
                  color: active ? "#fff" : "rgba(255,255,255,0.5)",
                  background: active ? "rgba(27,79,216,0.3)" : "transparent",
                  borderLeft: `2px solid ${active ? "#1B4FD8" : "transparent"}`,
                }}
              >{s.label}</button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────

function PrototypeApp() {
  const [screen, setScreen] = useState<Screen>("splash");
  const [role, setRole] = useState<Role>(null);

  const navigate: Go = s => setScreen(s);

  const splashBg = screen === "splash";
  const statusBg = splashBg ? "#1B4FD8" : "#fff";
  const statusTextColor = splashBg ? "#fff" : "#111827";
  const indicatorBg = splashBg ? "#1B4FD8" : "#fff";

  return (
    <div
      className="prototype-root flex h-screen overflow-hidden"
      style={{ background: "#0B1120", fontFamily: "'Inter', -apple-system, sans-serif" }}
    >
      <div className="prototype-sidebar">
        <Sidebar current={screen} onNavigate={navigate} />
      </div>

      {/* Canvas */}
      <div className="prototype-canvas flex-1 flex items-center justify-center overflow-hidden">
        {/* Phone shell */}
        <div
          className="prototype-phone-shell relative flex-shrink-0"
          style={{
            width: 390, height: 844,
            borderRadius: 44,
            border: "7px solid #2C3347",
            boxShadow: "0 0 0 1px #3D4560, 0 40px 100px rgba(0,0,0,0.8), inset 0 0 0 1px rgba(255,255,255,0.06)",
            overflow: "hidden",
            background: "#F7F8FA",
          }}
        >
          {/* Status bar */}
          <div
            className="flex items-center justify-between"
            style={{ height: 44, background: statusBg, paddingInline: 24, flexShrink: 0 }}
          >
            <span className="text-[13px] font-semibold" style={{ color: statusTextColor }}>9:41</span>
            <div className="flex items-center gap-1.5">
              <div className="flex items-end gap-[2px]">
                {[3,5,7,9].map((h,i) => (
                  <div key={i} className="w-[3px] rounded-sm" style={{ height: h, background: statusTextColor, opacity: i < 3 ? 1 : 0.35 }} />
                ))}
              </div>
              <div
                className="relative flex items-center"
                style={{ width: 18, height: 11, borderRadius: 3, border: `1.5px solid ${statusTextColor}` }}
              >
                <div className="absolute -right-[3px] top-[2.5px] w-[2px] h-[5px] rounded-r-sm" style={{ background: statusTextColor }} />
                <div className="ml-[2px] rounded-sm" style={{ width: "70%", height: "60%", background: statusTextColor }} />
              </div>
            </div>
          </div>

          {/* Screen content area */}
          <div className="flex flex-col overflow-hidden" style={{ height: 844 - 44 - 34 }}>
            <ScreenRouter screen={screen} navigate={navigate} role={role} setRole={setRole} />
          </div>

          {/* Home indicator */}
          <div
            className="flex items-center justify-center"
            style={{ height: 34, background: indicatorBg }}
          >
            <div
              className="rounded-full"
              style={{ width: 130, height: 5, background: splashBg ? "rgba(255,255,255,0.3)" : "#D1D5DB" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default ConnectedApp;
