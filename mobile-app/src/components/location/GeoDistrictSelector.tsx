import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, Search } from "../../app/ui/icons";

import { listDistricts } from "../../api/v2/marketplace.api";
import type { DistrictDTO, RegionDTO } from "../../api/v2/marketplace.api";

/**
 * "Tumanni tanlang" on the stage-2 catalogue - the same screen as `DistrictSelector`, one list further.
 *
 * Every row is just a district. It used to carry a count of verified stops underneath, and "Bekat yo'q" under
 * most of them, which was both discouraging and - since Q88 - untrue: the next screen is a map, the place is
 * marked on it, and a district without a catalogued stop serves a booking exactly as well as one with. Only
 * six of the country's districts have a stop at all, so that line told almost everybody their district was
 * unusable.
 */
type GeoDistrictSelectorProps = {
  region: Pick<RegionDTO, "id" | "name_uz">;
  onSelectDistrict: (district: DistrictDTO) => void;
  onBack: () => void;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
}

export function GeoDistrictSelector({ region, onSelectDistrict, onBack }: GeoDistrictSelectorProps) {
  const [query, setQuery] = useState("");
  const [districts, setDistricts] = useState<DistrictDTO[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    setIsLoading(true);
    setError("");
    listDistricts({ region_id: region.id, limit: 500 })
      .then((items) => {
        if (isActive) setDistricts(items);
      })
      .catch(() => {
        if (isActive) setError("Tumanlarni yuklab bo'lmadi");
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });
    return () => {
      isActive = false;
    };
  }, [region.id]);

  const visible = useMemo(
    () => districts.filter((district) => !query.trim() || normalize(district.name_uz).includes(normalize(query))),
    [districts, query],
  );

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-card">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
        <button
          type="button"
          onClick={onBack}
          aria-label="Orqaga"
          className="el-press flex h-10 w-10 items-center justify-center rounded-full bg-muted"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-foreground">Tumanni tanlang</h1>
      </header>
      <section className="border-b border-border px-5 py-4">
        <p className="mb-2 truncate text-[13px] font-semibold text-muted-foreground">{region.name_uz}</p>
        <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-feruza bg-card px-4">
          <Search size={19} color="var(--muted-foreground)" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Qidirish"
            className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none"
          />
        </label>
      </section>
      <section className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">Tumanlar yuklanmoqda...</div>
        ) : error ? (
          <div className="px-5 py-8 text-center text-[14px] text-destructive">{error}</div>
        ) : visible.length ? (
          visible.map((district) => (
            <button
              key={district.id}
              type="button"
              onClick={() => onSelectDistrict(district)}
              className="el-press flex min-h-[58px] w-full items-center gap-3 border-b border-border px-5 text-left last:border-b-0"
            >
              <span className="min-w-0 flex-1 truncate text-[16px] font-medium text-foreground">{district.name_uz}</span>
              <ChevronRight size={19} className="shrink-0 text-muted-foreground" />
            </button>
          ))
        ) : (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">Tuman topilmadi</div>
        )}
      </section>
    </main>
  );
}
