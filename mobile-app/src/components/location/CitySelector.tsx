import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronRight, MapPin, Search } from "lucide-react";

import { getCities } from "../../api/cities.api";
import type { City } from "../../types/city";

type CitySelectorProps = {
  mode: "pickup" | "dropoff";
  title: string;
  onSelectCity: (city: City) => void;
  onBack: () => void;
};

function normalize(value: string) {
  return value.trim().toLowerCase();
}

function cityMatches(city: City, query: string) {
  const term = normalize(query);
  if (!term) return true;
  return [city.name_uz, city.name_ru, city.region].some((value) => normalize(String(value ?? "")).includes(term));
}

export function CitySelector({ title, onSelectCity, onBack }: CitySelectorProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [cities, setCities] = useState<City[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    let isActive = true;
    setIsLoading(true);
    setError("");
    getCities({ search: debouncedQuery.trim() || undefined, limit: 100 })
      .then((items) => {
        if (isActive) setCities(items);
      })
      .catch(() => {
        if (isActive) setError("Shaharlarni yuklab bo'lmadi");
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });
    return () => {
      isActive = false;
    };
  }, [debouncedQuery]);

  const visibleCities = useMemo(() => cities.filter((city) => cityMatches(city, query)), [cities, query]);

  return (
    <main className="flex min-h-0 flex-1 flex-col bg-white">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[#E5E7EB] px-5">
        <button type="button" onClick={onBack} className="flex h-10 w-10 items-center justify-center rounded-full bg-[#F3F4F6]">
          <ArrowLeft size={18} />
        </button>
        <h1 className="min-w-0 flex-1 truncate text-[17px] font-bold text-[#111827]">{title}</h1>
        <button
          type="button"
          onClick={() => {
            setNotice("Avval shaharni tanlang");
            window.setTimeout(() => setNotice(""), 2200);
          }}
          className="rounded-full bg-[#EEF2FF] px-4 py-2 text-[14px] font-semibold text-[#1B4FD8]"
        >
          Xarita
        </button>
      </header>
      <section className="border-b border-[#E5E7EB] px-5 py-4">
        <label className="flex h-12 items-center gap-3 rounded-[16px] border-2 border-[#38BDF8] bg-white px-4">
          <Search size={19} color="#6B7280" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Qidirish"
            className="min-w-0 flex-1 bg-transparent text-[15px] text-[#111827] outline-none"
          />
        </label>
        <p className="mt-2 text-[12px] leading-5 text-[#6B7280]">
          Avval shaharni tanlang, keyin xaritada aniq manzilni belgilang.
        </p>
        {notice && <p className="mt-2 text-[12px] font-semibold text-[#DC2626]">{notice}</p>}
      </section>
      <section className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="px-5 py-8 text-center text-[14px] text-[#6B7280]">Shaharlar yuklanmoqda...</div>
        ) : error ? (
          <div className="px-5 py-8 text-center text-[14px] text-[#DC2626]">{error}</div>
        ) : visibleCities.length ? (
          visibleCities.map((city) => (
            <button
              key={city.id}
              type="button"
              onClick={() => onSelectCity(city)}
              className="flex min-h-[74px] w-full items-center gap-3 border-b border-[#E5E7EB] px-5 text-left last:border-b-0"
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F3F4F6] text-[#6B7280]">
                <MapPin size={20} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[16px] font-semibold text-[#111827]">{city.name_uz}</span>
                <span className="mt-0.5 block truncate text-[13px] text-[#6B7280]">{city.region || city.name_ru || "-"}</span>
              </span>
              <ChevronRight size={19} color="#9CA3AF" />
            </button>
          ))
        ) : (
          <div className="px-5 py-8 text-center text-[14px] text-[#6B7280]">Shahar topilmadi</div>
        )}
      </section>
    </main>
  );
}
