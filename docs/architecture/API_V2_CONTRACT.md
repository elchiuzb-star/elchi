# API_V2_CONTRACT — `/api/v2` kontrakti

**Muallif:** A0a • **Sana:** 13.09.2026 (wave 1: Q12–Q19, N1–N5 bilan) • **Holat:** Accepted (ADR’lar Q19)
**Konvensiyalar:** [ADR-0005](adr/0005-api-v2-conventions.md) • ID: [ADR-0002](adr/0002-public-identifiers.md) • Pul: [ADR-0003](adr/0003-money-minor-units-bps.md) • Vaqt: [ADR-0004](adr/0004-time-utc-offsets.md) • Lock: [ADR-0017](adr/0017-global-lock-order.md) • Sirlar: [ADR-0018](adr/0018-derived-keys-proof-codes-tokens.md)
**Kod:** `app/contracts/{dto,errors,enums,ids,idempotency,cursor,crypto,tracking}.py`

## 0. Umumiy
- Barcha yo‘llar `/api/v2` bilan (jadvalda qisqartirilgan). Auth: `Authorization: Bearer <v1 access token>` (ADR-0007), aks holda **Public**.
- Javob: `Envelope[DTO]`; ro‘yxatlar + `meta.next_cursor`. Xato: `ErrorEnvelope`.
- Umumiy xatolar (takrorlanmaydi): `VALIDATION_ERROR` 400, `UNAUTHORIZED` 401, `RATE_LIMITED` 429, `SERVER_ERROR` 500; ko‘rinmas/topilmagan obyekt `NOT_FOUND` 404.
- **Idem** `Y` — `Idempotency-Key` majburiy; domen 4xx ham replay qilinadi (savepoint naqshi, ADR-0005). **Ver** — body’da `expected_version` (yoki ko‘rsatilgan maydon).
- ID — prefiksli opaque. Pul — `*_minor` integer + `currency`. Vaqt — kirishda offset, chiqishda `Z`. O‘lchov — `*_g`, `*_ml`, `*_cm`, `*_m` integer.
- Capability — `Capability` enum; staff capability’lari `STAFF_ROLE_CAPABILITIES`. Eligibility bloki faqat `NEW_BUSINESS_CAPABILITIES`ni oladi (D16).

---

## 1. Identity (egasi A1; I4 — A12)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| I1 | `GET /me` | Auth | — | `MeDTO` | — | — | — | — |
| I2 | `GET /me/capabilities` | Auth | — | `CapabilitiesDTO` | — | — | — | AC41 |
| I3 | `POST /me/roles` | Marketplace akkaunt | `RoleActivateRequest` | `CapabilitiesDTO` | Y | — | `ROLE_COMBINATION_FORBIDDEN` (staff akkaunt, Q3) | §16 |
| I4 | `DELETE /me` (A12) | Auth | `AccountDeletionRequest` | `AccountDeletionDTO` | Y | — | `ACCOUNT_DELETION_BLOCKED` | §17.8 |
| I5 | `POST /admin/drivers/{user_id}/eligibility` | `ops.driver_eligibility_manage` (admin+) | `DriverEligibilityCommand` | `DriverEligibilityDTO` | Y | Y | `VERSION_CONFLICT`, `NOT_FOUND` | AC41, D16 |

DTO:
- `MeDTO`: `id (usr_)`, `phone`, `full_name`, `primary_role`, `roles[]`, `status`, `created_at`.
- `CapabilitiesDTO`: `roles[]`, `capabilities[]`, `driver_eligibility {verification_status, eligible, reasons[], has_active_obligations}`.
- `RoleActivateRequest`: `role: client|driver`.
- `AccountDeletionRequest`: `reason?`. `AccountDeletionDTO`: `status: deleted|scheduled`; blok `details {active_bookings, open_disputes, wallet_posted_minor, active_holds_minor}` (v1 `DELETE /auth/me` ham shu v2 servis tekshiruvlarini read-only chaqiradi, ADR-0006; N4: `wallet.service.blocking_state_for_user` — A3 wave 1, booking ekvivalenti — A4 wave 2; ulash H1/integrator funksiyalar paydo bo‘lishi bilan).
- `DriverEligibilityCommand`: `expected_version`, `action: block|unblock`, `reason`. Faqat yangi bron/listing/trip to‘xtaydi; faol trip’lar davom etadi. `users.status` o‘zgarmaydi (account suspension alohida).
- `DriverEligibilityDTO`: `user_id`, `eligible`, `blocked_reason?`, `active_trip_ids[]`, `version`.

## 2. Geo, koridor, bekat, marshrut (egasi A2)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| G1 | `GET /regions` | Public | — | `list[RegionDTO]` | — | — | — | — |
| G2 | `GET /corridors` | Public | `?service_type` | `list[CorridorDTO]` | — | — | — | §6.2 |
| G3 | `GET /corridors/{corridor_id}/stops` | Public | — | `list[StopDTO]` | — | — | — | §6.2 |
| G4 | `GET /stops/search` | Public | `?q&region_id&limit` | `list[StopDTO]` | — | — | `RATE_LIMITED` | §6.6 |
| G5 | `POST /routes/preview` | `trip.create` | `RoutePreviewRequest` | `RouteVersionDTO` (`draft`) | Y | — | `ROUTING_UNAVAILABLE`, `CORRIDOR_NOT_ACTIVE` | AC35 |
| G6 | `POST /routes/{route_version_id}/confirm` | `trip.create` | `{}` | `RouteVersionDTO` (`confirmed`) | Y | — | `INVALID_STATE_TRANSITION` | §6.2 |
| G7 | `GET /admin/corridors` | `ops.view` | cursor | `list[CorridorAdminDTO]` | — | — | — | — |
| G8 | `POST /admin/corridors` | `ops.corridor_manage` | `CorridorCreate` | `CorridorAdminDTO` | Y | — | `VALIDATION_ERROR` | §6.2 |
| G9 | `PATCH /admin/corridors/{corridor_id}` | `ops.corridor_manage` | `CorridorPatch` | `CorridorAdminDTO` | — | Y | `VERSION_CONFLICT` | §14, AC38 |
| G10 | `POST /admin/corridors/{corridor_id}/stops` | `ops.corridor_manage` | `StopCreate` | `StopDTO` | Y | — | `VALIDATION_ERROR` | §6.2 |
| G11 | `PATCH /admin/stops/{stop_id}` | `ops.corridor_manage` | `StopPatch` | `StopDTO` | — | Y | `VERSION_CONFLICT` | — |
| G12 | `GET /admin/corridors/{corridor_id}/price-bands` (**wave 1.6**) | `ops.view` | — | `list[PriceBandDTO]` | — | — | `NOT_FOUND` | Q42 |
| G13 | `PUT /admin/corridors/{corridor_id}/price-bands/{service_type}` (**wave 1.6**) | `ops.corridor_manage` — admin+ (**Q52**; operatorga kerak bo‘lsa keyin alohida `ops.price_band_manage`) | `PriceBandUpsert` | `PriceBandDTO` | Y | Y (`expected_version`; yangi band’da yo‘q) | `VALIDATION_ERROR`, `VERSION_CONFLICT`, `NOT_FOUND`, `CAPABILITY_REQUIRED` | Q42 |
| G14 | `GET /admin/corridors/{corridor_id}/price-bands/history` (**wave 1.6**) | `ops.view` | `?cursor&limit` | `list[PriceBandChangeDTO]` | — | — | `INVALID_CURSOR`, `NOT_FOUND` | Q42 |
| G16 | `GET /districts` (**wave 10**) | Public | `?region_id&q&limit` | `list[DistrictDTO]` | — | — | — (noma’lum region → bo‘sh ro‘yxat) | §6.2 |
| G17 | `GET /corridors/{corridor_id}/districts` (**wave 10**) | Public | — | `list[CorridorDistrictDTO]` | — | — | `NOT_FOUND` (ommaviy bo‘lmagan koridor) | §6.1, §6.5 |
| G18 | `GET /corridors/{corridor_id}/routes` (**wave 11**) | Public | `?limit` | `list[RouteVersionDTO]` (faqat `confirmed`, yangisi birinchi) | — | — | `NOT_FOUND` (ommaviy bo‘lmagan koridor) | §6.2, AC35 |
| G15 | `GET /admin/geo/checks/q47` (**wave 1.7**) | `ops.view` | — | `list[Q47ViolationDTO]` (Q47’ni allaqachon buzayotgan koridorlar; `reasons[]`: `needs_two_active_stops`, `stops_missing_meeting_evidence`) | — | — | — | Q47 |

**Wave 11 (QA, 17.09.2026) — G18 marshrut katalogi:** `POST /trips` majburiy `route_version_id` so‘raydi, uni olishning yagona yo‘li `POST /routes/preview` edi — u esa routing provayderini talab qiladi va provayder Q24/Q46 bo‘yicha **ataylab o‘chiq**. Natijada production konfiguratsiyasida haydovchi umuman safar yarata olmasdi (QA topilmasi **F-01**). G18 koridorning **tasdiqlangan** marshrut versiyalarini qaytaradi; ular avval tasdiqlangani uchun provayder kerak emas. Yangi yo‘l chizish uchun G5 o‘zgarishsiz qoladi va provayder yo‘q bo‘lsa `503 ROUTING_UNAVAILABLE` beradi (AC35: soxta moslik yo‘q).

**Wave 10 (A2/A5, 17.09.2026) — tuman yo‘nalish birligi sifatida (foydalanuvchi qarori):**
- `RegionDTO.requires_district` (additiv, standart `true`): klient shu bayroq bo‘yicha tuman qadamini ko‘rsatadi. Toshkent shahri (`UZ-TK`) uchun `false` — u yerda shahar o‘zi birlik. Qoida **ma’lumotda**, kodda joy nomi qattiq yozilmaydi.
- `DistrictDTO {id (dst_), region: RegionRefDTO, name_uz, name_ru, is_active, stops_count}`. `stops_count = 0` — joyni qidiruvda nomlash mumkin, lekin uni **hali tasdiqlangan bekat xizmat qilmaydi**; klient shuni aytadi, olib ketishni va’da qilmaydi.
- `CorridorDistrictDTO {district, sequence, stops_count, on_confirmed_route}`. Tartib — koridorning **tasdiqlangan marshrut versiyalari** bo‘yicha; `on_confirmed_route=false` = tuman koridorda bekatga ega, lekin tasdiqlangan yo‘l u yerdan o‘tishi tekshirilmagan (spec §6.1: “Toshkent → Qarshi albatta Chiroqchidan o‘tadi” deb qabul qilinmaydi). Bunday tumanlar ro‘yxat oxirida turadi va mahsulot matni ularni “yo‘lingizda” demaydi.
- Tuman katalogi **operator ma’lumoti**: `scripts/import_legacy_districts.py` legacy v1 `districts` jadvalidan `legacy_city_mappings` orqali ko‘chiradi (`--apply`siz faqat hisobot), noaniq moslik — o‘tkazib yuboriladi. Hech bir tuman nomi o‘ylab topilmaydi.

**Wave 1.7 (A2):**
- G13 non-fatal ogohlantirish `WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR` (`Envelope.warnings`, `details {service_type, corridor_floor_minor, lowest_segment_floor_minor}`) — koridor floor segment floor’dan yuqori; band saqlanadi (Q53).
- Narx diapazoni details yagona manbada: `app/modules/geo/pricing.py` (`floor_minor, ceiling_minor, currency, price_basis, scope`); A1 `marketplace/service.py::_check_price_band` shu funksiyalarni chaqiradi — o‘z details’ini qurmaydi. **Q90 (wave 15):** `evaluate_price_band` → ogohlantirish (`WarningCode.PRICE_OUTSIDE_REFERENCE`), `assert_price_within_band` → faqat `enforced` band uchun `400 PRICE_OUT_OF_BAND`. Ogohlantirish kodi xato kodi bilan **hech qachon bir xil yozilmaydi** (`tests/contracts/test_wave16_contact_filter.py`).
- Q47 CLI: `python -m app.modules.geo.checks q47` (mavjud buzilishlarni ro‘yxatlaydi). 0053 trigger semantikasi: koridor tekshiruvi faqat pilot/active’ga **tashqaridan kirishda** va `pilot → active`da (buzilgan koridorni `active → pilot → internal` qilib tuzatish mumkin); bekat o‘zgarishlari har doim tekshiriladi.
- **Q56:** production’da v2 xizmat flag’ini yoqish Q48 gate o‘tmasa `503 PRODUCTION_INVARIANTS_FAILED` `details.reason = gate_unavailable` (gate funksiyasi yo‘q) | `gate_error` | `gate_failed`; faqat aniq `true` o‘tadi. Flag qatori `FOR NO KEY UPDATE` bilan lock qilinadi. DB’da ham trigger (0053).

**Wave 1.6 (A2):**
- `PriceBandUpsert {expected_version? (yangi band’da yo‘q), origin_stop_id?, destination_stop_id? (ikkalasi birga — segment band; ikkalasi yo‘q — butun koridor), floor_minor, ceiling_minor (0 < floor ≤ ceiling), is_active, enforced (default `false` — Q90), reason}`; `PriceBandDTO {corridor_id, service_type, price_basis (passenger → per_seat, parcel → total), origin_stop_id?, destination_stop_id?, floor_minor, ceiling_minor, currency, is_active, enforced, version, reason, updated_by?, updated_at}`; `PriceBandChangeDTO {service_type, origin_stop_id?, destination_stop_id?, version, old_floor_minor?, old_ceiling_minor?, old_is_active?, new_floor_minor, new_ceiling_minor, new_is_active, actor?, reason, changed_at}`. Har o‘zgarish DB trigger’i bilan `corridor_price_band_changes`ga yoziladi (append-only). Marketplace (A1) P1/P5’da band’ni **o‘qiydi**: `enforced=false` → `warnings[PRICE_OUTSIDE_REFERENCE]` va ranking signali; `enforced=true` → `400 PRICE_OUT_OF_BAND` (Q90).
- `AdminStopDTO.meeting_photo_url` — qisqa muddatli imzolangan URL (H0 file access). `meeting_photo_file_id` faqat `stop_photo` upload turi: v1 `POST /api/v1/files/upload` `type=stop_photo`, faqat `ops.corridor_manage`li staff (boshqalarga v1 envelope’da `403 FORBIDDEN`); mavjud upload turlari o‘zgarmagan.
- **Q47:** pilot/active koridorda bekatni faolsizlantirish/o‘chirish, dalilni olib tashlash yoki koridorni pilot/active’ga o‘tkazish shartni buzsa `409 INVALID_STATE_TRANSITION` `details {machine: "corridor_stops", rollout_state, reason: needs_two_active_stops (active_stops) | stops_missing_meeting_evidence (stop_ids)}`; DB’da deferred constraint trigger (0046), mavjud qatorlar faqat keyingi o‘zgarishida tekshiriladi.
- **Q46:** production’da routing provayderi yo‘q → G5 `503 ROUTING_UNAVAILABLE`, matching detour natijalari qaytmaydi (faqat tasdiqlangan bekat match’lari); klient matni “yo‘lda olib ketadi” deb va’da qilmaydi.
- **Ichki (HTTP emas):** `app.modules.geo.jobs.routing_cache_cleanup_task` — worker’da soatiga bir marta (`app.worker.register_default_tasks`, `run_locked`; A7 keyinroq scheduling egasi). `matching.evaluate_route_match` detour quote’lar `TripRouteContext.route_version_public_id`siz berilsa `ValueError` ko‘taradi (chaqiruvchi xatosi — A1/A4 har doim uzatadi). Geo javoblarida `vehicle_class` ishlatilmaydi (trip/marketplace DTO’lari `enums.VehicleClass` qiymatlarini beradi).

DTO: `StopDTO {id (stp_), name_uz, name_ru, district {id, name_uz}, point {lat, lng}, meeting_note, is_active}`; `CorridorDTO {id (cor_), name, origin_region, destination_region, enabled_services[] (flag bilan kesishgan), stops_count}`; `CorridorAdminDTO` + `rollout_state, config_version, version, updated_at`; `CorridorCreate {name, origin_region_id, destination_region_id, default_max_detour_minutes, default_max_detour_m, search_radius_m}`; `CorridorPatch {expected_version, …, rollout_state?, reason}` (faol bron shartlari o‘zgarmaydi); `StopCreate/StopPatch {name_uz, name_ru, district_id, point, meeting_note, sequence_hint, is_active, expected_version?}`; `RoutePreviewRequest {stop_ids[] (≥2), departure_at}`; `RouteVersionDTO {id (rtv_), status, stops[{stop_id, seq, cumulative_distance_m, cumulative_duration_s}], distance_m, duration_s, geometry_polyline, provider, provider_version, is_estimate}`.

**Wave 1 kengaytmalari (A2 implementatsiyasi, qo‘shimcha):** `CorridorAdminDTO.config {revision, search_radius_m, default_max_detour_minutes, default_max_detour_m}` (`config_version` bilan birga); admin stop endpointlari (G10, G11) `AdminStopDTO` qaytaradi = `StopDTO` + `corridor_id (cor_)`, `sequence_hint`, `version`. Region id — `reg_…`, district id — `dst_…` (`PublicIdPrefix.REGION/DISTRICT`). Match sabablari — `app.contracts.enums.MatchReason`; koridor rollout holatlari — `CorridorRolloutState` (STATE_MACHINES §10).

**Wave 1.5 (A2):** `RouteVersionDTO.attribution` (provayder atributsiyasi); `StopCreate/StopPatch/AdminStopDTO.meeting_photo_file_id?` (Q27 dalili). Koridor `pilot`/`active` uchun kamida 2 faol bekat va bekat dalili. Production’da G5 (`/routes/preview`) routing provayderisiz (Q24) — `503 ROUTING_UNAVAILABLE`. A4 uchun geo ichki API’si (HTTP emas): `geo.types.DetourQuote` (kontrakt `DetourQuote` + `stop_id`, `arrive_offset_s`, `provider`, `provider_version`), `TripRouteContext.route_version_public_id`, `service.measure_detours_outside_transaction(...).quotes`, sof helper’lar `matching.validate_detour_quote(s)` (`409 ROUTE_CHANGED`, `details.reason`), `verify_existing_windows` (`409 TIME_WINDOW_CONFLICT`), `apply_insertions` (seq qayta raqamlanadi — `seq_map`), `service.set_active_booking_counter`. **Qaror:** `BookingWindow` va `TimelineChange` `app.contracts`ga ko‘tarilmaydi — ular geo’ning `OccurrenceTiming` tipiga bog‘langan jarayon ichidagi qiymat obyektlari; A4 ularni `app.modules.geo.types`dan (geo’ning ommaviy API’si, ADR-0001) ishlatadi. Saqlanadigan snapshot (`DetourQuote`) allaqachon kontraktda.

