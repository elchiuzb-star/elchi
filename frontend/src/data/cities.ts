import { useEffect, useState } from "react";
import { getCities } from "../api/cities.api";
import { getDistricts } from "../api/districts.api";
import type { City, District } from "../types/city";

export type UiCity = {
  id: number;
  uz: string;
  ru: string;
  en: string;
  dist: boolean;
  raw: City;
};

function toUiCity(c: City): UiCity {
  return {
    id: c.id,
    uz: c.name_uz,
    ru: c.name_ru || c.name_uz,
    en: c.name_ru || c.name_uz,
    dist: Boolean(c.requires_district),
    raw: c,
  };
}

let cache: UiCity[] | null = null;

export function useCities() {
  const [cities, setCities] = useState<UiCity[]>(cache ?? []);
  const [loading, setLoading] = useState(!cache);

  useEffect(() => {
    if (cache) return;
    let active = true;
    getCities({ limit: 100 })
      .then((list) => {
        const mapped = list.map(toUiCity);
        cache = mapped;
        if (active) setCities(mapped);
      })
      .catch(() => { if (active) setCities([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return { cities, loading };
}

const districtCache = new Map<number, District[]>();

export function useDistricts(cityId: number | null | undefined) {
  const [districts, setDistricts] = useState<District[]>(cityId ? districtCache.get(cityId) ?? [] : []);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!cityId) { setDistricts([]); return; }
    if (districtCache.has(cityId)) { setDistricts(districtCache.get(cityId)!); return; }
    let active = true;
    setLoading(true);
    getDistricts(cityId, { limit: 100 })
      .then((list) => { districtCache.set(cityId, list); if (active) setDistricts(list); })
      .catch(() => { if (active) setDistricts([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [cityId]);

  return { districts, loading };
}
