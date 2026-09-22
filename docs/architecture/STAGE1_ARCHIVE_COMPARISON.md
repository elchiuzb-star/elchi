# 1-bosqich hujjatlari va 2-bosqich spetsifikatsiyasi — taqqoslash

**Muallif:** A0a • **Sana:** 13.09.2026 • **Asos:** K1 qarori
**Arxivlangan fayllar:** [`docs/archive/stage1/MASTER_PROMPT.md`](../archive/stage1/MASTER_PROMPT.md) (MP), [`docs/archive/stage1/codex_backend_development_plan_v10.md`](../archive/stage1/codex_backend_development_plan_v10.md) (CP).

Qaror turlari: **KEEP** — o‘zgarishsiz saqlanadi; **ADAPT** — mazmuni saqlanadi, 2-bosqich shakliga moslanadi; **SUPERSEDED** — spetsifikatsiya bekor qiladi. Ziddiyatda har doim spetsifikatsiya ustun.

## 1. Ish jarayoni qoidalari

| # | Eski qoida | Manba | Qaror | Asos va yangi shakl | Spec |
|---|---|---|---|---|---|
| W1 | Bosqichma-bosqich ishlash, hammasini birdan qurmaslik | MP:3; CP:5, §22 | KEEP | Wave’lar; har wave’dan keyin hisobot + foydalanuvchi tasdig‘i | §21.1 |
| W2 | Avval repository’ni tekshirish va mavjudini xulosalash | MP:5; CP Etap 1 | KEEP | A0 audit (`BASELINE_AUDIT.md`) | §18.1 M0, §21 A0 |
| W3 | Har DB o‘zgarishiga migratsiya | MP:47; CP §0 | ADAPT | Migratsiya majburiy; raqamni **bitta integrator** beradi; bitta head | §13, §21.1; ADR-0016 |
| W4 | `upgrade → downgrade -1 → upgrade` tekshiruvi | CP Etap 2 | SUPERSEDED | Downgrade rollback vositasi emas; `upgrade` idempotent va takror no-op tekshiriladi; tuzatish forward migration (ADR-0016) | §18.3, §21 A10 |
| W5 | Har bosqichga avtomatik test | MP:48; CP §0 | ADAPT | Biznes invariant testlari; concurrency/pul/sig‘im — PostgreSQL’da | §21.2 |
| W6 | Destruktiv o‘zgarishni avval tushuntirish | MP:50 | KEEP | Legacy jadval/ustun o‘chirilmaydi (expand→contract); destruktiv amal foydalanuvchi tasdig‘i bilan | §18.1, §21 A0/A10 |
| W7 | Bosqich oxirida to‘xtab 6/8 banddan hisobot | MP:50-56; CP §22 | ADAPT | Hisobot + DoD (§21.2) + BR review + foydalanuvchi tasdig‘i | §21.2 |
| W8 | Test yiqilsa yangi funksiya qo‘shmaslik, root cause | CP §22 | KEEP | DoD tarkibida | §21.2 |
| W9 | “MVPda yo‘q funksiyani qo‘shma” | MP:49; CP §22 | ADAPT | Doira = spetsifikatsiya (P0/P1 skeleti) + foydalanuvchi qarorlari; doiradan tashqari ish taqiq | §4 |
| W10 | “First correct → clean → tested → next” | CP §25 | KEEP | DoD ruhi | §21.2 |

## 2. Mahsulot cheklovlari