## 3. Feature flags (egasi A2; rollout UI A13)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| F1 | `GET /feature-flags/effective` | Public | `?corridor_id` | `EffectiveFlagsDTO` | — | — | — | AC38 |
| F2 | `GET /admin/feature-flags` | `ops.view` | `?flag_key&scope_type` | `list[FlagValueDTO]` | — | — | — | — |
| F3 | `PUT /admin/feature-flags/{flag_key}/scopes/{scope_type}/{scope_ref}` | `ops.feature_flag_manage` (admin+); production’da `passenger_enabled`/`card_payments_enabled`ni yoqish — **super_admin + approval_reference** | `FlagValueUpsert` | `FlagValueDTO` | Y | Y (mavjud bo‘lsa) | `APPROVAL_REFERENCE_REQUIRED`, `FLAG_LOCKED_IN_ENVIRONMENT` (production’da `wallet_required=false`), `FORBIDDEN`, `VERSION_CONFLICT` | Q1, Q5 |
| F4 | `GET /admin/feature-flags/{flag_key}/history` | `ops.view` | cursor | `list[FlagChangeDTO]` | — | — | — | §20.3 |

DTO: `EffectiveFlagsDTO {corridor_id, flags {passenger_enabled, parcel_enabled, driver_listing_enabled, tracking_enabled}}`; `FlagValueUpsert {expected_version?, enabled, approval_reference?, reason}`; `FlagValueDTO {id (flg_), flag_key, scope_type, scope_ref, enabled, approval_reference, version, updated_by, updated_at}`; `FlagChangeDTO {scope_type, scope_ref, version, old_enabled, new_enabled, actor, reason, approval_reference, changed_at}`.
**Q87 guard (wave 7):** production’da `passenger_enabled`ni yoqish uchun `ELCHI_SUPPORT_PHONE` to‘ldirilgan bo‘lishi shart — aks holda `400 VALIDATION_ERROR` (`details.reason=support_contact_not_configured`). Soxta raqam yoki fallback qo‘yilmaydi; S13 `available=false` bo‘lib qolaveradi. Bu tekshiruv Q48 gate’idan **oldin** ishlaydi va faqat o‘chiqdan yoqiqqa o‘tishga tegishli.
**`scope_ref` formatlari:** `country` — `UZ`; `region` — ISO 3166-2 kodi (masalan `UZ-QA`, `^[A-Z]{2}-[A-Z0-9]{1,3}$`); `corridor` — `cor_…` public id; `cohort` — slug `^[a-z0-9][a-z0-9_-]{1,63}$`. Boshqa format → `400 VALIDATION_ERROR` (`details.field=scope_ref`). Legacy v1 yozuvini o‘chiruvchi flag yo‘q (Q4).

## 4. Vehicles va trips (egasi A1; trip action va manifest — A4)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| T1 | `POST /vehicles` | driver roli | `VehicleCreate` | `VehicleDTO` (`pending`) | Y | — | `VALIDATION_ERROR` (dublikat plate: `details.field="plate_number"`) | §13 |
| T2 | `GET /me/vehicles` | driver roli | — | `list[VehicleDTO]` | — | — | — | — |
| T3 | `POST /admin/vehicles/{vehicle_id}/verify` | `ops.driver_eligibility_manage` | `VehicleVerifyRequest` | `VehicleDTO` | Y | Y | `VERSION_CONFLICT` | §17.1 |
| T4 | `POST /trips` | `trip.create` | `TripCreate` | `TripDTO` | Y | — | `SCHEDULE_CONFLICT`, `VEHICLE_NOT_ELIGIBLE`, `DRIVER_NOT_ELIGIBLE`, `ROUTE_CHANGED` | AC13 |
| T5 | `GET /trips/{trip_id}` | Driver egasi, O → `TripDTO`; bron ishtirokchisi → `TripPublicDTO` | — | union | — | — | — | §10.6 |
| T6 | `GET /me/trips` | `trip.operate` | `?status&cursor` | `list[TripDTO]` | — | — | `INVALID_CURSOR` | — |
| T7 | `PATCH /trips/{trip_id}` | Driver egasi (`trip.create`) | `TripPatch` | `TripDTO` | — | Y | `INVALID_STATE_TRANSITION` (bronli trip marshruti), `SCHEDULE_CONFLICT` | §5.4 |
| T8 | `GET /trips/{trip_id}/availability` | Public (ochiq listing bo‘lsa) | — | `TripAvailabilityDTO` | — | — | — | AC10, AC11 |
| T9 | `POST /trips/{trip_id}/actions/{action}` (A4) | Driver egasi `trip.operate`; O (`interrupt/resume/complete/cancel`, cancel admin+) | `TripActionRequest` | `TripDTO` | Y | Y | `INVALID_STATE_TRANSITION`, `TRIP_HAS_UNRESOLVED_BOOKINGS` (`details.bookings[]`), `VERSION_CONFLICT` | AC42, D1 |
| T10 | `GET /trips/{trip_id}/manifest` (A4) | Driver egasi `trip.operate`, O | — | `TripManifestDTO` | — | — | — | §16 |

`{action}` ∈ `start_boarding`, `depart`, `complete`, `interrupt`, `resume`, `cancel`.

DTO:
- `VehicleCreate`: `plate_number`, `make_model`, `color`, `seat_capacity` (>0, haydovchidan tashqari), `baggage_capacity_ml?`, `cargo_max_weight_g?`, `cargo_max_volume_ml?`, `document_file_ids[]`. `VehicleDTO`: `id (veh_)`, shular, `plate_masked`, `verification_status`, `version`. `VehicleVerifyRequest`: `expected_version`, `decision: approve|reject`, `reason?`.
- `TripCreate`: `vehicle_id`, `route_version_id`, `stops[{stop_id, seq, planned_arrival_at, dwell_minutes}]`, `planned_start_at`, `planned_end_at`, `seat_capacity`, `baggage_capacity_ml?`, `cargo_capacity_weight_g?`, `cargo_capacity_volume_ml?`, `max_detour_minutes`, `max_detour_m`, `pickup_wait_minutes` (default 10), `booking_cutoff_at?`.
- `TripDTO`: `id (trp_)`, `status`, `version`, `vehicle`, `route_version_id`, `stops[]`, `planned_start_at`, `planned_end_at`, `timezone`, sig‘im maydonlari, `detour_used_s`, `booking_cutoff_at`, `listings[{id, service_type, status}]`, `open_cases {no_show_reviews, custody_cases}`.
- `TripPublicDTO`: `id`, `status`, `vehicle {vehicle_class, seat_capacity}`, bekat nomlari va rejalashtirilgan vaqtlar; boshqa bronlar yo‘q. **Wave 1.6 (R2, BR uchinchi ziddiyati):** avval accept’dan oldin `make_model`, `color`, `plate_masked` ko‘rsatilgan — Q43 bo‘yicha olib tashlandi (A1 implementatsiyasi). Avtomobil tafsiloti (model, rang, to‘liq plate) faqat bron ishtirokchisiga `BookingDTO.driver.vehicle` orqali (§8 qoidalari).
- `TripPatch`: `expected_version`, `planned_start_at?`, `planned_end_at?`, `stops?` (bronsiz), `max_detour_*?`.
- `TripAvailabilityDTO`: `trip_id`, `trip_version`, `computed_at`, `segments[{from_seq, to_seq, from_stop_id, to_stop_id, seats_remaining, baggage_remaining_ml, cargo_remaining_weight_g, cargo_remaining_volume_ml}]` — faqat hisob, rezerv emas.
- `TripActionRequest`: `expected_version`, `reason?` (cancel/interrupt/resume/operator complete’da majburiy), `evidence_file_ids?`.
- `TripManifestDTO`: `stops[{seq, stop, pickups[{booking_id, service_type, seats|parcel_summary, client_first_name, contact_phone}], dropoffs[…]}]` — **Q44:** `contact_phone` faqat bron start’dan (passenger `onboard`, parcel `picked_up`) terminal holatdan 24 soat o‘tguncha; boshqa vaqtda `null`.

## 5. Listings (egasi A1)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| L1 | `POST /listings` | `listing.create_request` \| `listing.create_trip_offer` | `ListingCreate` | `ListingDTO` (`draft`) | Y | — | `CAPABILITY_REQUIRED`, `DRIVER_NOT_ELIGIBLE`, `PRICE_BASIS_NOT_ALLOWED`, `CORRIDOR_NOT_ACTIVE` | AC01 |
| L2 | `GET /listings/{listing_id}` | Egasi → `ListingDTO`; boshqalar (published) → `ListingPublicDTO` | — | union | — | — | — | §10.6 |
| L3 | `PATCH /listings/{listing_id}` | Egasi | `ListingPatch` | `ListingDTO` | — | Y | `VERSION_CONFLICT`, `INVALID_STATE_TRANSITION` | §5.4, AC04 |
| L4 | `POST /listings/{listing_id}/publish` | Egasi | `ListingCommand` | `ListingDTO` | Y | Y | `LISTING_INCOMPLETE`, `FEATURE_DISABLED`, `LISTING_EXPIRED`, `DUPLICATE_LISTING`, `CORRIDOR_NOT_ACTIVE`, `DRIVER_NOT_ELIGIBLE` | AC01, AC38 |
| L5 | `POST /listings/{listing_id}/pause` | Egasi | `ListingCommand` | `ListingDTO` | Y | Y | `INVALID_STATE_TRANSITION` | — |
| L6 | `POST /listings/{listing_id}/resume` | Egasi | `ListingCommand` | `ListingDTO` | Y | Y | L4 xatolari | — |
| L7 | `POST /listings/{listing_id}/cancel` | Egasi; boshqa foydalanuvchi listing’ini bekor qilish — `ops.booking_command` (operator+) + **audit qatori**, sabab majburiy; operator `draft`ni bekor qila olmaydi (Q23) | `ListingCancel` | `ListingDTO` | Y | Y | `INVALID_STATE_TRANSITION` | §5.4 |
| L8 | `GET /me/listings` | Auth | `?status&kind&service_type&cursor` | `list[ListingDTO]` | — | — | `INVALID_CURSOR` | — |
| L9 | `GET /directions/preview` | Auth | `?origin_lat&origin_lng&origin_district_id&destination_lat&destination_lng&destination_district_id` | `DirectionPreviewDTO` | — | — | `ROUTE_MISMATCH` (yo'nalish yo'q) | Q88 |

DTO:
- **Q88 (18.09.2026) — uch = bekat yoki xaritadagi nuqta.** Har uchi uchun `*_stop_id` **yoki** `*_point` yuboriladi, ikkalasi emas (`VALIDATION_ERROR`). `PointEndInput`: `lat`, `lng`, `district_id` (**advisory** — faqat hujjatlash va qidiruv uchun; tuman chegarasi tekshirilmaydi), `address?`. Server nuqtani koridorning tasdiqlangan marshrutiga proyeksiya qiladi (`ST_LineLocatePoint`); yo'ldan `service_corridors.max_point_offset_m` (default 3000 m) dan uzoq bo'lsa yoki pickup dropoff'dan keyin tushsa — `ROUTE_MISMATCH`. Nuqtali uch **hech qachon `exact` moslik olmaydi** (eng ko'pi `on_route`). Trip-offer faqat bekat bilan e'lon qilinadi. Javobda `origin_point`/`destination_point`: `PointEndDTO` (`lat`, `lng`, `district?`, `address?`, `route_offset_m`).
- `DirectionPreviewDTO` (L9): `corridor_id`, `corridor_name`, `route_version_id`, `route_polyline`, `distance_m`, `duration_s`, `max_point_offset_m`, `origin`/`destination` (`PointEndDTO`), `districts_on_route[]`. Klient ikki nuqta belgilanishi bilan so'raydi; `409 ROUTE_MISMATCH` — mahsulot darajasidagi «bu ikki nuqta hozircha ELCHI yo'nalishiga mos kelmaydi» holati.
- `ListingCreate`: `kind`, `service_type`, `origin_stop_id`/`origin_point`, `destination_stop_id`/`destination_point`, `departure_window_start/end`, `timezone` (`Asia/Tashkent`), `price_basis`, `unit_price_minor`, `currency`, `payment_method` (`cash`), `expires_at?`, `comment?`, `trip_id?` (trip_offer’da majburiy), `passenger?: PassengerDetails` | `parcel?: ParcelDetails`.
- `PassengerDetails`: `seat_count` (>0), `adults` (≥1), `children`, `child_seat_required`, `baggage {pieces, total_weight_g, total_volume_ml?}`, `special_assistance?`, `amenities[]`; `adults + children = seat_count`.
- `ParcelDetails` (request): `parcel_type`, `weight_g`, `length_cm`, `width_cm`, `height_cm`, `fragile`, `declared_value_minor?` (sug‘urta emas), `photo_file_id?` (Q6: faqat egasi va tayinlangan haydovchi ko‘radi), `payer`, `sender {name, phone}`, `receiver {name, phone}`, `pickup_window_start/end`, `dropoff_window_start/end`. trip_offer: `max_weight_g`, `max_volume_ml`, `max_dimension_cm`, `accepted_parcel_types[]`.
- `ListingDTO`: `id (lst_)`, `kind`, `service_type`, `status`, `version`, `owner {id, display_name}`, bekatlar, oyna, `timezone`, `price_basis`, `unit_price_minor`, `quantity`, `total_minor` (server hisobi), `currency`, `payment_method`, `expires_at`, `trip_id?`, detallar, `published_at`, `created_at`.
- `ListingPublicDTO`: `id`, `kind`, `service_type`, `status`, bekat nomlari, oyna, `price_basis`, `unit_price_minor`, `quantity`, `total_minor`, `currency`, egasi `display_name`, reputatsiya xulosasi, parcel toifasi — telefon, uy manzili, aniq GPS, rasm yo‘q.
**U6 `rating_bucket` (wave 8, tasdiqlangan A-variant):** `ListingOfferDTO.rating_bucket` endi to‘ldiriladi — `new_verified` | `good` | `mixed` | `low`. Chegaralar: kamida **3** baho, `good ≥ 4.0`, `mixed ≥ 3.0`, `low < 3.0`; undan kami — `new_verified`. Yangi additiv maydon **`rating_count`** (int, standart 0) har doim bucket bilan birga o‘qiladi. Sun’iy reyting yo‘q, `null` o‘rniga 0 yozilmaydi, ichki `adjusted_rating` (4.5 prior bilan) hech qachon ko‘rsatilmaydi (§8.2, AC36). Anonimlik buzilmaydi: bucket ism, telefon yoki foto olib kelmaydi (ADR-0019).

- `ListingPatch`: `expected_version` + o‘zgartiriladigan maydonlar. `ListingCommand`: `expected_version`. `ListingCancel`: `expected_version`, `reason_code`, `comment?`.

### 5a. Taqiqlangan jo‘natmalar siyosati (§5.2, wave 7)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| L9 | `GET /parcel-policy` | **Auth talab qilinmaydi** (ilova ro‘yxatni kirishdan oldin ham ko‘rsatadi) | — | `ParcelPolicyDTO` | — | — | — | §5.2 |
| L10 | `GET /admin/parcel-policies` | `ops.view` | `?status` | `list[ParcelPolicyVersionDTO]` | — | — | — | §5.2 |
| L11 | `POST /admin/parcel-policies` | `platform.policy_manage` (`super_admin`) | `ParcelPolicyVersionCreate` | `ParcelPolicyVersionDTO` (`draft`) | Y | — | `CAPABILITY_REQUIRED`, `VALIDATION_ERROR`, `DUPLICATE_*` | §5.2 |
| L12 | `POST /admin/parcel-policies/{policy_id}/confirm` | `platform.policy_manage` | `VersionedCommand` | `ParcelPolicyVersionDTO` (`active`) | Y | Y | `CAPABILITY_REQUIRED` (**muallif o‘zini tasdiqlay olmaydi**), `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT` | §5.2, Q17 ruhi |

DTO:
- `ParcelPolicyDTO`: `approved: bool`, `label?`, `effective_from?`, `notice` (matn), `items: list[ParcelPolicyItemDTO]`.
  **`approved=false` va bo‘sh `items` hech qachon “hamma narsani jo‘natish mumkin” degani emas** — `notice` aynan
  shuni aytadi va ro‘yxat tasdiqlanmagani ko‘rsatiladi.
- `ParcelPolicyItemDTO`: `code`, `category` (`prohibited` | `restricted` | `business_declined`), `applies_to`
  (`parcel` | `passenger_baggage` | `all`), `title_uz`, `description_uz`, `legal_basis?`, `source_ref?`,
  `source_checked_on?`.
- `ParcelPolicyVersionCreate`: `label`, `source_note?`, `effective_from?`, `items: list[ParcelPolicyItemCreate]`.
  `prohibited` toifasidagi band `legal_basis` va `source_ref` siz **DB darajasida** rad etiladi.
- `ParcelPolicyVersionDTO`: `id (ppv_)`, `label`, `status`, `version`, `source_note?`, `created_by?`,
  `confirmed_by?`, `confirmed_at?`, `effective_from?`, `items`.

**Gate:** tasdiqlangan (`active`) versiya bo‘lmasa va muhit production bo‘lsa, `service_type='parcel'` uchun
L4 `publish` va P4 `accept` `503 PARCEL_POLICY_UNCONFIRMED` qaytaradi. Mavjud bronlar, tracking, proof va
support **tegilmaydi** (D16 majburiyat qoidasi); yo‘lovchi oqimiga ta’sir qilmaydi.

