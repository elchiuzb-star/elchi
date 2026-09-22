# ADR-0017: Global lock tartibi va tranzaksiya naqshlari

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §7, §15 (lock tartibi, retry), §9.4 • **AC:** AC06, AC07, AC08, AC21, AC41, AC42 • **BR:** D7, D10

## Kontekst
Spec §15 tartibi: users → trips → listings → proposals → wallets. 2-bosqich buyruqlari bronlar va bron bolalarini (amendment, no-show review, custody case, cash receipt, dispute) ham lock qiladi; ular spec ro‘yxatida yo‘q, shuning uchun deadlock xavfi bor edi (BR D7).

## Qaror
1. **Tartib:** `users → trips → listings → proposal_threads (→ proposal_versions) → bookings → booking bolalari (booking_amendments, no_show_reviews, custody_cases, cash_receipts, disputes_v2) → wallet_accounts → wallet_holds / topup_requests / ledger_adjustment_requests`. Har guruh ichida `id ASC`. Tracking sessiyalari trip’dan keyin mustaqil guruh; commission policy row lock olmaydi (exclusion constraint).
2. **Buyruqlar bo‘yicha qo‘llanishi** — to‘liq jadval `STATE_MACHINES.md` §0.2 da (accept, booking cancel, trip cancel/complete, amendment, admin eligibility block, capture/release, no-show confirm/reject, custody, dispute open/resolve, cash, top-up, adjustment).
3. **Asoslash:**
   - *users birinchi*: admin block faqat user’ni lock qiladi; accept eligibility’ni shu lock ostida tekshiradi → block/accept serializatsiya (AC41).
   - *trip bron’dan oldin*: sig‘im trip lock ostida o‘zgaradi (§7); cancel/amendment/no-show confirm allocation qaytaradi.
   - *listing/thread trip’dan keyin, bron’dan oldin*: accept sig‘imni, keyin kelishuvni tekshiradi va bronni yaratadi; cancel request listing’ni qayta ochadi.
   - *bron bolalari bron’dan keyin*: har bola faqat bron orqali o‘zgaradi.
   - *wallet oxirida*: pul har buyruqning yakuniy qadami; hech bir buyruq wallet’ni bron/boladan oldin lock qilmaydi. Top-up va adjustment faqat wallet guruhini oladi.
4. **Bola id bilan kirish:** lock’siz o‘qib ota id’larini topish → tartib bo‘yicha lock → bolani `FOR UPDATE` qayta o‘qib ota id’lari o‘zgarmaganini tekshirish; o‘zgargan bo‘lsa `409 VERSION_CONFLICT`.
5. **Retry:** `40P01` (deadlock) va `40001` (serialization) — butun tranzaksiya rollback, shu idempotency kaliti bilan ≤3 ichki qayta urinish, keyin `503 SERVICE_UNAVAILABLE`. **Wave 1.5:** har v2 buyrug‘i `app.modules.platform.service.run_with_db_retry` ichida bajariladi (idempotency savepoint naqshi bilan birga, ADR-0005).
6. **Hold o‘zgarishi (D10):** amendment accept bitta mavjud `wallet_holds` qatorini (`UNIQUE(booking_id, charge_kind)`) wallet lock ostida `adjust_hold` bilan o‘zgartiradi; ikkinchi hold yaratilmaydi.
7. **Reversal (D4):** yig‘indi ≤ captured tekshiruvi wallet lock ostida (`money.validate_reversal`).
8. **Tashqi chaqiruvlar** (routing, SMS, push) lock ostida emas (§15).
10. **Lock rejimi (wave 1.5 BR):** `users` qatorlari faqat `FOR NO KEY UPDATE` (SQLAlchemy `with_for_update(key_share=True)`) yoki `FOR SHARE` bilan olinadi — **oddiy `FOR UPDATE` taqiq**. Sabab: `users`ga FK bo‘lgan jadvallarga insert (masalan `user_roles`, `wallet_accounts`, `idempotency_records`) ota qatorga `FOR KEY SHARE` oladi; `FOR UPDATE` u bilan to‘qnashadi va parallel buyruqlarda deadlock beradi. `FOR NO KEY UPDATE` key-share bilan mos keladi, lekin eligibility o‘zgarishini (admin block) serializatsiya qiladi. Boshqa guruhlar uchun ham PK/unique kalit o‘zgarmasa `key_share=True` afzal.
11. **Release kontrakti (wave 1.5 BR):** allocation bo‘shatish idempotent: A4 `booking_allocations.active`ni trip lock ostida `true → false` o‘tkazadi va `trips.release`ni **faqat shu o‘tish sodir bo‘lganda** chaqiradi; takroriy cancel/no-show/amendment segment resurslarini ikki marta kamaytirmaydi.
12. **Lock rejimi kengaytmasi (wave 1.5, A1 implementatsiyasi):** `trips`, `listings` va `proposal_threads` qatorlari ham `FOR NO KEY UPDATE` bilan olinadi (ularga FK bo‘lgan bola jadvallarga insert — `trip_stop_occurrences`, `proposal_versions`, keyin `bookings` — key-share lock oladi). Oddiy `FOR UPDATE` faqat PK/unique kalit o‘zgaradigan kamdan-kam holatda va ADR bilan. v2 buyrug‘i (`app/api/v2/web.py::run_command`, `run_versioned`) har urinishda commit qiladi va `run_with_db_retry` ichida bajariladi (A1 o‘zgarishi, integrator ko‘rib chiqdi).
13. **v1 lock tartibi (H1, wave 1.5):** v1 servislar (`order_service`, `driver_order_service`, `admin_driver_service`, akkaunt o‘chirish) — `orders → users (FOR NO KEY UPDATE) → driver_profiles → wallet` (o‘chirishda wallet faqat read-only tekshiruv, N4); token refresh `users`ni `FOR KEY SHARE` bilan o‘qiydi. v1 va v2 bir biznes obyektini baham ko‘rmaydi (ADR-0006), shuning uchun `orders`ning `users`dan oldin kelishi v2 tartibiga zid emas; umumiy nuqta faqat `users` qatori va u ikkala yo‘lda ham key-share mos rejimda olinadi.
    **Wave 1.6 aniqlashtirish (H1) — v1 lock rejimlari:**
    - Qator **boshidanoq yakuniy rejimda** lock qilinadi (lock kuchaytirish yo‘q): unique ustun o‘zgarsa `FOR UPDATE` (`users.phone`/`username`, `driver_profiles.plate_number`), boshqa yozuvda `FOR NO KEY UPDATE`, qatorga faqat havola qiladigan yozuvda `FOR KEY SHARE`/`FOR SHARE`. (AGENTS §6 dagi “oddiy `FOR UPDATE` emas” qoidasining yagona istisnosi — unique kalit o‘zgarishi; bu holda FK key-share lock’lari bilan kutish kutilgan va deadlock emas, chunki lock tartibda birinchi olinadi.)
    - Akkaunt o‘chirish: `orders → users FOR UPDATE → driver_profiles/client_profiles FOR UPDATE` (telefon/plate anonimlashtiriladi) → **(v2 bookings — hali ulanmagan; `app/services/account_deletion_service.py`da A4 kiritish nuqtasi izohi)** → `wallet_accounts` (faqat read-only tekshiruv, N4).
    - **Wave 1.7 (H1):** admin mijozni block/unblock — `users FOR NO KEY UPDATE`; o‘chirilgan foydalanuvchi → `404`. O‘chirilgan driver uchun block/approve/reject/vehicle tahriri ham `404` (`admin_driver_service.get_driver_for_update`).