| # | Eski qoida | Manba | Qaror | Asos | Spec |
|---|---|---|---|---|---|
| P1 | Time matching yo‘q | MP:9; CP §0 | SUPERSEDED | Vaqt oynasi, pickup ETA | §5.2, §6.3 |
| P2 | Driver departure time yo‘q | MP:10 | SUPERSEDED | Trip jadvali | §5.2, §7 |
| P3 | Capacity check / driver capacity yo‘q | MP:11-12 | SUPERSEDED | Segment sig‘imi, vehicle | §7, §13 |
| P4 | Cargo type / weight / size yo‘q | MP:13-15 | SUPERSEDED | Parcel detallari (kod allaqachon `cargo_type` qo‘shgan: `20260630_0025`) | §5.2 |
| P5 | OTP/QR proof, pickup/delivery proof yo‘q | MP:16-18 | SUPERSEDED | Hash’langan boarding/pickup/delivery kodlari | §9.5, §11 |
| P6 | Online payment yo‘q | MP:19 | KEEP (2-bosqich uchun) | Karta — P2; `card_payments_enabled=false` | §4, §9.6 |
| P7 | P2P payment yo‘q; faqat naqd | MP:20,24 | ADAPT | Tashish haqi naqd; haydovchi faqat oldindan to‘ldiriladigan **komissiya** balansiga ega; P2P hamyon yo‘q | §9.1-9.2 |
| P8 | Real-time GPS yo‘q | MP:21 | SUPERSEDED | Backend tracking (A6), Android dala qismi keyinroq | §10 |
| P9 | Chat yo‘q | MP:22 | SUPERSEDED | Minimal scoped chat (P1) | §4, §16 |
| P10 | Asosiy oqim: mijoz buyurtma → driver bid → tanlash | MP:24 | ADAPT | v1 legacy oqim sifatida saqlanadi; v2 — ikki tomonlama listing/proposal/booking | §5, §18 |

## 3. Arxitektura va ma’lumot qoidalari

