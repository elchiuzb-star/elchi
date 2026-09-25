# ADR-0026 — Faqat mijoz e'loni, operator chati, jo'natma toifalari, kodsiz pochta

**Holat:** Accepted (foydalanuvchi qarori, 24.09.2026) • **Sana:** 25.09.2026 • **Muallif:** A0a (integrator)
**Almashtiradi (qisman):** Q92, Q97 (`side=offers` va `matches` qismi), Q99, Q21 (trip_offer qismi), ADR-0025/Q136, Q65,
Q75 (pochta kodi va reissue qismi), Q78 (foydalanuvchi ochadigan nizo qismi), Q79 (trip-offer qismi), Q85 (pochta
kodi qismi), spec §5.1 jadvalidagi `trip_offer`, §11 pochta kodlari, AC02. Spec o'zgartirilmaydi — chekinish shu ADR
va AGENTS §3 (Q138–Q143) da ochiq yoziladi.

## Kontekst
Foydalanuvchi mahsulot oqimini soddalashtirdi (24.09.2026). To'rt o'zgarish:
1. Pochtada topshirish/qabul qilish kodi, «haydovchi oldi / qabul qilindi» majburiy zanjiri va «naqd to'ladim / pulni
   oldim» tasdiqlari yo'q.
2. Jo'natma o'lcham-vazni raqam bilan kiritilmaydi — tayyor toifadan tanlanadi.
3. Mijoz/haydovchiga ko'rinadigan nizo formasi va bosqichlari o'rniga bronga bog'langan operator chati.
4. Haydovchi e'lon yaratmaydi: faqat mijoz yo'lovchi yoki pochta e'lonini beradi, haydovchi javob beradi.

Telefon OTP (Q137) va xodim MFA (ADR-0021) o'zgarmaydi.

## Qaror

### 1. Pochta — kodsiz va tasdiqsiz (Q139)
- `pickup_code`, `delivery_code`, `return_code` endi yaratilmaydi, ko'rsatilmaydi, so'ralmaydi, qayta chiqarilmaydi
  (`REISSUABLE_PROOF_KINDS = {boarding_code}`); yo'lovchi `boarding_code` o'zgarmaydi.
- Haydovchining pochta amallari (`pick_up`, `start_transit`, `deliver`, `report_delivery_failed`, `retry_delivery`,
  `return_to_sender`) va jo'natuvchining `complete` amali hech kimga ruxsat etilmaydi.
- Yangi holat yo'li (DB literallari o'zgarmaydi): `confirmed → awaiting_pickup` (trip `start_boarding`, tizim) →
  `in_transit` (trip `depart`, tizim, buyruq `trip_departed` — «haydovchi yo'lga chiqdi», topshirish da'vosi emas) →
  `delivered` (**operator** `mark_delivered`, sabab + ixtiyoriy dalil) → `completed` (**operator**
  `complete_with_evidence`). Qaytarish: operator `require_return` → `return_to_sender`.
- `in_transit`/`picked_up` pochta safarni yakunlashni to'smaydi (`PARCEL_AWAITING_OPERATOR_OUTCOME`) — natijani xodim
  yozadi; `delivered` pochta darhol `awaiting_confirmation` navbatida.
- Pochta uchun `cash_receipts` yaratilmaydi (`parcel_cash_receipts_retired`). Kelishilgan narx va to'lanadigan summa
  bronda ko'rinadi.
- **Pul:** komissiya faqat `_complete` da (operator yakunlaganda) capture qilinadi, blocking nizo bo'lsa — yo'q. Chat,
  vaqt o'tishi yoki tasdiq oynasi yo'qligi hech qachon «bajarildi»/«to'landi» deb talqin qilinmaydi.
- **Sig'im:** o'zgarmaydi — bekor qilishda bo'shaydi; yakunlanganda (avvalgidek) bo'shamaydi, trip yakuni bilan chiqadi.
- **Referral:** pochta bronida topshirish/yetkazish dalili va naqd tasdig'i yo'q ⇒ bron qualification'ga kirmaydi
  (mukofot avtomatik berilmaydi); enrollment qualification muddati bilan tugaydi (osilib qolmaydi). Pochta referral'i
  G20/Q131 bo'yicha baribir o'chiq.