14. **Bookings lock ketma-ketliklari (A4, wave 2, `app/modules/bookings/service.py` bosh qismida):**
    - **accept:** `users` mijoz+driver (`FOR NO KEY UPDATE`, id ASC) → `trips` (`FOR NO KEY UPDATE`) → `listings` request+supply (`FOR NO KEY UPDATE`, id ASC) → `proposal_threads` + joriy versiya (`FOR NO KEY UPDATE`) → trip segmentlari (rezerv, trip lock ostida) → [listing’ning boshqa ochiq thread’lari, listing lock orqasida] → booking insert → allocations insert → `wallet_accounts` (`FOR UPDATE`, A3) → `wallet_holds` insert.
    - **cancel:** `trips` → `listings` → `bookings` → (pending no-show review, o‘qish) → `wallet_accounts` → `wallet_holds`.
    - **participant actions:** `bookings` → proofs / no-show reviews / custody cases → wallet (complete → capture).
    - **no-show (operator qarori):** `trips` → `listings` → `bookings` → `no_show_reviews` → wallet.
    - **trip ops (T9):** `trips` → `listings` → `proposal_threads` → `bookings` (id ASC) → bolalar → wallet’lar.
    - **cash:** `bookings` → `cash_receipts`.
    - **amendment accept:** `trips` → `bookings` → `booking_amendments` → wallet.
    - Hammasi global tartibga mos (bola id bilan kelgan buyruq avval lock’siz o‘qib, keyin tartibda lock oladi). v1 akkaunt o‘chirishda bookings `driver_profiles`dan keyin, `wallet_accounts`dan oldin (§13; H1 ulaydi).
    - Driver self-service yozuvlari avval `users`ni lock qiladi va akkaunt `active` bo‘lishini talab qiladi (aks holda 403).
    - OTP: foydalanuvchi telefon bo‘yicha lock qilinadi.
    - Token refresh: `users FOR SHARE`, keyin `refresh_sessions FOR UPDATE`.
    - Akkaunt o‘chirish va v2 top-up tasdiqlash o‘rtasida deadlock yo‘q — H1 tahlili (H1 wave 1.6 hisobotida qayd etilgan; integrator mustaqil qayta tekshirmagan, PG concurrency testi bilan tasdiqlash — keyingi H1/A3 bandi).
9. PG testi (A4/A0b): har buyruq juftligi uchun parallel stsenariy, `lock_timeout` bilan deadlock yo‘qligi.

## Muqobillar
- **SERIALIZABLE izolyatsiya** — retry soni oshadi, lock tartibi baribir kerak; pilotda `READ COMMITTED` + explicit lock.
- **Advisory lock per trip** — row lock bilan dublikat, bola jadvallarini qoplamaydi.

## Oqibatlar
- Barcha modullar lock helper’larni (`identity.lock_user_eligibility`, `trips.lock_trip`, `marketplace.lock_listing/lock_thread`, `bookings.lock_booking`, `wallet.lock_wallet`) shu tartibda chaqiradi; BR tekshiradi.
