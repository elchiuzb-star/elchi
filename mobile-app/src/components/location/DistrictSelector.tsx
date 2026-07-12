import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, MapPin, Search } from "lucide-react";

import { getDistricts } from "../../api/districts.api";
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
        if (isActive) setError("Tumanlarni yuklab bo'lmadi");
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
    <main className="flex min-h-0 flex-1 flex-col bg-white">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#E5E7EB] px-5">
        <button type="button" onClick={onBack} className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F3F4F6]">
          <ArrowLeft size={18} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-[#111827]">Tumanni tanlang</h1>
      </header>
      <section className="border-b border-[#E5E7EB] px-5 py-4">
        <p className="mb-2 truncate text-[13px] font-semibold text-[#6B7280]">{city.name_uz}</p>
        <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-[#38BDF8] bg-white px-4">
          <Search size={19} color="#6B7280" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Tuman qidirish"
            className="min-w-0 flex-1 bg-transparent text-[15px] text-[#111827] outline-none"
          />
        </label>
        <p className="mt-2 text-[12px] leading-5 text-[#6B7280]">Keyin xaritada aniq manzilni belgilang.</p>
      </section>
      <section className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="px-5 py-8 text-center text-[14px] text-[#6B7280]">Tumanlar yuklanmoqda...</div>
        ) : error ? (
          <div className="px-5 py-8 text-center text-[14px] text-[#DC2626]">{error}</div>
        ) : visibleDistricts.length ? (
          visibleDistricts.map((district) => (
            <button
              key={district.id}
              type="button"
              onClick={() => onSelectDistrict(district)}
              className="flex min-h-[70px] w-full items-center gap-3 border-b border-[#E5E7EB] px-5 text-left last:border-b-0"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#EEF2FF] text-[#1B4FD8]">
                <MapPin size={19} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[16px] font-semibold text-[#111827]">{district.name_uz}</span>
                <span className="mt-0.5 block truncate text-[13px] text-[#6B7280]">{city.name_uz}</span>
              </span>
              <ChevronRight size={19} color="#9CA3AF" />
            </button>
          ))
        ) : (
          <div className="px-5 py-8 text-center text-[14px] text-[#6B7280]">Tuman topilmadi</div>
        )}
      </section>
    </main>
  );
}
