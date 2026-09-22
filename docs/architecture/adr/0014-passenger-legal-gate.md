# ADR-0014: Yo‘lovchi xizmati uchun huquqiy gate

**Holat:** Accepted (K7, Q5) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §4 (P0), §5.2 (yolg‘iz voyaga yetmaganlar), §17.1, §17.7, §20.3 • **AC:** AC01, AC07, AC10, AC11, AC38 • **Qarorlar:** K7

## Kontekst
K7: yo‘lovchi xizmati to‘liq quriladi va test qilinadi, lekin production’da har koridor uchun `passenger_enabled` huquqiy tekshiruvgacha o‘chiq. Pochta oqimi mustaqil. Spec §17.7 tashish va litsenziya talablarini launch oldidan mutaxassis tekshiruvini talab qiladi; hujjat huquqiy muvofiqlikni tasdiqlamaydi.

## Qaror
1. Yo‘lovchi funksionalligi (listing, proposal, segment sig‘imi, boarding kodi, no-show, rating) kodda to‘liq; gating faqat feature flag orqali (ADR-0008), kod shoxlanishi orqali emas.
2. `passenger_enabled` production default `false` (`PRODUCTION_FLAG_DEFAULTS`); yoqish uchun `super_admin` + `approval_reference` (`400 APPROVAL_REFERENCE_REQUIRED`) + audit.
3. Flag o‘chiq bo‘lsa server rad etadi: `POST /listings` (`service_type=passenger`) publish, proposal submit va accept → `403 FEATURE_DISABLED`. Feed passenger natijalarini qaytarmaydi. Trip offer’ning passenger listing’i yaratilmaydi; bir trip’dagi parcel listing ishlaydi.
4. Flag o‘chirilganda mavjud passenger bronlari bajariladi (AC38).
5. Pochta xizmati `parcel_enabled` bilan alohida boshqariladi; passenger flag unga ta’sir qilmaydi.
6. Dev/staging/test muhitlarida passenger yoqilgan holda AC’lar to‘liq bajariladi; A11 hisobotida “production’da o‘chiq” alohida ko‘rsatiladi.
7. Pilot siyosati: yolg‘iz voyaga yetmaganlar qabul qilinmaydi (`adults ≥ 1` CHECK, §5.2) — huquqiy xulosa emas, mahsulot cheklovi.

## Muqobillar
- **Passenger kodini keyinga qoldirish** — K7 ga zid, segment sig‘imi pochta+bagaj bilan umumiy.
- **Env bayrog‘i** — koridor scope va audit yo‘q.

## Oqibatlar
- mobile-app UI flag holatini ko‘rsatadi (“Bu yo‘nalishda yo‘lovchi xizmati hozircha mavjud emas”), soxta imkoniyat va’da qilinmaydi.
