# ADR-0027 — Haydovchi yo'nalishi: v1 kabi oddiy kiritish, v2 ichkarida

**Holat:** Accepted (foydalanuvchi qarori, 06.10.2026) • **Sana:** 06.10.2026 • **Muallif:** A0a (integrator)
**O'zgartiradi:** Q42/Q53 ta'siri yo'q; Q63 o'zgarmaydi; spec §7 (booking cutoff) — `boarding`/`in_progress` safarga
yangi bron (Q154) chekinishi; Q88 cheklovlari saqlanadi. Spec o'zgartirilmaydi — chekinish shu ADR va AGENTS §3
(Q150–Q156) da ochiq yoziladi.

## Kontekst
06.10.2026 dagi uchdan-uchgacha sinov (2 mijoz × yo'lovchi/pochta, 1 haydovchi, Toshkent → Qarshi koridori) ko'rsatdi:

1. Haydovchidan safar uchun koridor, marshrut, jo'nash vaqti, o'rin va yuk so'raladi; har safar boshidan. Foydalanuvchi
   v1 dagidek «yo'nalish qo'shish» bilan cheklanishni so'radi: koridor, marshrut, bekat, segment, safar — ichki model
   (Q93), ularni tizim o'zi bajaradi.
2. Lenta haydovchi safarini bilmaydi: mijoz 18:00 so'ragan e'lon 22:00 da jo'naydigan haydovchiga ko'rinadi, lekin
   taklif `TIME_WINDOW_CONFLICT` bilan rad etiladi; haydovchi boshqa vaqt taklif qila olmaydi.
3. Safar yo'lga chiqqach yo'l bo'yidagi yangi so'rovga taklif `BOOKING_CUTOFF_PASSED` — «yo'l-yo'lakay olish» yo'q.
4. **Xato:** nuqtali (Q88) so'rovda taklif interpolyatsiya qilingan ETA bilan o'tadi, accept esa bo'lak boshidagi
   bekat vaqti bilan rad etadi (`ROUTE_CHANGED schedule_changed`) — bekatdan oldingi nuqta hech qachon bron bo'lmaydi.

Android/iOS o'zgartirilmaydi (foydalanuvchi qarori): hamma o'zgarish backend va `mobile-app` (web klient + `/admin`)
da, API faqat **additiv**.

## Qaror

### 1. Haydovchi yo'nalishi (Q150)
- Yangi jadval `driver_directions` (trips moduli): haydovchi, mashina, qayerdan (hudud + ixtiyoriy tuman), qayerga
  (hudud + ixtiyoriy tuman), sig'im (standart — mashinadan), holat `active`/`paused`/`archived`, `version`.
  **Vaqt, koordinata, bekat, koridor, marshrut so'ralmaydi.**
- Yaratishda server koridorni topadi: har ochiq koridorning tasdiqlangan marshrutlarida uchlar joylashtiriladi —
  tumandagi faol bekat, bo'lmasa tuman (hudud) markazi koridor radiusi ichida proyeksiya bilan (Q88 mexanizmi).
  Qayerdan qayerga yo'nalishida (fraction o'sadi) joylashsa koridor mos; bir nechtasi bo'lsa eng yaqini. Topilmasa —
  `ROUTE_MISMATCH` (mahsulot holati: «bu yo'nalishda hali ELCHI yo'li yo'q»).
- Bitta haydovchida bir xil uchli bitta tirik (archived emas) yo'nalish (unique indeks).
- Yo'nalish e'lon emas va mijozga ko'rinmaydi (Q138 o'zgarmaydi). `trips.direction_id` safarni yo'nalishga bog'laydi.

