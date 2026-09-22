import { listCorridorStops, listCorridors, listDistricts } from "../../api/v2/marketplace.api";
import type { StopDTO } from "../../api/v2/marketplace.api";

export type StopOption = { stop: StopDTO; corridorId: string };

/**
 * The verified stops inside a district, if there are any.
 *
 * A stop is a meeting place an operator checked and a confirmed route passes, and choosing one is what earns
 * a listing an `exact` match (Q88). It is an **option**, not a step: six of the country's districts have a
 * stop, so a flow that asked for one first blocked everybody else. The map asks for a place, and offers these
 * alongside when they exist.
 *
 * `corridorId` narrows the search when the other end of the direction is already fixed - a listing is agreed
 * on one corridor, so a stop from another road could never serve it.
 */
export async function loadStopOptions(scope: {
  districtId?: string | null;
  regionId?: string | null;
  corridorId?: string | null;
}): Promise<StopOption[]> {
  const allowed = scope.districtId
    ? new Set([scope.districtId])
    : scope.regionId
      ? new Set((await listDistricts({ region_id: scope.regionId, limit: 500 })).map((item) => item.id))
      : null;
  const found: StopOption[] = [];
  const corridors = (await listCorridors()).filter(
    (corridor) => !scope.corridorId || corridor.id === scope.corridorId,
  );
  for (const corridor of corridors) {
    const stops = await listCorridorStops(corridor.id);
    for (const stop of stops) {
      if (stop.is_active && (!allowed || allowed.has(stop.district.id))) {
        found.push({ stop, corridorId: corridor.id });
      }
    }
  }
  return found;
}
