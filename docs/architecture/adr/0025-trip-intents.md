# ADR-0025 — Saqlangan safar/jo‘natma talabi (trip intent)

**Holat:** Accepted (foydalanuvchi topshirig‘i, 24.09.2026) • **Migratsiya:** `20260924_0091_marketplace_trip_intents` •
**Modul:** `app/modules/marketplace/` (`intents.py`, `models.py`, `api.py`, `schemas.py`); accept integratsiyasi —
`app/modules/bookings/service.py::accept_proposal` (A4 orkestratori)

## Kontekst
Mijoz haydovchilarning `trip_offer` e’lonlariga taklif yuborganda yo‘nalish, vaqt, odamlar soni yoki jo‘natma tafsilotlarini
har bir e’londa qayta kiritadi. Mavjud modellar bu “shaxsiy, qayta ishlatiladigan talab”ni ifodalamaydi:

- `listings (kind=request)` — **ommaviy** e’lon (haydovchilar ko‘radi, taklif beradi); talab esa shaxsiy bo‘lishi va hech kimga
  avtomatik yuborilmasligi shart.
- `saved_searches` — haydovchining yo‘nalish obunasi (xabarnoma uchun), narx/odamlar/jo‘natma yo‘q.
- `proposal_threads / proposal_versions` — bitta haydovchi bilan muzokara; bir talab bir nechta haydovchiga ketadi.
- Mijoz ilovasidagi qidiruv holati faqat xotirada — qayta ochilganda yo‘qoladi va takroriy bronni to‘xtatmaydi.

## Qaror
Yangi agregat **`trip_intents`** (+ o‘zgarmas **`trip_intent_versions`**), `marketplace` moduli ichida. To‘rt tushuncha alohida
qoladi: **talab** (shaxsiy, egasiniki) ≠ **ommaviy e’lon** (`listings`) ≠ **haydovchiga yuborilgan taklif** (`proposal_threads`)
≠ **tasdiqlangan bron** (`bookings`). Talab yaratish e’lon joylashtirmaydi, hech kimga taklif yubormaydi, bildirishnoma chiqarmaydi.

1. **Ma’lumot.** `trip_intents`: egasi (`owner_user_id`, server sessiyasidan), `service_type` (passenger/parcel), holat
   (`active → booked → active` (aniq “qayta qidirish”) · `active|booked → closed`), `current_version_no`, `terms_version`
   (faqat **muhim** o‘zgarishda oshadi), bron bog‘lanishi (`booking_id`, `status = booked` bilan birga), qator versiyasi.
   `trip_intent_versions` — har tahrir yangi o‘zgarmas qator: uchlar (bekat **yoki** tuman + ixtiyoriy nuqta/manzil), vaqt
   oralig‘i, `quantity` (odamlar yoki jo‘natma soni), ixtiyoriy narx maslahati (`price_basis` + `unit_price_minor` birga),
   pochta uchun turi va o‘lchamlari (`weight_g`, `*_cm`) va qabul qiluvchi (ism/telefon — faqat egasiga qaytadi; trip-offer
   pochtasi uchun majburiy (Q79) va taklifga baribir yoziladi; boshqa shaxsiy ma’lumot nusxalanmaydi). Mijozning bir nechta
   mustaqil faol talabi bo‘lishi mumkin.
2. **Taklifga bog‘lanish.** `POST /listings/{id}/proposals` ixtiyoriy `trip_intent {id, version_no}` qabul qiladi. Server:
   talab chaqiruvchiniki (aks holda **404**), `active`, versiya joriy, xizmat turi e’lon bilan bir xil, muddati o‘tmagan.
   Taklifning `quantity`, pochta talabi (tur, o‘lcham, qabul qiluvchi) va `price_basis` talab versiyasidan olinadi — body
   farq qilsa rad (`VALIDATION_ERROR reason=trip_intent_*_mismatch`); narx (`unit_price_minor`) va oyna — haydovchiga xos.
   `proposal_threads.trip_intent_id` va `trip_intent_terms_version` yoziladi va **o‘zgarmas** (DB trigger) — klient keyinroq
   identifikatorni olib tashlab takroriy bron himoyasidan chiqolmaydi. Talab bilan bog‘langan thread’da counter `quantity`/
   pochta talabini o‘zgartira olmaydi (mijoz ma’lumoti haydovchiga moslab yashirincha almashtirilmaydi — talabni tahrirlash
   kerak). Talabsiz eski taklif oqimi o‘zgarmaydi.