### 2. Yo'nalish lentasi (Q151)
`GET /driver-directions/{id}/requests` — shu koridordagi ochiq mijoz so'rovlari, ularning uchlari yo'nalish
oralig'ida: olish nuqtasi yo'nalish boshlanish tumanida yoki undan keyin, tushirish yo'nalish oxiri tumanida yoki
undan oldin (marshrut bo'yicha). Har element:
- `fit`: `no_trip` (faol safar yo'q — birinchi taklif safar vaqtini belgilaydi), `fits_trip` (faol safar olish
  nuqtasiga mijoz oynasida yetadi), `time_differs` (yetadi, lekin boshqa vaqtda — `pickup_eta` bilan),
  `passed` ko'rsatilmaydi (yo'lda safar nuqtadan o'tib ketgan, Q154);
- `match_type`: `exact` (ikkala uchi yo'nalish tumanlarida) yoki `on_route`.
Mavjud `GET /feed` o'zgarmaydi (native ilovalar shuni ishlatadi).

### 3. Yo'nalishdan taklif (Q152)
`POST /driver-directions/{id}/offers {listing_id, unit_price_minor, message?, pickup_at?}`. Tizim:
1. Yo'nalishning faol safari (`planned`/`boarding`/`in_progress`) bo'lsa — uni ishlatadi.
2. Faol safar bo'sh bo'lsa (bron ham, ochiq taklif ham yo'q, `planned`) va so'rov vaqtiga mos kelmasa — uni yangi
   so'rovga **qayta vaqtlaydi** (mavjud `patch_trip` qoidalari bilan).
3. Faol safar yo'q bo'lsa — yangi safar **yaratadi**: marshrut so'rovning ikkala uchini xizmat qiladigani, bekatlar
   yo'nalish oralig'idagi marshrut bekatlari, jo'nash vaqti = mijozning olish vaqti − olish nuqtasigacha yo'l vaqti
   (eng kamida hozir + 15 daqiqa), sig'im yo'nalishdan, chetlanish 15 daq/5 km, kutish 10 daq (mavjud standartlar).
4. Taklifni mavjud `submit_proposal` orqali beradi (barcha Q-tekshiruvlar o'zgarmaydi). Olish oynasi: mijoz oynasi
   ∩ [ETA − 30, ETA + 30] daqiqa (Android `OfferRules.pickupWindow` bilan bir xil).
5. Safar mijoz oynasiga yetmasa va `pickup_at` yo'q — `TIME_WINDOW_CONFLICT` (`details.eta`), klient «shu vaqtni
   taklif qilish» tugmasini ko'rsatadi; `pickup_at` bilan — vaqt taklifi (§4).

### 4. Vaqt taklifi (Q153)
- Haydovchi (faqat haydovchi) mijoz oynasidan tashqaridagi olish vaqtini taklif qila oladi, safar shu vaqtda nuqtaga
  yetishi shart (ETA ± kutish). **Q157 (06.10.2026):** chegara asimmetrik — oyna boshidan ko'pi bilan 3 soat oldin, oyna
  oxiridan ko'pi bilan 12 soat keyin (`settings.time_proposal_max_early_shift_minutes` / `_late_` — env, kod emas).
  Chegaradan tashqaridagi so'rov lentada ham ko'rsatilmaydi.
- Versiyada `outside_request_window = true` (DB ustuni, DTO maydoni). Mijoz ko'radi: «Haydovchi 22:30 da olishni
  taklif qilmoqda (siz 18:00 so'ragansiz)».
- Bron faqat mijoz roziligi bilan: mijoz shu versiyani qabul qiladi yoki narxni counter qiladi (counter oynani meros
  oladi — mijoz muallif, demak rozi). Mijoz oynani counter bilan tashqariga sura olmaydi (e'lonni tahrirlaydi, Q20).
- E'lon oynasi va muddati o'zgarmaydi: e'lon `departure_window_end` da tugaydi, shu paytgacha qabul qilinmagan vaqt
  taklifi ham tugaydi (pilot cheklovi).

### 5. Yo'lda bron (Q154)
- `boarding` va `in_progress` safarga yangi taklif/bron ruxsat: olish nuqtasi hali oldinda bo'lsa —
  jadval bo'yicha ETA ≥ hozir + 15 daqiqa (`MID_TRIP_MIN_LEAD`) **va** yangi GPS nuqtasi (≤ 10 daqiqa) bo'lsa, u
  marshrutda olish nuqtasidan kamida 2 km orqada (`MID_TRIP_MIN_AHEAD_M`). Aks holda `BOOKING_CUTOFF_PASSED`
  (`details.reason = pickup_passed`). `interrupted` safarga yo'q. `planned` safarda `booking_cutoff_at` o'zgarmaydi.
- Taklif muddati yo'ldagi safarda: `min(hozir + 10 daq, ETA − 15 daq, e'lon muddati)`.
- Yangi bron: safar `boarding`/`in_progress` bo'lsa darhol `awaiting_pickup` (tizim, `mark_awaiting_pickup`); pochta
  `in_progress` safarda shu tranzaksiyada `in_transit` (`trip_departed`, Q139/Q142 talqini — «safar bilan yo'lda»,
  topshirish da'vosi emas). Bron `terms_snapshot.booked_trip_status` ni yozadi.

### 6. Xato tuzatish (Q155)
Accept nuqtali olishni taklif bilan bir xil tekshiradi: interpolyatsiya qilingan ETA ± kutish olish oynasiga tushishi
kerak (`marketplace_service.point_pickup_eta`). Bekat uchli so'rov o'zgarmaydi.

### 7. Moslik (Q156)
- `/api/v1` va mavjud v2 endpointlari o'zgarmaydi; yangi endpointlar va DTO maydonlari additiv.
- Android/iOS kodi tegilmaydi; ular `ignoreUnknownKeys`/`Codable` bilan yangi maydonlarni e'tiborsiz qoldiradi.
  `scripts/gen_native_api.py --check` OpenAPI o'zgargani uchun «stale» bo'ladi — bu Android/iOS dasturchisiga
  handoff (`docs/handoff/ADR0027_NATIVE.md`), agentlar native fayllarni qayta generatsiya qilmaydi.
- Admin (`mobile-app /admin`): haydovchi yo'nalishlari ro'yxati, bronda «vaqt taklifi» va «yo'lda bron» belgilari.

### 8. Interfeysda bekat yo'q (Q158, 06.10.2026)
Foydalanuvchi interfeysi (yo'lovchi, haydovchi, admin) faqat A va B nuqtalar bilan ishlaydi; «bekat» so'zi va bekat tanlash
olib tashlangan. Ichki model (`corridor_stops`, `route_version_stops`, `trip_stop_occurrences`) — marshrut tayanch nuqtalari:
segment sig'imi va ETA uchun, foydalanuvchiga ko'rinmaydi. Q27/Q47/Q46 gate'larini olib tashlash — alohida qaror.

## Ma'lumot modeli (migratsiya `20261006_0096`)
- `driver_directions` — yuqoridagi ustunlar; `ck` uchlar farqli, holat literal, sig'im ≥ 0; partial unique
  `(driver_user_id, origin_region_id, coalesce(origin_district_id,0), destination_region_id,
  coalesce(destination_district_id,0)) WHERE status <> 'archived'`.
- `trips.direction_id` (nullable FK, `ON DELETE SET NULL` emas — yo'nalish o'chirilmaydi, faqat archived).
- `proposal_versions.outside_request_window boolean NOT NULL DEFAULT false`.
Idempotent; backfill yo'q.

## Oqibatlar
- Haydovchi: «Qayerdan → Qayerga» → lenta → narx → taklif. Safar, bekat va vaqt — avtomatik.
- Bitta yo'nalishda bir vaqtda bitta faol safar (vehicle EXCLUDE baribir ustma-ust safarni rad etadi).
- Ochiq: haqiqiy GPS bilan yo'lda bron dala sinovi; mijoz tomonida vaqt taklifi uchun push matni; marshrut
  provayderi yo'qligi (Q46) — chetlanish hisoblanmaydi, faqat tasdiqlangan marshrut proyeksiyasi.