## 6. Feed, matches, saved searches (egasi A5)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| M1 | `GET /feed` | Auth | `FeedQuery` | `list[FeedItemDTO]` + `meta.ranking_version` | — | — | `INVALID_CURSOR`, `ROUTING_UNAVAILABLE` (degradatsiya belgisi) | AC18, AC35, AC36 |
| M2 | `GET /listings/{listing_id}/matches` | Listing egasi | `?sort&cursor&limit&include_alternatives` | `list[MatchDTO]` | — | — | `INVALID_CURSOR` | AC14–AC16, AC36 |
| M3 | `POST /saved-searches` | Auth | `SavedSearchCreate` | `SavedSearchDTO` | Y | — | `RATE_LIMITED` | §6.6 |
| M4 | `GET /me/saved-searches` | Auth | — | `list[SavedSearchDTO]` | — | — | — | — |
| M5 | `DELETE /saved-searches/{saved_search_id}` | Egasi | — | `{}` | — | — | — | — |

DTO: `FeedQuery {service_type, side: requests|offers, origin_stop_id|origin_region_id, destination_…, date_from, date_to, seats?, max_total_minor?, amenities[]?, sort: recommended|cheapest|time|rating, cursor, limit}`; `FeedItemDTO {listing: ListingPublicDTO, match {match_type, reasons[], pickup_eta_window_start/end?, detour_minutes?, is_estimate}, ready_to_accept, labels[]}`; `MatchDTO {listing, trip_availability_summary?, match, ranking_version, group: primary|alternative}`; `SavedSearchCreate {service_type, origin_…, destination_…, time_window_start/end, quantity, notify}`; `SavedSearchDTO {id (svs_), …, created_at}`.

**Wave 10 (A5, 17.09.2026) — tuman uchi:** `FeedQuery` va `SavedSearchCreate/SavedSearchDTO` ga `origin_district_id` / `destination_district_id` qo‘shildi. Har uchida **aniq bitta** havola: bekat, tuman yoki viloyat (aks holda `400 VALIDATION_ERROR`, `details.field = "<end>_stop_id"`, `reason = exactly_one_of_stop_district_or_region`; DB’da `num_nonnulls(...) = 1` CHECK). Tuman uchi o‘sha tumandagi **faol bekatlarga** yoyiladi — moslik, sig‘im va narx band’i baribir bekat va tasdiqlangan marshrut tartibi bo‘yicha hisoblanadi. Shu sababli Toshkent → Qarshi tanlagan haydovchi Chiroqchi → Qarshi so‘rovini `on_route` + `intermediate_segment` sifatida ko‘radi, teskari yo‘nalishni esa ko‘rmaydi (AC16).

**Wave 3 (A5, 16.09.2026) — aniqlashtirishlar:** kontrakt `app/contracts/feed.py` (`RANKING_VERSION`, `CLIENT_SCORE_WEIGHTS` §8.2, `DRIVER_SCORE_WEIGHTS` §8.4, `MATCH_TYPE_SCORE`, `NEUTRAL_PRICE_SCORE`, `SAVED_SEARCH_MAX_PER_USER`, `SAVED_SEARCH_MAX_WINDOW_DAYS`, `FEED_MAX_LIMIT`), `enums.FeedSide`, `FeedSort`, `MatchGroup`, reputatsiya — `trust.ReputationSummary` (A12 `reputation_summaries`; reyting yo‘q → `ReputationLabel.new_verified`, sun’iy 4.5 yo‘q, AC36). `FeedItemDTO.listing` — A1 `marketplace.views.listing_public_dto` (Q43: egasi ismi yo‘q). Q21: eligible bo‘lmagan driver `trip_offer`lari lentada yo‘q. Q46: production’da `match_type=detour` va `detour_minutes` qaytmaydi. AC18: kelajak safarli oflayn driver lentada qoladi. `SavedSearchCreate` + `side` (`FeedSide`), uchlar `*_stop_id` yoki `*_region_id` (aniq bittasi). **M3** limit → `409 SAVED_SEARCH_LIMIT_REACHED` `details {limit}` (`RATE_LIMITED` faqat so‘rov chastotasi uchun); oyna > `SAVED_SEARCH_MAX_WINDOW_DAYS` → `400 VALIDATION_ERROR`. **M5** — soft delete (`deleted_at`), boshqaning qidiruvi `404`. `notify=true` qidiruvga mos yangi `listing.published` → `saved_search.matched {saved_search_id, listing_id, service_type, side}` (bir listing uchun bitta; o‘z listing’i uchun yo‘q); push A7 orqali, bekor/muddati o‘tgan listing uchun yuborilmaydi (A5 relevance check, §6.6).

## 7. Proposals (egasi A1; accept — A4)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| P1 | `POST /listings/{listing_id}/proposals` | `proposal.submit_as_client` \| `proposal.submit_as_driver` | `ProposalCreate` | `ProposalThreadDTO` | Y | — | `LISTING_NOT_OPEN`, `SELF_DEALING_FORBIDDEN`, `DRIVER_NOT_ELIGIBLE`, `FEATURE_DISABLED`, `QUANTITY_MISMATCH`, `CAPACITY_UNAVAILABLE`, `ROUTE_MISMATCH`, `PRICE_BASIS_NOT_ALLOWED`, `PRICE_OUT_OF_BAND` (Q90: faqat `enforced` band), `BOOKING_CUTOFF_PASSED`, `RATE_LIMITED` | AC02, AC03, AC05 |
| P2 | `GET /listings/{listing_id}/proposals` | Listing egasi | `?state&cursor` | `list[ProposalThreadDTO]` | — | — | — | — |
| P3 | `GET /proposals/{thread_id}` | Thread tomonlari | — | `ProposalThreadDTO` (tarix bilan) | — | — | — | — |
| P4 | `GET /me/proposals` | Auth | `?state&cursor` | `list[ProposalThreadDTO]` | — | — | — | — |
| P5 | `POST /proposals/{thread_id}/counter` | Joriy versiya qabul qiluvchisi | `ProposalCounter` | `ProposalThreadDTO` | Y | `expected_revision` | `PROPOSAL_CHANGED`, `NOT_PROPOSAL_RECIPIENT`, `NEGOTIATION_LIMIT_REACHED`, `QUANTITY_MISMATCH`, P1 xatolari | AC04 |
| P6 | `POST /proposals/{thread_id}/reject` | Qabul qiluvchi | `ProposalDecision` | `ProposalThreadDTO` | Y | `expected_revision` | `NOT_PROPOSAL_RECIPIENT`, `PROPOSAL_CHANGED` | — |
| P7 | `POST /proposals/{thread_id}/withdraw` | Muallif | `ProposalDecision` | `ProposalThreadDTO` | Y | `expected_revision` | `INVALID_STATE_TRANSITION` | §14 |
| P8 | `POST /proposals/{thread_id}/accept` (**A4**) | Qabul qiluvchi | `AcceptRequest` | `BookingDTO` (201) | **Y** | `expected_listing_version` | `PROPOSAL_CHANGED`, `PROPOSAL_EXPIRED` (fee quote ham shu bilan tugaydi), `QUANTITY_MISMATCH`, `CAPACITY_UNAVAILABLE`, `CARGO_LIMIT_EXCEEDED`, `INSUFFICIENT_COMMISSION_BALANCE`, `ROUTE_CHANGED`, `DETOUR_LIMIT_EXCEEDED`, `TIME_WINDOW_CONFLICT`, `IDEMPOTENCY_KEY_REUSED`, `SELF_DEALING_FORBIDDEN`, `NOT_PROPOSAL_RECIPIENT`, `DRIVER_NOT_ELIGIBLE`, `FEATURE_DISABLED`, `BOOKING_CUTOFF_PASSED` | AC02–AC09, AC12, AC17, AC19, AC41, AC43 |
| P9 | `GET /listings/{listing_id}/offers` (**wave 1.6, Q40–Q41**) | Eligible driver (`proposal.submit_as_driver`), listing unga ko‘rinadigan bo‘lsa (A5 lenta qoidasi bilan bir xil); faqat `kind=request` | `?cursor&limit` | `list[OpenOfferViewDTO]` | — | — | `NOT_FOUND` (listing ko‘rinmaydi, trip_offer yoki driver eligible emas), `INVALID_CURSOR` | ADR-0019 |

**R1/R2 (Q40–Q45, wave 1.6) qoidalari:**
- **`ListingOfferDTO`** (A1 implementatsiyasi, modul egaligidagi DTO `app/modules/marketplace/schemas.py`; kontrakt testi `tests/contracts/test_wave16_r2_dtos.py` identifikatsiya maydonlari yo‘qligini tekshiradi) `{label ("Haydovchi #2" — `listing_offer_labels`, birinchi aloqa tartibida, listing ichida barqaror, hech bir id’dan olinmaydi), is_mine, revision, quantity, price_basis, unit_price_minor, total_minor, currency, pickup_stop: StopRefDTO, dropoff_stop: StopRefDTO, pickup_window_start, pickup_window_end, vehicle_class (`enums.VehicleClass`: car|minivan|minibus), seat_capacity, rating_bucket? (A12 gacha `null` — sun’iy reyting yo‘q), completed_bookings? (A12 gacha `null`), updated_at}` — faqat har thread’ning **joriy** versiyasi (Q41). Yo‘q: ism, foto, plate, telefon, model/rang, user/driver/trip/thread/version id’lari, mijoz counter’lari. P9 faqat `proposal.submit_as_driver`li eligible driverga; listing egasi, mijozlar, bloklangan driverlar va `trip_offer` listing’lar — `404`. (Avvalgi rejadagi `OpenOfferViewDTO` nomi shu DTO bilan almashtirildi.) Mijoz ko‘rinishi (P2) o‘zgarmaydi.
- **Q43 — accept’dan oldingi DTO’lar (A1 implementatsiyasi):** `ListingPublicDTO`da `owner_display_name` **yo‘q**; `ProposalThreadDTO` tomonlari `ProposalPartyDTO {side, label ("Haydovchi #N" | "Mijoz"), id: null, display_name: null, reputation: null}` — identifikatsiya maydonlari bron mavjud bo‘lguncha (A4) har doim `null`; `TripPublicDTO.vehicle {vehicle_class, seat_capacity}`. Accept’dan keyin — BookingDTO qoidalari (§8).
- **Ataylab qoldirilgan identifikatsiya maydonlari (egasi/staff ko‘rinishi, Q43 ga zid emas — boshqa tomonga ko‘rsatilmaydi):** `MeDTO` (o‘zi), `VehicleDTO` (egasi driver/admin), `TripDTO` (egasi/staff), `ListingDTO` (egasi/staff), parcel `sender`/`receiver` kontaktlari (egasi/staff, Q6).
- **Kontakt filtri (A1 qamrovi):** listing izohi, bekor qilish izohi, `passenger.special_assistance`, taklif/counter `message`; keyin chat (A7), reyting matni va profil maydonlari (A12). Saqlanadigan va ko‘rsatiladigan qiymat — `masked_text`; moslikda audit qatori (faqat kategoriya sonlari), `trust.contact_filter.hit` (faqat staff, matnsiz) va ogohlantirish. Xato qaytarilmaydi (mask, blok emas). **Maqsadli javob shakli:** `Envelope.warnings[{code: "CONTACT_INFO_MASKED", field, message, details: ContactScanResult.warning_details()}]`. **Implementatsiya (wave 1.6 integratsiyasi, 2-qism):** handler `(dto, warnings)` qaytaradi; `app/api/v2/web.py::run_command` ularni `to_api_warnings` bilan `ApiWarning {code, message (WARNING_CATALOGUE), field, details {categories, match_count, filter_version}}`ga aylantirib `Envelope.warnings`ga yozadi va javob bilan idempotency yozuvida saqlaydi — replay aynan shu ogohlantirishlarni qaytaradi. `PATCH /listings/{id}` (versiyali) ham `Envelope.warnings`. `ListingDTO.warnings` / `ProposalThreadDTO.warnings` va `TextWarningDTO` olib tashlandi (klientlar hali ishlatmagan). Ogohlantirish bo‘lmasa `warnings` kaliti yo‘q (`null`).
- **Parcel `sender`/`receiver` ism va telefon maydonlari kontakt filtridan o‘tmaydi (integrator qarori, Q43 ga mos):** Q43 filtri erkin matnda **yashirilgan** kontaktni ushlaydi; bu maydonlar esa ataylab tuzilgan, xizmat uchun zarur kontakt ma’lumoti bo‘lib, ularni maskalash yetkazishni buzadi. Mos kelishi sharti: ular accept’dan oldin hech bir DTO’da boshqa tomonga ko‘rinmaydi (faqat egasi/staff, Q6), qabul qiluvchi telefoni driverga faqat `picked_up`dan keyin, jo‘natuvchi telefoni driverga hech qachon (Q44). Parcel **tavsifi** (`description`/izoh) esa erkin matn — filtrdan o‘tadi.
- **Narx referensi (Q42, Q53, Q90):** ELCHI — ikki tomonlama auksion; narxni tomonlar kelishadi, platforma hisoblamaydi. `corridor_price_bands` shuning uchun **referens**: avval aniq segment band, bo‘lmasa koridor band (Q88: nuqtali uchda segment yo‘q → koridor band). P1/P5’da narx referensdan tashqarida bo‘lsa javob **muvaffaqiyatli** qaytadi va `Envelope.warnings` ga `PRICE_OUTSIDE_REFERENCE` qo‘shiladi; shu qiymat ranking’dagi `P`/`Y` komponentiga ham kiradi. **Yagona `details` shakli (ogohlantirishda ham, xatoda ham):** `{floor_minor: int, ceiling_minor: int, currency: "UZS", price_basis: "per_seat"|"total", scope: "segment"|"corridor"}`. **Yagona qattiq rad:** `corridor_price_bands.enforced = true` (admin ataylab qo‘ygan abuse/safety chegarasi) → `400 PRICE_OUT_OF_BAND`. Band faqat submit (P1) va counter (P5) paytida o‘qiladi — **accept’da (P8) qayta o‘qilmaydi**; narxni va bekatni o‘zgartirmaydigan counter uni o‘tkazib yuboradi. Band yo‘q — referens yo‘q (`P=0.5`, spec §8.2).
- **Q54 (accept versiyasi):** P8 `AcceptRequest.expected_listing_version` `listings.terms_version`ga ishora qiladi (`listings.version` emas); additiv alias `expected_listing_terms_version` (ikkalasi qabul qilinadi, bir xil qiymat; ikkalasi berilib farq qilsa `400 VALIDATION_ERROR`). `ListingDTO.terms_version` (faqat taklifni bekor qiladigan tahrirda oshadi, Q20). A4 `proposal_versions.listing_terms_version != listings.terms_version` bo‘lsa `409 PROPOSAL_CHANGED`.
- **Wave 1.7 (A1 implementatsiyasi):**
  - `ListingOfferDTO.response_pending: bool` — mijoz counter qilgan, taklif shu driver javobini kutmoqda.
  - P9 service flag o‘chiq yoki koridor yopiq bo‘lsa `404`.
  - Request’ga taklif o‘z pickup oynasini request oynasi ichida bajarishi shart (`409 TIME_WINDOW_CONFLICT reason=proposal_window_outside_request_window`).
  - Offer parcel turlarini cheklasa, turi ko‘rsatilmagan parcel rad etiladi.
  - Kontakt filtri qo‘shimcha: `amenities`, `parcel_type`, `accepted_parcel_types`.
  - Filtr mosligi (audit qatori + staff event, matnsiz) buyruq muvaffaqiyatsiz bo‘lsa ham saqlanadi (alohida commit qilingan yozuv).
  - `ListingDTO.terms_version` ochiq (Q54); narxi o‘zgarmagan counter band tekshiruvini o‘tkazib yuboradi (Q53).
  - **Ma’lum cheklov (follow-up A1):** P9 expire bo‘lgan thread’larni o‘tkazib yuboradi — sahifa `limit`dan qisqa bo‘lishi va keyingi thread’lar bor bo‘lsa ham `next_cursor = null` bo‘lishi mumkin.
- **Envelope (additive):** `Envelope.warnings: list[ApiWarning{code, message, field?, details?}] | null` — `errors.WarningCode`.

DTO: `ProposalCreate {trip_id? (driver’da majburiy), pickup_stop_id, dropoff_stop_id, pickup_window_start/end, quantity (passenger request’da = seat_count; parcel = 1; trip_offer’da ≤ qolgan o‘rin), price_basis, unit_price_minor, message? (≤500), parcel? {weight_g, length_cm, width_cm, height_cm, volume_ml?}}` — **wave 1.5 (A1, implementatsiya qilingan):** `ProposalCreate` va `ProposalCounter` ixtiyoriy `baggage {pieces?, total_weight_g?, total_volume_ml?}` va `parcel {weight_g, length_cm, width_cm, height_cm, volume_ml?}` qabul qiladi; `ProposalVersionDTO.demand {baggage_ml, cargo_weight_g, cargo_volume_ml, parcel_length_cm?, parcel_width_cm?, parcel_height_cm?}` (DB: `proposal_versions`, 0044). A4 accept’da shu snapshot’dan rezerv qiladi (AC12). A1 domen API: `version_demand`, `expire_threads_for_trip`, `assert_trip_offers_on_trip`; `ProposalCounter {expected_revision, pickup_stop_id?, dropoff_stop_id?, pickup_window_*?, quantity?, unit_price_minor?, message?}`; `ProposalDecision {expected_revision, reason_code?}`; `AcceptRequest {proposal_version_id (prv_), expected_listing_version}`; `ProposalThreadDTO {id (prp_), listing_id, trip_id?, state, client, driver {id, display_name, reputation}, current_version, versions[]?, booking_id?}`; `ProposalVersionDTO {id (prv_), revision, author_side, status, status_reason?, pickup_stop, dropoff_stop, pickup_window_*, quantity, price_basis, unit_price_minor, total_minor, currency, expires_at, created_at, fee_quote? (faqat driver tomoniga), price_revisions_left {client, driver}}`; `FeeQuoteDTO {policy_id (cmp_), policy_kind, fee_bps, commission_minor, net_minor, valid_until (= version.expires_at)}`.