3. **Moslik (`GET /me/trip-intents/{id}/fit?listing_id=`).** Faqat o‘qiydi: xizmat turi, vaqt (talab oynasi vs e’lon oynasi,
   farq daqiqada), sig‘im (e’lon segmentida `trips.check_capacity`, qulfsiz — maslahat), bekat/tuman farqi, narx (e’lon narxi
   va talab narxi alohida, `quantity × unit = jami`). Hech narsa band qilmaydi; qaror submit/accept’da trip lock ostida qayta
   tekshiriladi. Routing provayderi va xizmat flag’lari bu funksiya sababli yoqilmaydi.
4. **Tahrir.** `PATCH /me/trip-intents/{id}` (`expected_version`). Muhim o‘zgarish (uchlar, vaqt, `quantity`, pochta talabi,
   qabul qiluvchi) `terms_version`ni oshiradi va shu talabning **ochiq** takliflari `trip_intent_changed` sababi bilan yopiladi.
   Ochiq taklif bo‘lsa, klient avval `acknowledge_open_offers=true` yuborishi shart, aks holda `409 TRIP_INTENT_OFFERS_AFFECTED`
   (`details.open_offers`) — mijoz nima bo‘lishini oldindan ko‘radi. Faqat narx maslahati o‘zgarsa takliflarga tegilmaydi.
   Band (`booked`) talab tahrirlanmaydi (`TRIP_INTENT_BOOKED`) — bitta safarga oid talab boshqa bron guruhiga aylanmaydi.
   Muddati o‘tgan oyna yashirincha surilmaydi: DTO `expired=true`, taklif `409 TRIP_INTENT_EXPIRED` — mijoz yangilaydi.
5. **Bitta talab — bitta tirik bron (atomar).** Accept talab bilan bog‘langan thread’da, thread lock’idan keyin talab qatorini
   `FOR NO KEY UPDATE` bilan oladi: `active` va `terms_version` thread’dagiga teng bo‘lishi shart (aks holda `TRIP_INTENT_BOOKED`
   / `TRIP_INTENT_CHANGED`), keyin sig‘im, promo rezervi, C_net hold va bron — mavjud bitta tranzaksiyada; talab `booked`,
   `booking_id` yoziladi. DB himoyasi: `uq_bookings_trip_intent_binding` (`trip_intent_id`, bron `cancelled` emas) va bron
   INSERT trigger’i bron `trip_intent_id` thread’nikiga teng bo‘lishini talab qiladi. Parallel ikki accept’dan ikkinchisi
   (umumiy mijoz `users` qatori yoki talab lock’ini kutib) `TRIP_INTENT_BOOKED` yoki — g‘olib uning thread’ini allaqachon
   yopgan bo‘lsa — `PROPOSAL_CHANGED` oladi va to‘liq rollback bo‘ladi (sig‘im, lot, hold qolmaydi).
6. **Boshqa takliflar.** Shu talabning boshqa ochiq thread’lari o‘sha tranzaksiyada `trip_intent_booked` texnik sababi bilan
   yopiladi (`FOR NO KEY UPDATE SKIP LOCKED` — boshqa driver listing/thread lock’larini kutmaydi, lock tartibi buzilmaydi);
   band bo‘lganlar `marketplace.close_stale_intent_threads` ishchi vazifasida yopiladi. Yopilish — tizim expiry’si
   (`proposal.expired`, outbox), mijozning aybli bekor qilishi yoki no-show emas: jarima, strike, reyting yo‘q. Xabarnoma
   kechiksa ham ular bo‘yicha accept/counter backend’da darhol rad etiladi (talab `booked`).
