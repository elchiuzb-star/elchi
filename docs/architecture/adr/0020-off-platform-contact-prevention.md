# ADR-0020: Platformadan tashqari aloqani oldini olish

**Holat:** Accepted (Q43–Q45, 14.09.2026, wave 1.6) — **foydalanuvchi qarori spec §16 dagi “tasdiqlangan ishtirokchiga telefon ochiladi” qoidasini almashtiradi** (telefon xizmat boshlanganda ochiladi). Egalar: **A1 hozir** (DTO ko‘rinish qoidalari, listing/proposal matnlarida filtr), **A4** (start’da telefon ochish, 24 soatdan keyin yashirish, parcel qabul qiluvchi telefoni pickup’dan keyin), **A7** (chat + filtr), **A12** (strike’lar, ko‘rib chiqish navbati, aylanib o‘tish signallari); filtr kontrakti `app/contracts/contact_filter.py` (A0a) • **Sana:** 14.09.2026 • **Muallif:** A0a
**Spec:** §9.5 (jarima yo‘q), §10.6 (ko‘rinish), §16 (aloqa), §17 (ishonch, maxfiylik), §22 AC30 • **Bog‘liq:** ADR-0007, ADR-0012, ADR-0015, ADR-0019

## Kontekst
Yangi talab R2: parcel/trip boshlanguncha mijoz va haydovchi ilovadan tashqarida bog‘lana olmasin (komissiyani chetlab o‘tish va xavfsizlik).

**Spetsifikatsiya bilan ziddiyat (aniq):**
- **§16** kelishuv chati haqida: “telefon faqat **tasdiqlangan ishtirokchilarga** ochiladi” — ya’ni bron **qabul qilingandan** keyin. R2 telefonni faqat **xizmat boshlanganda** ochadi. Bu §16 dan qat’iyroq va foydalanuvchi qarori bilan §16 ni o‘zgartiradi (spetsifikatsiya faylining o‘zi o‘zgartirilmaydi; ADR ustunligi AGENTS §1 bo‘yicha qaror sifatida).
- **§10.6 / §17:** qabuldan oldin telefon, uy manzili, aniq GPS ommaviy e’londa yo‘q — R2 bilan mos, kuchaytiradi.
- Legacy v1 va muzlatilgan `android-app` tayinlashdan keyin telefonni ko‘rsatadi — bu ADR v1 ga taalluqli emas (ma’lum bo‘shliq).

## Taklif etilgan qaror
1. **Qabuldan oldin:** telefon, to‘liq ism, davlat raqami, aniq manzil hech bir DTO’da yo‘q (hozirgi API §5/§7 qoidalari saqlanadi va tekshiriladi).
2. **Kontakt-ma’lumot detektori** (barcha erkin matnlar: listing izohi, taklif xabari, chat, parcel tavsifi, rating matni, profil maydonlari):
   - telefon raqamlari har formatda (bo‘shliq/defis/nuqta bilan ajratilgan raqamlar, `+998`, `998`, `9x xxx xx xx`), kirill/lotin so‘z bilan yozilgan raqamlar (“to‘qson bir”, “девяносто”), e-mail, `@handle`, `t.me/…`, `telegram`, `whatsapp`, `instagram` havolalari, “tel/qo‘ng‘iroq qiling/позвони/звони” naqshlari;
   - moslik **maskalanadi** (`•••`), muallifga ogohlantirish; takroriy urinishlar **strike** yozadi va operator ko‘rib chiqish navbatiga (A12); **avtomatik ban yo‘q**;
   - detektor qoidalari versiyalanadi, false-positive holatlarida operator tiklaydi.
3. **Qabuldan keyin, xizmat boshlanguncha** (passenger: boarding code/`onboard`; parcel: `picked_up`): aloqa faqat ilova ichidagi chat va tezkor tugmalar (“Bekatdaman”, “5 daqiqada yetaman”), tracking oynasida haydovchining jonli joylashuvi va “Keldim” (`arrive_at_pickup`) signali. Telefon almashinuvi yo‘q. Telefoniya relay orqali maskalangan qo‘ng‘iroq — keyingi ixtiyoriy qo‘shimcha (xarajat va provayder mavjudligi; §16 “majburiy emas”).
4. **Xizmat boshlanganda:** xavfsizlik uchun ishtirokchilar telefoni ochiladi; yakunlangandan keyin **24 soat** o‘tib yana yashiriladi.
5. **Parcel:** qabul qiluvchi telefoni haydovchiga faqat **pickup’dan keyin**; jo‘natuvchi telefoni haydovchiga hech qachon ko‘rsatilmaydi (faqat chat).
6. **Har doim mavjud:** support/SOS va favqulodda raqam (xizmat holatidan qat’i nazar).
7. **Aylanib o‘tish signallari** (A12 operator navbati): chatda kontaktdan keyin tez bekor qilingan bron, bir juftlikning takroriy bekor qilishlari, detektor strike’lari. Pilotda jarima yo‘q (§9.5); har qanday jazo siyosati — alohida qaror.
8. **Rasmlar:** cargo/avtomobil rasmlarida kontakt bo‘lishi mumkin — hozir operator tanlab tekshiradi; OCR — keyinroq (P2).
9. **v1/muzlatilgan Android:** o‘zgarmaydi (tayinlashdan keyin telefon ko‘rinadi) — Android v2 klienti uchun ma’lum bo‘shliq.
10. **Rostgo‘ylik:** bu choralar platformadan tashqari aloqani **kamaytiradi, lekin to‘liq to‘xtata olmaydi** (yuzma-yuz uchrashuv, ilova tashqarisidagi tanishlik). UI va’da qilmaydi.
11. **Egalar (tasdiqdan keyin):** A1 (DTO ko‘rinish qoidalari hozirgi endpointlarda), A4 (booking DTO’larida xizmat boshlanganda ochish va 24 soatdan keyin yashirish), A7 (chat + filtr), A12 (strike, ko‘rib chiqish navbati, signallar); detektor kontrakti — integrator (`app/contracts`, tasdiqdan keyin).

