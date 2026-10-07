# ADR-0028 — ELCHI A→B: oraliq nuqtalarsiz, marshrut bo'yidagi pozitsiya modeli

**Holat:** Accepted — maqsadli arxitektura (foydalanuvchi qarori, 06.10.2026) • **Sana:** 06.10.2026 • **Muallif:** A0a
**Almashtiradi (bosqichma-bosqich, §6):** Q27, Q46 (bekat qismi), Q47, Q63, Q88 4-band (bekat uchi `exact`), ADR-0027
§1 dagi «tumandagi faol bekat» nomzodi, spec §6.2 (bekatlar ketma-ketligi) va §6.3 (bekat bo'yicha moslik). Spec
o'zgartirilmaydi — chekinish shu ADR va AGENTS §3 (Q159) da ochiq yoziladi.

## Kontekst
Foydalanuvchi qarori (06.10.2026):

> ELCHI bekatlar tizimi emas. Har bir mijoz buyurtmasi A nuqtadan B nuqtaga, har bir haydovchi yo'nalishi ham A
> nuqtadan B nuqtaga ishlaydi. Oraliq nuqtalar foydalanuvchi yoki operator yaratadigan biznes obyektlari emas.

Ikki yo'l ko'rib chiqildi: (A) oraliq tugunlarni tizim geometriyadan avtomatik yasaydi; (B) tugunsiz, toza A→B.
Foydalanuvchi **B** ni tanladi: avtomatik tugunlar bekat modelini boshqa nom bilan saqlab qolgan bo'lardi.

Hozirgi kodda bekat (`corridor_stops`) quyidagilarning tayanchi:

| Joy | Bekatga bog'liqlik |
|---|---|
| Marshrut | `route_versions` bekatlar ketma-ketligidan quriladi (`prepare_route_preview(stop_api_ids)`), `route_version_stops` |
| Safar | `trip_stop_occurrences` (har bekatga reja vaqti) — kamida 2 ta; ETA bekat vaqtlaridan interpolyatsiya |
| Sig'im | `trip_segment_resources` (bekat juftligi bo'lagi), `booking_allocations.segment_from_seq` |
| Taklif/bron | `proposal_versions`/`bookings.pickup/dropoff_occurrence_seq`, `*_stop_id` |
| Moslik | `/feed`, saqlangan qidiruv, `find_candidates` — bekat id bo'yicha; nuqta eng yaqin bekat bo'lagiga |
| Narx bandi | bekat juftligi bandi (`corridor_price_bands.origin/destination_stop_id`) |
| Koridor rollout | Q47 (≥ 2 faol bekat, 0046 trigger), Q27 (bekat dalili) |
| Admin | operator bekat yaratadi/tasdiqlaydi («tayanch nuqtalar») |
| Native API | `TripCreate.stops`, `ListingCreate.origin_stop_id` |

## Qaror (maqsadli arxitektura)

### 1. Biznes obyektlari
Faqat ikkita joy turi bor: **A** (olish) va **B** (tushirish) — mijoz xaritada belgilagan nuqta (Q88). Haydovchi
yo'nalishi ham A→B (hudud/tuman uchlari, ADR-0027). Operator **oraliq nuqta yaratmaydi, tasdiqlamaydi, tahrirlamaydi**.
Tizim ham oraliq tugun **yasamaydi** — na jadvalda, na xotirada «bekat o'rnini bosuvchi» ro'yxat sifatida.

### 2. Yo'l = tasdiqlangan geometriya
- `route_versions`: `geometry` (LineString), `distance_m`, `duration_s` — yo'lning yagona tavsifi.
- Yo'l koridorning ikki uchidan quriladi (A va B: hudud markazi yoki operator xaritada belgilagan ikki uch). Bir
  nechta yo'l varianti bo'lsa operator **provayder qaytargan muqobil geometriyalardan** birini tanlaydi — oraliq
  nuqta kiritmaydi. Q24/Q46: production'da provayder yo'q ekan, geometriya fixture/import manbasidan, faqat
  tasdiqlangan.