- **Aloqa (Q44 talqini):** pochta xizmati «boshlandi» = trip jo'nashi (`in_transit`); telefonlar va kuzatuv oynasi shundan.
- **Ochiq qaror D-1:** pochtani yakunlash qoidasi (operator, haydovchining bitta «yetkazdim» yozuvi yoki boshqa). Hozirgi
  xulq xavfsiz vaqtinchalik: pul faqat xodim yakunlaganda.

### 2. Jo'natma toifalari katalogi (Q140)
- `parcel_category_versions` (draft → active → superseded; `platform.policy_manage` admini faollashtiradi, audit; ikkinchi
  xodim talabi 0094 da olib tashlandi; bitta active; `synthetic`)
  va o'zgarmas `parcel_category_items` (nom uz/ru, ikonka kaliti, max bo'yi/eni/balandligi, max og'irlik, max hajm).
- Mijoz `parcel.category_id` tanlaydi (`GET /parcel-categories`); raqamli o'lcham-vazn saqlanmaydi. `ParcelType` (Q68,
  mazmun turi) saqlanadi — u o'lcham emas.
- E'lon, taklif versiyasi va bron toifa elementiga ishora qiladi; bronda trigger bilan muzlatilgan — katalog tahriri
  (yangi versiya) mavjud kelishuvni o'zgartirmaydi.
- **Sig'im:** toifa segment sig'imidan o'zining **max** og'irligi va **max** hajmini talab qiladi (eng yomon holat).
  Sig'im mexanizmi o'zgarmaydi.
- Haydovchi taklifdan oldin toifani va chegaralarini ko'radi (`ListingPublicDTO.parcel_category`).
- **Production:** tasdiqlangan, `synthetic=false` katalog bo'lmasa yangi pochta e'loni va broni rad
  (`PARCEL_CATALOG_UNCONFIRMED`, fail-closed); sintetik katalog production'da tasdiqlanmaydi. Haqiqiy chegaralar
  o'ylab topilmaydi — demo/test qiymatlari `synthetic` deb belgilanadi.

### 3. Operator chati (Q141)
- `support_threads` + `support_messages` (`trust_support.threads`). «Shikoyat qilish» → `POST
  /bookings/{id}/support-thread`: shu foydalanuvchining shu bron bo'yicha ochiq chati yoki yangisi. DB partial unique
  (bitta ochiq chat / bron / so'rovchi) — takror bosish yoki tarmoq retry dublikat yaratmaydi.
- Mijoz↔operator va haydovchi↔operator chatlari alohida; boshqa odamning chati 404.
- Operator paneli: so'rovchi, bron, yozishmalar, mas'ul operator, ochiq/yopiq; navbat (`support_thread` O4 queue).
  Foydalanuvchi rost holatni ko'radi (`waiting` / `assigned` / `answered` / `closed`), javob vaqti va'da qilinmaydi.
- Chat ochilishi/yopilishi pul qaytarmaydi, komissiyani bekor qilmaydi, bonus bermaydi, firibgarlik hukmi emas.
- Foydalanuvchi nizo route'lari olib tashlandi (`POST /bookings/{id}/disputes`, `GET /me/disputes`, `GET /disputes/{id}`,
  `POST /disputes/{id}/evidence`). `disputes_v2` — faqat xodim ichki yozuvi; uning capture/finance_review/promo/GPS dalil
  ta'sirlari (Q66/Q74/Q77/Q84/Q127) o'zgarmaydi.
- Eski nizolar (mijoz/haydovchi ochgan) chatga ko'chirildi (0092): tavsif, dalil izohlari + fayl id'lari, xodim qarori;
  `disputes_v2` qatorlari o'zgarmaydi.