| # | Eski qoida | Manba | Qaror | Asos | Spec |
|---|---|---|---|---|---|
| A1 | FastAPI + PostgreSQL + SQLAlchemy + Alembic + Pydantic + JWT | MP:5 | KEEP | + PostGIS, Redis, worker | §1 |
| A2 | Modular kod; modul ro‘yxati (auth…admin) | MP:26-45; CP §23 | ADAPT | `app/modules/<name>/`; legacy `app/services` bosqichli adapter | §12; ADR-0001 |
| A3 | Muhim amal `audit_logs`ga | CP §0 | KEEP | Immutable audit (`0024`) qayta ishlatiladi; operator buyrug‘i actor+sabab bilan | §9.4, §16 |
| A4 | Har status o‘zgarishi `status_history`ga | CP §0 | ADAPT | Har agregat uchun o‘z tarix yozuvi | §11 |
| A5 | Qat’iy role-based access | CP §0, Etap 18 | ADAPT | `user_roles` + server capability; v1 `users.role` saqlanadi | §2, §12; ADR-0007 |
| A6 | **Operator barcha statuslarga aralasha oladi** | CP §0, Etap 14 | SUPERSEDED | Admin/operator ham domen buyruqlari va invariantlar orqali | §2, §21 A9 |
| A7 | Normal oqimdan tashqari amalda sabab majburiy | CP §0 | KEEP | Operator buyruqlarida sabab + dalil + audit | §16 |
| A8 | `users.phone` unique | CP Etap 2 | KEEP | Bir shaxs — bir telefon — ko‘p rol | §2; ADR-0007 |
| A9 | `plate_number` unique | CP Etap 2 | ADAPT | `vehicles.plate_normalized` unique | §13 |
| A10 | `from_city_id <> to_city_id` | CP Etap 2 | ADAPT | Legacy’da qoladi; v2’ga ko‘r-ko‘rona ko‘chirilmaydi | §18.1 M2 |
| A11 | `bids unique(order, driver)` | CP Etap 2 | SUPERSEDED (v2) | Proposal thread + o‘zgarmas versiyalar | §5.3, §13 |
| A12 | `ratings.order_id` unique, 1..5 | CP Etap 2, 12 | ADAPT | Bron bo‘yicha o‘zaro baho, 1..5 saqlanadi | §17.2, §13 |
| A13 | Public ro‘yxatdan o‘tish faqat client/driver; staff ichkarida | CP Etap 3 | KEEP | Staff roli faqat staff boshqaruvi orqali | §13 |
| A14 | JWT access + refresh, bloklangan user kira olmaydi | CP Etap 3 | KEEP | + refresh revoke real-time kanalni ham yopadi | §17.6 |
| A15 | Dev’da mock OTP; OTP xavfsiz saqlash | CP Etap 3 | ADAPT | Hash saqlash KEEP; production’da global dev OTP yo‘q; 4 xona saqlanadi, 6 xona Android v2 klienti bilan (Q8) | §17.5 |
| A16 | Upload auth, tur/hajm validatsiyasi | CP Etap 4 | KEEP | | §17.4 |
| A17 | Fayl lokal saqlanib `file_url` qaytadi | CP Etap 4 | SUPERSEDED | Private storage, qisqa muddatli/autentifikatsiyali yuklab olish (H0) | §17.4; ADR-0015 |
| A18 | Tarifdan suggested price | CP Etap 5 | ADAPT | Operator/tarixiy diapazon, “taxminiy” belgisi; yakuniy narx kelishuvda | §6.5, §8.2 |
| A19 | Driver faqat `approved` bo‘lsa `available` | CP Etap 6 | ADAPT | Eligibility (approved, faol, blok yo‘q); kelajak safarda `is_available` talab qilinmaydi | §8.1, AC18 |
| A20 | Driver route faqat from/to; departure/capacity yo‘q | CP Etap 6 | SUPERSEDED | `driver_routes` preferensiya bo‘lib qoladi; trip/route_version alohida | §6.2, §7 |
| A21 | Mijoz faqat o‘z buyurtmasini boshqaradi | CP Etap 7 | KEEP | Owner/participant scope | §13 |
| A22 | Draft → publish; cancel sababi majburiy | CP Etap 7 | KEEP | Listing `draft/published`; sabab va initiator saqlanadi | §5.4, §11 |
| A23 | Matching: shahar tengligi + `is_available` | CP Etap 8 | SUPERSEDED | Yo‘l geometriyasi, bekat tartibi, ETA | §6 |
| A24 | `order_offers` dublikatsiz | CP Etap 8 | ADAPT | Push/notification dedup | §6.6 |
| A25 | **Qabuldan oldin to‘liq manzil/telefon yashirin** | CP Etap 9, 18 | KEEP | Tasdiqlangan uchrashuv bekati ochiq bo‘lishi mumkin | §10.6 |
| A26 | Birinchi bid order’ni `bidding`ga o‘tkazadi | CP Etap 9 | SUPERSEDED (v2) | Taklif listing statusini o‘zgartirmaydi | §5.3, §11 |
| A27 | Select driver — tranzaksiya, boshqa bid’lar yopiladi | CP Etap 10 | ADAPT | Atomar accept: allocation + hold + boshqa takliflar | §15 |
| A28 | Status ketma-ketligidan tashqari o‘tmaydi | CP Etap 11 | KEEP | Holat mashinalari (`app/contracts/state_machines.py`) | §11 |
| A29 | Driver `picked_up`dan keyin bekor qila olmaydi | CP Etap 11 | ADAPT | Custody/return oqimi | §11, AC22 |
| A30 | Confirm’da `payment_status=paid_manual` | CP Etap 12 | SUPERSEDED | `service_status`, `cash_collection_status`, `fee_status` mustaqil | §9.5 |
| A31 | Nizo buyurtmani `disputed` qiladi va oldingi statusni saqlaydi | CP Etap 13 | SUPERSEDED | Mustaqil nizo hayot sikli, tiklash yo‘q | §2, §11 |
| A32 | Driver tasdiqlash/rad/blok sabab va audit bilan | CP Etap 15 | KEEP | + hujjat muddati, transport mosligi | §17.1 |
| A33 | Faqat in-app, FCM qo‘shmaslik | CP Etap 16 | SUPERSEDED | Durable outbox + push | §15, §16 |
| A34 | Audit loglarni admin o‘qiydi, filtrlar | CP Etap 17 | KEEP | Operator keng tarixiy kirishi auditga yoziladi | §10.6 |
| A35 | Bir xil xato formati | CP Etap 18 | KEEP | v2 envelope + xato kodlari katalogi | §14.2; ADR-0005 |
| A36 | Swagger/OpenAPI, Postman | CP Etap 19 | ADAPT | OpenAPI → TypeScript generatsiya; v2’da `response_model` majburiy | §12; ADR-0010 |
| A37 | To‘liq happy-path integratsion test | CP Etap 20 | ADAPT | AC01–AC44 matritsasi | §22 |

## 4. Xulosa

Saqlangan kuchli qoidalar (AGENTS.md’ga ko‘chirildi): bosqichli ish va tasdiq (W1, W7), har DB o‘zgarishiga migratsiya (W3), har bosqichga test (W5), destruktiv o‘zgarishni oldindan tushuntirish (W6), qabuldan oldin manzil/telefonni yashirish (A25), OTP hash (A15), immutable audit (A3), naqd tashish haqi (P7), sabab majburiyligi (A7). Qolgan mahsulot cheklovlari 2-bosqichda bekor.