- Yo'l vaqti marshrut bo'yicha chiziqli: `t(x) = duration_s × x / distance_m`. Keyin kerak bo'lsa provayderning vaqt
  profili geometriyaning **atributi** (M qiymatlar) sifatida qo'shiladi — tugun emas.

### 3. Marshrut bo'yidagi pozitsiya
- **`*_position_m`** — tasdiqlangan yo'l boshidan nuqtaning proyeksiyasigacha masofa, metrda, butun son:
  `round(ST_LineLocatePoint(geometry, point) × distance_m)`.
- Mavjud **`*_route_offset_m`** (Q88) o'zgarmaydi — u nuqtadan yo'lgacha **ko'ndalang** masofa.
- Tartib: `pickup_position_m < dropoff_position_m` (Q88 3-band).

### 4. Safar
- Safar: `route_version_id`, **`route_start_m`, `route_end_m`** (yo'lning qaysi qismini bosib o'tadi),
  `planned_start_at` (`route_start_m` dagi vaqt), `planned_end_at`.
- ETA: `planned_start_at + duration_s × (x − route_start_m) / distance_m`; kutish oynasi `pickup_wait_minutes` (Q154,
  Q155 mexanizmi o'zgarmaydi, faqat bekat vaqtlari o'rniga pozitsiya).
- **Q63 o'rniga:** safarda bironta sig'im da'vosi (faol yoki bo'shatilgan) bo'lsa `route_version_id`, `route_start_m`,
  `route_end_m` o'zgarmaydi.