### 7a. Saqlangan safar/jo‘natma talabi (ADR-0025, 24.09.2026)

Egasi — sessiyadagi foydalanuvchi (body’da egasi yo‘q); begona yoki noma’lum id → `404 NOT_FOUND`. Talab e’lon emas: feed’da
ko‘rinmaydi, hech kimga taklif yubormaydi. Barcha buyruqlar `Idempotency-Key` bilan.

| # | Method / path | Auth | Request | Response | Idem | Ver | Xatolar |
|---|---|---|---|---|---|---|---|
| TI1 | `POST /me/trip-intents` | `proposal.submit_as_client` | `TripIntentCreate` | `TripIntentDTO` (201) | Y | — | `TRIP_INTENT_EXPIRED`, `QUANTITY_MISMATCH` (pochta = 1), `VALIDATION_ERROR` |
| TI2 | `GET /me/trip-intents` | Auth (o‘zi) | `?status&limit` | `list[TripIntentDTO]` | — | — | — |
| TI3 | `GET /me/trip-intents/{id}` | Egasi | — | `TripIntentDTO` | — | — | `NOT_FOUND` |
| TI4 | `PATCH /me/trip-intents/{id}` | Egasi | `TripIntentUpdate` | `TripIntentDTO` | Y | `expected_version` | `TRIP_INTENT_OFFERS_AFFECTED` (`details.open_offers`), `TRIP_INTENT_BOOKED`, `TRIP_INTENT_EXPIRED`, `VERSION_CONFLICT` |
| TI5 | `POST /me/trip-intents/{id}/close` | Egasi | `TripIntentCommand` | `TripIntentDTO` | Y | `expected_version` | `INVALID_STATE_TRANSITION` |
| TI6 | `POST /me/trip-intents/{id}/reopen` | Egasi | `TripIntentCommand` | `TripIntentDTO` | Y | `expected_version` | `INVALID_STATE_TRANSITION` (bron bekor qilinmagan) |
| TI7 | `GET /me/trip-intents/{id}/fit?listing_id=` | Egasi | — | `TripIntentFitDTO` | — | — | `NOT_FOUND` |

- **P1 qo‘shimchasi (additiv):** `ProposalCreate.trip_intent: {id, version_no} | null` — faqat mijoz tomoni. `quantity`, `price_basis`
  va pochta talabi (tur, o‘lcham, qabul qiluvchi) talab versiyasiniki bo‘lishi shart (`VALIDATION_ERROR reason=trip_intent_*_mismatch`);
  eskirgan versiya → `409 TRIP_INTENT_CHANGED`, band talab → `409 TRIP_INTENT_BOOKED`, muddati o‘tgan → `409 TRIP_INTENT_EXPIRED`.
  Narx va oyna haydovchiga xos, talabga yozilmaydi. `ProposalThreadDTO.trip_intent_id` — faqat mijoz ko‘rinishida.
- **P5/P8:** talab bilan bog‘langan thread’da counter `quantity`/pochta talabini o‘zgartirmaydi; accept talab lock’i ostida
  `active` va `terms_version`ni qayta tekshiradi; talab bo‘yicha bitta bekor qilinmagan bron (`uq_bookings_trip_intent_binding`).
- **Eski klientlar:** `trip_intent` yubormaydigan klient (shu jumladan muzlatilgan Android v1 — u v2 ishlatmaydi) avvalgidek
  ishlaydi; ularning takliflari talab himoyasisiz. Tarixiy thread/bronlar guruhlanmaydi.
- **Ishchi vazifa:** `marketplace.close_stale_intent_threads` — `SKIP LOCKED` sababli o‘tkazib yuborilgan ochiq takliflarni yopadi
  (accept/counter ularni baribir rad etadi).

## 8. Bookings (egasi A4)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| B1 | `GET /bookings/{booking_id}` | Ishtirokchi, O | — | `BookingDTO` | — | — | — | §14.2 |
| B2 | `GET /me/bookings` | Auth | `?role=client|driver&status&cursor` | `list[BookingDTO]` | — | — | `INVALID_CURSOR` | — |
| B3 | `POST /bookings/{booking_id}/cancel` | C, D (obligation) | `BookingCancel` | `BookingDTO` | Y | Y | `INVALID_STATE_TRANSITION`, `CUSTODY_REQUIRES_RETURN_FLOW`, `NO_SHOW_REVIEW_PENDING`, `VERSION_CONFLICT` | AC21, AC22 |
| B4 | `POST /bookings/{booking_id}/actions/{action}` | `BookingAction` bo‘yicha (STATE_MACHINES §4–5); D uchun `trip.operate` (eligibility blokida ham) | `BookingActionRequest` | `BookingDTO` | Y | Y | `INVALID_STATE_TRANSITION`, `PROOF_INVALID`, `PROOF_ATTEMPTS_EXCEEDED`, `NO_SHOW_NOT_ALLOWED`, `NO_SHOW_REVIEW_PENDING`, `VERSION_CONFLICT`, `FORBIDDEN` | AC20, AC22, AC42, Q7 |
| B5 | `GET /bookings/{booking_id}/codes` | Kod egasi (passenger → boarding; sender → pickup/return; receiver share link → delivery) | — | `BookingCodesDTO` | — | — | `FORBIDDEN` | §11 |
| B6 | `POST /bookings/{booking_id}/cash-receipts` | D yoki payer | `CashReceiptReport` | `CashReceiptDTO` | Y | Y | `INVALID_STATE_TRANSITION` | AC26 |
| B7 | `POST /bookings/{booking_id}/cash-receipts/{receipt_id}/acknowledge` | Qarshi tomon | `CashReceiptDecision` | `CashReceiptDTO` | Y | Y | `FORBIDDEN`, `INVALID_STATE_TRANSITION` | AC26 |
| B8 | `POST /bookings/{booking_id}/cash-receipts/{receipt_id}/contest` | Qarshi tomon | `CashReceiptDecision` | `CashReceiptDTO` + `dispute_id` | Y | Y | `DISPUTE_ALREADY_OPEN` | AC26 |
| B9 | `POST /bookings/{booking_id}/amendments` | C yoki D | `AmendmentCreate` | `AmendmentDTO` | Y | Y | `AMENDMENT_CONFLICT`, `QUANTITY_MISMATCH`, `INVALID_STATE_TRANSITION` | §5.3(7) |
| B10 | `POST /amendments/{amendment_id}/accept` | Qarshi tomon | `AmendmentDecision` | `BookingDTO` | Y | Y | `CAPACITY_UNAVAILABLE`, `TIME_WINDOW_CONFLICT`, `INSUFFICIENT_COMMISSION_BALANCE` (hold oshsa), `AMENDMENT_CONFLICT`, `VERSION_CONFLICT` | §5.3(7), D10 |
| B11 | `POST /amendments/{amendment_id}/reject` \| `/withdraw` | Qarshi tomon \| muallif | `AmendmentDecision` | `AmendmentDTO` | Y | Y | `INVALID_STATE_TRANSITION` | — |
| B9r | `GET /bookings/{booking_id}/amendments` | C yoki D (ishtirokchi) | — | `list[AmendmentDTO]` | — | — | `NOT_FOUND` (ishtirokchi bo‘lmasa) | §5.3(7) |
| B12 | `GET /admin/bookings` | `ops.view` | `?queue=awaiting_confirmation|no_show_review|custody_case|hold_escalation&corridor_id&cursor` | `list[BookingDTO]` | — | — | — | §16 |
| B13 | `POST /admin/bookings/{booking_id}/commands/{command}` | `OPERATOR_COMMAND_CAPABILITY[command]` | `OperatorBookingCommandRequest` | `BookingDTO` | Y | Y | STATE_MACHINES guard xatolari, `FORBIDDEN` | AC41, AC42, Q7, D1 |

`{command}` (B13, `OperatorBookingCommand`): `confirm_no_show`, `reject_no_show`, `complete_with_evidence`, `drop_off`, `require_return`, `return_to_sender`, `resolve_custody_case` — `ops.booking_command` (operator+); `cancel` — `ops.booking_cancel` (admin+); `finalize_fee` — `finance.fee_finalize` (finance roli; ulanguncha super_admin, Q17). Pul ta’sir qiladigan buyruqlar production invariantlari buzilganda `503 PRODUCTION_INVARIANTS_FAILED`. Hech biri guard yoki lock tartibini chetlab o‘tmaydi.

DTO:
- `BookingDTO`: `id (bkg_)`, `service_type`, `service_status`, `cash_status`, `commission_status` (Q16: C’ga hech qachon ko‘rsatilmaydi; event’larda ham — N2), `version`, `trip_id`, `listing_ids {request?, supply?}`, `accepted_proposal_version_id`, `quantity`, `price_basis`, `unit_price_minor`, `total_minor`, `currency`, `payment_method`, `pickup {stop, window_start, window_end, eta_window?}`, `dropoff {…}`, `driver {…, vehicle, contact_phone?}` (C’ga), `client {id, display_name, contact_phone?}` (D’ga), `parcel_contacts? {receiver_phone?}` (D’ga), `contact {phones_visible, visible_from?, visible_until?, chat_thread_id}` (**wave 1.6, Q44 — spec §16 telefon qoidasini almashtiradi; egasi A4**: accept → start oralig‘ida `contact_phone`/`receiver_phone` = `null`, `phones_visible=false`, aloqa chat + tracking oynasi + “keldim” signali; start’da (passenger `onboard` / boarding code, parcel `picked_up`) ishtirokchi telefonlari ochiladi; terminal holatdan 24 soat keyin yana `null`; parcel qabul qiluvchi telefoni driverga faqat `picked_up`dan keyin; **jo‘natuvchi telefoni driverga hech qachon**; support/SOS har doim; `display_name` start’gacha ism (first name) yoki anonim yorliq, to‘liq ism emas), `fee {policy_id, policy_kind, fee_bps, commission_minor, net_minor}` (faqat D va O), `no_show_review? {status, reported_at}`, `custody_case? {status, opened_at}`, `policy_versions`, `cancellation_policy_summary`, `cancelled? {by_side, reason_code, at}`, `created_at`.
- `BookingCancel`: `expected_version`, `reason_code`, `comment?`.
- `BookingActionRequest`: `expected_version`, `code?` (6 raqam), `evidence_file_ids?`, `note?`, `contact_attempts?[{at, channel}]` (report_no_show), `observed_at?`.
- `BookingCodesDTO`: `codes[{kind, code, valid_until}]` — kod saqlanmaydi, `crypto.derive_proof_code` (maxsus subkey, ADR-0018).
- `CashReceiptReport`: `expected_version`, `amount_minor`, `reported_at`, `note?`. `CashReceiptDecision`: `expected_version`, `comment?`. `CashReceiptDTO`: `id (csh_)`, `reported_by_side`, `amount_minor`, `status`, `reported_at`, `decided_at?`.
- `AmendmentCreate`: `expected_version`, `changes {pickup_stop_id?, dropoff_stop_id?, pickup_window_*?, quantity?, unit_price_minor?}`, `reason`. `AmendmentDecision`: `expected_version`. `AmendmentDTO`: `id (amd_)`, `status`, `author_side`, `changes`, `new_total_minor`, `fee_delta_minor` (D; bitta mavjud hold o‘zgaradi), `expires_at`.
- `OperatorBookingCommandRequest`: `expected_version`, `reason` (majburiy), `evidence_file_ids?`, `fee_decision? {mode: capture|release|partial, amount_minor?}`.

### Wave 2 — A4 implementatsiyasi (15.09.2026)

**Endpointlar (mounted, `app/modules/bookings/api.py`):** P8 `POST /proposals/{thread_id}/accept` → **201** `Envelope[BookingDTO | BookingClientDTO]`; B1 `GET /bookings/{id}`; B2 `GET /me/bookings`; B3 `POST /bookings/{id}/cancel`; B4 `POST /bookings/{id}/actions/{action}`; B5 `GET /bookings/{id}/codes`; B6 `POST /bookings/{id}/cash-receipts` (201), `…/cash-receipts/{receipt_id}/acknowledge`, `…/contest`; B9 `POST /bookings/{id}/amendments` (201); **B9r `GET /bookings/{id}/amendments`** (ishtirokchilar; qarshi tomon javob berishi kerak bo‘lgan so‘rovni shu yerdan topadi — wave 4d, additiv); B10 `POST /amendments/{id}/accept`, `…/reject`, `…/withdraw`; B12 `GET /admin/bookings?queue=awaiting_confirmation|no_show_review|custody_case|hold_escalation` (`ops.view`); B13 `POST /admin/bookings/{id}/commands/{command}` (`OPERATOR_COMMAND_CAPABILITY`); T9 `POST /trips/{trip_id}/actions/{start_boarding|depart|complete|interrupt|resume|cancel}` (driver `trip.operate`; operator `ops.booking_command`, cancel `ops.booking_cancel`); T10 `GET /trips/{trip_id}/manifest` (driver `trip.operate`, staff `ops.view`). Barcha buyruqlar `run_command` (Idempotency-Key, savepoint, retry); B4 proof urinishlari `run_command(..., after_command=...)` hook’i bilan savepoint rollback’idan keyin shu tranzaksiyada hisoblanadi (spec §11).

**DTO’lar:** `BookingClientDTO` (mijoz; **`commission_status` va `fee` kalitlari yo‘q**, Q16) va `BookingDTO(BookingClientDTO)` (driver/staff; `commission_status`, `fee {policy_id, policy_kind, fee_bps, commission_minor, net_minor}`). `viewer_side`; `driver {id, display_name, vehicle {vehicle_class, seat_capacity, make_model, color, plate_masked, plate_number?}, contact_phone?}`; `client {id, display_name, contact_phone?}`; `parcel_contacts {receiver_name?, receiver_phone?}`; `contact {phones_visible, visible_from?, visible_until?, chat_thread_id? (A7), support_available}`; `no_show_review?`, `custody_case?`, `cancelled? {by_side, reason_code, fault_side?, at}`, `policy_versions {listing_version, listing_terms_version, cancellation_policy}`. `AcceptRequest {proposal_version_id, expected_listing_version | expected_listing_terms_version}` (Q54 alias; ikkalasi berilsa teng bo‘lishi shart, aks holda 422/400 validatsiya).

**Accept lock ketma-ketligi (implementatsiya):** `users` (mijoz+driver, `FOR NO KEY UPDATE`, id ASC) → `trips` (`FOR NO KEY UPDATE`) → `listings` request+supply (id ASC) → thread + joriy versiya → trip segmentlari (rezerv, trip lock ostida) → [listing’ning boshqa ochiq thread’lari] → booking insert → allocations insert → wallet (`FOR UPDATE`, A3) → hold insert. Tekshiruvlar: Q21 eligibility, Q54 `terms_version`, trip `planned` + `booking_cutoff_at > now`, route/occurrence snapshot, `version_demand` rezervi, 0 bps → exempt (hold yo‘q), aks holda `hold_fee(fee_policy_id)`.

**Q44 ko‘rinish tanlovlari (integrator bahosi, BR tekshiruvi uchun belgilangan):**
- *Staff ko‘rinishi telefonlarni ko‘rsatadi, API audit qatori yozadi* — Q43/Q44 ishtirokchilar orasidagi oshkor qilishni cheklaydi; staff support/SOS vazifasi (Q44 “support har doim”) bilan mos, audit bilan. **Mos.**
- *To‘liq davlat raqami `awaiting_pickup`dan boshlab* (`views.PLATE_VISIBLE_STATUSES`) — bu **accept’dan keyin, lekin xizmat start’idan oldin**. Q43 raqamni faqat accept’gacha taqiqlaydi; Q44 start’gacha faqat **telefon**ni cheklaydi — raqam yo‘lovchi to‘g‘ri mashinaga chiqishi uchun zarur (spec §16, xavfsizlik). **Q43/Q44 matniga mos, lekin ADR-0020 ruhi (platformadan tashqari aloqa) nuqtai nazaridan BR ko‘rib chiqsin** (raqam orqali egasini topish xavfi past, lekin nol emas).
- *Delivery code jo‘natuvchiga ko‘rsatiladi, u qabul qiluvchiga ulashadi* — kodlar telefon emas; jo‘natuvchi telefoni driverga ko‘rinmaydi (Q44), qabul qiluvchi telefoni driverga faqat `picked_up`dan keyin. **Mos.** (Share-link orqali qabul qiluvchi ko‘rinishi — A13.)
- Telefonlar start’da (passenger `onboard`, parcel `picked_up`) ochiladi, terminaldan 24 soat keyin yashiriladi (`rules.CONTACT_HIDE_AFTER_TERMINAL`). **Mos.**

**Pilot cheklovlari:** amendment faqat `quantity` va `unit_price_minor` (boshqa maydon `400 VALIDATION_ERROR reason=pilot_amends_quantity_and_unit_price_only`; TTL 2 soat). **Accept’da detour qo‘shish rad:** `409 ROUTE_MISMATCH reason=detour_insertion_not_supported` — A1 insertion API’lari chiqquncha (wave 2.1); Q46 bilan mos (production’da router yo‘q). Shu sababli **AC13 qayta tekshiruvi (tugash vaqti uzayishi) test qilinmagan**. Signal event’lari (staff): `booking.confirmation_overdue` (24 soat), `wallet.hold.escalation_due` (48 soat).

### Wave 2.1 — o‘zgarishlar (15.09.2026, Q59–Q73; implementatsiya egalari kartalarda)

