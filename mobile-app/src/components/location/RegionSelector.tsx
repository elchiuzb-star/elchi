import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, MapPin, Search } from "../../app/ui/icons";

import { listRegions } from "../../api/v2/marketplace.api";
import { translate } from "../../i18n";
import type { RegionDTO } from "../../api/v2/marketplace.api";

/**
 * "Qayerdan? / Qayerga?" - the first step of a direction, on the stage-2 catalogue.
 *
 * Same screen as `CitySelector` in every visible way; only the list behind it changed, from the v1 `cities`
 * table to the stage-2 regions. `requires_district` comes from the server, so the flow knows without a
 * hard-coded name that Tashkent city has no district step.
 */
type RegionSelectorProps = {
  title: string;
  onSelectRegion: (region: RegionDTO) => void;
  onBack: () => void;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
}

export function RegionSelector({ title, onSelectRegion, onBack }: RegionSelectorProps) {
  const [query, setQuery] = useState("");
  const [regions, setRegions] = useState<RegionDTO[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;
    setIsLoading(true);
    setError("");
    listRegions()
      .then((items) => {
        if (isActive) setRegions(items);
      })
      .catch(() => {
        if (isActive) setError(translate("location.regionsLoadFailed"));
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });
    return () => {
      isActive = false;
    };
  }, []);

  const visible = useMemo(
    () => regions.filter((region) => !query.trim() || normalize(region.name_uz).includes(normalize(query))),
    [regions, query],
  );

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-card">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
        <button
          type="button"
          onClick={onBack}
          aria-label={translate("common.back")}
          className="el-press flex h-10 w-10 items-center justify-center rounded-full bg-muted"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-foreground">{title}</h1>
      </header>
      <section className="border-b border-border px-5 py-4">
        <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-feruza bg-card px-4">
          <Search size={19} color="var(--muted-foreground)" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={translate("location.search")}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none"
          />
        </label>
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">
          {translate("location.pickRegionThenDistrict")}
        </p>
      </section>
      <section className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">{translate("location.regionsLoading")}</div>
        ) : error ? (
          <div className="px-5 py-8 text-center text-[14px] text-destructive">{error}</div>
        ) : visible.length ? (
          visible.map((region) => (
            <button
              key={region.id}
              type="button"
              onClick={() => onSelectRegion(region)}
              className="flex min-h-[74px] w-full items-center gap-3 border-b border-border px-5 text-left last:border-b-0"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <MapPin size={20} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[16px] font-semibold text-foreground">{region.name_uz}</span>
                <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">
                  {region.requires_district ? translate("location.districtRequired") : translate("location.noDistrict")}
                </span>
              </span>
              <ChevronRight size={19} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
            </button>
          ))
        ) : (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">{translate("location.regionNotFound")}</div>
        )}
      </section>
    </main>
  );
}
