/**
 * The client's navigation drawer.
 *
 * It replaces the bottom tab bar. The home screen is a full-bleed map with a sheet over it, and a permanent
 * 72px tab bar was taking a fifth of the remaining height from the part people actually read - the direction
 * rows and the price. A drawer costs one tap and gives the sheet the room back.
 *
 * "Haydovchi e'lonlari" lives here too, as its own destination rather than a second button under the primary
 * one. Q92: ELCHI is a market in both directions - publishing your own request and answering a driver who
 * published theirs are two ways in, not a main action and a footnote.
 */
import { useEffect, type ComponentType } from "react";

import { Bell, Home, LogOut, Package, Truck, User, X } from "../../app/ui/icons";
import { cls } from "../../app/ui/mobile";
import { translate } from "../../i18n";

export type SidebarItem = {
  id: string;
  label: string;
  description?: string;
  icon: ComponentType<{ size?: number; color?: string }>;
  /** Shown as a dot on the row - the in-app inbox is the only delivery channel there is (Q82). */
  badge?: number;
};

export function clientSidebarItems(unread: number): SidebarItem[] {
  return [
    { id: "client-home", label: translate("nav.home"), description: translate("nav.homeHint"), icon: Home },
    // Q138 (ADR-0026): no driver listings to browse - clients publish requests and compare the offers they get.
    { id: "client-orders", label: translate("nav.orders"), description: translate("nav.ordersHint"), icon: Package },
    { id: "client-notifications", label: translate("nav.messages"), description: translate("nav.messagesHint"), icon: Bell, badge: unread },
    { id: "client-profile", label: translate("nav.profile"), description: translate("nav.profileHint"), icon: User },
  ];
}

export function AppSidebar({
  open,
  active,
  items,
  title = "ELCHI",
  subtitle,
  onSelect,
  onClose,
  onLogout,
}: {
  open: boolean;
  active: string;
  items: SidebarItem[];
  title?: string;
  subtitle?: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  onLogout?: () => void;
}) {
  // Escape closes it, because on a desktop browser (where this app is developed and demoed) that is the
  // gesture people reach for before they look for the X.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div className={cls("absolute inset-0 z-40", open ? "" : "pointer-events-none")} aria-hidden={!open}>
      <button
        type="button"
        tabIndex={open ? 0 : -1}
        aria-label={translate("nav.closeMenu")}
        onClick={onClose}
        className={cls(
          "absolute inset-0 bg-slate-900/45 transition-opacity duration-200",
          open ? "opacity-100" : "opacity-0",
        )}
      />
      <aside
        className={cls(
          "absolute inset-y-0 left-0 flex w-[280px] max-w-[82%] flex-col bg-card shadow-2xl transition-transform duration-200",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <p className="truncate text-[18px] font-bold text-foreground">{title}</p>
            {subtitle && <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{subtitle}</p>}
          </div>
          <button
            type="button"
            tabIndex={open ? 0 : -1}
            onClick={onClose}
            aria-label={translate("common.close")}
            className="el-press flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted"
          >
            <X size={17} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {items.map((item) => {
            const isActive = item.id === active;
            return (
              <button
                key={item.id}
                type="button"
                tabIndex={open ? 0 : -1}
                onClick={() => onSelect(item.id)}
                className={cls(
                  "el-press mb-1 flex w-full items-center gap-3 rounded-[14px] px-3 py-3 text-left",
                  isActive ? "bg-accent" : "bg-transparent",
                )}
              >
                <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-muted">
                  <item.icon size={18} color={isActive ? "var(--primary)" : "var(--muted-foreground)"} />
                  {Boolean(item.badge) && (
                    <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-card bg-destructive" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cls("block truncate text-[15px] font-semibold", isActive ? "text-primary" : "text-foreground")}>
                    {item.label}
                  </span>
                  {item.description && (
                    <span className="block truncate text-[12px] text-muted-foreground">{item.description}</span>
                  )}
                </span>
              </button>
            );
          })}
        </nav>

        {onLogout && (
          <div className="border-t border-border p-3">
            <button
              type="button"
              tabIndex={open ? 0 : -1}
              onClick={onLogout}
              className="el-press flex w-full items-center gap-3 rounded-[14px] px-3 py-3 text-left"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px] bg-destructive/10">
                <LogOut size={18} color="var(--destructive)" />
              </span>
              <span className="text-[15px] font-semibold text-destructive">{translate("nav.logout")}</span>
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}

/** The trigger. Placed wherever a client screen used to rely on the tab bar to get anywhere else. */
export function SidebarButton({ onClick, className }: { onClick: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={translate("nav.menu")}
      className={cls("el-press flex h-11 w-11 items-center justify-center rounded-full bg-card shadow-lg", className)}
    >
      <span className="flex h-[15px] w-[18px] flex-col justify-between">
        <span className="h-[2px] w-full rounded-full bg-foreground" />
        <span className="h-[2px] w-full rounded-full bg-foreground" />
        <span className="h-[2px] w-full rounded-full bg-foreground" />
      </span>
    </button>
  );
}
