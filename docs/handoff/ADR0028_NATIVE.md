# ADR-0028 (Q159) — Android/iOS ilovalar uchun handoff: A→B pozitsiyalari, bekatsiz model

**Kimga:** native (Android/iOS) dasturchisi. Agentlar `android-app/` va native generator fayllarini o'zgartirmaydi
(Q156); `scripts/gen_native_api.py --check` OpenAPI o'zgargani uchun «stale» deydi — qayta generatsiya sizda.

## 4-bosqich (Q160, 07.10.2026): bekat id endi **rad etiladi**
Foydalanuvchi qarori: ELCHI'da «bekat» tushunchasi yo'q. Server bekat id li so'rovni qabul qilmaydi va bekat
maydonlarini qaytarmaydi. Ilova yangilanmaguncha **e'lon, taklif va safar yaratish ishlamaydi** (ma'lum oqibat).

- `POST /listings`: `origin_stop_id`/`destination_stop_id` → `400 VALIDATION_ERROR`; `origin_point`/`destination_point`
  majburiy (`{lat, lng, district_id, address?}`).
- `POST /proposals...`, counter, amendment: `pickup_stop_id`/`dropoff_stop_id` → `400`; yubormang (joylar e'londan).
- `POST /trips`, `PATCH /trips/{id}`: `stops` → `400`; `route_version_id` + ixtiyoriy `route_start_m`/`route_end_m`.
- `POST /routes/preview`: `stop_ids` → `400`; `corridor_id` + `origin` + `destination`.
- `GET /feed`: `origin_stop_id`/`destination_stop_id` → `400 reason: stops_retired`; tuman yoki hudud id yuboring.
- Olib tashlangan endpointlar: `GET /corridors/{id}/stops`, `GET /stops/search`, `/admin/corridors/{id}/stops`,
  `/admin/stops/{id}`.
- Javoblarda yo'q: `*_stop`, `TripDTO.stops`, `RouteVersionDTO.stops`, `stops_count`, `occurrence_seq`,
  `segments`. Yangi: `BookingEndDTO {point, planned_arrival_at, ...}`, manifest `places[]`, mavjudlik `stretches[]`,
  ochiq sahifa `origin_name`/`destination_name`, sig'im xatosi `positions[]`.
- Tezkor javob kodlari `at_stop`/`clarify_stop` o'zgarmaydi.

## Ilovada qilish kerak
1. OpenAPI dan turlarni qayta generatsiya qiling (bekat turlari yo'q; `BookingEndDTO`, `ManifestPlaceDTO`,
   `StretchAvailabilityDTO`; `TripCreate.route_start_m/route_end_m`; `RoutePreviewRequest.corridor_id/origin/destination`).
2. Bron va safarni joy (manzil yoki tuman) va vaqt bilan ko'rsating — bekat nomi yo'q.
3. E'lonni bekat id bilan emas, xaritadagi nuqta (`*_point`) bilan yuboring.
4. Taklifda bekat id yubormang — e'lon joylari meros qoladi.
5. Real qurilmadagi sinovlar (spec §10.5) — sizning doirangiz; bu hujjat ularni «o'tdi» demaydi.