7. **Bron bekor bo‘lsa** talab `booked` holicha qoladi, eski takliflar qayta ochilmaydi. Mijoz aniq amal bilan
   `POST /me/trip-intents/{id}/reopen` qiladi — yangi versiya, `terms_version` oshadi (eski thread’lar hech qachon qabul
   qilinmaydi). Cheklov faqat shu talabga tegishli, mijozning boshqa bronlariga emas.
8. **Promo/referral.** Har thread o‘z promo quote’i, roziligi va haydovchi tasdig‘i bilan (Q104, Q123–Q129 o‘zgarmaydi); talab
   quote ko‘chirmaydi, hech narsa band qilmaydi — rezerv faqat accept’da. Talab yaratish attribution, “yangi mijoz” eligibility
   yoki birinchi bron tarixiga tegmaydi.
9. **Lock tartibi (ADR-0017 ga qo‘shimcha):** `… → proposal_threads → trip_intents → bookings → …`. Tahrir/yopish: talabning
   ochiq thread’lari (id bo‘yicha) → talab. Accept: thread → talab.

## Muqobillar
- `listings (kind=request)` ni “yashirin” qilish — ommaviy e’lon semantikasi (feed, taklif, fulfil) bilan aralashadi.
- Faqat klient xotirasida saqlash — qayta ochishda yo‘qoladi, takroriy bronni backend to‘xtatmaydi.
- Talab bir nechta haydovchiga avtomatik taklif yuborishi — topshiriq taqiqlaydi (ommaviy tarqatish yo‘q).

## Oqibatlar
- Yangi `ErrorCode`: `TRIP_INTENT_BOOKED`, `TRIP_INTENT_CHANGED`, `TRIP_INTENT_OFFERS_AFFECTED`, `TRIP_INTENT_EXPIRED` (409).
- `PublicIdPrefix.TRIP_INTENT = "tin"`. `ProposalThreadDTO.trip_intent_id` faqat mijozga qaytadi (haydovchi talab
  identifikatorini ko‘rmaydi). Bron DTO’larida talab maydoni yo‘q — bog‘lanish `TripIntentDTO.booking_id` orqali o‘qiladi.
- Eski klientlar (talab yubormaydi) avvalgidek ishlaydi; ularning takliflari talab himoyasisiz. Tarixiy thread va bronlar
  guruhlanmaydi, o‘zgarmaydi; o‘xshash yo‘nalish bo‘yicha avtomatik birlashtirish yo‘q.
- Production flag’lari o‘zgarmaydi; yo‘lovchi rejimi `passenger_enabled` bo‘yicha yopiq bo‘lsa ilovada talab ham yaratilmaydi.

## Klient (`mobile-app`)
- Yo‘nalish xulosasida «Haydovchi e’lonlarini ko‘rish» talabni yaratadi (narx ixtiyoriy); «Haydovchi e’lonlari» ekrani va taklif
  ekrani tepasida qisqa xulosa (`Toshkent → Qarshi · ertaga 12:00–14:00 · 3 kishi`), «Tahrirlash» va «Yangi safar/jo‘natma».
- Faol talab id’si `localStorage`da **foydalanuvchi bo‘yicha** (`elchi.tripIntent.active.<user_id>`), manbasi baribir server;
  login almashganda holat tozalanadi va yangi akkaunt talablari qayta o‘qiladi.
- Taklif ekrani talabdan to‘ldiriladi; odamlar soni talabniki (maydon emas). Haydovchi narxi va mijoz taklifi alohida
  qatorlar, birlik aniq (`3 kishi × 190 000 so‘m = 570 000 so‘m`). Talab narxi boshqa birlikda bo‘lsa, maydon haydovchi narxidan
  boshlanadi va shu aytiladi. Haydovchiga xos narx talabga yozilmaydi.
