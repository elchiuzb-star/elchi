# U6 — `rating_bucket`: qaror uchun variantlar

> ## ✅ QAROR QABUL QILINDI — 17.09.2026: **A-variant**
>
> Wave 8 da implementatsiya qilindi: `RatingBucket` enum (`new_verified`/`good`/`mixed`/`low`),
> `RATING_BUCKET_MIN_COUNT = 3`, `good ≥ 4.0`, `mixed ≥ 3.0`, `low < 3.0`;
> `ListingOfferDTO.rating_bucket` + yangi `rating_count` maydoni to‘ldiriladi.
> Testlar: `tests/contracts/test_rating_bucket_u6.py` (12), `tests/pg/marketplace/test_marketplace_wave16_pg.py` (U6 qismi).
> Quyidagi matn qaror qabul qilingunga qadar yozilgan tahlil sifatida saqlanadi.


**Holat:** ochiq (foydalanuvchi qarori) • **Tayyorladi:** wave 7 agenti • **Sana:** 17.09.2026
**Spec:** §8.2 (“UI’da yangi haydovchiga sun’iy 4.5 yozilmaydi”), §8.3, AC36 • **Bog‘liq:** ADR-0019 (R1 anonim
taklif ko‘rinishi), Q40 (mijoz raqobatchi takliflarni ko‘radi)

> Hozirgi xulq **o‘zgartirilmadi**: `rating_bucket` hamon `null`. Bu hujjat faqat variantlarni taqdim etadi.

## 1. Hozir nima bor

| Joy | Holat |
|---|---|
| `ListingOfferDTO.rating_bucket` ([schemas.py](../../../app/modules/marketplace/schemas.py)) | `str \| None`, **doim `null`** — “A12 gacha sun’iy reyting yo‘q” |
| `ListingOfferDTO.completed_bookings` | `int \| None`, hozir `null` |
| Reyting manbai | `trust_support.service.reputation_summaries` → `ReputationSummary` (`rating_count`, `rating_sum`, `completed_bookings`, `on_time_count`, …) |
| Ko‘rsatiladigan o‘rtacha | `average_rating` — `rating_count = 0` bo‘lsa `None` (S2) |
| Yorliq | `ReputationLabel`: `new_verified` (baho yo‘q) / `rated` |
| Ichki saralash | `adjusted_rating = (sum + m × prior) / (n + m)`, `m = 10`, `prior = 4.5` — **faqat tartiblash uchun**, UI’da ko‘rsatilmaydi (§8.2) |
| Mijoz ko‘radigan taklif kartasi | Anonim: “Haydovchi #2”, avtomobil klassi, o‘rin sig‘imi, narx, oyna (ADR-0019) |

Ya’ni ranking allaqachon Bayes tuzatishi bilan ishlaydi; yetishmayotgani — **mijozga ko‘rsatiladigan qisqa
ishonch belgisi**. `rating_bucket` aynan shu ko‘rsatkich uchun ajratilgan maydon.

## 2. Nega bu qaror kerak

- Reytingni aniq son bilan ko‘rsatish (“4.8”) kam bahoda adolatsiz: 1 ta 5.0 va 200 ta 4.8 bir xil ko‘rinadi
  (§8.2 aynan shundan ogohlantiradi).
- Butunlay ko‘rsatmaslik mijozga tanlash uchun signal bermaydi va operator yordamiga bosim tushadi.
- Shuning uchun spec “bucket” (guruh) tushunchasini qoldirgan: aniq son emas, **ishonch darajasi**.

## 3. Variantlar

### A-variant (tavsiya etiladi) — baholar soniga bog‘langan uch guruh + “yangi”

| Bucket | Shart | Mijoz ko‘radi |
|---|---|---|
| `new_verified` | `rating_count < 3` | “Yangi haydovchi (hujjatlari tekshirilgan)” |
| `good` | `rating_count ≥ 3` va `average ≥ 4.0` | “Yaxshi baholangan · 12 ta baho” |
| `mixed` | `rating_count ≥ 3` va `3.0 ≤ average < 4.0` | “Aralash baholar · 7 ta baho” |
| `low` | `rating_count ≥ 3` va `average < 3.0` | “Past baholangan · 5 ta baho” |

- **Minimal baholar soni:** 3 (pilotda kam ma’lumot — 1 ta baho guruh bermaydi).
- **Ma’lumot yetarli bo‘lmasa:** `new_verified` (sun’iy 4.5 emas, nol ham emas).
- **Har doim baholar soni bilan** ko‘rsatiladi (§20.4 “kichik n’da foiz yonida son”).
- Ustunligi: mijoz farqni ko‘radi, lekin bitta baho butun profilni ko‘tarmaydi.

### B-variant — faqat ikki holat: “yangi” yoki “baholangan (n ta)”

| Bucket | Shart | Mijoz ko‘radi |
|---|---|---|
| `new_verified` | `rating_count = 0` | “Yangi haydovchi (hujjatlari tekshirilgan)” |
| `rated` | `rating_count ≥ 1` | “12 ta baho” (o‘rtacha ko‘rsatilmaydi) |

- Hozirgi `ReputationLabel` bilan aynan bir xil — ya’ni amalda **yangi qaror talab qilmaydi**.
- Ustunligi: past baho bilan “yorliqlash” yo‘q, nizo kam.
- Kamchiligi: mijozga sifat signali bermaydi; tanlov faqat narx va vaqtga tushadi.

### C-variant — o‘rtacha bahoni faqat yetarli n’da ko‘rsatish

| Bucket | Shart | Mijoz ko‘radi |
|---|---|---|
| `new_verified` | `rating_count < 10` | “Yangi haydovchi · 4 ta baho” |
| `rated` | `rating_count ≥ 10` | “4.7 ★ · 23 ta baho” |

- Ustunligi: tanish va tushunarli.
- Kamchiligi: 10 chegarasidan o‘tgan zahoti “4.2” va “4.8” farqi kuchayadi; past baholi haydovchi amalda
  ko‘rinmay qolishi mumkin (§8.4 “yangi haydovchiga oz miqdorda navbatli ko‘rinish” siyosati bilan ziddiyat).

## 4. Qaror ta’siri

| Tanlov | Kodda o‘zgaradigan joy | Ta’sir |
|---|---|---|
| A | `app/contracts/trust.py` ga bucket funksiyasi + `ListingOfferDTO.rating_bucket`/`completed_bookings` to‘ldirish (A12 → A1 servis funksiyasi orqali) | Yangi migratsiya **kerak emas** (ma’lumot `reputation_snapshots` da bor); mobil UI matni A8 |
| B | Faqat `rating_bucket = label` mapping | Eng kichik o‘zgarish |
| C | A bilan bir xil, chegara boshqa | Bir xil |

Barcha variantlarda saqlanadi: sun’iy reyting yo‘q, `null` o‘rniga 0 yozilmaydi, ichki `adjusted_rating`
ko‘rsatilmaydi, baholar soni har doim ko‘rinadi.

## 5. Savol

**`rating_bucket` uchun A, B yoki C variant tanlanadimi?** Tanlangach chegaralar `app/contracts/trust.py` ga
konstanta sifatida kiritiladi va `ListingOfferDTO` to‘ldiriladi; tasdiqlanmaguncha maydon `null` qoladi.
