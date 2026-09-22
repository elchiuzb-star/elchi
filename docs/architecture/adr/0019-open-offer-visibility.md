# ADR-0019: Ochiq taklif ko‘rinishi (request listing’da “ochiq auksion”)

**Holat:** Accepted (Q40–Q42, 14.09.2026, wave 1.6); **narx qismi Q90 bilan almashtirildi (18.09.2026, wave 15)** — egalar: **A1** (offers endpoint, anonim DTO, listing/proposal matn filtri, narx referensi), **A2** (koridor segmenti narx referensi konfiguratsiyasi, 0046/0078), A5 (ko‘rinish huquqi lenta bilan bir xil), A7 (event), A8/A9 (UI), A12 (til biriktirish signallari) • **Sana:** 14.09.2026 • **Muallif:** A0a

> **Q90 tuzatishi (18.09.2026).** Bu ADR’ning 7-bandi diapazondan tashqari taklifni `400 PRICE_OUT_OF_BAND`
> bilan rad etardi va “ogohlantirish” variantini **ataylab rad etgan** edi. Foydalanuvchi qarori Q90 aynan shu
> tanlovni qaytardi: ELCHI ikki tomonlama auksion, narxni tomonlar kelishadi, shuning uchun diapazon
> **referens** — ogohlantiradi (`WarningCode.PRICE_OUTSIDE_REFERENCE`) va ranking’ga kiradi, lekin taklifni
> bloklamaydi. Yagona qattiq rad — admin ataylab qo‘ygan `corridor_price_bands.enforced = true` (abuse/safety
> chegarasi), u hamon `400 PRICE_OUT_OF_BAND` beradi. Sabab spetsifikatsiyaning o‘zida: §8.2 `L/U` ni **faqat**
> `P` ranking komponenti deb ataydi va ishonchli diapazon bo‘lmasa `P=0.5` beradi; 188-qator esa masofaga
> mutanosib hisob “yakuniy kelishuv o‘rnini bosmaydi” deydi. ADR’ning qolgan qismi (anonim ko‘rinish, Q40/Q41)
> o‘zgarmadi.
**Spec:** §3 (inDrive tamoyillari), §5.3 (kelishuv protokoli), §8 (saralash, L/U), §10.6 (ko‘rinish/maxfiylik), §15 (event’lar), §17.3 (firibgarlik) • **Bog‘liq:** ADR-0005, ADR-0007, ADR-0012, ADR-0020

## Kontekst
Yangi talab R1: mijozning request listing’iga haydovchilar bergan takliflar boshqa haydovchilarga ham ko‘rinsin (ochiq auksion kabi). Hozirgi kontrakt (API §7): P2 `GET /listings/{id}/proposals` faqat listing egasiga; thread va versiyalar tomonlar o‘rtasida xususiy. v1’da (`app/services/driver_order_service.py`, HEAD) boshqa haydovchilarning bid’lari cheklangan shaklda driver lentasida ko‘rinadi — ya’ni ochiqlikning ma’lum darajasi legacy’da bor.
Xavflar: narx dempingi (§8.4 “arzonlikni mukofotlash xato”), haydovchilar o‘rtasida til biriktirish, raqobatchini aniqlab platformadan tashqarida kelishish (ADR-0020), shaxsiy ma’lumot sizishi (§10.6).

## Taklif etilgan qaror
1. **Doira:** faqat v2, faqat `kind=request` listing’lar (passenger va parcel). Haydovchi `trip_offer`iga mijoz takliflari **xususiy** qoladi.
2. **Kim ko‘radi:** listing’ni ko‘ra oladigan (A5 lenta/matching bo‘yicha mos, `proposal.submit_as_driver` capability’li, eligible) haydovchilar.
3. **Nima ko‘rinadi (har raqobatchi faol taklif uchun anonim):**
   - joriy versiyaning `total_minor` va `unit_price_minor`, `price_basis`;
   - taklif qilingan pickup oynasi va segment (bekatlar nomi);
   - avtomobil klassi va o‘rin sig‘imi (aniq model emas);
   - reyting bucket’i (masalan `new`, `4.0–4.4`, `4.5+`) va bajarilgan bronlar soni (§8.2 adjusted rating ichki qoladi);
   - yuborilgan/yangilangan vaqt;
   - barqaror anonim yorliq: “Haydovchi #3” (listing ichida thread bo‘yicha tartib raqami, boshqa listing’lar bilan bog‘lab bo‘lmaydi);
   - o‘z taklifi ajratib ko‘rsatiladi (`is_mine: true`).
