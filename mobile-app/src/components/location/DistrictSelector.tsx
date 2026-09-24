import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, MapPin, Search } from "../../app/ui/icons";

import { getDistricts } from "../../api/districts.api";
import { translate } from "../../i18n";
import type { City, District } from "../../types/city";

type DistrictSelectorProps = {
  mode: "pickup" | "dropoff";
  city: City;
  onSelectDistrict: (district: District) => void;
  onBack: () => void;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function districtMatches(district: District, query: string) {
  const term = normalize(query);
  if (!term) return true;
  return [district.name_uz, district.name_ru].some((value) => normalize(String(value ?? "")).includes(term));
}

export function DistrictSelector({ city, onSelectDistrict, onBack }: DistrictSelectorProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [districts, setDistricts] = useState<District[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    let isActive = true;
    setIsLoading(true);
    setError("");
    getDistricts(city.id, { search: debouncedQuery.trim() || undefined, limit: 100 })
      .then((items) => {
        if (isActive) setDistricts(items);
      })
      .catch(() => {
        if (isActive) setError(translate("location.districtsLoadFailed"));
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });
    return () => {
      isActive = false;
    };
  }, [city.id, debouncedQuery]);

  const visibleDistricts = useMemo(() => districts.filter((district) => districtMatches(district, query)), [districts, query]);

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
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-foreground">{translate("location.pickDistrict")}</h1>
      </header>
      <section className="border-b border-border px-5 py-4">
        <p className="mb-2 truncate text-[13px] font-semibold text-muted-foreground">{city.name_uz}</p>
        <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-feruza bg-card px-4">
          <Search size={19} color="var(--muted-foreground)" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={translate("location.searchDistrict")}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-foreground outline-none"
          />
        </label>
        <p className="mt-2 text-[12px] leading-5 text-muted-foreground">{translate("location.thenMarkOnMap")}</p>
      </section>
      <section className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">{translate("location.districtsLoading")}</div>
        ) : error ? (
          <div className="px-5 py-8 text-center text-[14px] text-destructive">{error}</div>
        ) : visibleDistricts.length ? (
          visibleDistricts.map((district) => (
            <button
              key={district.id}
              type="button"
              onClick={() => onSelectDistrict(district)}
              className="flex min-h-[70px] w-full items-center gap-3 border-b border-border px-5 text-left last:border-b-0"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent text-primary">
                <MapPin size={19} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[16px] font-semibold text-foreground">{district.name_uz}</span>
                <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">{city.name_uz}</span>
              </span>
              <ChevronRight size={19} color="color-mix(in srgb, var(--foreground) 42%, var(--background))" />
            </button>
          ))
        ) : (
          <div className="px-5 py-8 text-center text-[14px] text-muted-foreground">{translate("location.districtNotFound")}</div>
        )}
      </section>
    </main>
  );
}
