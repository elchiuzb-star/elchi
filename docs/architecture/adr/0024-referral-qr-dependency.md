# ADR-0024: Referral QR kodi — `qrcode-generator` kutubxonasi (mobile-app)

**Holat:** Accepted (foydalanuvchi topshirig‘i 23.09.2026: «oddiy dependency tanlovi uchun alohida ruxsat kutib qolmang») • **Sana:** 24.09.2026
**Qarorlar:** Q107 (havola), Q123–Q129 bilan bir topshiriqda • **AGENTS.md §2:** yangi dependency ADR asosida, pin bilan

## Kontekst
5-bosqichda haydovchi o‘z taklif havolasini QR ko‘rinishida ko‘rsatishi kerak. Talablar:
- QR **qurilmada** yaratiladi — referral kodi yoki shaxsiy ma’lumot uchinchi tomon QR xizmatiga (masalan, rasm URL’i
  qaytaradigan API) yuborilmaydi;
- QR ichida faqat server bergan `share_url` (`https://<ELCHI_REFERRAL_LINK_HOST>/r/<kod>`) — hech narsa qo‘shilmaydi;
- kodni nusxalash va qo‘lda kiritish yo‘li saqlanadi.

`mobile-app/package.json` dagi mavjud dependency’larda QR generatori yo‘q edi (`@phosphor-icons/react`, React, Vite, test
vositalari).

## Qaror
`qrcode-generator` **2.0.4** — `mobile-app/package.json` da aniq versiya bilan (`"qrcode-generator": "2.0.4"`,
`npm install --save-exact`), `package-lock.json` yangilangan.

| Mezon | Qiymat (npm reyestri, 24.09.2026 tekshirildi) |
|---|---|
| Litsenziya | MIT |
| Runtime dependency | yo‘q (0) |
| Tiplar | paket ichida (`dist/qrcode.d.ts`), ESM (`dist/qrcode.mjs`) |
| Muallif / manba | Kazuhiko Arase, `github.com/kazuhikoarase/qrcode-generator` — QR ning keng tarqalgan JS implementatsiyasi |
| Oxirgi nashr | 2.0.4 (reyestr `time.modified` 2025-08-07) |
| Tarmoq | kod ichida `fetch`/XHR yo‘q; faqat matritsa hisoblanadi |

Ishlatilishi: `mobile-app/src/app/v2/PromoScreens.tsx` → `ReferralQr` — `qrcode(0, "M")`, `addData(url, "Byte")`,
`isDark(row, col)` bo‘yicha React SVG `<path>` chiziladi (`dangerouslySetInnerHTML` va `<img>` yo‘q). Ranglar tema
tokenlari `--qr-light`/`--qr-dark` (qorong‘u rejimda ham oq fonda qora — skanerlar uchun ataylab temalanmagan).
Test: `PromoScreens.test.tsx` — SVG chiziladi, `fetch` chaqirilmaydi, `<img>`/tashqi QR xizmati yo‘q.

## Muqobillar
- `qrcode` (soldair) — PNG/terminal/CLI uchun qo‘shimcha dependency’lar (`pngjs`, `yargs`, …); bizga faqat matritsa kerak.
- `uqr` (MIT, 0 dependency) — ham mos, lekin `qrcode-generator` uzoqroq vaqt davomida keng ishlatilgan.
- Uchinchi tomon QR rasm API’si — taqiqlangan (kod tashqariga chiqadi).

## Oqibatlar
- Bundle’ga ~20 KB (gzip’dan oldin) qo‘shiladi; yangi runtime dependency daraxti yo‘q.
- QR yaratilgani havola yoki App Links ishlashining **dalili emas**: domen, DNS, TLS, deploy va qurilmadagi tekshiruv
  alohida (`docs/referral/INFRA_HANDOFF.md`, `docs/referral/APP_LINKS_HANDOFF.md`). `share_url` bo‘sh bo‘lsa QR
  ko‘rsatilmaydi, kodni nusxalash va qo‘lda kiritish qoladi.
- Versiyani yangilash — shu ADR’ni yangilab, pin bilan.