4. **Nima ko‘rinmaydi:** ism, foto, davlat raqami, telefon, aniq avtomobil modeli/rangi, user/driver public id, thread/version id’lari, counter tarixi.
5. **Muzokara xususiyligi:** mijoz ↔ haydovchi counter shartlari faqat shu juftlikka; boshqalar har haydovchining faqat **joriy** taklifini ko‘radi (counter natijasida joriy versiya o‘zgarsa, yangi joriy qiymat ko‘rinadi — tafsilotsiz).
6. **Mijoz ko‘rinishi:** o‘zgarmaydi — to‘liq takliflar §8 bo‘yicha saralangan (P2, `MatchDTO`).
7. **Demping cheklovi:** koridor segmenti bo‘yicha operator konfiguratsiyasidagi narx floor/ceiling (`corridor_config_versions.price_reference`, §8.2 L/U). Floor’dan past/ceiling’dan yuqori taklif `400 VALIDATION_ERROR` (`details.reason=price_out_of_range`) yoki ogohlantirish — pilot qarori tasdiqda aniqlanadi (tavsiya: rad etish).
8. **Endpoint:** `GET /api/v2/listings/{listing_id}/offers` (driver ko‘rinishi), cursor pagination, `Envelope[list[OpenOfferViewDTO]]`.
   `OpenOfferViewDTO {label ("Haydovchi #3"), is_mine, total_minor, unit_price_minor, price_basis, currency, pickup_stop_name, dropoff_stop_name, pickup_window_start, pickup_window_end, vehicle_class, seat_capacity, rating_bucket, completed_bookings, submitted_at, updated_at}`. Listing ko‘rinmasa/eligible bo‘lmasa `404`.
9. **Event auditoriyasi:** yangi auditoriya qoidasi — `proposal.created/superseded/withdrawn/expired` event’larining “raqobatchi driver” nusxasi faqat `listing_id` va yangilanish belgisini oladi (payload’da narx yo‘q; klient endpointni qayta o‘qiydi). A7 yetkazishni amalga oshirmaguncha klient polling qiladi (masalan 15–30 s, ETag/`updated_at` bilan).
10. **Egalar (tasdiqdan keyin):** A1 (endpoint, DTO, anonimlashtirish, floor/ceiling tekshiruvi), A2 (koridor narx konfiguratsiyasi), A5 (ko‘rinish huquqi lenta bilan bir xil), A7 (event), A8/A9 (UI), A12 (til biriktirish signallari).

## Muqobillar
| Variant | Nega tavsiya etilmaydi |
|---|---|
| To‘liq yopiq (joriy kontrakt) | R1 ga zid |
| To‘liq ochiq (ism, reyting, avtomobil bilan) | §10.6 maxfiylik, platformadan tashqari kelishuv xavfi (ADR-0020) |
| Faqat agregat (min/median narx, takliflar soni) | Kamroq sizish, lekin R1 “takliflar ko‘rinsin” talabini qisman bajaradi — **zaxira variant** sifatida tavsiya etiladi |
| Faqat eng past narx | Dempingni rag‘batlantiradi (§8.4) |

## Oqibatlar
- Narx raqobati kuchayadi; floor/ceiling va §8 reytingi (narx 20%) muvozanatni saqlashi kerak.
- Qo‘shimcha o‘qish yuklamasi (polling) — cache/ETag kerak.
- Anonim yorliqlar listing ichida barqaror bo‘lishi uchun deterministik (thread yaratilish tartibi) hisoblanadi; boshqa listing’lar bo‘ylab bog‘lanmaydi.
- Legacy v1 xulqi o‘zgarmaydi.

## Mavjud DTO’larga ta’sir (A1 qaydi, wave 1.5)
- `ProposalThreadDTO` hozir qarshi tomonning **ismi (first name)**ni ko‘rsatadi — ochiq ko‘rinishda raqobatchi driverlarga bu DTO berilmaydi (faqat `OpenOfferViewDTO`); tasdiqlansa, thread DTO’dagi ism qoidasi ADR-0020 bilan birga qayta ko‘riladi.
- `ListingPublicDTO.owner_display_name` — request listing’ni ko‘radigan barcha driverlarga ko‘rinadi; ADR-0019/0020 tasdiqlansa, qabuldan oldin anonim yorliq (masalan “Mijoz”) bilan almashtirish tavsiya etiladi.
