/**
 * Q140 (ADR-0026): the sender picks a parcel size category instead of typing length, width, height and weight.
 * The rows come from the server catalog (GET /parcel-categories) - the same data the driver sees and the capacity
 * check uses. With no confirmed catalog nothing can be picked, and the screen says why.
 */
import { useEffect, useState } from "react";

import { parcelCategories, type ParcelCategoryCatalogDTO, type ParcelCategoryDTO } from "../../api/v2/marketplace.api";
import { translate } from "../../i18n";
import { cls } from "../ui/mobile";

const ICONS: Record<string, string> = {
  envelope: "✉️",
  box_small: "📦",
  box_medium: "📦",
  box_large: "🗃️",
  bag: "👜",
};

/** "30×20×20 sm gacha · 5 kg gacha" - the category's limits in the reader's language. */
export function categoryLimitsText(item: Pick<ParcelCategoryDTO, "max_length_cm" | "max_width_cm" | "max_height_cm" | "max_weight_g">): string {
  const kg = Math.round((item.max_weight_g / 1000) * 10) / 10;
  return translate("parcelCategory.limits", {
    length: item.max_length_cm, width: item.max_width_cm, height: item.max_height_cm, weight: kg,
  });
}

export function categoryIcon(iconKey: string): string {
  return ICONS[iconKey] ?? "📦";
}

export function ParcelCategoryPicker(props: { value: string; onChange: (item: ParcelCategoryDTO) => void }) {
  const [catalog, setCatalog] = useState<ParcelCategoryCatalogDTO | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    parcelCategories()
      .then((value) => alive && setCatalog(value))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed) return <p className="text-[13px] text-destructive">{translate("parcelCategory.loadFailed")}</p>;
  if (!catalog) return <p className="text-[13px] text-muted-foreground" aria-busy="true">{translate("parcelCategory.loading")}</p>;
  if (!catalog.confirmed || !(catalog.items ?? []).length) {
    return <p className="rounded-[12px] bg-warning/14 px-3 py-2.5 text-[12px] leading-5 text-warning">{translate("parcelCategory.unconfirmed")}</p>;
  }
  return (
    <div className="flex flex-col gap-2" role="radiogroup" aria-label={translate("parcelCategory.label")}>
      <span className="text-[14px] font-medium text-secondary-foreground">{translate("parcelCategory.label")}</span>
      {(catalog.items ?? []).map((item) => {
        const selected = props.value === item.id;
        return (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => props.onChange(item)}
            className={cls(
              "el-press flex items-center gap-3 rounded-[14px] border p-3 text-left",
              selected ? "border-primary bg-accent" : "border-border bg-card",
            )}
          >
            <span className="text-[26px]" aria-hidden="true">{categoryIcon(item.icon_key)}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-semibold text-foreground">{item.name_uz}</span>
              <span className="block text-[12px] text-muted-foreground">{categoryLimitsText(item)}</span>
            </span>
          </button>
        );
      })}
      <p className="text-[12px] leading-5 text-muted-foreground">{translate("parcelCategory.hint")}</p>
      {catalog.synthetic && <p className="text-[11px] text-warning">{translate("parcelCategory.synthetic")}</p>}
    </div>
  );
}

/** The agreed category as a compact line (driver feed, bid screen, booking detail). */
export function ParcelCategoryLine({ category }: { category: ParcelCategoryDTO | null | undefined }) {
  if (!category) return null;
  return (
    <p className="text-[12px] text-muted-foreground" data-testid="parcel-category-line">
      {categoryIcon(category.icon_key)} {category.name_uz} · {categoryLimitsText(category)}
    </p>
  );
}
