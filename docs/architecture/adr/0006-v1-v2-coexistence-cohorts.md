# ADR-0006: v1/v2 birga yashashi — legacy faqat read-only view

**Holat:** Accepted (Q4, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §18.1 M1–M7, §18.2, §18.3 • **AC:** AC37, AC38, AC39 • **Qarorlar:** M4/S1, K6, Q4 • **BR:** D5, D6

## Kontekst
Muzlatilgan `android-app/` va `frontend/` `/api/v1` ishlatadi (`android-app/src/api/http.ts:5`, `frontend/src/api/http.ts:5`). Stage-2 klient — `mobile-app/`. Spec M3 legacy buyurtmalarni v2 obyektlariga ko‘chirishni taklif qiladi, M4 bir obyektni ikki engine mustaqil o‘zgartirishini taqiqlaydi. Foydalanuvchi Q4 qarori: legacy faqat read-only view; v1 va v2 pochta bozorlari parallel; v1 cutover 2-bosqichga kirmaydi.

## Qaror
1. **Engine egaligi jadval bo‘yicha:** `orders/bids/...` — v1; `listings/proposals/bookings/trips/...` — v2. `engine_version` ustuni kerak emas.
2. **Chegara (D5 bilan tuzatilgan):**
   - v1 endpointlari v2 jadvallariga **to‘g‘ridan-to‘g‘ri yozmaydi va o‘qimaydi**.
   - v1 kodi v2 modul **servislarini** chaqirishi mumkin, faqat quyidagi hollarda:
     a) akkaunt o‘chirish (`DELETE /api/v1/auth/me`) — read-only tekshiruvlar: faol v2 bronlar, ochiq nizolar, nol bo‘lmagan wallet balansi yoki faol hold’lar (`bookings`, `trust_support`, `wallet` servislari);
     b) v1 settings adapteri — `wallet` servisi orqali commission policy’ni o‘qish/yaratish (ADR-0009; yozuv servis ichida, v1 kodi jadvalga tegmaydi).
   - Yangi istisno — integrator va BR tasdig‘i bilan.
3. **Legacy proyeksiya (D6):** v1 buyurtmalar v2 yozuv jadvallarida (`listings`, `trips`, `bookings`, `proposal_*`, `ratings_v2`, `disputes_v2`, ledger) **hech qachon qator bo‘lmaydi**. v2 o‘qish uchun PostgreSQL **view**lar (`legacy_parcel_orders_v`, kerak bo‘lsa `legacy_order_status_history_v`, `legacy_ratings_v`) — `CREATE OR REPLACE VIEW`, qayta qurish idempotent (A10b, wave 5). Vaqt/o‘lcham yo‘q maydonlar `unknown` bayrog‘i bilan; `legacy_links` jadvali yo‘q.
4. **Mutatsiya:** legacy obyektga v2 orqali har qanday yozuv → `409 LEGACY_OBJECT_READ_ONLY`; v1 klient v2 obyektini ko‘rmaydi (AC39).
5. **Parallel bozorlar:** v2 parcel request’lari v1 driver feed’ida ko‘rinmaydi va aksincha. Operator paneli (A9) ikkalasini alohida ko‘rsatadi (`GET /api/v2/admin/legacy-orders` — read-only).
6. **Cutover:** 2-bosqich doirasida emas. v1 yozuvini o‘chiruvchi flag yaratilmaydi.
7. **Moliya:** legacy `system_fee` ledger’ga yozilmaydi; `legacy_calculated_fee` faqat view’dan hisobot (§18.2, AC37).
8. **Rollback:** flag yangi v2 e’lon/bronni o‘chiradi, mavjud v2 bronlar bajariladi (AC38). Deploy rollback ≠ data rollback (§18.3).

## Muqobillar
- **Legacy’ni v2 jadvallariga backfill (spec M3)** — Q4 rad etdi: dublikat va noto‘g‘ri aniqlik xavfi, M4 chegarasini xiralashtiradi.
- **Dual-write** — M4 ga zid.

## Oqibatlar
- Pilotda ikki parallel pochta bozori; likvidlik bo‘linadi.
- v2 reputatsiya/hisobotlar legacy ma’lumotni faqat view orqali o‘qiydi.