### 5. Sig'im — interval da'volari
- `trip_capacity_claims`: bitta bronning bitta faol da'vosi — `[from_m, to_m)` = `[pickup_position_m,
  dropoff_position_m)` va resurslar (o'rin, bagaj, yuk og'irligi/hajmi).
- Invariant: safar yo'lining **har bir nuqtasi** `x` da `Σ faol da'volar (from_m ≤ x < to_m) ≤ safar sig'imi`. Eng
  katta yuk har doim biror da'vo boshida, shuning uchun tekshiruv faqat shu nuqtalarda. Qaror servisda trip lock
  ostida; DB trigger — himoya chizig'i (trip qatorini `FOR NO KEY UPDATE` bilan oladi, ADR-0017 tartibi buzilmaydi).
- Release kontrakti (ADR-0017 §11) saqlanadi: `active` true→false faqat bir marta; da'vo mazmuni o'zgarmas.

### 6. Moslik
- So'rov ↔ yo'l: ikkala uch koridor radiusida (`max_point_offset_m`, Q88) va `pos(A) < pos(B)`.
- So'rov ↔ safar: `route_start_m ≤ pos(A) < pos(B) ≤ route_end_m`, ETA oynasi, interval sig'imi; yo'ldagi safarda
  `pos(A)` mashinadan oldinda (Q154).
- Moslik sifati — `on_route` + ko'ndalang masofa. Bekat uchiga `exact` (Q88 4-band) yangi ma'lumotda yo'q.
- **Q46 o'rniga:** provayder yo'q production'da moslik faqat tasdiqlangan geometriyaga proyeksiya bilan; detour
  o'lchanmaydi (Q62 o'zgarmaydi).
- Eski `/feed` va saqlangan qidiruv bekat id o'rniga proyeksiya bilan.

### 7. Koridor va narx
- **Q27/Q47 o'rniga:** koridor `pilot`/`active` ga faqat kamida bitta tasdiqlangan yo'l versiyasi bilan o'tadi; bekat
  soni va bekat dalili talab qilinmaydi. 0046 triggerlari forward migratsiya bilan olib tashlanadi (jadval/ustun
  emas — trigger).
- Narx bandi koridor bo'yicha (Q90 maslahat signali o'zgarmaydi). Bekat juftligi bandlari — legacy, faqat o'qish.

## Bosqichlar (expand → migrate → switch → contract, spec §18.3)
Har bosqich oxirida hisobot va foydalanuvchi tasdig'i. Hech bir bosqich `/api/v1` ni yoki native API ni buzmaydi (Q156).

| Bosqich | Mazmun | Qaror kim chiqaradi |
|---|---|---|
| **1. Expand + dual write** (0097) | `trips.route_start_m/route_end_m`, `proposal_versions`/`bookings.pickup/dropoff_position_m`, `trip_capacity_claims` + DB himoyasi; backfill; har accept/bo'shatish/amendment da'voni ham yozadi; DB commit'da «faol allokatsiya ⇔ faol da'vo» tekshiradi | Eski bekat/bo'lak modeli (hech narsa almashtirilmaydi) |
| **2. Switch reads/decisions** (0098, 0099) | Sig'im qarori da'volardan, yangi bron faqat da'vo yozadi (bo'lak modeli bitta bo'lak ichidagi ketma-ket ikki nuqtani ifodalay olmaydi); ETA, accept va yo'ldagi safar pozitsiyadan; yo'nalish rejalashtiruvchisi shu formulada; eski `/feed` va saqlangan qidiruv yo'l bo'yidagi joylashuv bilan; koridor gate'i — tasdiqlangan yo'l; narx bandi koridor bo'yicha | Pozitsiya modeli; bo'laklar faqat ko'zgu |
| **3. Switch writes** | Yo'l A/B uchlaridan (provayder muqobillari); yangi safar `trip_stop_occurrences`/`trip_segment_resources` siz; `*_occurrence_seq` nullable; admin bekat CRUD olib tashlanadi; hudud/tumanni yo'lga joylashtirish bekatsiz (tuman markazi); eski stop matcher (`evaluate_route_match`) olib tashlanadi; native `stops`/`*_stop_id` kirishi nuqtaga tarjima; DTO'da `stops` — legacy, hosila | Pozitsiya modeli yagona |
| **4. Contract** (0101, Q160) | «Bekat» tushunchasi butunlay yo'q: API bekat id ni rad etadi, kod bekat jadvallariga tegmaydi, DB bekat jadvallarini muzlatadi (faqat tarix); hujjat va native handoff yakuni | Pozitsiya modeli yagona va yolg'iz |

Legacy jadval va ustunlar **o'chirilmaydi** (AGENTS §2) — tarix uchun o'qiladi.

## Ma'lumot modeli — 1-bosqich (migratsiya `20261006_0097`)
- `trips.route_start_m`, `trips.route_end_m` — `INTEGER NULL`, `ck_trips_route_span` (`0 ≤ start ≤ end`). Backfill:
  birinchi/oxirgi occurrence bekatining `line_fraction × distance_m`.
- `proposal_versions.pickup_position_m`, `dropoff_position_m` — `INTEGER NULL`; faqat yangi versiyalar (versiyalar
  o'zgarmas, 0044) — eski ochiq versiya accept'da hisoblanadi.
- `bookings.pickup_position_m`, `dropoff_position_m` — `INTEGER NULL`, bir marta yoziladi (NULL → qiymat;
  `trg_bookings_positions_set_once`). Backfill: nuqta yoki bekat proyeksiyasi bron yo'liga.
- `trip_capacity_claims` (trips moduli): `trip_id`, `booking_id`, `from_m < to_m`, resurslar ≥ 0 (kamida bittasi > 0),
  `active`, `released_at`; `uq_trip_capacity_claims_booking_active`. Triggerlar: mazmun o'zgarmas, faqat true→false,
  o'chirish/TRUNCATE taqiq; sig'im (`trip_capacity_claims_within_capacity`, trip lock ostida); bron safari bilan bir
  xil. Backfill: har faol allokatsiyali bronga bitta faol da'vo.
- Dual-write isboti: `trg_booking_allocations_claim_parity` va `trg_trip_capacity_claims_parity` (DEFERRABLE
  INITIALLY DEFERRED) — commit'da har bronda faol allokatsiya bor ⇔ faol da'vo bor.
- Nima uchun 1-bosqichda sig'im triggeri hech qachon yolg'on rad etmaydi: da'vo intervali bron egallagan bo'laklar
  ichida, demak har nuqtadagi interval yuki o'sha bo'lak yukidan oshmaydi, bo'lak yuki esa sig'imdan oshmaydi (0038
  CHECK).

## 2-bosqich — amalga oshirildi (migratsiyalar `20261006_0098`, `20261007_0099`)
- **Sig'im:** qaror `trips.require_claim_capacity` / `claim` (trip lock ostida) — taklif tekshiruvi, accept va amendment
  aniq `[pickup_position_m, dropoff_position_m)` oralig'i bo'yicha. Yangi bron `booking_allocations` va bo'lak
  hisoblagichiga **yozmaydi**: aks holda bo'lak modeli oraliq qabul qilgan bronni `used ≤ capacity` CHECK bilan rad
  etardi. 0098: parity «faol allokatsiya ⇒ faol da'vo» (1-bosqich bronlari ikkalasini birga bo'shatadi); 0054 Q63
  triggerlari da'volarni ham sanaydi. `get_segment_loads` endi da'volardan (har bo'lakdagi eng yuqori yuk) — bo'lak
  bilan ishlaydigan o'quvchilar (lenta, trip DTO) o'zgarmaydi. Xato tafsiloti: `positions` (yangi) + `segments`
  (eski shakl, Q156 additiv).
- **ETA:** `trips.trip_eta_at` — safarning rejalashtirilgan boshlanish va tugash vaqti orasida yo'l oralig'i bo'yicha
  chiziqli (`route_position.eta_at`); bekatdagi to'xtash (dwell) yo'q. Taklif, accept (nuqta ham, eski bekat uchi
  ham), yo'ldagi safar tekshiruvi (Q154: avtomobil va olish nuqtasi metrda) shu bitta qoidada. Yo'nalish
  rejalashtiruvchisi jo'nash va davomiylikni xuddi shu formuladan oladi (occurrence vaqtlari — faqat legacy yozuv).
  Eski stop matcher faqat «qaysi bekat, qaysi tartib»ni aytadi; vaqtni pozitsiya hal qiladi.
- **Moslik:** eski `GET /feed` (`side=requests`) va saqlangan qidiruv — mezon uchlari maydon (bekat → uning tumani,
  tuman, hudud), so'rov yo'lga joylashtiriladi va maydonlar orasidagi oraliqda bo'lishi tekshiriladi (yo'nalish
  lentasi bilan bir qoida). `alternative` faqat vaqt farqi; «yaqin bekat» endi chiqmaydi. Trip-offer tarmoqlari
  (Q138) legacy bo'lib qoldi.
- **Ochiq (3-bosqich):** hudud/tumanni yo'lga joylashtirish hali eski faol bekatlarni nomzod sifatida o'qiydi (tuman
  markazi bilan birga) — tuman chegarasi/markazi bilan almashtiriladi.
- **Koridor gate (0099):** pilot/active koridor uchun yagona shart — kamida bitta `confirmed` yo'l versiyasi (servis +
  0046 funksiyasi qayta yozildi + `trg_route_versions_public_corridor_road`). `start_internal` bekat talab qilmaydi.
  `find_q47_violations` endi «tasdiqlangan yo'l yo'q» koridorlarni qaytaradi (DTO shakli o'zgarmagan).
- **Narx bandi:** `resolve_price_band` faqat koridor bandini o'qiydi; bekat juftligi bandini yaratish yoki qayta
  yoqish rad (`segment_bands_retired`), faqat o'chirish mumkin.

## 3-bosqich — amalga oshirildi (migratsiya `20261007_0100`)
- **Yo'l A/B uchlaridan:** `POST /routes/preview` additiv `corridor_id` + `origin` + `destination` qabul qiladi
  (`geo.prepare_road_preview`); bunday yo'lda `route_version_stops` yo'q. 0100: `geo_route_versions_guard` bekatsiz
  yo'lni tasdiqlashga ruxsat beradi (bekat bo'lsa — 0..n-1 ketma-ketlik, kamida 2). Proyeksiya bekatsiz yo'lda ishlaydi
  (`seq_before/seq_after = None`, vaqt/masofa yo'lning o'zidan).
- **Safar — yo'l oralig'i:** `TripCreate.stops` ixtiyoriy (native eski kirish, faqat legacy «aks»); bo'lmasa
  `route_start_m/route_end_m` (yoki butun yo'l) — `trip_stop_occurrences`/`trip_segment_resources` yozilmaydi.
  `TripPatch` ham oraliqni o'zgartira oladi (da'vo bo'lmasa). Yo'nalish rejalashtiruvchisi faqat shunday safar yaratadi
  va qayta vaqtlaydi.
- **Taklif/accept:** bekatsiz safarda har uch (nuqta yoki eski bekat) yo'ldagi joylashuv sifatida tekshiriladi; seq
  `NULL` (0100: `bookings.*_occurrence_seq` nullable, `ck_bookings_place_known`). Accept ETA'ni versiyadagi pozitsiyadan
  oladi; bekatsiz safarda joylar safar oralig'ida bo'lishi shart (`ROUTE_CHANGED outside_trip_stretch`).
- **Ko'rinishlar:** `BookingStopDTO.occurrence_seq` nullable, `planned_arrival_at` — pozitsiya ETA'si; bekatsiz safar
  manifesti — bronlarning o'z joylari yo'l tartibida; o'rin-km KPI — pozitsiyalar va safar oralig'idan.
- **Maydon joylashuvi:** hudud/tuman yo'lga markazi bilan; eski bekatlar faqat markazi noma'lum tumanda (99/170 tumanda
  tekshirilgan markaz bor — qolgani ma'lumot bo'shlig'i, 4-bosqich).
- **Bekat id tarjimasi:** yangi e'londagi `origin/destination_stop_id` o'sha bekat nuqtasi + tumani bilan nuqta uchiga
  aylanadi. Taklifdagi bekat id faqat e'lon joyining aynan o'zi bo'lsa qabul qilinadi (native haydovchi), aks holda
  `VALIDATION_ERROR listing_ends_are_points` — haydovchi mijoz joyini o'zgartirmaydi; teskari so'rov yaratishda rad.
- **Admin:** `POST /admin/corridors/{id}/stops` → `409 INVALID_STATE_TRANSITION reason: stops_retired`; admin UI'da
  yaratish formasi yo'q, eski nuqtalar ko'rish/tahrir/o'chirish uchun qoladi.
- **Ochiq (4-bosqich):** bekat jadvallariga yangi qatorni DB'da taqiqlash; markazsiz tumanlar; staff uchun A/B yo'l
  qurish UI'si (production'da provayder yo'q — yo'l importi); eski stop matcher faqat occurrence'li eski safarlar uchun.

## 4-bosqich — amalga oshirildi (migratsiya `20261007_0101`, Q160)
Foydalanuvchi qarori (07.10.2026): «bekat tushunchasi umuman kerak emas» — mijoz e'loni faqat A va B nuqta; native API
bekat id ni **rad etadi**, bekat jadvallari **muzlatiladi** (o'chirilmaydi).

- **API (v2):** bekat bilan bog'liq hamma narsa olib tashlandi. Kirishda: `ListingCreate.origin_point/destination_point`
  majburiy (`*_stop_id` yo'q), `ListingPatch`, `ProposalCreate/Counter`, `AmendmentChanges` da bekat id yo'q,
  `TripCreate/TripPatch` da `stops` yo'q (faqat `route_start_m/route_end_m`), `RoutePreviewRequest` faqat
  `corridor_id + origin + destination`, lenta va saqlangan qidiruv uchlari faqat tuman/hudud. `ContractModel`
  `extra=forbid` bo'lgani uchun eski maydon `400 VALIDATION_ERROR` bilan rad etiladi; lentadagi
  `origin_stop_id/destination_stop_id` so'rov parametri ham aniq `400 reason: stops_retired` beradi. Endpointlar olib
  tashlandi: `GET /corridors/{id}/stops`, `GET /stops/search`, `GET/POST /admin/corridors/{id}/stops`,
  `PATCH /admin/stops/{id}`. Javobda: `StopRefDTO`, `stops_count`, `RouteVersionDTO.stops`, `TripDTO.stops`,
  `*_stop` maydonlari yo'q; `BookingStopDTO` → `BookingEndDTO` (`point`, ETA), manifest `TripManifestDTO.places`
  (`ManifestPlaceDTO`), mavjudlik `TripAvailabilityDTO.stretches` (`from_m/to_m` bo'yicha), ochiq sahifa
  `origin_name/destination_name` (tuman), `MatchReason` dan `pickup_at_stop/dropoff_at_stop/nearby_stop/same_stop`,
  `FeedPageMeta.match_scope = "confirmed_roads"`, `listing.published` event'ida bekat id yo'q. Narx bandi faqat koridor
  bo'yicha (bekat jufti yo'q). Tezkor javob kodlari `at_stop`/`clarify_stop` o'zgarmaydi (Q158).
- **Kod:** geo bekat CRUD/qidiruv, bekat matcher (`geo/matching.py`), detour o'lchovi, segment sig'imi
  (`reserve/release/get_segment_loads`), occurrence'lar, trip-offer bekat tekshiruvlari, saqlangan talablar (ADR-0025)
  ning bekat qismi olib tashlandi. Maydon (tuman/hudud) yo'lga faqat markazi bilan joylanadi; markazi noma'lum tuman
  joylanmaydi (zaxira bekat yo'q). Koridor tumanlari — markazi tasdiqlangan yo'lga radius ichida tushganlar, yo'l
  tartibida. Accept: versiya pozitsiyalari safar oralig'ida bo'lishi shart; sig'imni faqat da'vo ushlaydi.
- **DB (0101):** tarix nuqtaga o'tkaziladi (listing/taklif versiyasi/bron uchlari bekat nuqtasi va tumani bilan; ochiq
  e'londan bekat id olib tashlanadi; saqlangan qidiruv bekat → tuman; saqlangan talab versiyasi tuman+nuqta);
  `ck_<jadval>_<uch>_point_required`; `trg_<jadval>_no_new_stop` — hech bir qator yangi bekat id/occurrence seq
  olmaydi (eskilari tarix sifatida qoladi); `corridor_stops`, `route_version_stops`, `trip_stop_occurrences`,
  `trip_segment_resources`, `booking_allocations` ga har qanday INSERT/UPDATE/DELETE `stops_retired` bilan rad;
  1-bosqich parity trigger'lari olib tashlandi. Idempotent; hech narsa o'chirilmaydi.
- **Ma'lum oqibat:** muzlatilgan Android ilovasi (bekat id yuboradi) yangilanmaguncha e'lon/taklif/safar yarata
  olmaydi — handoff `docs/handoff/ADR0028_NATIVE.md`.

## Oqibatlar
- Operator ishidan bekat yuritish yo'qoladi; koridorni ishga tushirish bitta tasdiqlangan yo'lga tushadi.
- Mijoz yo'l bo'yidagi istalgan nuqtadan olinishi mumkin; sig'im aniq bosib o'tiladigan oraliq bo'yicha — bekat
  bo'lagining yaxlitlanishi yo'q (bir xil o'rinni bo'lak ichida ketma-ket ikki mijoz egallay oladi).
- ETA bekat rejasi o'rniga chiziqli yo'l vaqtidan — aniqligi provayder vaqt profiliga bog'liq (ochiq: 2-bosqichda
  `pickup_wait_minutes` oynasi bilan qoplanadi, profil keyin).
- Native ilovalar o'zgarmaguncha legacy kirish (bekat id) tarjima qilinadi; DTO'lar additiv kengayadi.
- Ochiq: native handoff (`docs/handoff/ADR0028_NATIVE.md` — 3-bosqichda), provayder vaqt profili, Q87/Q24 dagi
  production gate'lar o'zgarmaydi.