### 4. Haydovchi e'loni olib tashlandi (Q138)
- `trip_offer` yaratish/nashr/davom/tahrir/taklif/counter/accept servisda (`DRIVER_LISTING_RETIRED`) va DB trigger'da
  (yangi qator, `published`/`paused` ga o'tish) rad; `LISTING_CREATE_TRIP_OFFER` hech kimga berilmaydi.
- `GET /feed?side=offers`, `side=offers` saqlangan qidiruv — rad; `GET /listings/{id}/matches` olib tashlandi.
- Saqlangan talablar (ADR-0025) yangi yaratilmaydi/tahrirlanmaydi/qayta ochilmaydi (`TRIP_INTENT_RETIRED`, DB trigger);
  tarix o'qiladi va yopiladi.
- Trip ichki model (haydovchi rejasi, avtomobil, segment sig'imi) saqlanadi va mijozga e'lon sifatida ko'rinmaydi.
- `marketplace.retire_driver_listings` ishchi vazifasi ochiq e'lonlar, ularning takliflari va faol talablarni texnik
  sabab (`driver_listing_retired`) bilan yopadi; bronlarga tegmaydi; jarima/strike yo'q; idempotent.

## O'tish jadvali (eski ma'lumot)
| Eski holat | Nima bo'ladi |
|---|---|
| `trip_offer` `draft` | Qoladi, nashr qilib bo'lmaydi (servis + trigger) |
| `trip_offer` `published`/`paused` | Ishchi vazifa `cancelled` (`driver_listing_retired`), `listing.cancelled` outbox |
| Ochiq taklif (`trip_offer` da) | Muddati tugatiladi (`driver_listing_retired`, `proposal.expired`), accept/counter rad |
| Faol bron (`trip_offer` dan) | O'zgarmaydi — narx, sig'im, hold, promo saqlanadi |
| Faol saqlangan talab | `closed` (`driver_listing_retired`), ochiq takliflari yopiladi |
| Band (`booked`) talab | O'zgarmaydi, bron bog'lanishi saqlanadi |
| Pochta bron (`picked_up` … `delivery_failed`) | Davom etadi; natijani operator yozadi (`mark_delivered`, qaytarish) |
| Pochta ochiq naqd kvitansiya | Tarix; yangi kvitansiya yo'q; xodim ko'radi |
| Mijoz/haydovchi ochgan nizo | Chatga ko'chirilgan (tarix + dalil); `disputes_v2` qatori saqlangan |
| Pochta referral enrollment | Yangi dalil yo'q ⇒ qualification yo'q, muddat bilan tugaydi |

## Muzlatilgan klientlar
`android-app/` va `frontend/` faqat v1 ni chaqiradi (v1 buyurtma, nizo, kodsiz haydovchi statuslari) — v1 o'zgarmaydi
(Q4). Handoff: `docs/architecture/HANDOFF_ADR0026.md`.

## Oqibatlar
- Yangi xato kodlari: `DRIVER_LISTING_RETIRED`, `TRIP_INTENT_RETIRED`, `SUPPORT_THREAD_CLOSED`, `PARCEL_CATEGORY_REQUIRED`,
  `PARCEL_CATALOG_UNCONFIRMED`. Yangi id prefikslari: `pcv`, `pct`, `sth`, `smg`. Yangi hodisalar:
  `support.thread.opened` (xodim), `support.thread.replied` (so'rovchi).
- Migratsiya `20260924_0092` (additiv). Production flag'lari o'zgarmaydi.

## Ochiq savollar (foydalanuvchi qarori kerak, 25.09.2026)
- **D-1** Pochtani yakunlash qoidasi (§1). Variantlar: A — faqat operator (hozirgi; pul faqat xodim tasdig‘i bilan,
  xodim ishi ko‘p, pochta referral’i ishlamaydi); B — haydovchining bitta «yetkazdim» yozuvi faqat operator navbatini
  tezlashtiradi, capture baribir xodimda (yozuv — da’vo, dalil emas); C — qabul qiluvchining bir martalik havola orqali
  tasdig‘i (mustaqil dalil, referral uchun ham; SMS/havola infratuzilmasi va huquqiy tekshiruv kerak).
- **D-2** Bron miqdorini amendment bilan o‘zgartirish. D9 so‘rov bronining miqdorini o‘zgartirishni taqiqlaydi; D10 yo‘li
  faqat `trip_offer` bronlari uchun edi. Q138 dan keyin yangi bronlarda miqdor amendment’i **imkonsiz** (narx amendment’i
  ishlaydi). Variantlar: D9 ni saqlash (mijoz bekor qilib yangi so‘rov beradi) yoki so‘rov bronida miqdor o‘zgarishini
  ruxsat etish (sig‘im/hold/promo qayta hisobi mavjud D10 mexanizmi bilan). Legacy offer bronlari D10 bilan ishlaydi.
- **D-3** Nomlash: bron sahifasida «Shikoyat qilish» (operator chati) va «Xavfsizlik → Shikoyat: Bron» (foydalanuvchi
  haqida trust report, Q45) yonma-yon. Ikkinchisi nizo formasi emas va olib tashlanmadi; nomini alohida qaror bilan
  aniqlashtirish mumkin («Foydalanuvchi haqida xabar berish» kabi).

## Test paytida topilgan va tuzatilgan (25.09.2026)
- Haydovchi pochta bron sahifasida qabul qiluvchi kontakti umuman ko‘rsatilmas edi — kodsiz topshirishda bu yagona yo‘l.
  Endi pochtada «Qabul qiluvchi» qatori (trip jo‘nagach ism + telefon, Q142), jo‘natuvchi telefoni ko‘rsatilmaydi (Q44).
- `booking.confirmation_overdue` pochta uchun `overdue_since` ni 24 soat keyin deb yozardi, holbuki pochta navbatga darhol
  tushadi; endi `overdue_since` = qayd vaqti.

## Kuzatuv (25.09.2026) — Q144–Q147 va tekshiruvda topilganlar
- **D-1 → Q144 (vaqtinchalik):** operator yakunlashi saqlanadi, yakuniy qaror emas. Tekshiruv natijasi: ishlayotgan ilovada
  dispute probe ro'yxatdan o'tgan, shuning uchun `complete_with_evidence` (`ops.booking_command`) pochta komissiyasini o'zi
  capture qilardi — ya'ni finance vakolati chetlab o'tilardi. Endi pochtada xodim yakuni `held` + finance navbati
  (`parcel_staff_completion`, 0093), capture faqat `finalize_fee`. Yo'lovchi oqimi o'zgarmadi (mijoz tasdig'i capture).
- **D-2 → Q145:** so'rovda odamlar soni tahriri (klient formasi qo'shildi), bronda `quantity_amendable`.
- **D-3 → Q146:** «Yordam / shikoyat» va «Xavfsizlik haqida xabar berish».
- **Q147:** pochta enrollment'lari uchun `qualification_path_retired` review (ishchi
  `promotions.review_retired_parcel_enrollments`, muddat o'tgani ularni bo'shatmaydi). **D-4 (ochiq):** tasdiqlangan
  (approve) review'dagi va'da qanday bajariladi — hozir rezerv saqlanadi, grant yo'q.
- **Mijoz solishtiruvi:** mijoz o'z so'roviga kelgan takliflarni avvaldan ko'rardi (narx, marshrut, vaqt, counter, tanlash,
  rad etish). Olib tashlangani — mustaqil haydovchi e'lonlari lentasi (`side=offers`). Solishtirish uchun avtomobil va reyting
  yo'q edi; endi `ProposalThreadDTO.driver_summary` (faqat so'rov egasiga: avtomobil klassi, o'rinlar, reyting guruhi va
  soni — Q40 bilan bir xil anonim to'plam).
- **«Yo'lda» ma'nosi (Q142):** pochta `in_transit` = «Haydovchi yo'lga chiqdi». Progress zinasidagi «Haydovchi bekatda» va
  «Yuk olindi» (dalilsiz da'vo) olib tashlandi; ommaviy kuzatuv matni ham. Referral bu hodisani dalil sifatida ishlatmaydi
  (unga `delivery_code` proof kerak, u endi yo'q).

## Yakunlash (25.09.2026)
- **D-1** o'zgarmadi: operator yakunlashi lokal vaqtinchalik yechim, yakuniy qaror yoki production oqimi emas.
- **Dalil fayllari:** `GET /admin/support-threads/{id}/files/{ref}` — faol sessiya (`sid`), `ops.trust_review`, fayl shu
  murojaatga tegishli; javob mavjud qisqa muddatli imzoli havola (`media_ref`), ko'rish audit'da. Admin DTO'da xom storage
  kaliti o'rniga `files[{ref, name, message_id, staff_only}]`. Original fayl nomi saqlanmagani uchun nom — «Dalil N -
  muallif, sana, format».
- **Katalog (0094):** ikkinchi xodim talabi olib tashlandi (asos yo'q: repo'dagi ikki xodim qoidalari faqat pul bo'yicha);
  boshqaruv, versiyalash, audit va production'da sintetik katalog rad etilishi saqlandi.
- **D-4 (ochiq):** `qualification_path_retired` review rad etilmaydi; ma'qullash grant emas. Qaror uchun kerak: qaysi
  enrollment'lar (ADR-0026 dan oldin `promised` bo'lgan pochta enrollment'lari), qanday muqobil dalil (masalan, xodim qayd
  etgan yetkazish + operator dalili + real komissiya capture + ochiq nizo yo'qligi, yoki qabul qiluvchi tasdig'i) va qaysi
  vakolat bilan grant (masalan, `promo.fraud_decide` + budjet uchun finance). Qarorgacha rezervlar saqlanadi.