- Pochta ma’lumoti birinchi taklif ekranida kiritilsa, avval talabga (`PATCH`) yoziladi — keyingi haydovchilar ekrani shu bilan
  ochiladi. `409 TRIP_INTENT_OFFERS_AFFECTED` → nechta ochiq taklif yopilishi so‘raladi, faqat rozilikdan keyin qayta yuboriladi.
- Muddati o‘tgan talab: ogohlantirish va «Vaqtni yangilash»; taklif tugmasi o‘chiq. `fit` bloklovchi farq (sig‘im, xizmat turi,
  muddat) bo‘lsa tugma o‘chiq; vaqt/bekat farqi faqat ogohlantirish.
- Talabsiz eski oqim (sidebar → e’lon → taklif) o‘zgarmagan.

## Qabul matritsasi
| Talab | Dalil (test) |
|---|---|
| 3 haydovchiga bitta talabdan to‘ldirish, har biri o‘z narxi bilan | `test_offers_to_three_drivers_carry_the_request_and_their_own_price`; vitest `fills three drivers' offers…` |
| Passenger/parcel aralashmaydi, `quantity` talabniki | `test_the_request_decides_quantity_and_passenger_and_parcel_never_mix`; vitest `keeps passenger and parcel data apart` |
| Muddati o‘tgan sana surilmaydi; vaqt farqi, sig‘im yetmasligi ko‘rsatiladi | `test_an_expired_window_is_refused_and_never_moved_and_the_offer_fit_is_shown`; vitest `reports an expired window…`, `shows what does not match…` |
| Kishi boshiga narx va jami | vitest `says the unit…`, `TripIntentSummary reads as one line…` |
| Tahrir va accept parallel (ikkala tartib) | `test_an_edit_racing_an_accept_has_one_consistent_outcome[edit_first/accept_first]` |
| Ikki haydovchi parallel accept (haqiqiy `accept_proposal`): bitta bron, sig‘im/lot/hold faqat g‘olibda | `test_two_drivers_accepting_in_parallel_make_exactly_one_booking_and_the_loser_leaves_nothing`; `test_parallel_accepts_from_one_request_reserve_promo_only_for_the_booking` |
| Boshqa takliflar texnik sabab bilan yopiladi (outbox `proposal.expired`) | yuqoridagi test + `test_the_other_offers_close_in_the_accept_transaction_when_nobody_holds_them` |
| Muvaffaqiyatsiz accept to‘liq rollback | `test_a_failed_accept_rolls_back_everything_and_the_request_stays_open` |
| Idempotent retry / timeout (bir xil kalit — bitta taklif, bitta bron) | `test_http_owner_from_session_and_retries_with_the_same_key_make_one_offer_and_one_booking` |
| Bir mijozning ikki mustaqil talabi | `test_two_independent_requests_of_one_client_book_separately`; vitest `keeps two independent requests apart…` |
| Begona talab (404), bog‘lanishni olib tashlash va DB bypass | `test_a_foreign_request_is_unknown_and_the_link_cannot_be_removed`; `test_the_database_keeps_one_live_booking_even_if_the_service_check_were_bypassed` |
| Muhim tahrir oldidan ochiq takliflar haqida so‘rash | `test_a_material_edit_shows_what_happens_to_open_offers_before_closing_them`; vitest `TripIntentEditor…` |
| Promo yoqilgan/o‘chiq; rozilik boshqa haydovchiga ko‘chmaydi | promo o‘chiq: `tests/pg/marketplace/test_trip_intents_pg.py` (hammasi); yoqilgan: `tests/pg/promotions/test_trip_intents_promo_pg.py` |
| Bekor qilingan bron eski takliflarni qayta ochmaydi; qayta qidirish aniq amal | `test_a_cancelled_booking_reopens_nothing_by_itself_and_search_again_is_explicit`; vitest `after a cancelled booking…` |
| Migratsiya: toza baza, 0090→0091, head’da no-op, qayta ishga tushirish | `tests/pg/marketplace/test_trip_intents_migration_pg.py` |
| Talab boshqa akkauntga ko‘rinmaydi (klient xotirasi) | vitest `remembers the active request per signed-in person only` |