## Muqobillar
| Variant | Nega tavsiya etilmaydi |
|---|---|
| §16 bo‘yicha qabuldan keyin telefon ochish (joriy) | R2 ga zid |
| Telefonni hech qachon ko‘rsatmaslik (faqat relay) | Relay xarajati va provayder mavjudligi noaniq; xizmat davomida xavfsizlik uchun to‘g‘ridan-to‘g‘ri aloqa kerak |
| Avtomatik ban/jarima | §9.5 pilotda jarima yo‘q; false-positive xavfi |
| Faqat regex filtri, signallarsiz | Aylanib o‘tish oson; operator ko‘rinishi yo‘q |

## Oqibatlar
- Qabul va xizmat boshlanishi orasida aloqa ilovaga bog‘liq — push/chat ishonchliligi (A7, AC34) muhimroq bo‘ladi.
- Legacy v1 bilan nomuvofiqlik (parallel bozorlar, ADR-0006).
- Detektor false-positive’lari UX’ga ta’sir qiladi — maskalash (bloklash emas) va operator tiklashi bilan yumshatiladi.
- §16 matni bilan ziddiyat hujjatlashtirilgan; tasdiqlansa COVERAGE_MATRIX va API kontraktida DTO ko‘rinish qoidalari yangilanadi.

## Mavjud DTO’larga ta’sir (A1 qaydi, wave 1.5)
- `ProposalThreadDTO` qarshi tomonning ismini (first name) ko‘rsatadi — R2 bo‘yicha qabuldan oldin **olib tashlanishi** yoki anonim yorliq bilan almashtirilishi kerak (qidiruv/tanishuv orqali tashqi aloqa xavfi).
- `ListingPublicDTO.owner_display_name` — qabuldan oldin barcha ko‘ruvchilarga; R2 bo‘yicha anonimlashtirish tavsiya etiladi.
- Ikkalasi hozirgi Accepted kontraktda (API §5, §7) ruxsat etilgan; ADR tasdiqlanmaguncha o‘zgartirilmaydi.

## Wave 2.1 Q-qarorlari (15.09.2026)
- **Q64 — davlat raqami:** accept’dan keyin ishtirokchiga maskalangan raqam (`disclosure.mask_plate_number`) + model + rang (`dto.BookingVehicleDisclosureDTO`); **to‘liq raqam** faqat trip `boarding` holatida yoki bron pickup vaqtiga ≤ 30 daqiqa qolganda (`disclosure.full_plate_visible`). Wave 2 dagi “`awaiting_pickup`dan boshlab” implementatsiyasini almashtiradi; 1-band (accept’dan oldin raqam yo‘q) o‘zgarmaydi.
- **Q65 — delivery kodi va chat:** `delivered` bronni avtomatik yakunlamaydi (jo‘natuvchi tasdiqlaydi yoki 24 soatda operator navbati); delivery kodi jo‘natuvchiga “faqat qabul qiluvchiga bering” ogohlantirishi bilan; chatda 6 xonali kodlar maskalanadi (A7 `mask_proof_codes=True`). Kod qabul qiluvchiga havola/SMS orqali — keyin.

## Staff kontakt ko‘rinishi auditi (15.09.2026, wave 2.1 BR tuzatish raundi)
- 4-banddagi “Operator (staff) ko‘rinishi o‘zgarmaydi (audit bilan)” qoidasining implementatsiyasi: staff javobida ishtirokchi telefoni ko‘rsatilsa `audit_logs` qatori yoziladi, telefon qiymati yozilmaydi. Bronlar — `booking_contacts_viewed` (A4, B1/B12); listinglar — `listing_contacts_viewed` (A1, L2 staff ko‘rinishi, parcel sender/receiver telefonlari; `marketplace.service.record_staff_listing_contact_view`).
