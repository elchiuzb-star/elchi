# Elchi — Loyiha bahosi va rivojlanish yo'l xaritasi

_Sana: 2026-07-05 · Holat: MVP funksional yakunlangan, ishga tushirishdan oldingi bosqich_

---

## 1. Loyiha qaysi bosqichda?

**Xulosa: Backend MVP to'liq yakunlangan (20/20 etap), 3 rol uchun frontend backend'ga ulangan. Loyiha "MVP tayyor → pilot/ishga tushirishdan oldingi mustahkamlash" bosqichida.**

| Qatlam | Holat |
|--------|-------|
| Backend (FastAPI) | ✅ Barcha MVP modullari yozilgan, **~308 test yashil** |
| Buyurtma hayotiy sikli | ✅ `draft → published → bidding → accepted → picked_up → in_transit → delivered → confirmed` |
| Rollar | ✅ client / driver / operator / admin / super_admin (RBAC) |
| Frontend (Client/Driver/Admin) | ✅ Figma UI backend'ga ulangan (`frontend/`) |
| Audit log + status history | ✅ Har bir muhim amal yoziladi |
| To'lov | ⚠️ Faqat naqd (`cash`), `unpaid → paid_manual` |
| Ishlab chiqarish (prod) infratuzilma | ❌ Yo'q (CI/CD, monitoring, SMS provider, deploy) |

Implementatsiya qilingan modullar (rejaga to'liq mos): auth, users, cities/districts, route_tariffs, driver_profiles/documents/routes, orders, bids, order_offers, status_history, disputes, ratings, notifications, audit_logs, admin panel.

MVP'dan **ataylab chiqarilgan** (rejaga ko'ra): real-time GPS tracking, chat, online/P2P to'lov, QR/pickup/delivery proof, cargo type/weight/size, time/capacity matching.

---

## 2. Texnik arxitektura to'g'ri ketayaptimi?

**Umumiy baho: Backend arxitekturasi mustahkam va to'g'ri yo'lda. Asosiy texnik qarz — frontend'dagi monolit fayl.**

### Yaxshi tomonlar ✅
- **Modulli backend:** `models / schemas / services / api` qatlamlari toza ajratilgan.
- **To'g'ri patternlar:** RBAC, audit log, status history, tranzaksiyalar (`with_for_update`), Alembic migratsiyalar.
- **Test qamrovi kuchli:** har etap uchun testlar, integratsion "happy-path" testi.
- **API versiyalash** (`/api/v1`) mavjud.
- **Konfiguratsiya** env orqali (pydantic settings), komissiya sozlanadi.

### Texnik qarz / xavflar ⚠️
1. **Frontend `App.tsx` — monolit (~3800+ qator).** Barcha ekranlar, tarjimalar, komponentlar bitta faylda. Bu eng katta qarz: qo'llab-quvvatlash qiyin, merge-konflikt xavfi, sekin IDE.
   - **Tavsiya:** feature bo'yicha bo'lish — `screens/client/*`, `screens/driver/*`, `screens/admin/*`, `i18n/` (T obyektini alohida faylga), `components/ui/`.
2. **Google Maps API kaliti git tarixida ochiq** (avval `.env.example`larda edi). **Rotatsiya + HTTP referrer cheklovi shart.**
3. **Maps API'lariga bog'liqlik:** Directions + Geocoding + Places yoqilishi va billing kerak. Shaharlarda `center_lat/lng` yo'q (faqat tumanlarda) → geocoding fallback mo'rt.
4. **Bundle > 1 MB**, code-splitting yo'q.
5. **Prod kuzatuvi yo'q:** Sentry/error monitoring, structured logging, rate limiting, health/readiness metrikalari.
6. **CI/CD yo'q:** lint (`ruff`), coverage (`pytest-cov`), test avtomatlashtirish o'rnatilmagan.
7. **SMS OTP mock** — prod uchun real provider (Eskiz.uz / Play Mobile) integratsiyasi kerak.
8. **`mobile-app/` eskirgan dublikat** — `frontend/` bilan chalkashlik. Bittasini tanlash kerak.

---

## 3. Tuzatilishi / mustahkamlanishi kerak (ustuvorlik bo'yicha)

### P0 — Ishga tushirishdan oldin majburiy
- [ ] Google Maps kalitini **rotatsiya** qilish + domain/referrer cheklovi.
- [ ] Real **SMS OTP provider** (Eskiz.uz) integratsiyasi + fallback/rate-limit.
- [ ] **To'lov/komissiya yig'ish mexanizmi** (4-bo'limga qarang) — hozir komissiya hisoblanadi, lekin **yig'ilmaydi**.
- [ ] Deploy: Docker + boshqariladigan PostgreSQL + migratsiya pipeline + backup.
- [ ] Error monitoring (Sentry) + structured logging.
- [ ] Rate limiting (login/OTP endpointlarda albatta).

### P1 — Barqarorlik va sifat
- [ ] `App.tsx` monolitini bo'lish (texnik qarz).
- [ ] Shaharlarga `center_lat/lng` qo'shish (geocoding'ga tayanmaslik).
- [ ] CI: `ruff` + `pytest` + `pytest-cov` + typecheck har PR'da.
- [ ] Code-splitting (bundle hajmi).
- [ ] `mobile-app/` taqdirini hal qilish (o'chirish yoki native'ga aylantirish).
- [ ] FastAPI `asyncio.iscoroutinefunction` deprecation ogohlantirishlari (180 ta) — kelajakdagi Python mosligi.