**Yangi/qayta ishlatiladigan xato kodlari (`app/contracts/errors.py`):**
| Kod | HTTP | Qayerda | Manba |
|---|---|---|---|
| `TRIP_NOT_STARTED` | 409 | B4 `board` / `pick_up` trip `planned` (yoki `interrupted`/terminal) bo‘lsa | BR 4, `state_machines.service_start_allowed` |
| `TRIP_STOPS_LOCKED` | 409 | T7 `PATCH /trips/{id}` `stops`, trip’da bironta allocation bo‘lsa (inactive ham) | Q63 |
| `PROOF_REISSUE_LIMITED` | 429 | B5a self-service reissue limiti; `details {retry_after_s, reissues_left}` | BR 3, `proofs.reissue_decision` |
| `INTEGRITY_CONFLICT` | 409 | DB qoidasi rad etgan har qanday v2 buyruq (`details {reason}`) | `db_errors.py` |
| `VEHICLE_NOT_ELIGIBLE` (mavjud) | 409 | P8 accept: trip vehicle’i `approved` emas — faqat yangi bron | Q61 |
| `ROUTE_MISMATCH` (mavjud) | 409 | P8 accept: versiyada detour quote → `details.reason = "detour_not_available"` (barcha muhitlar) | Q62 |
| `NO_SHOW_REVIEW_PENDING` (mavjud) | 409 | T9 `cancel`: tripning bironta bronida pending no-show review (`details.bookings[]`) | Q19, Q7 |
| `TRIP_HAS_UNRESOLVED_BOOKINGS` (mavjud) | 409 | T9 `cancel` **har qanday trip holatida**: `state_machines.booking_blocks_trip_cancel` | BR 4 |
| `PRODUCTION_INVARIANTS_FAILED` (mavjud) | 503 | W top-up tasdiqlash, kredit adjustment, amendment `adjust_hold` (delta > 0) — production’da Q48 gate o‘tmaguncha | Q70, A3 |

**DB xatolari envelope’i (integrator, `app/api/v2/web.py::db_error_handler`, `app.main` faqat `/api/v2`):** servisdan qochib chiqqan non-retryable `DBAPIError` → `app.contracts.db_errors.map_db_error` → `ErrorEnvelope`. Ustunlik: `diag.constraint_name` (`CONSTRAINT_RULES`: `trip_stops_locked` → `TRIP_STOPS_LOCKED`, `booking_snapshot_frozen` → `INTEGRITY_CONFLICT`, `approver_not_finance_staff` → `403 FORBIDDEN`, `q48_gate_money_refused` → `503 PRODUCTION_INVARIANTS_FAILED reason=gate_failed`, `flag_enable_source_refused` → `500 SERVER_ERROR`) → eski trigger xabari prefiksi (0053 flag gate → 503, 0048 snapshot → 409, `LEDGER_SOURCE_INVALID` → 500, `platform_environment:` → 500) → SQLSTATE (`23505/23P01/23503/23514/23001` → `409 INTEGRITY_CONFLICT`; `40001/40P01/55P03/57014` va `08*/53*/57*` → `503 SERVICE_UNAVAILABLE`; `23502`, `42501` → 500) → `500 SERVER_ERROR reason=database_error`. `details` faqat `{reason}` — DB matni, constraint va SQL hech qachon javobda emas (log’da). Bunday javob idempotency yozuvida saqlanmaydi (tranzaksiya rollback) — shu kalit bilan qayta so‘rov buyruqni qayta bajaradi. v1 yo‘llari o‘zgarmagan (exception qayta ko‘tariladi). Deferred trigger xatolari endi “generic 500” emas (WAVE2 kartasi §1.10 eslatmasi eskirdi).

**Endpoint/DTO o‘zgarishlari:**
- **B5a (yangi, A4):** `POST /bookings/{booking_id}/codes/{kind}/reissue` — kod egasi (passenger → `boarding_code`; sender → `pickup_code|delivery_code|return_code`), driver `403`; body `{reason?}`; `Idem Y`; javob `BookingCodesDTO` (faqat yangi kod); xatolar `PROOF_REISSUE_LIMITED`, `INVALID_STATE_TRANSITION` (proof allaqachon qabul qilingan), `FORBIDDEN`, `NOT_FOUND`. Operator: B13 `{command} = reissue_proof_code` (`ops.booking_command`, `reason` majburiy, `OperatorBookingCommandRequest.proof_kind` qo‘shiladi). Event `booking.proof_code.reissued {service_type, proof_kind, code_rotation, requested_by_side}` (kodsiz, barcha ishtirokchilar).
- **B5 (Q65):** delivery kodi jo‘natuvchiga qaytarilganda `Envelope.warnings[{code: "DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY", field: "codes.delivery_code"}]`.
- **B4 `deliver` (Q65):** bron `delivered`da qoladi (avtomatik `completed` va capture yo‘q). Jo‘natuvchi B4 `complete` bilan tasdiqlaydi; `DELIVERED_OPERATOR_QUEUE_AFTER` (24 soat) o‘tgach B12 `awaiting_confirmation` navbatida, operator B13 `complete_with_evidence`.
- **B12 (Q66, Q74):** `queue` qiymatlari `enums.AdminBookingQueue` — qo‘shimcha `finance_review` (xizmat yakunlangan, komissiya `held`, sabab `CommissionReviewReason`). **Q74:** A12 dispute probe ro‘yxatdan o‘tmaguncha pilotda **har** yakunlangan bron shu navbatga tushadi; finance B13 `finalize_fee` bilan yopadi (AC20 — bitta capture). A12 probe’ni ro‘yxatdan o‘tkazgach (wave 3) bu navbat `dispute_module_unavailable` sababi bilan to‘lmaydi: `clear` → yakunlash tranzaksiyasida capture, `open` → capture kechiktiriladi (finance navbatiga tushmaydi); staff event `commission.finance_review_required {booking_id, reason_code, amount_minor, currency}`. Admin ro‘yxat/tafsilot javobida telefon ko‘rsatilsa audit qatori (telefon qiymatisiz): bronlar — `audit_logs.action = "booking_contacts_viewed"` (A4, B1/B12 staff); listinglar — `"listing_contacts_viewed"` (A1, L2 staff ko‘rinishi parcel sender/receiver telefonlari bilan, `marketplace.service.record_staff_listing_contact_view`).
- **`BookingDTO.driver.vehicle` (Q64):** shakli `dto.BookingVehicleDisclosureDTO {vehicle_class, seat_capacity, make_model, color, plate_masked, plate_number?, plate_number_visible_from?}`; `plate_number` faqat `disclosure.full_plate_visible` (trip `boarding` yoki bron `pickup_window_start`ga ≤ 30 daqiqa) bo‘lganda, aks holda `null`; staff har doim (audit). Wave 2 dagi “`awaiting_pickup`dan boshlab” qoidasi (yuqoridagi Q44 bahosi) almashtirildi.
- **Listings/Proposals (Q68, A1):** `PassengerDetails.amenities[]` — `enums.Amenity`; `ParcelDetails.parcel_type`, `accepted_parcel_types[]` — `enums.ParcelType`; boshqa qiymat `400 VALIDATION_ERROR` (erkin matn filtri bu maydonlardan olib tashlanadi). `ProposalThreadDTO.booking_id` to‘ldiriladi (`bookings.service.booking_public_id_for_proposal_version`). P5 band tekshiruvi narx yoki pickup/dropoff bekati o‘zgarsa (Q67). P9 sahifalash: expire thread’lar sababli `next_cursor` erta `null` bo‘lmaydi.
- **F3 (Q72, A2):** v2 xizmat flag’ini yoqish faqat shu endpoint orqali (DB marker); psql/migratsiya bilan yoqish DB’da rad.
- **Chat (A7, wave 3):** `contact_filter.scan(text, mask_proof_codes=True)` — 6 xonali kodlar `proof_code` kategoriyasi bilan maskalanadi.

**Wave 2.1 yakuniy implementatsiyasi (integrator, agent hisobotlaridan, 15.09.2026):**
- **Marketplace (A1):** `ProposalParcel.receiver: ContactDetails {name, phone} | null` va `ProposalVersionDTO.receiver` — trip-offer parcel qabul qiluvchisi; **faqat mijoz tomoni** ko‘radi (Q43/Q44), driverga hech qachon; DB `proposal_versions.receiver_name/receiver_phone` (0054). `PassengerDetails.amenities: list[Amenity]`, `ParcelDetails.parcel_type: ParcelType | null`, `accepted_parcel_types: list[ParcelType]`, `ListingPublicDTO.parcel_type: ParcelType | null` — qat’iy enum (Q68), boshqa qiymat `400 VALIDATION_ERROR`.
- **Wallet (A3):** W8 (adjustment yaratish/posting), W16 (ikkinchi tasdiq), W17 (reject) va top-up tasdiqlash — approver effektiv rollarida (`users.role` yoki faol `user_roles`) `finance`/`super_admin` bo‘lmasa `403 FORBIDDEN details.reason = "approver_not_finance_staff"` (DB backstop 0055). Production’da Q48 gate o‘tmasa top-up tasdiqlash, kredit adjustment va `adjust_hold` (delta > 0) `503 PRODUCTION_INVARIANTS_FAILED`, `details.failed` ichida `"q48_money_gate"`; debit adjustment va commission reversal gate’dan ozod (Q70 talqini). Readiness/gate hisobotida 7 ta check (DATA_MODEL 0055).
- **Bookings (A4):** B5a `POST /bookings/{booking_id}/codes/{kind}/reissue` → `Envelope[BookingCodesDTO]` (faqat yangi kod). B13 `OperatorBookingCommandRequest.proof_kind: ProofKind | null` — `reissue_proof_code` uchun majburiy. B12 `queue` — `enums.AdminBookingQueue` (`awaiting_confirmation`, `no_show_review`, `custody_case`, `hold_escalation`, `finance_review`). Q66 amalda: A12 probe yo‘q **va** `disputes_v2` jadvali mavjud bo‘lsa → yakun + `finance_review`; jadval yo‘q bo‘lsa → odatdagi capture (`bookings.service.dispute_state`; ochiq savol — WAVE1_CARDS “Wave 2.1 yakuni”).
- **Flags (A2):** F3 yozuvi `geo.service.mark_flag_change_source` markeri bilan; psql/migratsiya bilan yoqish 0057 guard’ida rad.
- **v1 (H1, Q15, additiv):** `POST /api/v1/admin/drivers/{id}/block` body `AdminDriverBlock {reason?, emergency: bool = false}` (`emergency=true` faqat super_admin, aks holda v1 `403 FORBIDDEN`); javob `data`ga additiv maydonlar `block_type`, `v2_eligibility_blocked`, `v2_active_trip_count`, `v2_active_booking_count`. Faol v2 biznesli driverda default — faqat yangi biznes bloki. v1 OpenAPI: 93 operatsiya o‘zgarmagan, faqat `AdminDriverBlock.emergency` schema maydoni qo‘shilgan. Batafsil — `docs/API_GUIDE.md`.
- **OpenAPI soni (15.09.2026):** v1 93, v2 87, prefikssiz 2 (`/health/live`, `/health/ready`).

## 9. Wallet, top-up, ledger, komissiya (egasi A3)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| W1 | `GET /wallet` | `wallet.view_own` | — | `WalletDTO` | — | — | — | AC19 |
| W2 | `GET /wallet/transactions` | `wallet.view_own` | cursor | `list[LedgerLineDTO]` | — | — | `INVALID_CURSOR` | §9.4 |
| W3 | `POST /wallet/topups` | `wallet.topup_request` | `TopupCreate` | `TopupDTO` (`pending`) | Y | — | `VALIDATION_ERROR` | AC24 |
| W4 | `GET /wallet/topups` | `wallet.view_own` | cursor | `list[TopupDTO]` | — | — | — | — |
| W5 | `GET /admin/topups` | `finance.reports` | `?status&cursor` | `list[TopupAdminDTO]` | — | — | — | — |
| W6 | `POST /admin/topups/{topup_id}/approve` | `finance.topup_approve` (finance roli; ulanguncha super_admin — Q17; katta summa ikkinchi, boshqa xodim) | `TopupApprove` | `TopupAdminDTO` | Y | Y | `TOPUP_REFERENCE_DUPLICATE`, `SECOND_APPROVER_REQUIRED`, `VERSION_CONFLICT`, `INVALID_STATE_TRANSITION` | AC23 |
| W7 | `POST /admin/topups/{topup_id}/reject` | `finance.topup_approve` | `TopupReject` | `TopupAdminDTO` | Y | Y | `INVALID_STATE_TRANSITION` | AC24 |
| W8 | `POST /admin/ledger/adjustments` | `finance.adjustment` (chegaradan katta — `pending_second_approval`, W16) | `LedgerAdjustmentCreate` | `201 LedgerTransactionDTO` \| **`202 LedgerAdjustmentDTO`** (ikkinchi tasdiqlovchi kerak — W16; wave 1 implementatsiyasi) | Y | — | `LEDGER_UNBALANCED`, `REVERSAL_EXCEEDS_CAPTURED`, `SECOND_APPROVER_REQUIRED` | AC25, D4 |
| W9 | `GET /admin/finance/reports/{report}` | `finance.reports` | `?from&to&corridor_id` | `FinanceReportDTO` | — | — | `NOT_FOUND` (noma’lum report), `VALIDATION_ERROR`; **wave 1 cheklovlari:** `legacy_calculated_fee` → `503 SERVICE_UNAVAILABLE` (`reason=legacy_views_wave5`) wave 5 legacy view’larigacha; `corridor_id` filtri → `400 VALIDATION_ERROR` (`reason=available_with_bookings_wave2`) bronlar paydo bo‘lguncha | §9.4 |
| W10 | `GET /admin/finance/reconciliation` | `finance.reports` | `?date` | `ReconciliationDTO` | — | — | — | §9.4 |
| W11 | `GET /commission/quote` | `proposal.submit_as_driver` | `?corridor_id&service_type&total_minor` | `FeeQuoteDTO` | — | — | `CORRIDOR_NOT_ACTIVE` | AC43 |
| W12 | `GET /admin/commission-policies` | `finance.commission_policy_view` (operator, admin, super_admin) | `?active_at&kind&cursor` | `list[CommissionPolicyDTO]` | — | — | — | K5, Q2 |
| W13 | `POST /admin/commission-policies` | `finance.commission_policy_manage` (**faqat super_admin**) | `CommissionPolicyCreate` | `CommissionPolicyDTO` | Y | — | `COMMISSION_POLICY_OVERLAP`, `COMMISSION_POLICY_RETROACTIVE`, `VALIDATION_ERROR` (standard 0 bps yoki muddatsiz kampaniya), `FORBIDDEN` | K5, Q1, Q2, AC43 |
| W14 | `GET /admin/commission-policies/{policy_id}` | `finance.commission_policy_view` | — | `CommissionPolicyDTO` | — | — | — | — |
| W15 | `POST /admin/commission-policies/{policy_id}/end` | `finance.commission_policy_manage` (super_admin) | `CommissionPolicyEnd` | `CommissionPolicyDTO` | Y | Y | `COMMISSION_POLICY_RETROACTIVE`, `INVALID_STATE_TRANSITION`, `FORBIDDEN` | K5, Q2 |
| W16 | `POST /admin/ledger/adjustments/{adjustment_id}/approve` | `finance.adjustment_approve`; tasdiqlovchi yaratuvchidan **boshqa** xodim (Q17) | `AdjustmentApprove {expected_version, note?}` | `LedgerTransactionDTO` | Y | Y | `SECOND_APPROVER_REQUIRED` (o‘sha xodim), `INVALID_STATE_TRANSITION`, `PRODUCTION_INVARIANTS_FAILED` | AC25, Q17 |
| W17 | `POST /admin/ledger/adjustments/{adjustment_id}/reject` | `finance.adjustment_approve`, so‘rovchidan **boshqa** xodim (Q49) | `AdjustmentReject {expected_version, reason}` | `LedgerAdjustmentDTO` (`rejected`) | Y | Y | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT`, `403 FORBIDDEN` `details.reason=requester_must_withdraw` (so‘rovchi o‘zi) | Q17, Q49 |
| W17a | `POST /admin/ledger/adjustments/{adjustment_id}/withdraw` (**wave 1.6**) | `finance.adjustment`, **faqat so‘rovchi** | `{expected_version, reason?}` | `LedgerAdjustmentDTO` (`withdrawn`, terminal) | Y | Y | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT`, `FORBIDDEN` (so‘rovchi emas) | Q49 |
| W18 | `GET /admin/ledger/adjustments` | `finance.reports` | `?status=pending_second_approval|posted|rejected|withdrawn&wallet_id&cursor&limit` (`enums.LedgerAdjustmentStatus`) | `list[LedgerAdjustmentDTO]` | — | — | `INVALID_CURSOR` | Q17, Q30 |
| W18a | `GET /admin/ledger/adjustments/{adjustment_id}` | `finance.reports` | — | `LedgerAdjustmentDTO` | — | — | `NOT_FOUND` | Q17 |
| W19 | `POST /admin/commission-policies/{policy_id}/confirm` | `finance.commission_policy_manage` (**super_admin**) | `{expected_version, reason}` | `CommissionPolicyDTO` (`confirmed_by`, `confirmed_at`) | Y | Y | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT`, `FORBIDDEN` | Q28 |
| W20 | `GET /admin/finance/signals/split-adjustments` | `finance.reports` | `?from&to&wallet_id&cursor` | `list[SplitAdjustmentSignalDTO]` | — | — | `INVALID_CURSOR` | Q30 |

**Wave 1.5 A3 implementatsiya qaydlari:** `wallet.service.hold_fee(..., fee_policy_id)` — production’da `fee_policy_id` majburiy (A4 uzatadi); `replace_global_standard(..., effective_from)`; `reverse_fee` `actor_capabilities` talab qiladi va HTTP orqali reversal **faqat** adjustment so‘rovlari (W8/W16) orqali. CLI `python -m app.modules.wallet.checks legacy-rate|reconcile` (Q29 pre-deploy, reconciliation). Qaytarish tartibi — `docs/ops/FINANCE_REFUNDS.md` (Q31). Q28 tasdiqlash — W19.

**Wave 1.5 qaydlari (§9):** `LedgerAdjustmentDTO {id (adj_), wallet_id, direction, amount_minor, currency, reason, status (LedgerAdjustmentStatus), requested_by, approved_by?, split_flag? (Q30), ledger_transaction_id?, version, created_at, pending_age_seconds? (wave 1.6 — faqat `pending_second_approval`da)}`.

**Wave 1.7 A3 (Q48/Q55/Q56):** `platform.service.q48_gate_status(session) -> GateReport(ok, passed, checks, failed, as_dict())`; tekshiruvlar: `app_role_not_superuser`, `app_role_cannot_write_balances`, `balance_guard_uses_trigger_depth`, `ledger_source_links_enforced`, `seed_rate_confirmed`. SQL (0052): `public.q48_gate_checks()` (har tekshiruv bir qator — app va DB uchun yagona manba), `public.q48_gate_ok()`, `public.platform_q48_gate_passed()` (A2 trigger’i chaqiradi). Production invariantlarida `q48_money_gate` — faqat yangi biznesni (`hold_fee`) bloklaydi; majburiyatlar (capture/release/reversal) davom etadi. Reconciliation hisobotida `orphan_postings` (manbasiz posting’lar).

**Wave 1.6 A3 implementatsiya qaydlari:** `require_money_invariants(new_business=True)` faqat `hold_fee`da — majburiyatlar (capture/release/reversal) faol global standard policy’siz ham ishlaydi; `ProductionInvariantReport.notices` ga `unconfirmed_seed_policy_active` — faqat ma’lumot, readiness’ga ta’sir qilmaydi (Q28 bloki quote/hold’da qoladi); `platform.service.lookup_idempotent_response(...)` — faqat o‘qiydigan idempotency lookup; muhit markeri trigger’i passenger/card flag’lari `approval_reference`siz yoqilgan bo‘lsa `production`ga o‘tishni rad etadi (Q5, K7). **Q28:** faqat migratsiya seed global standard policy (`created_by IS NULL`) amal qilsa production’da W11 quote va accept’dagi hold `503 COMMISSION_POLICY_UNCONFIRMED`. **Q22:** W1–W4 faol driver akkaunti uchun tasdiqdan oldin/blokda ham ochiq. **Q31:** o‘chirilayotgan haydovchi balansini qaytarish — W8 debit adjustment + dalil.

**v1 moslik (A3):** `GET /api/v1/admin/settings` — o‘zgarishsiz (operator/admin/super_admin), global standard policy’dan. `PATCH /api/v1/admin/settings/driver-commission` — **faqat super_admin** (admin → v1 `403 FORBIDDEN`); yangi global standard versiya; 0% → v1 `400 VALIDATION_ERROR` (0% faqat kampaniya, Q1). Javob shakli o‘zgarmaydi.

`{report}` ∈ `commission_revenue`, `calculated_commission`, `cash_inflows`, `reversals`, `legacy_calculated_fee` (legacy view’dan, §18.2).

DTO:
- `WalletDTO`: `id (wal_)`, `currency`, `posted_balance_minor`, `held_minor`, `available_minor`, `pending_topups_minor`, `as_of` — “komissiya balansi”.
- `LedgerLineDTO`: `transaction_id (ltx_)`, `occurred_at`, `kind (topup|commission_capture|reversal|adjustment)`, `direction`, `amount_minor`, `balance_after_minor`, `reference {type, id}`.
- `TopupCreate`: `amount_minor`, `method (bank_transfer|cash_desk)`, `payer_reference?`, `evidence_file_id?`, `note?`. `TopupDTO`: `id (top_)`, `status`, `amount_minor`, `method`, `created_at`, `decided_at?`. `TopupAdminDTO`: + `driver`, `evidence`, `first_approver?`, `version`.
- `TopupApprove`: `expected_version`, `source_type (bank_statement|cashier_receipt)`, `source_reference`, `received_amount_minor`, `received_at`, `note?`. `TopupReject`: `expected_version`, `reason`.
- `LedgerAdjustmentCreate`: `wallet_id`, `amount_minor`, `direction`, `reason`, `evidence_file_ids[]`, `booking_id?`, `reversal_of_transaction_id?` (bir capture’ga bir nechta qisman reversal mumkin, yig‘indi ≤ captured).
- `LedgerTransactionDTO`: `id (ltx_)`, `reference`, `entries[{account_code, direction, amount_minor}]`, `reversal_of?`, `created_by`, `created_at`.
- `CommissionPolicyCreate`: `kind (standard|campaign)`, `scope {corridor_id?, service_type?}`, `fee_bps` (standard: 1..10000; campaign: 0..10000), `effective_from` (≥ now), `effective_to?` (campaign’da majburiy), `campaign_name?` (campaign’da majburiy), `reason`.
- `CommissionPolicyEnd`: `expected_version`, `effective_to` (≥ now), `reason`.
- `CommissionPolicyDTO`: `id (cmp_)`, `kind`, `scope`, `fee_bps`, `fee_percent` (`"15.00"`), `effective_from`, `effective_to?`, `campaign_name?`, `reason`, `created_by`, `created_at`, `version`, `is_active_now`.
- `FinanceReportDTO`: `report`, `period`, `rows[{date, corridor?, amount_minor, count}]`, `totals`. `ReconciliationDTO`: `date`, `wallets_checked`, `mismatches[]`, `unbalanced_transactions[]`, `overdraft_wallets[]` (production’da bo‘sh bo‘lishi shart).

## 10. Tracking (egasi A6)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| K1 | `POST /tracking/sessions` | `tracking.publish` (obligation), trip driveri, trip `boarding/in_progress/interrupted` | `TrackingSessionCreate` | `TrackingSessionDTO` | Y | — | `FORBIDDEN`, `INVALID_STATE_TRANSITION`, `FEATURE_DISABLED` (faqat yangi trip uchun; boshlangan trip davom etadi) | AC29, AC38 |
| K2 | `POST /tracking/sessions/{session_id}/points:batch` | Sessiya egasi | `PointsBatch` (≤ `MAX_POINTS_PER_BATCH`=100) | `PointsBatchAck` | — (dedup `session_id+seq`) | — | `TRACKING_SESSION_SUPERSEDED`, `TRACKING_BATCH_TOO_LARGE` | AC27–AC29 |
| K3 | `POST /tracking/sessions/{session_id}/close` | Sessiya egasi, S | `{}` | `TrackingSessionDTO` | Y | — | — | — |
| K4 | `GET /bookings/{booking_id}/tracking` | Bron ishtirokchisi (grant oynasida), O | — | `BookingTrackingDTO` | — | — | `TRACKING_WINDOW_NOT_OPEN`, `NOT_FOUND` | AC27, AC28, AC30, AC31, AC44 |
| K5 | `POST /bookings/{booking_id}/tracking-grants` | Bron egasi | `TrackingGrantCreate` | `TrackingGrantDTO` (URL bir marta) | Y | — | `INVALID_STATE_TRANSITION` | AC30 |
| K6 | `DELETE /bookings/{booking_id}/tracking-grants/{grant_id}` | Bron egasi | — | `{}` | — | — | — | AC31 |
| K7 | `GET /public/tracking/{token}` | Public (token) | — | `PublicTrackingDTO` | — | — | `NOT_FOUND` | AC30, AC31 |
| K8 | `GET /ws` (WebSocket) | Auth token | subscribe `{booking_id}` | `tracking.point`, `tracking.stale`, `booking.status_changed` | — | — | close `4401/4403/4404` | AC31, AC34 |

DTO: `TrackingSessionCreate {trip_id, device_id, platform (android|web), app_version}`; `TrackingSessionDTO {id (trs_), status, last_seq, started_at, recommended_interval_s}`; `PointsBatch {points[{seq, captured_at, lat, lng, accuracy_m, speed_mps?, heading_deg?, battery_pct?, is_mock?}]}`; `PointsBatchAck {accepted_seqs[], duplicate_seqs[], rejected[{seq, reason: too_old (>24 soat) | future_timestamp | invalid | payload_conflict}], session_status}` — ACK DB commit’dan keyin; `BookingTrackingDTO {booking_id, freshness (fresh ≤30 s | delayed 31–120 s | lost >120 s | no_data), last_point? {lat, lng, accuracy_m, low_accuracy (>100 m), captured_at, received_at}, eta_window?, window_opens_at?, subject_label}`; `TrackingGrantCreate {scope: recipient_link, ttl_minutes}`; `TrackingGrantDTO {id (trg_), url, expires_at}` — token `crypto.new_secret_token` (≥128 bit), bazada hash; `PublicTrackingDTO {freshness, last_point, eta_window?, status_label}` — `Referrer-Policy: no-referrer`, analytics yo‘q.

**Wave 3 (A6, 16.09.2026) — yakuniy kontrakt (yuqoridagi DTO qatoridan ustun):**
- **DTO’lar `app/contracts/dto.py`da:** `TrackingPointIn {seq ≥ 0, captured_at (offset majburiy), lat −90..90, lng −180..180, accuracy_m int 0..10000, speed_mps int?, heading_deg int 0..359?, battery_pct int 0..100?, is_mock bool}` — birliklar integer (daraja bundan mustasno); `PointsBatchIn {points[≥1]}`; `PointsBatchAck {accepted_seqs[], duplicate_seqs[], rejected[{seq, reason: enums.TrackingPointRejectReason}], session_status}`; `TrackingLastPointDTO {lat, lng, accuracy_m, low_accuracy, captured_at, received_at}`; `TrackingWindowDTO {is_open, reason: enums.TrackingWindowReason, opens_at?}`; `BookingTrackingDTO {booking_id, window, freshness, last_point?, driver_arrived_at?, eta_window_start?, eta_window_end?, eta_is_estimate, subject_label}`; `PublicTrackingDTO {freshness, last_point?, status_label, subject_label}`. **“GPS faol” maydoni yo‘q** — faqat oxirgi ishonchli nuqta freshness’i (§10.5, AC32). `subject_label` = `vehicle_carrying_your_booking` (§10.3).
- `TrackingSessionCreate.platform` — `enums.ClientPlatform` (`android|ios|web`); `TrackingSessionDTO.recommended_interval_s` = `tracking.RECOMMENDED_INTERVAL_SECONDS`.
- **K1:** trip `boarding|in_progress|interrupted`, driver `tracking.publish` (obligation — eligibility blokida ham, D16); trip `FOR SHARE` → oldingi faol sessiya `supersede`. `tracking_enabled` o‘chiq → `403 FEATURE_DISABLED` faqat trip’da hech qachon sessiya bo‘lmagan bo‘lsa (boshlangan trip davom etadi, AC38).
- **K2:** > `MAX_POINTS_PER_BATCH` → `400 TRACKING_BATCH_TOO_LARGE`; eskirgan sessiya → `409 TRACKING_SESSION_SUPERSEDED` (AC29); yopilgan sessiya yoki trip terminal → `409 TRACKING_SESSION_CLOSED` (yangi). Nuqta: `tracking.point_rejection` (`too_old`, `future_timestamp` > 60 s), `(session, seq)` takrori → `duplicate_seqs`, boshqa hash → `payload_conflict`; `quality_flags` (`is_trusted_for_live`) — mock/imkonsiz tezlik/eski nuqta tarixga yoziladi, live marker va freshness’ni o‘zgartirmaydi (AC28). ACK commit’dan keyin.
- **K4:** ishtirokchi uchun oyna yopiq → `403 TRACKING_WINDOW_NOT_OPEN` `details {reason, opens_at?}`; oyna — `tracking.tracking_window` (passenger pickup − 30 daq yoki `onboard`dan `arrived`gacha; parcel `picked_up`dan `delivered`gacha; trip terminal → yopiq). Staff (`ops.view`) — har doim 200 + audit `tracking_viewed` (§10.6). `driver_arrived_at` — A4 `arrive_at_pickup` (“Keldim”) qiymati, GPS’dan avtomatik emas.
- **K5–K7:** `TrackingGrantCreate {scope: recipient_link, ttl_minutes}` (`TRACKING_GRANT_MIN_TTL`..`MAX_TTL`), faqat bron egasi (mijoz / parcel jo‘natuvchisi); token `crypto.new_secret_token`, bazada `secret_token_hash`, URL bir marta. K7: oyna yopiq, grant bekor yoki muddati o‘tgan → `404`; `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- **K8 WebSocket:** REST bilan bir xil scope; server har `WS_PUSH_INTERVAL_SECONDS` (5 s) oyna/grant’ni qayta tekshirib snapshot yuboradi; oyna yopilsa `4403` bilan yopadi (AC31); Redis yo‘q → PG snapshot (AC34); klient fallback — HTTP polling 10–15 s.
- **K9 (yangi):** `GET /admin/trips/{trip_id}/tracking` — `ops.view`, audit `tracking_viewed` → `TripTrackingAdminDTO {trip_id, active_session, session_started_at?, freshness, last_point?}` (A6 modul DTO’si; operator “GPS eskirishi” navbati, §16).
- **Event’lar:** `tracking.stale {trip_id, freshness, last_captured_at}` (A6 worker, epizod bo‘yicha dedup), `tracking.window_opened {booking_id, trip_id, service_type, opens_at}` (A6 worker, bron bo‘yicha dedup). Koordinata hech bir event’da yo‘q.

## 11. Communications (egasi A7)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| N1 | `GET /events` | Auth | `?after=cursor&limit` | `list[EventDTO]` | — | — | `INVALID_CURSOR` | AC33, AC34 |
| N2 | `POST /devices/push-token` | Auth | `PushTokenRegister` | `DeviceDTO` | Y | — | — | §16 |
| N3 | `DELETE /devices/{device_id}` | Egasi | — | `{}` | — | — | — | — |
| N4 | `GET /notifications` | Auth | `?unread&cursor` | `list[NotificationDTO]` | — | — | — | — |
| N5 | `POST /notifications/{notification_id}/read` | Egasi | `{}` | `NotificationDTO` | — | — | — | — |
| N6 | `GET /proposals/{thread_id}/messages` \| `GET /bookings/{booking_id}/messages` | Tomonlar | cursor | `list[ChatMessageDTO]` | — | — | — | §16 |
| N7 | `POST /proposals/{thread_id}/messages` \| `POST /bookings/{booking_id}/messages` | Tomonlar | `ChatMessageCreate` | `ChatMessageDTO` | Y | — | `RATE_LIMITED`, `FORBIDDEN` | §16 |
| N8 | `GET /admin/outbox` | `ops.view` | `?state=failed|dead&cursor` | `list[OutboxEventAdminDTO]` | — | — | — | §16 |
| N9 | `POST /admin/outbox/{event_id}/retry` | `ops.booking_command` | `{reason}` | `OutboxEventAdminDTO` | Y | — | `INVALID_STATE_TRANSITION` | AC33 |

DTO: `EventDTO {id (evt_), event_type, aggregate_type, aggregate_id, aggregate_version, occurred_at, payload}` — payload `EVENT_PAYLOAD_ALLOWLIST` bo‘yicha va chaqiruvchi auditoriyasi uchun `payload_for_audience` orqali (mijozga `wallet.*`/`commission.*` yo‘q, komissiya maydonlari olib tashlanadi — N2, Q16); `PushTokenRegister {platform: web|android, token_or_subscription, app_version}`; `DeviceDTO {id (dev_), platform, created_at}`; `NotificationDTO {id, type, title_key, body_key, params, is_read, created_at, link}`; `ChatMessageCreate {text (≤1000), quick_reply_code?, attachment_file_id?}`; `ChatMessageDTO {id (msg_), author_side, text, quick_reply_code?, attachment?, created_at}` — chat shartnomani o‘zgartirmaydi.

**Wave 3 (A7, 16.09.2026) — yakuniy kontrakt (yuqoridagi DTO qatoridan ustun):**
- **DTO’lar `app/contracts/dto.py`da:** `ChatMessageCreate {text? (≤ 1000), quick_reply_code? (enums.QuickReplyCode), attachment_file_id?}` — `text` yoki `quick_reply_code` majburiy; `ChatMessageDTO {id (msg_), author_side, is_mine, text?, quick_reply_code?, moderation_status, created_at}` — muallif user id/ismi/telefoni yo‘q (Q43); `EventDTO {id (evt_), event_type, aggregate_type, aggregate_id, aggregate_version, occurred_at, payload}`. Qoidalar — `app/contracts/communications.py`.
- **N6/N7 chat:** faqat thread/bron tomonlari (boshqalar `404`). Yozish `communications.chat_writable`: proposal chat faqat thread `open` bo‘lsa, bron chat terminaldan 24 soatgacha → aks holda `409 CHAT_CLOSED` (yangi). Matn `contact_filter.scan(text, mask_proof_codes=True)` — faqat maskalangan matn saqlanadi, `Envelope.warnings[CONTACT_INFO_MASKED]` (6 xonali kodlar `proof_code` kategoriyasi, Q65); moslik yozuvi `marketplace.service.record_contact_filter_hits` (`subject_type = "chat_message"`) buyruqdan keyin alohida commit (R2-b). Tezkor javob shartni o‘zgartirmaydi (`price_agreed` accept emas, §16). `attachment_file_id` → `400 VALIDATION_ERROR reason=chat_attachments_not_available` (wave 3). Chastota > `CHAT_MAX_MESSAGES_PER_MINUTE` → `429 RATE_LIMITED`. Event `chat.message.created {thread_id, thread_kind, message_id, author_side, quick_reply}` — matnsiz.
- **N10 (yangi):** `GET /admin/bookings/{booking_id}/messages` | `GET /admin/proposals/{thread_id}/messages` — `ops.view`, audit `chat_viewed` → `list[ChatMessageAdminDTO]` (+ `author_user_id`, staff ko‘rinishi). **N11 (yangi):** `POST /admin/chat/messages/{message_id}/hide` — `ops.trust_review`, `{reason}`, Idem Y → `moderation_status = hidden_by_staff` (tomonlarga `text = null`), audit.
- **N1/N4/N5 (integrator qarori):** v2 inbox legacy `notifications`da emas, `notification_deliveries` (`channel = in_app`)da — v1 `GET /api/v1/notifications` o‘zgarmaydi. N1 — chaqiruvchiga yetkazilgan event’lar (`payload_for_audience` natijasi, xom payload hech qachon); staff — `STAFF` auditoriyali barcha event’lar. `NotificationDTO.id` — `ntf_`.
- **Auditoriya:** `EventAudience.COMPETING_DRIVER` (ADR-0019 §9) — listing’da ochiq thread’i bor, event thread’ining tomoni bo‘lmagan driver; faqat `proposal.created|superseded|withdrawn|expired`, nusxada faqat `listing_id` (`events.COMPETING_DRIVER_PAYLOAD_KEYS`). `wallet.*`/`commission.*` mijozga hech qachon (N2, Q16).
- **Outbox dispatch (ADR-0012):** `FOR UPDATE SKIP LOCKED`, `consumer_receipts` shu tranzaksiyada, qayta urinish `communications.outbox_retry_delay` (1m, 5m, 15m, 1h, 6h), 10 urinishdan keyin dead-letter → N8/N9. Push payload faqat `PUSH_PAYLOAD_KEYS`; takror push `NOTIFICATION_DEDUP_WINDOW` ichida bittaga; tashqi yuborish DB tranzaksiyasidan tashqarida (lease → commit → yuborish → natija). **N2 `PushTokenRegister.platform`** — `enums.ClientPlatform`. **Ochiq (U3):** real push provayderi (Web Push/FCM/Expo) va xom token saqlash — qarorgacha faqat in-app kanali ishlaydi.