### P2 — Yaxshilashlar
- [ ] E2E testlar (frontend) — Playwright.
- [ ] Push-bildirishnomalar (hozir faqat ilova ichida).
- [ ] Admin panelida analitika/dashboard metrikalari.

---

## 4. Biznes model — eng muhim strategik masala

**Markaziy muammo:** to'lov **naqd**, komissiya (**15%**) haydovchidan olinadi. Lekin haydovchi mijozdan naqd oladi — platforma o'z 15%'ini **qanday undiradi?** Hozir `system_fee`/`driver_income` har buyurtmada **hisoblanadi va yoziladi**, ammo **yig'ish/hisob-kitob (settlement) modeli yo'q** (wallet/balance/payout modellari mavjud emas). Bu — MVP'ning eng katta biznes bo'shlig'i.

### Variantlar (tavsiya tartibida)

**A) Haydovchi hamyoni (prepaid balance) — tavsiya etiladi (naqd bilan mos)**
- Haydovchi balansni oldindan to'ldiradi (Payme/Click/Uzum orqali).
- Har buyurtma yakunlanganda 15% komissiya balansdan yechiladi.
- Balans manfiy bo'lsa — yangi buyurtma ololmaydi.
- Yangi modellar: `driver_wallet`, `wallet_transaction`. Naqd oqimini o'zgartirmaydi, faqat komissiyani ishonchli undiradi.

**B) Obuna (subscription) — eng sodda**
- Haydovchi oylik/haftalik flat to'lov (masalan, 99 000 so'm/oy), komissiyasiz.
- Naqd bilan juda mos, hisob-kitob sodda. Kamchilik: kam ishlaydigan haydovchi uchun qimmat, take-rate buyurtma hajmiga bog'lanmaydi.

**C) Har bid/kontakt uchun to'lov (lead-gen)**
- Haydovchi bid qo'yish yoki mijoz kontaktini ko'rish uchun kichik haq to'laydi.
- Konversiyaga bog'liq daromad. B modeli bilan birlashtirilishi mumkin.

**D) Onlayn to'lov (escrow) — eng toza, eng katta o'zgarish**
- Mijoz ilova orqali to'laydi, platforma komissiyani manbada ushlab, qolganini haydovchiga o'tkazadi.
- Take-rate avtomatik. Lekin MVP "cash only" tamoyilidan chiqadi, integratsiya + ishonch talab qiladi.

**Tavsiya:** pilotni **B (obuna)** yoki **A (prepaid hamyon)** bilan boshlang — ikkalasi ham naqd oqimiga tegmaydi va komissiyani ishonchli undiradi. Keyinchalik **D (onlayn to'lov)** ni qo'shib, ikki tomonlama take-rate'ga o'ting.

### Boshqa biznes yo'nalishlari
- **Ikki tomonlama reyting** (mijozni ham baholash) — sifat nazorati.
- **Narx dinamikasi:** yo'nalish/talab bo'yicha tavsiya narxni moslash (hozir statik tarif).
- **Vertikallar:** hujjat/posilka'dan tashqari — kichik yuk, marketplace yetkazish (do'konlar uchun B2B).
- **Sug'urta / kafolat** qo'shimcha daromad sifatida.

---

## 5. Mahsulotga qo'shimchalar (roadmap)

### Ishga tushirishgacha (MVP+)
- Real SMS OTP.
- To'lov/komissiya mexanizmi (4-bo'lim).
- Buyurtma tarixi, kvitansiya/chek.
- Haydovchi/mijoz uchun sodda onboarding + yordam (mavjud).

### Ishga tushirilgandan keyin (v2)
- **Yaqin-real vaqt tracking** (haydovchi bosqichlarni belgilaydi → keyin jonli lokatsiya). MVP'da yo'q, lekin foydalanuvchi kutadi.
- **Push-bildirishnoma** (FCM).
- **Chat yoki tez javob shablonlari** (mijoz-haydovchi).
- **Referral / promo-kod**, aksiya.
- **Reja bo'yicha buyurtma** (scheduling), ko'p posilka.
- **Haydovchi daromad hisoboti** kengaytirilgan (soliq/hisob uchun).

---

## 6. Tavsiya etilgan keyingi 3 qadam

1. **Biznes modelni qaror qiling** (obuna yoki prepaid hamyon) — bu barcha keyingi texnik ishni belgilaydi.
2. **Ishga tushirish minimal to'plami (P0):** SMS OTP + kalit rotatsiya + deploy/monitoring + tanlangan to'lov mexanizmi.
3. **Kichik pilot** (1 yo'nalish, masalan Toshkent–Samarqand) bilan real foydalanuvchilarда sinov → o'lchov → iteratsiya.

> Qisqasi: **mahsulot MVP sifatida tayyor va arxitektura sog'lom.** Endi asosiy e'tibor — kod emas, balki **biznes modeli (komissiya yig'ish)**, **ishga tushirish infratuzilmasi** va **haqiqiy foydalanuvchi pilotiga** qaratilishi kerak.