## 12. Trust & support (egasi A12)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| S1 | `POST /bookings/{booking_id}/ratings` | Ishtirokchi | `RatingCreate` | `RatingDTO` | Y | — | `RATING_NOT_ALLOWED`, `RATING_ALREADY_EXISTS` | AC36 |
| S2 | `GET /users/{user_id}/reputation` | Auth | `?service_type` | `ReputationDTO` | — | — | — | AC36 |
| S3 | `POST /bookings/{booking_id}/disputes` | Ishtirokchi (obligation), O | `DisputeCreate` | `DisputeDTO` | Y | — | `DISPUTE_ALREADY_OPEN` | AC26 |
| S4 | `GET /me/disputes` | Auth | cursor | `list[DisputeDTO]` | — | — | — | — |
| S5 | `GET /disputes/{dispute_id}` | Ishtirokchi, O | — | `DisputeDTO` | — | — | — | — |
| S6 | `POST /disputes/{dispute_id}/evidence` | Ishtirokchi, O | `DisputeEvidenceCreate` | `DisputeDTO` | Y | — | `INVALID_STATE_TRANSITION` | §9.5 |
| S7 | `GET /admin/disputes` | `ops.view` | `?status&type&cursor` | `list[DisputeDTO]` | — | — | — | §16 |
| S8 | `POST /admin/disputes/{dispute_id}/{command}` | `start_review`: `ops.dispute_resolve` (operator+); `resolve`/`reject`: **`ops.dispute_decide` (admin+, wave 3.1 — v1 Q13/Q38 pariteti)**; moliyaviy buyruqda + `finance.adjustment` | `DisputeCommand` (+ `cash_outcome?`) | `DisputeDTO` | Y | Y | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT`, `CAPABILITY_REQUIRED`, `VALIDATION_ERROR` (`cash_outcome`) | AC25, AC26 |
| S9 | `POST /blocks` | Auth | `BlockCreate` | `BlockDTO` | Y | — | — | §8.1 |
| S10 | `DELETE /blocks/{user_id}` | Auth | — | `{}` | — | — | — | — |
| S11 | `POST /reports` | Auth | `ReportCreate` | `ReportDTO` | Y | — | `RATE_LIMITED` | §17.3 |
| S12 | `GET /admin/reports` \| `GET /admin/fraud-signals` | `ops.view` | cursor | `list[ReportDTO]` \| `list[FraudSignalDTO]` | — | — | — | §17.3 |

`{command}` ∈ `start-review`, `resolve`, `reject`. DTO: `RatingCreate {subject_side, stars (1..5), comment?}`; `RatingDTO {id (rat_), stars, comment_moderated, published_at?}` (ikkala tomon baholaguncha yoki 7 kun yashirin); `ReputationDTO {user_id, service_type, rating_count, average_rating? (n=0 → null), label (new_verified|rated), completed_bookings, completed_trips}` — adjusted rating ichki; legacy v1 baholari read-only view’dan hisobga olinishi mumkin (Q4); `DisputeCreate {type, description, evidence_file_ids[]}`; `DisputeDTO {id (dsp_), booking_id, type, status, version, opened_by_side, description, evidence[], resolution?, created_at, escalate_at}`; `DisputeEvidenceDTO {author_side, note?, file_ids[], file_urls[] (wave 5 — qisqa muddatli imzolangan havolalar, faqat shu javobni ko‘rishga haqli tomonga; ADR-0018/`file_access`), created_at}`; `DisputeCommand {expected_version, resolution_code?, resolution_text?, reason?}`; `BlockCreate {user_id}`; `ReportCreate {subject_type, subject_id, reason_code, details?}`; `FraudSignalDTO {signal_type, subject, detected_at, status}` — avtomatik hukm yo‘q.

**Wave 5 (integrator, 17.09.2026):** ikkita additiv event — `booking.amendment_requested` (`amendment_id`, `service_type`, `author_side`, `new_quantity`, `new_total_minor`, `currency`, `expires_at`) va `booking.amendment_decided` (`amendment_id`, `service_type`, `author_side`, `status`). Auditoriya — ishtirokchilar va staff; payload’da komissiya maydonlari yo‘q (N2/Q16) va erkin matn yo‘q (§15). `BookingDTO.contact.chat_thread_id` endi to‘ldiriladi (A7 read-only lookup); chat ochilmagan bo‘lsa `null` qoladi — bronni ochish thread yaratmaydi.

**Wave 3 (A12, 16.09.2026) — yakuniy kontrakt:** qoidalar `app/contracts/trust.py`, holat mashinalari `state_machines.DISPUTE`, `TRUST_REVIEW`, `SUPPORT_TICKET`.
- **S3/S8 nizolar:** ochish — ishtirokchi (obligation; bloklangan driver ham, D16) yoki O; `bookings.service.lock_booking` → `disputes_v2` insert (lock tartibi: bookings → bola); bitta faol (booking, type) → `409 DISPUTE_ALREADY_OPEN` (DB: `uq_disputes_v2_booking_type_active`). Bron/trip holati o‘zgarmaydi, “oldingi holatni tiklash” yo‘q; moliyaviy/xizmat buyruqlari alohida (B13, W8). `DisputeCommand.resolution_code` — `enums.DisputeResolutionCode`. `DisputeCreate.description` — kontakt filtri. `trust.BLOCKING_DISPUTE_TYPES` (`service`, `commission`, `payment`, `delivery`) ochiq bo‘lsa yakuniy capture kechiktiriladi.
- **A4 hook’lari:** `trust_support.service.register_booking_hooks()` → `bookings.service.set_blocking_dispute_probe` (`trust.BlockingDisputeProbe`) va `set_payment_dispute_opener` (`trust.PaymentDisputeOpener`, B8 contest → `payment` nizo, `cash_receipts.dispute_id`). Ro‘yxatdan o‘tgach Q74 fallback (`finance_review`) tugaydi: `clear` → capture, `open` → kechiktirish.
- **S1/S2 reyting (§17.2, AC36):** faqat yakunlangan bron, tomon bo‘yicha bitta; ikkala tomon baholagach yoki 7 kundan keyin nashr (`trust.RATING_PUBLISH_AFTER`); izoh kontakt filtridan; `ReputationDTO.label` — `enums.ReputationLabel`, `average_rating` n=0 → `null`; tuzatilgan reyting faqat ichki (`trust.ReputationSummary`). Legacy baholar ko‘chirilmaydi (Q4). Event `rating.published`.
- **Q45 signal navbati (yangi):** S18 `GET /admin/trust/reviews` (`ops.view`, `?status&signal_type&cursor`) → `list[TrustReviewDTO {id (trv_), subject_user_id, signal_type, status, evidence (faqat id va sanoqlar), decision?, decided_by?, decided_at?, version, created_at}]`; S19 `POST /admin/trust/reviews/{review_id}/{command}` (`start-review` | `dismiss` | `action`) — `ops.trust_review`, Idem Y, Ver Y, body `{expected_version, decision? (enums.TrustReviewDecision; action’da majburiy), note}`; S20 `GET /admin/trust/users/{user_id}/strikes` (`ops.view`). Signal turlari `enums.TrustSignalType`: `contact_filter_strikes`, `quick_cancel_after_chat`, `repeated_pair_cancellations`. Avtomatik ban/jarima yo‘q; `warning_issued` → `trust.warning_issued` (foydalanuvchiga), `escalated_to_admin` → admin I5 orqali alohida qaror. Event’lar `trust.contact_strike.recorded`, `trust.review.opened` — faqat staff.
- **Support/SOS (§16, yangi):** S13 `GET /support/contacts` (Auth) → `SupportContactsDTO {available, phone?, hours_text?}` — konfiguratsiya yo‘q bo‘lsa `available=false`; 24/7 yoki javob vaqti va’dasi yo‘q (`trust.SUPPORT_PROMISES_RESPONSE_TIME = False`). S14 `POST /support/tickets` (Auth, Idem Y) `SupportTicketCreate {kind: support|sos, booking_id?, message? (≤ 2000, kontakt filtri)}` → `SupportTicketDTO {id (sup_), kind, status, booking_id?, created_at, acknowledged_at?, resolved_at?}`; `booking_id` faqat o‘z broni (aks holda `404`); `RATE_LIMITED`. S15 `GET /me/support/tickets`. S16 `GET /admin/support/tickets` (`ops.view`, `?kind&status&cursor`). S17 `POST /admin/support/tickets/{ticket_id}/{command}` (`acknowledge` | `resolve`) — `ops.trust_review`, Idem Y, Ver Y. Event’lar: `support.sos.raised`, `support.ticket.opened` (staff, koordinatasiz), `support.ticket.status_changed` (so‘rovchiga).
- **I4 `DELETE /me`:** `bookings.service.blocking_state_for_user` + `wallet.service.blocking_state_for_user` + `trust_support.service.blocking_state_for_user` (ochiq nizolar, ochiq SOS) → `409 ACCOUNT_DELETION_BLOCKED` `details`; aks holda v1 o‘chirish servisi qayta ishlatiladi. v1 `DELETE /api/v1/auth/me` ham trust tekshiruvini oladi (javob shakli o‘zgarmaydi, `details` additiv).
- **S9–S12 (wave 6 da bajarildi, 17.09.2026):** `POST /blocks` (`BlockCreate {user_id}` → `BlockDTO`, Idem Y, idempotent va **jim**: bloklangan tomonga xabar berilmaydi), `GET /blocks`, `DELETE /blocks/{blocked_user_id}` (idempotent), `POST /reports` (`ReportCreate {subject_type: user|listing|booking|chat_message, subject_id, reason_code, details?}` → `ReportDTO`; `details` kontakt filtridan o‘tadi, `429 RATE_LIMITED` — kuniga 10), `GET /me/reports`, `GET /admin/reports` (`ops.view`), `POST /admin/reports/{report_id}/review` (`ops.trust_review`, `ReportCommand {expected_version, status, note?}`), `GET /admin/fraud-signals` (`ops.view`), `POST /admin/fraud-signals/{signal_id}/review` (`ops.trust_review`). Fraud signallari `trust_support.scan_fraud_signals` worker vazifasidan keladi (`shared_device_accounts`, `self_dealing_device`, `repeated_pair_bookings`) — **avtomatik hukm yo‘q**: signal faqat operator navbatiga tushadi (§17.3).
- **§8.1 blok effekti:** bloklangan juftlik lentada ko‘rinmaydi (`feed`/`matches`), yangi muzokara `404` (blok oshkor qilinmaydi); mavjud majburiyatlar (faol bron) davom etadi.
- **§16 yangi operator navbatlari (wave 6):** `unanswered_listing`, `stale_tracking`, `ineligible_driver_trip` — `GET /admin/ops/queues/{queue}` orqali, yangi jadvalsiz, faqat o‘qish.
- **§10.8 kvota (wave 6):** `GET /admin/metrics/provider-quota` (`ops.view`) → `list[ProviderQuotaDTO {provider, day, calls, credits, failures, limit, ratio, state: ok|warn|restrict, estimated}]`; `estimated=true` doim — bu Elchi hisobi, provayder hisob-fakturasi emas. GPS qabul qilish bu son sababli hech qachon to‘xtamaydi.
- **§19.3 SLO (wave 6):** `feed_p95_seconds` va `booking_accept_p95_seconds` endi ilovaning o‘z o‘lchovidan keladi (`measured=true`, namuna ≥ 20 bo‘lsa); izohda “bitta worker jarayonining server tomoni” deb aytiladi. Qo‘shildi: `server_error_rate` (§19.2 5xx) va `outbox_oldest_pending_seconds` (outbox lag/retries).

## 12a. Wave 3 integratsiyasi (A0a, 16.09.2026)
- **Ulash:** `app/api/v2/router.py` — tracking (K1–K7, K9, WebSocket `GET /api/v2/ws`), communications (N1–N11), trust_support (I4 `DELETE /me`, S1–S8, S13–S20), marketplace feed (M1–M5). Method+path to‘qnashuvi, takroriy `operationId` va soyalangan yo‘l yo‘q (`GET /me` identity’da, `DELETE /me` trust_support’da). **OpenAPI:** v1 **93** (o‘zgarmagan), v2 **131**, prefikssiz 2.
- **Q74 → hook’lar:** `configure_v2_ports()` endi `trust_support.service.register_booking_hooks()`ni chaqiradi — ishlayotgan ilovada `dispute_state` `open|clear` qaytaradi, `finance_review` (`dispute_module_unavailable`) navbati to‘lmaydi. Hook ro‘yxatdan o‘tmagan jarayonda (masalan ayrim testlar) Q74 fallback amal qiladi.
- **A6 aniqlashtirishlar:** `TrackingSessionDTO {id, status, last_seq: int | null, started_at, ended_at?, recommended_interval_s}`; `TrackingGrantDTO {id, url: string | null (idempotent replay’da `null` — token qayta ko‘rsatilmaydi), valid_from, expires_at}`. K1: boshqa haydovchining yoki ko‘rinmas trip’i → `404` (FORBIDDEN emas); sessiya yaratish trip bo‘yicha transaction advisory lock bilan ketma-ketlashtiriladi. K4 staff javobida oyna yopiq bo‘lsa ham `last_point` qaytadi (audit bilan) — **ochiq savol** (§10.6 “operatsion vazifa doirasida”).
- **BR M2 (A4):** B13 `finalize_fee` (capture va release) ro‘yxatdan o‘tgan probe ochiq bloklovchi nizo ko‘rsatsa → `409 INVALID_STATE_TRANSITION` `details.reason = "blocking_dispute_open"`; probe yo‘q (Q74) yo‘li o‘zgarmagan.
- **Naqd nizo qarori (A12 + A4):** S8 `resolve` (`payment`) → `resolution_code = paid_confirmed` → `cash_status acknowledged`, `unpaid_confirmed` → `unpaid`; boshqa kodlar va `reject` → `contested` qoladi (`bookings.service.resolve_contested_cash_receipt`). Kontrakt bo‘shlig‘i: `DisputeCommand`da alohida naqd natija maydoni yo‘q (follow-up).
- **BR M3 (A12):** S14 `kind=sos` hech qachon `429` qaytarmaydi — takroriy bosish ochiq hal qilinmagan SOS ticket’ni (shu bron yoki bronsiz) `201` bilan qaytaradi, `press_count`/`last_pressed_at` oshadi, staff qayta xabardor qilinadi; `kind=support` — soatiga 5 ta (`429 RATE_LIMITED`).
- **BR L4/L7/L8 (A12):** commission nizosi event’lari chiqariladi (mijozga `CLIENT_HIDDEN_DISPUTE_TYPES` bilan bormaydi); `dispute.escalation_due` har nizoga bir marta; faqat `proof_code` mosliklari strike/review sanog‘iga kirmaydi; juftlik bekor qilish signali subyekti — bekor qilgan tomon.
- **BR L6 (H1):** v1 va v2 `DELETE /me` yuklangan fayllarni faqat tranzaksiya commit’idan keyin o‘chiradi (rollback’da o‘chirilmaydi).
- **BR L10 (A6):** K5 grant `valid_from` = kuzatuv oynasi ochilish vaqti; oyna ochilishidan 24 soatdan ko‘proq oldin → `400 VALIDATION_ERROR` `details {reason: "grant_too_early", issuable_from}`. **BR L1 (A7):** trip darajasidagi tracking event’lari mijozga faqat uning bronining kuzatuv oynasi ochiq bo‘lsa yetkaziladi.
- **A5:** `dto.FeedPageMeta {next_cursor, limit, ranking_version, match_scope (= feed.MATCH_SCOPE_CONFIRMED_STOPS), degraded[]}`, `dto.FeedMatchDTO`, `FeedReputationDTO`, `TripAvailabilitySummaryDTO` kontraktda; `FeedItemDTO` va `MatchDTO` (+ `group`, `ready_to_accept`, `labels`, `reputation`, `comparable_total_minor`) modul DTO’si (A1 `ListingPublicDTO`ni o‘z ichiga oladi).
- **A7:** `dto.PushTokenRegister`, `DeviceDTO`, `NotificationDTO`, `OutboxEventAdminDTO`, `OutboxRetryRequest`, `ChatMessageAdminDTO`, `ChatHideRequest` kontraktda; **wave 3.1** dan `app/modules/communications/schemas.py` faqat shu kontrakt sinflarini re-eksport qiladi (nusxa yo‘q). A5 uchun ham shunday: `feed/schemas.py` `FeedMatchDTO`/`FeedReputationDTO`/`TripAvailabilitySummaryDTO`/`FeedPageMeta`ni kontraktdan oladi.
- **A12:** `EventType.DISPUTE_ESCALATION_DUE` (`dispute.escalation_due {booking_id, dispute_type, escalate_at}`, faqat staff) — modul hozir event chiqarmaydi (`escalated_at` belgilaydi), chiqarish A12 follow-up. `events.CLIENT_HIDDEN_DISPUTE_TYPES = {commission}` — `dispute.*` mijoz nusxasi `commission` nizolari uchun yuborilmaydi (Q16); modul hozir commission nizosi event’ini umuman chiqarmaydi — kontrakt qoidasi bilan driver/staff’ga chiqarish A12 follow-up. S7 `?escalated=true|false`.
- **A4 (wave 3.1, bajarildi):** `CommissionReviewReason.DISPUTE_RESOLVED` (`dispute_resolved`) — migratsiya `20260916_0062` CHECK’ni kengaytirdi; nizo yopilgach `mark_finance_review_after_dispute` shu sababni yozadi (`commission.finance_review_required` payload’ida `reason_code`). Q74 yo‘li `dispute_module_unavailable` bo‘lib qoladi.
- **A12/A4 (wave 3.1):** `DisputeCommand.cash_outcome` (`enums.CashResolutionOutcome`: `paid`|`unpaid`) — `contested` naqd kvitansiyani nizo qarori bilan yopadi (STATE_MACHINES §6/§8). Qoidalar: `resolution_code` allaqachon natijani anglatsa (`paid_confirmed`/`unpaid_confirmed`) va `cash_outcome` unga zid bo‘lsa → `400 VALIDATION_ERROR details {field: cash_outcome, resolution_code, implied}`; payment nizosi `contested` kvitansiya ustida yopilayotgan bo‘lsa va natija ko‘rsatilmagan bo‘lsa → `400 VALIDATION_ERROR details {field: cash_outcome, cash_status}`; boshqa holatda `cash_outcome` yuborilsa ham xato. Audit qatorida `cash_outcome`, `start_review`da operator izohi `note` sifatida saqlanadi.
- **M1 (wave 3.1):** nizo ochilganda safar xom GPS nuqtalari `tracking_evidence_points`ga ko‘chiriladi (`tracking.service.hold_trip_evidence`), nizo yopilganda hold bo‘shatiladi va 30 kundan keyin nusxa o‘chiriladi (`contracts.tracking.EVIDENCE_RETENTION_AFTER_RELEASE`). API o‘zgarmadi — dalil faqat DB’da.
- **W21-4 (wave 3.1):** trip-offer parcel taklifida mijoz `parcel.receiver`ni berishi **majburiy** (`400 VALIDATION_ERROR details {field: parcel.receiver, reason: receiver_required}`); counter’da oldingi versiyaning qabul qiluvchisi saqlanadi. `pick_up` qabul qiluvchisiz bronni rad etadi (`details {field: receiver}`) — oxirgi himoya chizig‘i.
- **Env (H0, wave 3.1 bajarildi):** `ELCHI_TRACKING_PUBLIC_URL_TEMPLATE`, `ELCHI_SUPPORT_PHONE`, `ELCHI_SUPPORT_HOURS_TEXT` va worker interval o‘zgaruvchilari `.env.example` va `app.env.example`da; private upload turlari `dispute_evidence` (S6 fayllari faqat yuklovchiga bog‘lanadi) va `chat_photo` (`CHAT_ATTACHMENTS_ENABLED` yoqilgunicha 403).

## 13. Operations va growth (egasi A13)

| # | Method / path | Auth / capability | Request | Response | Idem | Ver | Xatolar | AC |
|---|---|---|---|---|---|---|---|---|
| O1 | `POST /listings/{listing_id}/share-links` | Listing egasi | `ShareLinkCreate` | `ShareLinkDTO` | Y | — | `LISTING_NOT_OPEN` | §20.2 |
| O2 | `DELETE /share-links/{share_link_id}` | Egasi | — | `{}` | — | — | — | — |
| O3 | `GET /public/listings/{token}` | Public | — | `PublicListingPageDTO` | — | — | `NOT_FOUND` | §20.2 |
| O4 | `GET /admin/ops/queues/{queue}` | `ops.view` | `?corridor_id&cursor` | `list[OpsQueueItemDTO]` | — | — | — | §16 |
| O5 | `GET /admin/metrics/kpi` | `ops.view` | `?corridor_id&from&to` | `KpiDTO` | — | — | — | §20.4 |
| O6 | `GET /admin/metrics/slo` | `ops.view` | `?from&to` | `SloDTO` | — | — | — | §19.3 |
| O7 | `POST /admin/listings/on-behalf` | `ops.booking_command` | `ListingCreate` + `owner_user_id`, `consent_reference` | `ListingDTO` | Y | — | `CAPABILITY_REQUIRED` | §20.2 |
| O8 | `GET /admin/legacy-orders` \| `GET /admin/legacy-orders/{legacy_order_number}` | `ops.view` | `?status&cursor&limit` | `LegacyOrderViewDTO` | — | — | `NOT_FOUND` | Q4, AC37 |

DTO: `ShareLinkCreate {channel: telegram|generic, ttl_hours}`; `ShareLinkDTO {id (shl_), channel, url, share_text, expires_at, created_at}` — token `crypto.new_secret_token`; `PublicListingPageDTO {kind, service_type, origin_stop_name, destination_stop_name, departure_date, departure_window, total_minor|unit_price_minor, currency, status_open, cta}` — PII yo‘q; `OpsQueueItemDTO {queue, item_type, item_id, corridor, age_minutes, summary}`; `KpiDTO`, `SloDTO` (kichik n’da son bilan); `LegacyOrderViewDTO {legacy_order_number, status, route_summary, engine: "v1", final_price_minor?, legacy_calculated_fee_minor?, currency, flags[unknown_time, unknown_dimensions], created_at, updated_at}` — faqat o‘qish; mutatsiya yo‘q (`LEGACY_OBJECT_READ_ONLY`). O8 egasi A10b (wave 5), UI A9.

**Wave 5 implementatsiyasi (A10b, 17.09.2026):** O8 faqat `legacy_parcel_orders_v` view’ini o‘qiydi (migratsiya 0065) — `orders` jadvaliga ham, biror v2 yozuv jadvaliga ham tegmaydi. Tafsilot yo‘li v1 `order_number` bilan ochiladi (legacy qatorda `public_id` yo‘q); noma’lum raqam → `404 NOT_FOUND`. `route_summary` — “Shahar (tuman) → Shahar”; telefon, ism, aniq manzil yoki yuk fotosi **yo‘q**. `legacy_calculated_fee_minor` — v1 **hisoblagan** komissiya, tushgan pul emas va haydovchi qarzi emas (§18.2). `flags` — v1 umuman saqlamagan narsalar (va’da qilingan oyna, yuk o‘lchamlari); bo‘sh joyga taxminiy qiymat qo‘yilmaydi. Lifecycle vaqtlari DTO’da yo‘q: ular 0066 dan oldin naive edi, DTO esa faqat aware `UtcDateTime` qabul qiladi — kerak bo‘lsa keyingi additiv qadamda qo‘shiladi.

**Wave 4 implementatsiyasi (A13, 16.09.2026 — O1–O7 bajarildi; O8 wave 5 da):**
- **O1** ochiq (`published`) yoki `paused` listing egasiga; bir listingda ko‘pi bilan `SHARE_LINK_MAX_ACTIVE_PER_LISTING = 5` faol havola (`400 VALIDATION_ERROR details {reason: "too_many_active", limit}`), `ttl_hours` 1…336. Token faqat javobda; bazada SHA-256. `share_text` — yo‘nalish, sana/oyna, jami narx va havola; telefon, ism yoki va’da yo‘q.
- **O2** bekor qilish idempotent; qator o‘chirilmaydi (DB guard `share_link_immutable`).
- **O3** autentifikatsiyasiz yagona v2 yo‘li. Noma’lum, bekor qilingan, muddati o‘tgan yoki yopilgan listing → **404** (token borligi oshkor qilinmaydi). Har ochilish `opened_count`ni oshiradi; ko‘ruvchi haqida hech narsa saqlanmaydi. `PublicListingPageDTO` maydonlari yuqoridagi ro‘yxat bilan bir xil — ism/telefon/manzil yo‘q.
- **O4** `OpsQueue` enum: `awaiting_confirmation`, `no_show_review`, `custody_case`, `hold_escalation`, `finance_review` (A4 `admin_queue`), `dispute`, `support_ticket`, `trust_review` (A12). Yangi jadval yo‘q; `summary` faqat xizmat/status/sanoq.
- **O5** `kpi_daily` dan o‘qiladi (worker `operations.refresh_kpi_daily` kunlik hisoblaydi, oxirgi 3 tugagan kunni qayta hisoblaydi). Har metrika `numerator`/`denominator` bilan; `denominator = 0` → `value: null`; `denominator < 30` → `small_sample: true`; `target` §20.4 dan. **`missing_metrics`** — o‘lchanmaydigan metrikalar nomlari: nol sifatida ko‘rsatilmaydi. **Wave 7 dan ro‘yxat bo‘sh** — §20.4 ning barcha 11 metrikasi saqlangan ma’lumotdan hisoblanadi (`booked_seat_km_ratio` hamrohi `seat_km_route_coverage` bilan: masofasi tasdiqlanmagan safarlar ikkala tomondan ham chiqarib tashlanadi va qamrov alohida ko‘rsatiladi — to‘g‘ri chiziqli masofa **hech qachon** yo‘l masofasi o‘rniga qo‘yilmaydi; `net_commission_per_corridor` — `commission_revenue` ledger hisobidagi capture − reversal, **nisbat emas, summa**, hold/top-up/pending daromad kirmaydi va bu **sof foyda emas**, operatsion xarajatlar ayirilmagan). Diapazon ≤ 92 kun.
- **O6** `tracking_freshness` saqlangan nuqtalardan (ketma-ket nuqtalar orasidagi ≤ 30 s ulushi, **barcha** safarlar bo‘yicha), `sample_size` bilan; `feed_p95_seconds` va `booking_accept_p95_seconds` — `value: null`, `measured: false` (ilova so‘rov kechikishini o‘lchamaydi). Diapazon ≤ 31 kun.
- **O7** `ListingCreate` + `owner_user_id`, `consent_reference` (majburiy, bo‘sh bo‘lsa 400). Ega — haqiqiy foydalanuvchi, `created_by_operator_id` va `consent_reference` A1 jadvalida, audit qatori `listing_created_on_behalf`.

## 13a. Staff MFA va sessiya (wave 8 servis, wave 9 API; ADR-0021/§17.6)

**Wave 9 (17.09.2026) endpointlari** — egasi A1; hammasi `Envelope`, buyruqlar `Idempotency-Key` bilan:

| # | Method / path | Auth | Body | Javob | Idem | Xatolar |
|---|---|---|---|---|---|---|
| I6 | `GET /me/mfa` | Staff akkaunt | — | `StaffMfaStateDTO` | — | `FORBIDDEN` (`staff_only`, Q3) |
| I7 | `POST /me/mfa/enroll` | Staff akkaunt | — | `StaffMfaEnrollmentDTO` (**201**, sir va 10 tiklash kodi — faqat bir marta) | Y | `FORBIDDEN` |
| I8 | `POST /me/mfa/step-up` | Staff akkaunt | `StaffMfaCodeCommand` | `StaffMfaStepUpDTO` | Y | `VALIDATION_ERROR` (`invalid_code`), `RATE_LIMITED` |
| I9 | `POST /me/mfa/recovery` | Staff akkaunt | `StaffMfaCodeCommand` | `StaffMfaRecoveryDTO` | Y | `VALIDATION_ERROR`, `RATE_LIMITED` |
| I10 | `POST /admin/staff/{user_id}/mfa/activate` | `staff.mfa_approve` (super_admin) | `StaffMfaCodeCommand` | `StaffMfaFactorDTO` | Y | `FORBIDDEN` (`self_activation`), `NOT_FOUND` (`no_pending_factor`), `VALIDATION_ERROR`, `RATE_LIMITED` |
| I11 | `POST /admin/staff/{user_id}/mfa/reset` | `staff.mfa_approve` (super_admin) | `StaffMfaResetCommand` | `StaffMfaResetDTO` | Y | `FORBIDDEN` (`self_reset`), `CAPABILITY_REQUIRED`, `NOT_FOUND` |

* **Taxmin qilishga qarshi:** 15 daqiqada 5 xato kod → `429 RATE_LIMITED` (`details.reason="too_many_failed_codes"`,
  `retry_after_s`), to‘g‘ri kod ham shu oynada rad etiladi. `audit_only` rejimidagi “omil yo‘q” qatorlari sanalmaydi.
* **Sir bir marta:** `StaffMfaEnrollmentDTO` dan boshqa hech bir DTO da sir, tiklash kodi yoki hash yo‘q.
* **Ikkinchi qurilma:** `enroll` mavjud faol omilni bekor qilmaydi (`StaffMfaStateDTO.active` va
  `pending_activation` bir vaqtda `true` bo‘lishi mumkin); tasdiqlanmagunicha eski omil bilan step-up ishlaydi.
* **Tiklash kodi hech qachon tasdiq emas:** javob faqat `enrollment_allowed` beradi (Q17/Q49).

Wave 8 dagi kontraktga ta’sir qilgan o‘zgarishlar (endpointsiz):

| O‘zgarish | Ta’sir |
|---|---|
| **Staff access token 15 daqiqa** (`staff_access_token_expire_minutes`) | Token **opaque** bo‘lib qoladi, javob shakli o‘zgarmaydi; faqat `expires_in` staff uchun `900`. Marketplace akkauntlari 3600 da qoladi |
| **Step-up** (`identity.mfa.STEP_UP_CAPABILITIES`) | `finance.topup_approve`, `finance.adjustment_approve`, `finance.fee_finalize`, `finance.commission_policy_manage`, `ops.feature_flag_manage`, `platform.policy_manage`, `staff.manage` buyruqlari 5 daqiqadan eski omil tekshiruvi bilan `403 FORBIDDEN` (`details.reason = "step_up_required"`) qaytaradi. **Standart holda o‘chiq** (`staff_mfa_mode=audit_only`) — hozirgi klientlar uchun hech nima o‘zgarmaydi |
| **v1 `§17.6`** | `POST /api/v1/auth/logout` dan keyin o‘sha sessiyaning access tokeni darhol `401`. Javob **envelope’i o‘zgarmadi**. Token yangilangach (`/auth/refresh`) eski access token v1 da **ishlashda davom etadi** (`revoked_reason='rotated'`) — muzlatilgan klientning yo‘ldagi so‘rovlari uzilmasin; v2 va tracking WS avvalgidek qat’iy |
| Yangi capability | `staff.mfa_approve` (faqat `super_admin`) — **boshqa** xodimning omilini faollashtirish |

## 14. Health (egasi A10a, prefikssiz)

| Method / path | Auth | Javob |
|---|---|---|
| `GET /health/live` | Public | `200 {"status":"live"}` |
| `GET /health/ready` | **Faqat monitoring IP’lari** (Caddy allowlist, Q33); tafsilotsiz | `200/503 {"status":"ready"|"degraded"|"unavailable", "checks": {"database", "redis", "migrations", "production_invariants"}}` — **503 faqat** DB yetib bo‘lmasa yoki DB migration head kod head’iga mos kelmasa; Redis yo‘q → 200 `degraded`; production invariant ma’lumot buzilishi (`wallet_required=false`, `test_overdraft_allowed` wallet, muhit markeri nomuvofiq) → `production_invariants: "fail"` + alert, status `degraded` (503 emas); shu vaqtda pul buyruqlari `503 PRODUCTION_INVARIANTS_FAILED` (BR N1) |

`GET /api/v1/health` o‘zgarishsiz.

**Q32 (readiness migratsiya holati):** `checks.migrations` — `ok` (DB head = kod head), `ahead` (DB head kod head’ining ma’lum avlodi, masalan kod rollback’i → **200 `degraded`**), `behind`/`unknown` (DB orqada yoki noma’lum revision → **503**). **Cheklov (A10a implementatsiyasi):** `ahead` faqat kod o‘z migratsiya skriptlarida DB head’ni taniy olsa aniqlanadi; DB head’dan **eskiroq image**ga rollback qilinganda (u yangi revision faylini bilmaydi) holat `unknown` → 503. Rollback runbook’i buni hisobga oladi.
**Wave 1.7 (A10a, Q56, Q57):** javobga `notices: [nomlar]` (masalan `unconfirmed_seed_policy_active`) — faqat ma’lumot, status va HTTP kodni hech qachon o‘zgartirmaydi. Production’da Q48 gate `production_invariants` tarkibida (boshqa muhitda emas). Operator CLI `python -m app.ops.gates status` — bitta JSON (`hooks`, `q48_gate {available, ok, failed}`, `invariant_failures_excluding_q48`, `enabled_v2_service_flags`), app roli bilan, read-only; `deploy.sh` shu natija bo‘yicha qaror qiladi.
**`checks.database: busy`** (A10a): connection pool timeout → 200 `degraded` (DB yetib bo‘lmasa — `unavailable`, 503). Barcha holatlar: `database ok|unavailable|busy`, `redis ok|unavailable|not_configured`, `migrations ok|ahead|behind|unknown`, `production_invariants ok|fail|…` (`app/api/health_probes.py`).

**Detour snapshot (A2/A4, wave 1.5):** `app.contracts.detour.DetourQuote {route_version_id, trip_version, after_seq, extra_s, extra_m, measured_at, expires_at}`; `TripDTO.detour_used_s` (soniya).

---

## 15. R1/R2 (wave 1.6 — Accepted, Q40–Q45)
- **ADR-0019 (R1) Accepted:** P9 `GET /listings/{listing_id}/offers`, `ListingOfferDTO`, narx diapazoni `PRICE_OUT_OF_BAND` — §7. Egasi A1 (endpoint, anonimlashtirish, narx tekshiruvi), A2 (band konfiguratsiyasi va admin endpointlari — A2 kartasida).
- **ADR-0020 (R2) Accepted:** accept’dan oldin DTO’larda kontakt yo‘q (§4 `TripPublicDTO`, §5, §7), kontakt filtri va `warnings` (§7), telefon ochilish qoidalari (§8 `BookingDTO`, `TripManifestDTO`). Spec §16 dagi “tasdiqlanganda telefon” qoidasi foydalanuvchi qarori (Q43–Q44) bilan almashtirildi.
- **Q46:** production’da routing provayderi yo‘q → detour match’lar qaytmaydi (faqat tasdiqlangan bekat match’lari); klient matni buni aytadi, “yo‘lda olib ketadi” va’dasi yo‘q.
