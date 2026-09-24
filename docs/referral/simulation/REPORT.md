# Referral simulyatsiyasi (6-bosqich) — **SINTETIK SSENARIYLAR**

> Barcha kirish qiymatlari va natijalar **sintetik ssenariy**: haqiqiy ma'lumot yo'q, hech bir qiymat tasdiqlanmagan va production konfiguratsiyasiga ko'chirilmaydi. Natijalar faqat kiritilgan taxminlarning oqibati — foydalanuvchilar soni albatta oshishi yoki platforma zarar ko'rmasligi isboti **emas**. Operatsion (haqiqiy) ko'rsatkichlar bu yerda yo'q — ular admin hisobotida (`GET /api/v2/admin/promo/report`, `data_source = operational`).

## Takrorlash

- Buyruq: `py scripts/promo_simulate.py` (tekshirish: `py scripts/promo_simulate.py --check`)
- Kod barmoq izi: `6acd2f5b07d56678` (simulyator + `app/contracts/promo.py`, `money.py`, `enums.py`)
- Konfiguratsiya: `docs/referral/simulation/scenarios.json`; natijalar: `results.json`
- Seed va konfiguratsiya barmoq izi har ssenariy uchun:

| Ssenariy | Seed | Konfiguratsiya barmoq izi | Sintetik | Izoh |
|---|---|---|---|---|
| control | 20260924 | `0ff67cf6b1d0f6b3` | ha |  |
| conservative | 20260924 | `e27870e9255cbafe` | ha |  |
| medium | 20260924 | `fad342f6a029d144` | ha |  |
| adverse | 20260924 | `4ecee5eb2d782a54` | ha |  |
| stress_full_redemption | 20260924 | `e10f43cee39f52fd` | ha |  |
| ops_delay_shortage | 20260924 | `b05294a2d1876dce` | ha |  |
| zero_budget | 20260924 | `4e0dc795b8fc2279` | ha |  |
| budget_cut | 20260924 | `db70ccfc5184870b` | ha |  |
| funding_loss | 20260924 | `d417a854822c0c8a` | ha |  |
| variant_A | 20260924 | `2bfa8f0d38d8d233` | ha | Foydalanuvchi qarori 24.09.2026: kelajakdagi yo'lovchi pilotini baholash uchun asosiy nomzod. Summalar va 600 000 so'mlik budjet production uchun TASDIQLANMAGAN; yo'lovchi xizmatining huquqiy/texnik gate'lari saqlanadi. |
| variant_B | 20260924 | `84d4e65f4182ac91` | ha | Foydalanuvchi qarori 24.09.2026: hozirgi ko'rinishida tasdiqlanmaydi; pochta qismi alohida baholanadi (parcel_* tajribalari). |
| variant_C | 20260924 | `1e9cdfa577da718e` | ha | Foydalanuvchi qarori 24.09.2026: keyingi baholashga qoldirildi (haydovchi milestone va qo'shimcha kampaniyalar hozir yo'q). |
| parcel_base | 20260924 | `f5f52c600893c83c` | ha | tajriba: pochta_sintetik_tajriba |
| parcel_small_reward | 20260924 | `cfad0fbcb50f515b` | ha | tajriba: pochta_sintetik_tajriba |
| parcel_long_validity | 20260924 | `9d41d38543ff5052` | ha | tajriba: pochta_sintetik_tajriba |
| parcel_more_orders | 20260924 | `4f42baeafbfca55f` | ha | tajriba: pochta_sintetik_tajriba |
| parcel_richer_mix | 20260924 | `d6cae97f75b67124` | ha | tajriba: pochta_sintetik_tajriba |
| parcel_small_long | 20260924 | `94c799e9e131664c` | ha | tajriba: pochta_sintetik_tajriba |

## 1. Model nimani hisoblaydi

- Oqim: taklif kodi → attribution → enrollment (ikkala tomon maksimal majburiyati budjetdan rezerv) → qualification (48 soatlik risk oynasi, taklif qiluvchi xizmati hisoblanmaydi, pochtada 2 ta jo'natma) → grant (va'da → berilgan) → sarflash (keyingi buyurtmalarda P, haydovchi buyurtmalarida H).
- Birinchi va takroriy buyurtmalar; bekor qilish (Q129), nizo, fee release, reversal (Q127), kech capture, review, qisman sarf, expiry, grace, reinstate (Q122), haydovchi milestone'lari, P va H birga/alohida, haydovchi topilmasligi; past/o'rta/yuqori narx.
- **Formula bitta:** har bron shartlari `contracts.promo` dan (`choose_passenger_source`, `choose_driver_source`, `quote_at_accept`, `combined_margin_policy`); lot `LotBalance`, budjet `BudgetPosition`, qualification `evaluate_qualification`. PostgreSQL bilan solishtirilgan: `tests/pg/promotions/test_promo_simulation_pg.py`.
- **Ikki marta sanalmaydi:** `F_cash = F − P`, `C_net = C − P − H`; `C − P − H − reversal = saqlangan C_net` alohida tekshiriladi. F va F_cash — hajm, tushum emas; haydovchi top-up modelda yo'q. Doimiy xarajat va soliq **noma'lum** → biznes natijasi hisoblanmaydi.
- **Attribution ≠ sabab.** Qo'shimcha foydalanuvchilar (`incremental_new_per_day`) — ochiq taxmin; faqat va'da bera oladigan kampaniya bo'lsa keladi. Har ssenariy **juft nazorat** bilan (xuddi shu dunyo, referral o'chiq, `<nom>~control`); tasodifiy sonlar barqaror identifikator bo'yicha chiziladi.
- **Cohort langari (A6.2) — har ko'rsatkich o'z langari bilan, aralashtirilmaydi:**
  - *enrollment* → qualification ulushi (qualification oynasi + capture/review dumi o'tgan enrollment'lar);
  - *aktivlashish* (commission capture qilingan birinchi bronning xizmat kuni) → D30/D60 qaytish, D60 marja;
  - *grant* (`available_from`, bonus sarflanishi mumkin bo'lgan lahza) → 30 kunlik bonus sarfi; yaqinda berilgan lot yetilmagan hisoblanadi.
  - Oynasi hali to'lmagan kuzatuv **yetilmagan** deb alohida sanaladi — "qaytmadi", "nol daromad" yoki "ishlatilmadi" hisoblanmaydi. Yetilgan kuzatuv minimaldan kam bo'lsa qiymat **"hali baholab bo'lmaydi"**, nol emas. Hisob sanasi — snapshot kuni (kuzatilgan oxirgi kun = kun − 1).

## 2. Asosiy natijalar (90 kun, so'm) — juft nazoratga nisbatan

Stress marja — qolgan majburiyat (va'da + sarflanmagan bonus) kelajakda to'liq sarflansa.

| Ssenariy | Xizmat ko'rsatilgan | C | P | H | Saqlangan C_net | Reversal | O | Operatsion marja | Nazoratdan farq | Qolgan majburiyat | Stress farq | Rad (budjet) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | 1115 | 9 040 000 | 0 | 0 | 9 000 250 | 39 750 | 1 115 000 | 7 885 250 | — | 0 | — | 0 |
| conservative | 1272 | 10 149 000 | 55 000 | 0 | 10 034 750 | 59 250 | 1 272 000 | 8 762 750 | 877 500 | 438 000 | 439 500 | 20 |
| medium | 1401 | 11 404 500 | 102 000 | 126 000 | 11 118 500 | 58 000 | 1 401 000 | 9 717 500 | 1 832 250 | 1 193 000 | 639 250 | 0 |
| adverse | 1033 | 8 282 000 | 39 000 | 84 000 | 7 871 750 | 287 250 | 1 033 000 | 6 838 750 | 1 366 000 | 1 108 000 | 258 000 | 0 |
| stress_full_redemption | 1952 | 14 983 500 | 242 000 | 134 000 | 14 531 250 | 76 250 | 1 952 000 | 12 579 250 | 2 382 750 | 1 257 000 | 1 125 750 | 0 |
| ops_delay_shortage | 837 | 5 948 500 | 21 000 | 44 000 | 5 850 500 | 33 000 | 837 000 | 5 013 500 | 1 036 750 | 1 138 000 | -101 250 | 0 |
| zero_budget | 1115 | 9 040 000 | 0 | 0 | 9 000 250 | 39 750 | 1 115 000 | 7 885 250 | 0 | 0 | 0 | 0 |
| budget_cut | 1401 | 11 404 500 | 84 000 | 111 000 | 11 151 500 | 58 000 | 1 401 000 | 9 750 500 | 1 865 250 | 780 000 | 1 085 250 | 110 |
| funding_loss | 1401 | 11 404 500 | 63 000 | 92 000 | 11 191 500 | 58 000 | 1 401 000 | 9 790 500 | 1 905 250 | 407 000 | 1 498 250 | 201 |
| variant_A | 1273 | 10 950 000 | 83 000 | 0 | 10 809 250 | 57 750 | 1 273 000 | 9 536 250 | 1 651 000 | 509 500 | 1 141 500 | 55 |
| variant_B | 1388 | 11 254 500 | 85 000 | 0 | 11 109 500 | 60 000 | 1 388 000 | 9 721 500 | 1 836 250 | 632 500 | 1 203 750 | 56 |
| variant_C | 1285 | 11 088 000 | 34 000 | 268 000 | 10 731 750 | 54 250 | 1 285 000 | 9 446 750 | 1 561 500 | 402 000 | 1 159 500 | 64 |
| parcel_base | 1231 | 9 356 500 | 2 000 | 0 | 9 312 500 | 42 000 | 1 231 000 | 8 081 500 | 196 250 | 125 000 | 71 250 | 0 |
| parcel_small_reward | 1231 | 9 356 500 | 1 000 | 0 | 9 313 500 | 42 000 | 1 231 000 | 8 082 500 | 197 250 | 62 500 | 134 750 | 0 |
| parcel_long_validity | 1231 | 9 356 500 | 2 000 | 0 | 9 312 500 | 42 000 | 1 231 000 | 8 081 500 | 196 250 | 128 000 | 68 250 | 0 |
| parcel_more_orders | 1408 | 9 854 500 | 6 000 | 0 | 9 801 250 | 47 250 | 1 408 000 | 8 393 250 | 294 250 | 134 000 | 160 250 | 0 |
| parcel_richer_mix | 1231 | 9 764 500 | 3 000 | 0 | 9 716 500 | 45 000 | 1 231 000 | 8 485 500 | 276 250 | 124 000 | 152 250 | 0 |
| parcel_small_long | 1231 | 9 356 500 | 1 000 | 0 | 9 313 500 | 42 000 | 1 231 000 | 8 082 500 | 197 250 | 64 000 | 133 250 | 0 |

Biznes natijasi (doimiy xarajat va soliqdan keyin): **noma'lum** — `fixed_costs_per_30_days_minor = null`.

## 3. 30 / 60 / 90 kun: pul va cohort ko'rsatkichlari

| Ssenariy | Kun | Operatsion marja | Sarflangan rag'bat (P+H) | Qolgan majburiyat | Rezerv (bronlarda) |
|---|---|---|---|---|---|
| control | 30 | 1 627 250 | 0 | 0 | 0 |
| control | 60 | 4 705 500 | 0 | 0 | 0 |
| control | 90 | 7 885 250 | 0 | 0 | 0 |
| conservative | 30 | 1 800 750 | 6 000 | 354 000 | 6 000 |
| conservative | 60 | 5 279 500 | 25 000 | 443 000 | 0 |
| conservative | 90 | 8 762 750 | 55 000 | 438 000 | 2 000 |
| medium | 30 | 1 966 250 | 32 000 | 850 000 | 7 000 |
| medium | 60 | 5 801 500 | 127 000 | 1 129 000 | 6 000 |
| medium | 90 | 9 717 500 | 228 000 | 1 193 000 | 3 000 |
| adverse | 30 | 1 619 750 | 9 000 | 840 000 | 7 000 |
| adverse | 60 | 4 394 750 | 65 000 | 1 043 000 | 2 000 |
| adverse | 90 | 6 838 750 | 123 000 | 1 108 000 | 0 |
| stress_full_redemption | 30 | 2 103 250 | 45 000 | 837 000 | 5 000 |
| stress_full_redemption | 60 | 6 906 000 | 210 000 | 1 079 000 | 3 000 |
| stress_full_redemption | 90 | 12 579 250 | 376 000 | 1 257 000 | 3 000 |
| ops_delay_shortage | 30 | 505 500 | 0 | 882 000 | 0 |
| ops_delay_shortage | 60 | 2 690 000 | 28 000 | 1 053 000 | 10 000 |
| ops_delay_shortage | 90 | 5 013 500 | 65 000 | 1 138 000 | 18 000 |
| zero_budget | 30 | 1 627 250 | 0 | 0 | 0 |
| zero_budget | 60 | 4 705 500 | 0 | 0 | 0 |
| zero_budget | 90 | 7 885 250 | 0 | 0 | 0 |
| budget_cut | 30 | 1 966 250 | 32 000 | 850 000 | 7 000 |
| budget_cut | 60 | 5 807 500 | 121 000 | 787 000 | 2 000 |
| budget_cut | 90 | 9 750 500 | 195 000 | 780 000 | 0 |
| funding_loss | 30 | 1 966 250 | 32 000 | 850 000 | 7 000 |
| funding_loss | 60 | 5 810 500 | 118 000 | 558 000 | 4 000 |
| funding_loss | 90 | 9 790 500 | 155 000 | 407 000 | 0 |
| variant_A | 30 | 1 926 750 | 22 500 | 492 500 | 2 500 |
| variant_A | 60 | 5 716 500 | 53 000 | 527 000 | 0 |
| variant_A | 90 | 9 536 250 | 83 000 | 509 500 | 2 500 |
| variant_B | 30 | 1 975 750 | 22 500 | 604 500 | 2 500 |
| variant_B | 60 | 5 843 500 | 54 000 | 648 000 | 0 |
| variant_B | 90 | 9 721 500 | 85 000 | 632 500 | 2 500 |
| variant_C | 30 | 1 891 250 | 58 000 | 497 000 | 6 000 |
| variant_C | 60 | 5 610 500 | 190 000 | 460 000 | 8 000 |
| variant_C | 90 | 9 446 750 | 302 000 | 402 000 | 4 000 |
| parcel_base | 30 | 1 676 250 | 0 | 110 000 | 0 |
| parcel_base | 60 | 4 832 500 | 1 000 | 121 000 | 0 |
| parcel_base | 90 | 8 081 500 | 2 000 | 125 000 | 0 |
| parcel_small_reward | 30 | 1 676 250 | 0 | 55 000 | 0 |
| parcel_small_reward | 60 | 4 833 000 | 500 | 60 500 | 0 |
| parcel_small_reward | 90 | 8 082 500 | 1 000 | 62 500 | 0 |
| parcel_long_validity | 30 | 1 676 250 | 0 | 110 000 | 0 |
| parcel_long_validity | 60 | 4 832 500 | 1 000 | 121 000 | 0 |
| parcel_long_validity | 90 | 8 081 500 | 2 000 | 128 000 | 0 |
| parcel_more_orders | 30 | 1 697 250 | 0 | 110 000 | 0 |
| parcel_more_orders | 60 | 4 954 000 | 4 000 | 127 000 | 0 |
| parcel_more_orders | 90 | 8 393 250 | 6 000 | 134 000 | 0 |
| parcel_richer_mix | 30 | 1 782 000 | 0 | 110 000 | 0 |
| parcel_richer_mix | 60 | 5 070 750 | 2 000 | 120 000 | 0 |
| parcel_richer_mix | 90 | 8 485 500 | 3 000 | 124 000 | 0 |
| parcel_small_long | 30 | 1 676 250 | 0 | 55 000 | 0 |
| parcel_small_long | 60 | 4 833 000 | 500 | 60 500 | 0 |
| parcel_small_long | 90 | 8 082 500 | 1 000 | 64 000 | 0 |

### Cohort ko'rsatkichlari (langar, yetilgan/yetilmagan)

Qiymat faqat yetilgan kuzatuvlardan; "hali baholab bo'lmaydi" — nol emas.

| Ssenariy | Xizmat | Ko'rsatkich | Langar | Guruh | Kun 30 | Kun 60 | Kun 90 |
|---|---|---|---|---|---|---|---|
| control | passenger | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | 36.0% (150 yetilgan / 179 yetilmagan) | 30.7% (339 yetilgan / 178 yetilmagan) |
| control | passenger | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 329 yetilmagan; kamida 20) | 37.3% (150 yetilgan / 367 yetilmagan) |
| control | passenger | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 329 yetilmagan; kamida 20) | 15 593 so'm (150 yetilgan / 367 yetilmagan) |
| control | parcel | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | 38.6% (88 yetilgan / 89 yetilmagan) | 35.0% (180 yetilgan / 106 yetilmagan) |
| control | parcel | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 177 yetilmagan; kamida 20) | 38.6% (88 yetilgan / 198 yetilmagan) |
| control | parcel | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 177 yetilmagan; kamida 20) | 2 773 so'm (88 yetilgan / 198 yetilmagan) |
| variant_A | passenger | Qualification ulushi | enrollment | referee | hali baholab bo'lmaydi (0 yetilgan / 103 yetilmagan; kamida 20) | 53.1% (49 yetilgan / 112 yetilmagan) | 51.8% (141 yetilgan / 80 yetilmagan) |
| variant_A | passenger | D30 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | 35.3% (34 yetilgan / 41 yetilmagan) | 25.3% (79 yetilgan / 25 yetilmagan) |
| variant_A | passenger | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | 35.6% (129 yetilgan / 148 yetilmagan) | 31.6% (285 yetilgan / 158 yetilmagan) |
| variant_A | passenger | D60 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 75 yetilmagan; kamida 20) | 38.2% (34 yetilgan / 70 yetilmagan) |
| variant_A | passenger | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 277 yetilmagan; kamida 20) | 37.2% (129 yetilgan / 314 yetilmagan) |
| variant_A | passenger | D60 marja / kishi | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 75 yetilmagan; kamida 20) | 16 471 so'm (34 yetilgan / 70 yetilmagan) |
| variant_A | passenger | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 277 yetilmagan; kamida 20) | 15 384 so'm (129 yetilgan / 314 yetilmagan) |
| variant_A | passenger | Lot 30 kunda ishlatilgan | grant | bonus_lots | hali baholab bo'lmaydi (0 yetilgan / 60 yetilmagan; kamida 20) | 25.0% (60 yetilgan / 86 yetilmagan) | 18.5% (146 yetilgan / 44 yetilmagan) |
| variant_A | passenger | Bonus qiymati 30 kunda ishlatilgan | grant | bonus_value | hali baholab bo'lmaydi (0 yetilgan / 60 yetilmagan; kamida 20) | 25.0% (60 yetilgan / 86 yetilmagan) | 17.9% (146 yetilgan / 44 yetilmagan) |
| variant_A | parcel | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | 38.6% (88 yetilgan / 89 yetilmagan) | 35.0% (180 yetilgan / 106 yetilmagan) |
| variant_A | parcel | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 177 yetilmagan; kamida 20) | 38.6% (88 yetilgan / 198 yetilmagan) |
| variant_A | parcel | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 83 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 177 yetilmagan; kamida 20) | 2 773 so'm (88 yetilgan / 198 yetilmagan) |
| variant_B | passenger | Qualification ulushi | enrollment | referee | hali baholab bo'lmaydi (0 yetilgan / 103 yetilmagan; kamida 20) | 53.1% (49 yetilgan / 112 yetilmagan) | 53.2% (141 yetilgan / 76 yetilmagan) |
| variant_B | passenger | D30 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | 35.3% (34 yetilgan / 42 yetilmagan) | 26.2% (80 yetilgan / 23 yetilmagan) |
| variant_B | passenger | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | 35.6% (129 yetilgan / 148 yetilmagan) | 31.6% (285 yetilgan / 158 yetilmagan) |
| variant_B | passenger | D60 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 76 yetilmagan; kamida 20) | 38.2% (34 yetilgan / 69 yetilmagan) |
| variant_B | passenger | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 277 yetilmagan; kamida 20) | 37.2% (129 yetilgan / 314 yetilmagan) |
| variant_B | passenger | D60 marja / kishi | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 31 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 76 yetilmagan; kamida 20) | 16 471 so'm (34 yetilgan / 69 yetilmagan) |
| variant_B | passenger | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 121 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 277 yetilmagan; kamida 20) | 15 384 so'm (129 yetilgan / 314 yetilmagan) |
| variant_B | passenger | Lot 30 kunda ishlatilgan | grant | bonus_lots | hali baholab bo'lmaydi (0 yetilgan / 60 yetilmagan; kamida 20) | 25.0% (60 yetilgan / 92 yetilmagan) | 17.8% (152 yetilgan / 44 yetilmagan) |
| variant_B | passenger | Bonus qiymati 30 kunda ishlatilgan | grant | bonus_value | hali baholab bo'lmaydi (0 yetilgan / 60 yetilmagan; kamida 20) | 25.0% (60 yetilgan / 92 yetilmagan) | 17.2% (152 yetilgan / 44 yetilmagan) |
| variant_B | parcel | Qualification ulushi | enrollment | referee | hali baholab bo'lmaydi (0 yetilgan / 56 yetilmagan; kamida 20) | 15.6% (32 yetilgan / 73 yetilmagan) | 16.7% (78 yetilgan / 76 yetilmagan) |
| variant_B | parcel | D30 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | 47.8% (23 yetilgan / 20 yetilmagan) | 34.1% (44 yetilgan / 21 yetilmagan) |
| variant_B | parcel | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | 32.9% (73 yetilgan / 82 yetilmagan) | 32.3% (158 yetilgan / 100 yetilmagan) |
| variant_B | parcel | D60 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 43 yetilmagan; kamida 20) | 47.8% (23 yetilgan / 42 yetilmagan) |
| variant_B | parcel | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 155 yetilmagan; kamida 20) | 32.9% (73 yetilgan / 185 yetilmagan) |
| variant_B | parcel | D60 marja / kishi | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 43 yetilmagan; kamida 20) | 2 848 so'm (23 yetilgan / 42 yetilmagan) |
| variant_B | parcel | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 155 yetilmagan; kamida 20) | 2 658 so'm (73 yetilgan / 185 yetilmagan) |
| variant_B | parcel | Lot 30 kunda ishlatilgan | grant | bonus_lots | hali baholab bo'lmaydi (0 yetilgan / 4 yetilmagan; kamida 20) | hali baholab bo'lmaydi (4 yetilgan / 18 yetilmagan; kamida 20) | 4.5% (22 yetilgan / 10 yetilmagan) |
| variant_B | parcel | Bonus qiymati 30 kunda ishlatilgan | grant | bonus_value | hali baholab bo'lmaydi (0 yetilgan / 4 yetilmagan; kamida 20) | hali baholab bo'lmaydi (4 yetilgan / 18 yetilmagan; kamida 20) | 4.5% (22 yetilgan / 10 yetilmagan) |
| parcel_base | passenger | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | 36.0% (150 yetilgan / 179 yetilmagan) | 30.7% (339 yetilgan / 178 yetilmagan) |
| parcel_base | passenger | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 329 yetilmagan; kamida 20) | 37.3% (150 yetilgan / 367 yetilmagan) |
| parcel_base | passenger | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 137 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 329 yetilmagan; kamida 20) | 15 593 so'm (150 yetilgan / 367 yetilmagan) |
| parcel_base | parcel | Qualification ulushi | enrollment | referee | hali baholab bo'lmaydi (0 yetilgan / 56 yetilmagan; kamida 20) | 12.5% (32 yetilgan / 73 yetilmagan) | 16.7% (78 yetilgan / 76 yetilmagan) |
| parcel_base | parcel | D30 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | 47.8% (23 yetilgan / 20 yetilmagan) | 34.1% (44 yetilgan / 21 yetilmagan) |
| parcel_base | parcel | D30 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | 32.9% (73 yetilgan / 82 yetilmagan) | 32.3% (158 yetilgan / 100 yetilmagan) |
| parcel_base | parcel | D60 qaytish | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 43 yetilmagan; kamida 20) | 47.8% (23 yetilgan / 42 yetilmagan) |
| parcel_base | parcel | D60 qaytish | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 155 yetilmagan; kamida 20) | 32.9% (73 yetilgan / 185 yetilmagan) |
| parcel_base | parcel | D60 marja / kishi | activation | referee | hali baholab bo'lmaydi (0 yetilgan / 20 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 43 yetilmagan; kamida 20) | 2 848 so'm (23 yetilgan / 42 yetilmagan) |
| parcel_base | parcel | D60 marja / kishi | activation | organic | hali baholab bo'lmaydi (0 yetilgan / 70 yetilmagan; kamida 20) | hali baholab bo'lmaydi (0 yetilgan / 155 yetilmagan; kamida 20) | 2 658 so'm (73 yetilgan / 185 yetilmagan) |
| parcel_base | parcel | Lot 30 kunda ishlatilgan | grant | bonus_lots | hali baholab bo'lmaydi (0 yetilgan / 4 yetilmagan; kamida 20) | hali baholab bo'lmaydi (4 yetilgan / 18 yetilmagan; kamida 20) | 4.5% (22 yetilgan / 12 yetilmagan) |
| parcel_base | parcel | Bonus qiymati 30 kunda ishlatilgan | grant | bonus_value | hali baholab bo'lmaydi (0 yetilgan / 4 yetilmagan; kamida 20) | hali baholab bo'lmaydi (4 yetilgan / 18 yetilmagan; kamida 20) | 4.5% (22 yetilgan / 12 yetilmagan) |

## 4. Xizmat va koridor bo'yicha (90 kun)

Pochta natijasi yo'lovchi zararini yashirmasligi uchun har xizmat alohida, o'z juft nazorati bilan.

| Ssenariy | Qamrov | Xizmat ko'rsatilgan | Chegirmali | P | H | Saqlangan C_net | O | Operatsion marja | Juft nazorat | Farq | Stress farq (xizmat) | Haydovchi topilmagan |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | corridor:pilot_A | 687 | 0 | 0 | 0 | 5 643 000 | 687 000 | 4 956 000 | noma'lum | — | — | 65 |
| control | corridor:pilot_B | 428 | 0 | 0 | 0 | 3 357 250 | 428 000 | 2 929 250 | noma'lum | — | — | 89 |
| control | service:parcel | 416 | 0 | 0 | 0 | 1 118 250 | 416 000 | 702 250 | noma'lum | — | — | 59 |
| control | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | noma'lum | — | — | 95 |
| conservative | corridor:pilot_A | 787 | 19 | 37 000 | 0 | 6 294 000 | 787 000 | 5 507 000 | 4 956 000 | 551 000 | — | 77 |
| conservative | corridor:pilot_B | 485 | 10 | 18 000 | 0 | 3 740 750 | 485 000 | 3 255 750 | 2 929 250 | 326 500 | — | 104 |
| conservative | service:parcel | 497 | 3 | 3 000 | 0 | 1 314 750 | 497 000 | 817 750 | 702 250 | 115 500 | 21 500 | 71 |
| conservative | service:passenger | 775 | 26 | 52 000 | 0 | 8 720 000 | 775 000 | 7 945 000 | 7 183 000 | 762 000 | 418 000 | 110 |
| medium | corridor:pilot_A | 876 | 29 | 83 000 | 80 000 | 7 063 500 | 876 000 | 6 187 500 | 4 956 000 | 1 231 500 | — | 81 |
| medium | corridor:pilot_B | 525 | 7 | 19 000 | 46 000 | 4 055 000 | 525 000 | 3 530 000 | 2 929 250 | 600 750 | — | 115 |
| medium | service:parcel | 532 | 3 | 3 000 | 0 | 1 429 500 | 532 000 | 897 500 | 702 250 | 195 250 | -59 750 | 79 |
| medium | service:passenger | 869 | 33 | 99 000 | 126 000 | 9 689 000 | 869 000 | 8 820 000 | 7 183 000 | 1 637 000 | 699 000 | 117 |
| adverse | corridor:pilot_A | 641 | 10 | 30 000 | 62 000 | 4 962 000 | 641 000 | 4 321 000 | 3 464 250 | 856 750 | — | 61 |
| adverse | corridor:pilot_B | 392 | 3 | 9 000 | 22 000 | 2 909 750 | 392 000 | 2 517 750 | 2 008 500 | 509 250 | — | 92 |
| adverse | service:parcel | 378 | 0 | 0 | 0 | 965 250 | 378 000 | 587 250 | 450 750 | 136 500 | -71 500 | 60 |
| adverse | service:passenger | 655 | 13 | 39 000 | 84 000 | 6 906 500 | 655 000 | 6 251 500 | 5 022 000 | 1 229 500 | 329 500 | 93 |
| stress_full_redemption | corridor:pilot_A | 1224 | 62 | 174 000 | 85 000 | 9 219 250 | 1 224 000 | 7 995 250 | 6 389 250 | 1 606 000 | — | 113 |
| stress_full_redemption | corridor:pilot_B | 728 | 27 | 68 000 | 49 000 | 5 312 000 | 728 000 | 4 584 000 | 3 807 250 | 776 750 | — | 160 |
| stress_full_redemption | service:parcel | 837 | 16 | 20 000 | 0 | 2 275 250 | 837 000 | 1 438 250 | 1 123 500 | 314 750 | 26 750 | 117 |
| stress_full_redemption | service:passenger | 1115 | 73 | 222 000 | 134 000 | 12 256 000 | 1 115 000 | 11 141 000 | 9 073 000 | 2 068 000 | 1 099 000 | 156 |
| ops_delay_shortage | corridor:pilot_A | 541 | 5 | 15 000 | 18 000 | 3 750 250 | 541 000 | 3 209 250 | 2 500 750 | 708 500 | — | 447 |
| ops_delay_shortage | corridor:pilot_B | 296 | 1 | 6 000 | 26 000 | 2 100 250 | 296 000 | 1 804 250 | 1 476 000 | 328 250 | — | 365 |
| ops_delay_shortage | service:parcel | 316 | 0 | 0 | 0 | 742 500 | 316 000 | 426 500 | 343 750 | 82 750 | -121 250 | 311 |
| ops_delay_shortage | service:passenger | 521 | 6 | 21 000 | 44 000 | 5 108 000 | 521 000 | 4 587 000 | 3 633 000 | 954 000 | 20 000 | 501 |
| zero_budget | corridor:pilot_A | 687 | 0 | 0 | 0 | 5 643 000 | 687 000 | 4 956 000 | 4 956 000 | 0 | — | 65 |
| zero_budget | corridor:pilot_B | 428 | 0 | 0 | 0 | 3 357 250 | 428 000 | 2 929 250 | 2 929 250 | 0 | — | 89 |
| zero_budget | service:parcel | 416 | 0 | 0 | 0 | 1 118 250 | 416 000 | 702 250 | 702 250 | 0 | 0 | 59 |
| zero_budget | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| budget_cut | corridor:pilot_A | 876 | 23 | 65 000 | 73 000 | 7 088 500 | 876 000 | 6 212 500 | 4 956 000 | 1 256 500 | — | 81 |
| budget_cut | corridor:pilot_B | 525 | 7 | 19 000 | 38 000 | 4 063 000 | 525 000 | 3 538 000 | 2 929 250 | 608 750 | — | 115 |
| budget_cut | service:parcel | 532 | 3 | 3 000 | 0 | 1 429 500 | 532 000 | 897 500 | 702 250 | 195 250 | -57 750 | 79 |
| budget_cut | service:passenger | 869 | 27 | 81 000 | 111 000 | 9 722 000 | 869 000 | 8 853 000 | 7 183 000 | 1 670 000 | 1 143 000 | 117 |
| funding_loss | corridor:pilot_A | 876 | 16 | 44 000 | 62 000 | 7 120 500 | 876 000 | 6 244 500 | 4 956 000 | 1 288 500 | — | 81 |
| funding_loss | corridor:pilot_B | 525 | 7 | 19 000 | 30 000 | 4 071 000 | 525 000 | 3 546 000 | 2 929 250 | 616 750 | — | 115 |
| funding_loss | service:parcel | 532 | 3 | 3 000 | 0 | 1 429 500 | 532 000 | 897 500 | 702 250 | 195 250 | -59 750 | 79 |
| funding_loss | service:passenger | 869 | 20 | 60 000 | 92 000 | 9 762 000 | 869 000 | 8 893 000 | 7 183 000 | 1 710 000 | 1 558 000 | 117 |
| variant_A | corridor:pilot_A | 794 | 23 | 58 000 | 0 | 6 863 000 | 794 000 | 6 069 000 | 4 956 000 | 1 113 000 | — | 75 |
| variant_A | corridor:pilot_B | 479 | 10 | 25 000 | 0 | 3 946 250 | 479 000 | 3 467 250 | 2 929 250 | 538 000 | — | 100 |
| variant_A | service:parcel | 416 | 0 | 0 | 0 | 1 118 250 | 416 000 | 702 250 | 702 250 | 0 | 0 | 59 |
| variant_A | service:passenger | 857 | 33 | 83 000 | 0 | 9 691 000 | 857 000 | 8 834 000 | 7 183 000 | 1 651 000 | 1 141 500 | 116 |
| variant_B | corridor:pilot_A | 866 | 24 | 59 000 | 0 | 7 052 500 | 866 000 | 6 186 500 | 4 956 000 | 1 230 500 | — | 81 |
| variant_B | corridor:pilot_B | 522 | 11 | 26 000 | 0 | 4 057 000 | 522 000 | 3 535 000 | 2 929 250 | 605 750 | — | 114 |
| variant_B | service:parcel | 532 | 2 | 2 000 | 0 | 1 430 500 | 532 000 | 898 500 | 702 250 | 196 250 | 73 250 | 79 |
| variant_B | service:passenger | 856 | 33 | 83 000 | 0 | 9 679 000 | 856 000 | 8 823 000 | 7 183 000 | 1 640 000 | 1 130 500 | 116 |
| variant_C | corridor:pilot_A | 803 | 13 | 26 000 | 183 000 | 6 815 000 | 803 000 | 6 012 000 | 4 956 000 | 1 056 000 | — | 75 |
| variant_C | corridor:pilot_B | 482 | 4 | 8 000 | 85 000 | 3 916 750 | 482 000 | 3 434 750 | 2 929 250 | 505 500 | — | 101 |
| variant_C | service:parcel | 416 | 0 | 0 | 0 | 1 118 250 | 416 000 | 702 250 | 702 250 | 0 | 0 | 59 |
| variant_C | service:passenger | 869 | 17 | 34 000 | 268 000 | 9 613 500 | 869 000 | 8 744 500 | 7 183 000 | 1 561 500 | 1 159 500 | 117 |
| parcel_base | corridor:pilot_A | 760 | 1 | 1 000 | 0 | 5 844 500 | 760 000 | 5 084 500 | 4 956 000 | 128 500 | — | 71 |
| parcel_base | corridor:pilot_B | 471 | 1 | 1 000 | 0 | 3 468 000 | 471 000 | 2 997 000 | 2 929 250 | 67 750 | — | 103 |
| parcel_base | service:parcel | 532 | 2 | 2 000 | 0 | 1 430 500 | 532 000 | 898 500 | 702 250 | 196 250 | 71 250 | 79 |
| parcel_base | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| parcel_small_reward | corridor:pilot_A | 760 | 1 | 500 | 0 | 5 845 000 | 760 000 | 5 085 000 | 4 956 000 | 129 000 | — | 71 |
| parcel_small_reward | corridor:pilot_B | 471 | 1 | 500 | 0 | 3 468 500 | 471 000 | 2 997 500 | 2 929 250 | 68 250 | — | 103 |
| parcel_small_reward | service:parcel | 532 | 2 | 1 000 | 0 | 1 431 500 | 532 000 | 899 500 | 702 250 | 197 250 | 134 750 | 79 |
| parcel_small_reward | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| parcel_long_validity | corridor:pilot_A | 760 | 1 | 1 000 | 0 | 5 844 500 | 760 000 | 5 084 500 | 4 956 000 | 128 500 | — | 71 |
| parcel_long_validity | corridor:pilot_B | 471 | 1 | 1 000 | 0 | 3 468 000 | 471 000 | 2 997 000 | 2 929 250 | 67 750 | — | 103 |
| parcel_long_validity | service:parcel | 532 | 2 | 2 000 | 0 | 1 430 500 | 532 000 | 898 500 | 702 250 | 196 250 | 68 250 | 79 |
| parcel_long_validity | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| parcel_more_orders | corridor:pilot_A | 868 | 2 | 2 000 | 0 | 6 141 250 | 868 000 | 5 273 250 | 5 072 250 | 201 000 | — | 80 |
| parcel_more_orders | corridor:pilot_B | 540 | 4 | 4 000 | 0 | 3 660 000 | 540 000 | 3 120 000 | 3 026 750 | 93 250 | — | 119 |
| parcel_more_orders | service:parcel | 709 | 6 | 6 000 | 0 | 1 919 250 | 709 000 | 1 210 250 | 916 000 | 294 250 | 160 250 | 104 |
| parcel_more_orders | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| parcel_richer_mix | corridor:pilot_A | 760 | 2 | 2 000 | 0 | 6 093 250 | 760 000 | 5 333 250 | 5 153 250 | 180 000 | — | 71 |
| parcel_richer_mix | corridor:pilot_B | 471 | 1 | 1 000 | 0 | 3 623 250 | 471 000 | 3 152 250 | 3 056 000 | 96 250 | — | 103 |
| parcel_richer_mix | service:parcel | 532 | 3 | 3 000 | 0 | 1 834 500 | 532 000 | 1 302 500 | 1 026 250 | 276 250 | 152 250 | 79 |
| parcel_richer_mix | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |
| parcel_small_long | corridor:pilot_A | 760 | 1 | 500 | 0 | 5 845 000 | 760 000 | 5 085 000 | 4 956 000 | 129 000 | — | 71 |
| parcel_small_long | corridor:pilot_B | 471 | 1 | 500 | 0 | 3 468 500 | 471 000 | 2 997 500 | 2 929 250 | 68 250 | — | 103 |
| parcel_small_long | service:parcel | 532 | 2 | 1 000 | 0 | 1 431 500 | 532 000 | 899 500 | 702 250 | 197 250 | 133 250 | 79 |
| parcel_small_long | service:passenger | 699 | 0 | 0 | 0 | 7 882 000 | 699 000 | 7 183 000 | 7 183 000 | 0 | 0 | 95 |

## 5. Budjet: limit, majburiyat, mablag' bilan ta'minlanganlik (90 kun)

Majburiyat = va'da + berilgan (sarflanmagan) + sarflangan. Ta'minlangan = majburiyat − kamomad. Foydalanish cho'qqisi — **o'sha lahzadagi** limitga nisbatan. Budjet manbai — aniq parametr; kelajakdagi daromad mavjud mablag' emas.

| Ssenariy | Kampaniya | Xizmat | Boshlang'ich limit | Yakuniy limit | Majburiyat | Ta'minlangan | Kamomad | Kamaytirish: bajarildi / rad | Funding loss | Kamaytirish mumkin (B − S − L) | Foydalanish cho'qqisi | Rad (budjet) | Reinstate / bajarilmagan |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| conservative | 1 (referral_client_client) | passenger | 400 000 | 400 000 | 396 000 | 396 000 | 0 | 0 / 0 | 0 | 4 000 | 100.0% | 20 | 4 000 / 0 |
| conservative | 2 (referral_client_client) | parcel | 150 000 | 150 000 | 97 000 | 97 000 | 0 | 0 / 0 | 0 | 53 000 | 76.0% | 0 | 0 / 0 |
| medium | 1 (referral_client_client) | passenger | 1 500 000 | 1 500 000 | 744 000 | 744 000 | 0 | 0 / 0 | 0 | 756 000 | 55.0% | 0 | 9 000 / 0 |
| medium | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 258 000 | 258 000 | 0 | 0 / 0 | 0 | 242 000 | 61.6% | 0 | 1 000 / 0 |
| medium | 3 (referral_driver_client) | passenger | 1 000 000 | 1 000 000 | 309 000 | 309 000 | 0 | 0 / 0 | 0 | 691 000 | 31.5% | 0 | 0 / 0 |
| medium | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 110 000 | 110 000 | 0 | 0 / 0 | 0 | 390 000 | 22.0% | 0 | 0 / 0 |
| adverse | 1 (referral_client_client) | passenger | 1 500 000 | 1 500 000 | 648 000 | 648 000 | 0 | 0 / 0 | 0 | 852 000 | 48.0% | 0 | 9 000 / 0 |
| adverse | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 208 000 | 208 000 | 0 | 0 / 0 | 0 | 292 000 | 52.4% | 0 | 0 / 0 |
| adverse | 3 (referral_driver_client) | passenger | 1 000 000 | 1 000 000 | 279 000 | 279 000 | 0 | 0 / 0 | 0 | 721 000 | 28.5% | 0 | 0 / 0 |
| adverse | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 96 000 | 96 000 | 0 | 0 / 0 | 0 | 404 000 | 20.0% | 0 | 0 / 0 |
| stress_full_redemption | 1 (referral_client_client) | passenger | 1 500 000 | 1 500 000 | 894 000 | 894 000 | 0 | 0 / 0 | 0 | 606 000 | 60.0% | 0 | 0 / 0 |
| stress_full_redemption | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 308 000 | 308 000 | 0 | 0 / 0 | 0 | 192 000 | 70.4% | 0 | 0 / 0 |
| stress_full_redemption | 3 (referral_driver_client) | passenger | 1 000 000 | 1 000 000 | 315 000 | 315 000 | 0 | 0 / 0 | 0 | 685 000 | 32.1% | 0 | 0 / 0 |
| stress_full_redemption | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 116 000 | 116 000 | 0 | 0 / 0 | 0 | 384 000 | 23.2% | 0 | 0 / 0 |
| ops_delay_shortage | 1 (referral_client_client) | passenger | 1 500 000 | 1 500 000 | 654 000 | 654 000 | 0 | 0 / 0 | 0 | 846 000 | 45.6% | 0 | 0 / 0 |
| ops_delay_shortage | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 204 000 | 204 000 | 0 | 0 / 0 | 0 | 296 000 | 51.2% | 0 | 0 / 0 |
| ops_delay_shortage | 3 (referral_driver_client) | passenger | 1 000 000 | 1 000 000 | 261 000 | 261 000 | 0 | 0 / 0 | 0 | 739 000 | 26.7% | 0 | 0 / 0 |
| ops_delay_shortage | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 84 000 | 84 000 | 0 | 0 / 0 | 0 | 416 000 | 18.4% | 0 | 0 / 0 |
| zero_budget | 1 | — | 0 | 0 | — | — | — | — | — | — | — | faollashtirilmadi (budget_allocated_minor) | — |
| zero_budget | 2 | — | 0 | 0 | — | — | — | — | — | — | — | faollashtirilmadi (budget_allocated_minor) | — |
| zero_budget | 3 | — | 0 | 0 | — | — | — | — | — | — | — | faollashtirilmadi (budget_allocated_minor) | — |
| zero_budget | 4 | — | 0 | 0 | — | — | — | — | — | — | — | faollashtirilmadi (budget_allocated_minor) | — |
| budget_cut | 1 (referral_client_client) | passenger | 1 500 000 | 450 000 | 450 000 | 450 000 | 0 | 1 050 000 / 450 000 | 0 | 0 | 100.0% | 78 | 9 000 / 0 |
| budget_cut | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 256 000 | 256 000 | 0 | 0 / 0 | 0 | 244 000 | 61.6% | 0 | 1 000 / 0 |
| budget_cut | 3 (referral_driver_client) | passenger | 1 000 000 | 168 000 | 159 000 | 159 000 | 0 | 832 000 / 168 000 | 0 | 9 000 | 100.0% | 32 | 0 / 0 |
| budget_cut | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 110 000 | 110 000 | 0 | 0 / 0 | 0 | 390 000 | 22.0% | 0 | 0 / 0 |
| funding_loss | 1 (referral_client_client) | passenger | 1 500 000 | 0 | 153 000 | 0 | 153 000 | 0 / 0 | 1 500 000 | 0 | 30.0% | 140 | 0 / 3 000 |
| funding_loss | 2 (referral_client_client) | parcel | 500 000 | 500 000 | 258 000 | 258 000 | 0 | 0 / 0 | 0 | 242 000 | 61.6% | 0 | 1 000 / 0 |
| funding_loss | 3 (referral_driver_client) | passenger | 1 000 000 | 0 | 39 000 | 0 | 39 000 | 0 / 0 | 1 000 000 | 0 | 16.8% | 61 | 0 / 0 |
| funding_loss | 4 (referral_driver_driver) | passenger | 500 000 | 500 000 | 112 000 | 112 000 | 0 | 0 / 0 | 0 | 388 000 | 22.4% | 0 | 0 / 0 |
| variant_A | 1 (referral_client_client) | passenger | 600 000 | 600 000 | 592 500 | 592 500 | 0 | 0 / 0 | 0 | 7 500 | 100.0% | 55 | 15 000 / 0 |
| variant_B | 1 (referral_client_client) | passenger | 600 000 | 600 000 | 592 500 | 592 500 | 0 | 0 / 0 | 0 | 7 500 | 100.0% | 56 | 22 500 / 0 |
| variant_B | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 125 000 | 125 000 | 0 | 0 / 0 | 0 | 175 000 | 50.7% | 0 | 0 / 0 |
| variant_C | 3 (referral_driver_client) | passenger | 600 000 | 600 000 | 592 000 | 592 000 | 0 | 0 / 0 | 0 | 8 000 | 100.0% | 64 | 0 / 0 |
| variant_C | 4 (referral_driver_driver) | passenger | 300 000 | 300 000 | 112 000 | 112 000 | 0 | 0 / 0 | 0 | 188 000 | 37.3% | 0 | 0 / 0 |
| parcel_base | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 127 000 | 127 000 | 0 | 0 / 0 | 0 | 173 000 | 50.7% | 0 | 0 / 0 |
| parcel_small_reward | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 63 500 | 63 500 | 0 | 0 / 0 | 0 | 236 500 | 25.3% | 0 | 0 / 0 |
| parcel_long_validity | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 130 000 | 130 000 | 0 | 0 / 0 | 0 | 170 000 | 50.7% | 0 | 0 / 0 |
| parcel_more_orders | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 140 000 | 140 000 | 0 | 0 / 0 | 0 | 160 000 | 55.0% | 0 | 0 / 0 |
| parcel_richer_mix | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 127 000 | 127 000 | 0 | 0 / 0 | 0 | 173 000 | 50.7% | 0 | 0 / 0 |
| parcel_small_long | 2 (referral_client_client) | parcel | 300 000 | 300 000 | 65 000 | 65 000 | 0 | 0 / 0 | 0 | 235 000 | 25.3% | 0 | 0 / 0 |

**Budjetni kamaytirish (G14, migratsiya 0090).** Oddiy `reduce_allocation` budjetni sarflangan summa va bajarilmagan majburiyatlar yig'indisidan pastga tushira olmaydi: `B ≥ S + L`, kamaytirish mumkin bo'lgan summa `max(0, B − S − L)`. B — tasdiqlangan jami ajratma, S — hisobga olingan sof sarf (hech bir ledger turi uni kamaytirmaydi), L — va'da rezervi + berilgan sarflanmagan bonus (bronda band qilingan qism uning ichida, bir marta) + budjet joyini kutayotgan tasdiqlangan tiklashlar. Review yoki kech capture kutayotgan majburiyatlar va'da/berilgan ichida qoladi. Servis va DB trigger (budjet qatori lock'i ostida) tekshiradi; vakolatli admin ham chetlab o'tolmaydi. `budget_cut` ssenariysi endi shu kontraktni ishlatadi: so'ralgan summaning faqat `B − S − L` qismi bajariladi, qolgani **rad etiladi** — kamomad paydo bo'lmaydi, joy qolmagani uchun yangi va'dalar to'xtaydi.

**Tashqi moliyalashtirish yo'qolishi — alohida holat (`funding_loss`).** Oddiy kamaytirish emas: dalil (`evidence_reference`) bilan qayd etiladi, finance va katta summada ikki turli xodim qoidasi bilan. U majburiyatdan pastga tushishi mumkin — bu haqiqiy kamomad: hech bir va'da, bonus yoki sarf bekor qilinmaydi, kampaniya o'sha tranzaksiyada pauzaga o'tadi, yangi va'dalar to'xtaydi, admin hisobotida `budget_shortfall` ogohlantirishi va audit yozuvi. Ssenariy: `funding_loss`. Avvalgi "104%" — cho'qqi majburiyat kesilgan yakuniy limitga bo'lingan edi (noto'g'ri solishtirish) va taqiqlanishi kerak bo'lgan kamaytirishni ruxsat etilgandek ko'rsatardi; ikkalasi ham tuzatilgan. Dalil: `tests/pg/promotions/test_promo_budget_floor_pg.py`, `tests/contracts/test_promo.py::test_g14_*`, `tests/contracts/test_promo_simulation.py`.

## 6. Pochta: amaliy foyda alohida (model natijasi, haqiqiy ma'lumot emas)

Lotlar, bonus egalari va bonus qiymati alohida; faqat **yetilgan** lotlar (sarflash mumkin bo'lgan kun ≥ yetilish kunlari yoki yopilgan) baholanadi. Ishlatilmagan lot sababi — egasi bonusni ishlatishga eng yaqin kelgan holat.

| Ssenariy | Lot (yetilgan / yetilmagan) | Ishlatilgan lot (yetilgan) | Ishlatgan egalar | Qiymat ishlatilgan (yetilgan) | Muddati tugagan | Ochiq | Review'da (enrollment) |
|---|---|---|---|---|---|---|---|
| conservative | 20 / 8 | 3 (15%) | 3 / 20 (15%) | 3 000 / 20 000 (15%) | 1 000 | 24 000 | 1 |
| medium | 24 / 14 | 2 (8%) | 2 / 23 (9%) | 3 000 / 48 000 (6%) | 6 000 | 67 000 | 0 |
| adverse | 5 / 5 | 0 (0%) | 0 / 5 (0%) | 0 / 10 000 (0%) | 0 | 16 000 | 0 |
| stress_full_redemption | 41 / 23 | 12 (29%) | 12 / 38 (32%) | 19 000 / 82 000 (23%) | 0 | 104 000 | 1 |
| budget_cut | 25 / 13 | 2 (8%) | 2 / 24 (8%) | 3 000 / 50 000 (6%) | 6 000 | 65 000 | 0 |
| funding_loss | 24 / 14 | 2 (8%) | 2 / 23 (9%) | 3 000 / 48 000 (6%) | 6 000 | 67 000 | 0 |
| variant_B | 22 / 10 | 2 (9%) | 2 / 21 (10%) | 2 000 / 22 000 (9%) | 3 000 | 27 000 | 1 |
| parcel_base | 22 / 12 | 2 (9%) | 2 / 22 (9%) | 2 000 / 22 000 (9%) | 3 000 | 29 000 | 1 |
| parcel_small_reward | 22 / 12 | 2 (9%) | 2 / 22 (9%) | 1 000 / 11 000 (9%) | 1 500 | 14 500 | 1 |
| parcel_long_validity | 22 / 12 | 2 (9%) | 2 / 22 (9%) | 2 000 / 22 000 (9%) | 0 | 32 000 | 1 |
| parcel_more_orders | 32 / 20 | 6 (19%) | 6 / 31 (19%) | 6 000 / 32 000 (19%) | 3 000 | 42 000 | 0 |
| parcel_richer_mix | 22 / 12 | 3 (14%) | 3 / 22 (14%) | 3 000 / 22 000 (14%) | 3 000 | 28 000 | 1 |
| parcel_small_long | 22 / 12 | 2 (9%) | 2 / 22 (9%) | 1 000 / 11 000 (9%) | 0 | 16 000 | 1 |

**Ishlatilmagan lotlar sababi (90 kun, lot soni; qavsda — shundan muddati tugaganlar):**

| Ssenariy | lot hali yetilmagan (< yetilish kunlari) | bronda rezervda, capture kutilmoqda | egasi qayta buyurtma bermagan | mos haydovchi topilmagan | komissiyada chegirmaga joy yo'q (C_net − O ≥ M) | qabul qiluvchi to'laydi | mijoz bonusni tanlamagan | buyurtma bekor qilingan | firibgarlik sababli qaytarilgan |
|---|---|---|---|---|---|---|---|---|---|
| conservative | 8 (0) | 0 (0) | 16 (1) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| medium | 14 (0) | 0 (0) | 21 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| adverse | 5 (0) | 0 (0) | 3 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 2 (0) |
| stress_full_redemption | 22 (0) | 0 (0) | 20 (0) | 0 (0) | 5 (0) | 0 (0) | 0 (0) | 2 (0) | 2 (0) |
| budget_cut | 13 (0) | 0 (0) | 21 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 1 (0) |
| funding_loss | 14 (0) | 0 (0) | 21 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| variant_B | 10 (0) | 0 (0) | 19 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| parcel_base | 12 (0) | 0 (0) | 19 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| parcel_small_reward | 12 (0) | 0 (0) | 19 (3) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| parcel_long_validity | 12 (0) | 0 (0) | 19 (0) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| parcel_more_orders | 20 (0) | 0 (0) | 20 (2) | 0 (0) | 2 (0) | 1 (1) | 1 (0) | 1 (0) | 1 (0) |
| parcel_richer_mix | 12 (0) | 0 (0) | 19 (3) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |
| parcel_small_long | 12 (0) | 0 (0) | 19 (0) | 0 (0) | 1 (0) | 0 (0) | 0 (0) | 0 (0) | 0 (0) |

**Pochta tajribalari (faqat sintetik; narx, haydovchi daromadi va M o'zgarmagan) — pochta qamrovi, o'z juft nazoratiga nisbatan:**

| Tajriba | Marja farqi | Stress farq | Zararsizlik (simulyatsiya to'ri) | Qo'shimcha foydalanuvchi yo'q (stress farq) | Hammasi birga, yarim qo'shimcha (stress farq) |
|---|---|---|---|---|---|
| parcel_base | 196 250 | 71 250 | 40% dan (barqaror) | -37 000 | -44 500 |
| parcel_small_reward | 197 250 | 134 750 | 20% dan (barqaror) | -18 500 | -2 500 |
| parcel_long_validity | 196 250 | 68 250 | 40% dan (barqaror) | -38 000 | -44 500 |
| parcel_more_orders | 294 250 | 160 250 | 20% dan (barqaror) | -37 000 | -46 250 |
| parcel_richer_mix | 276 250 | 152 250 | 20% dan (barqaror) | -37 000 | -44 500 |
| parcel_small_long | 197 250 | 133 250 | 20% dan (barqaror) | -19 000 | -2 500 |

## 7. Foydalanuvchi tomoni va CAC (90 kun)

| Ssenariy | Xizmat | Kelgan | Qo'shimcha (taxmin) | Kod bilan | Enrollment | Aktivlashgan referee | O'rtacha haqiqiy chegirma | Grant → birinchi sarf (kun) | O'rtacha review kutish (kun) | Haydovchi topilmagan referee |
|---|---|---|---|---|---|---|---|---|---|---|
| control | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | — | 0 |
| control | parcel | 705 | 0 | 0 | 0 | 0 | noma'lum | — | — | 0 |
| conservative | passenger | 1263 | 131 | 293 | 181 | 81 | 2 000 | 17.3 | 2.7 | 9 |
| conservative | parcel | 818 | 113 | 185 | 106 | 50 | 1 000 | 24.0 | 2.7 | 11 |
| medium | passenger | 1411 | 279 | 449 | 304 | 137 | 3 000 | 14.3 | 2.4 | 19 |
| medium | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 2.4 | 15 |
| adverse | passenger | 1411 | 279 | 449 | 304 | 110 | 3 000 | 12.3 | 2.4 | 16 |
| adverse | parcel | 897 | 192 | 264 | 154 | 57 | noma'lum | — | 2.4 | 15 |
| stress_full_redemption | passenger | 1411 | 279 | 449 | 304 | 142 | 3 041 | 15.2 | 3.3 | 27 |
| stress_full_redemption | parcel | 897 | 192 | 264 | 154 | 70 | 1 250 | 17.2 | 3.3 | 20 |
| ops_delay_shortage | passenger | 1411 | 279 | 449 | 304 | 76 | 3 500 | 35.1 | 12.6 | 89 |
| ops_delay_shortage | parcel | 897 | 192 | 264 | 154 | 33 | noma'lum | — | 12.6 | 50 |
| zero_budget | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | — | 0 |
| zero_budget | parcel | 705 | 0 | 0 | 0 | 0 | noma'lum | — | — | 0 |
| budget_cut | passenger | 1411 | 279 | 449 | 194 | 95 | 3 000 | 15.7 | 3.0 | 11 |
| budget_cut | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 3.0 | 15 |
| funding_loss | passenger | 1411 | 279 | 449 | 103 | 56 | 3 000 | 17.6 | 2.0 | 8 |
| funding_loss | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 2.0 | 15 |
| variant_A | passenger | 1384 | 252 | 410 | 221 | 104 | 2 515 | 15.3 | 2.9 | 14 |
| variant_A | parcel | 705 | 0 | 0 | 0 | 0 | noma'lum | — | 2.9 | 0 |
| variant_B | passenger | 1381 | 249 | 405 | 217 | 103 | 2 515 | 15.3 | 2.9 | 14 |
| variant_B | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 2.9 | 15 |
| variant_C | passenger | 1411 | 279 | 449 | 240 | 113 | 2 000 | 16.6 | 2.8 | 15 |
| variant_C | parcel | 705 | 0 | 0 | 0 | 0 | noma'lum | — | 2.8 | 0 |
| parcel_base | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_base | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 3.0 | 15 |
| parcel_small_reward | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_small_reward | parcel | 897 | 192 | 264 | 154 | 65 | 500 | 31.5 | 3.0 | 15 |
| parcel_long_validity | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_long_validity | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 31.5 | 3.0 | 15 |
| parcel_more_orders | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_more_orders | parcel | 897 | 192 | 264 | 154 | 69 | 1 000 | 18.5 | 3.0 | 17 |
| parcel_richer_mix | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_richer_mix | parcel | 897 | 192 | 264 | 154 | 65 | 1 000 | 25.0 | 3.0 | 15 |
| parcel_small_long | passenger | 1132 | 0 | 0 | 0 | 0 | noma'lum | — | 3.0 | 0 |
| parcel_small_long | parcel | 897 | 192 | 264 | 154 | 65 | 500 | 31.5 | 3.0 | 15 |

CAC surati: sarflangan rag'bat + qolgan majburiyat + qo'shimcha marketing; maxrajlar aralashtirilmaydi.

| Ssenariy | Surat | / attribution | / enrollment | / aktivlashgan referee | / qo'shimcha aktivlashgan (TAXMIN) |
|---|---|---|---|---|---|
| conservative | 493 000 | 1 031 | 1 718 | 3 763 | 4 565 |
| medium | 1 421 000 | 1 993 | 3 103 | 7 035 | 6 898 |
| adverse | 1 231 000 | 1 726 | 2 688 | 7 371 | 6 839 |
| stress_full_redemption | 1 633 000 | 2 290 | 3 566 | 7 703 | 7 491 |
| ops_delay_shortage | 1 203 000 | 1 687 | 2 627 | 11 037 | 10 109 |
| budget_cut | 975 000 | 1 367 | 2 802 | 6 094 | 4 733 |
| funding_loss | 562 000 | 788 | 2 187 | 4 645 | 2 728 |
| variant_A | 592 500 | 1 445 | 2 681 | 5 697 | 5 152 |
| variant_B | 717 500 | 1 072 | 1 934 | 4 271 | 3 698 |
| variant_C | 704 000 | 1 568 | 2 933 | 6 230 | 5 587 |
| parcel_base | 127 000 | 481 | 825 | 1 954 | 1 588 |
| parcel_small_reward | 63 500 | 241 | 412 | 977 | 794 |
| parcel_long_validity | 130 000 | 492 | 844 | 2 000 | 1 625 |
| parcel_more_orders | 140 000 | 530 | 909 | 2 029 | 1 628 |
| parcel_richer_mix | 127 000 | 481 | 825 | 1 954 | 1 588 |
| parcel_small_long | 65 000 | 246 | 422 | 1 000 | 812 |

## 8. Moliyaviy tengliklar va budjet invariantlari

- control: 18/18 ✓
- conservative: 30/30 ✓
- medium: 42/42 ✓
- adverse: 42/42 ✓
- stress_full_redemption: 42/42 ✓
- ops_delay_shortage: 42/42 ✓
- zero_budget: 18/18 ✓
- budget_cut: 42/42 ✓
- funding_loss: 42/42 ✓
- variant_A: 24/24 ✓
- variant_B: 30/30 ✓
- variant_C: 30/30 ✓
- parcel_base: 24/24 ✓
- parcel_small_reward: 24/24 ✓
- parcel_long_validity: 24/24 ✓
- parcel_more_orders: 24/24 ✓
- parcel_richer_mix: 24/24 ✓
- parcel_small_long: 24/24 ✓

## 9. Xulosa chegaralari: zararsizlik, stresslar, seed tarqalishi

**Zararsizlik qanday topiladi.** Avvalgi "Kerak / Taxmin" oddiy nisbat edi: (sarflangan rag'bat + qolgan majburiyat) / juft nazoratdagi bitta aktivlashgan foydalanuvchi marjasi. U har qo'shimcha foydalanuvchi birinchi kundan o'rtacha marja beradi va xarajat chiziqli o'sadi deb faraz qiladi — budjet limiti (limitga yetgach yangi va'da yo'q), qualification yiqilishlari va kech kelganlar buni buzadi. Endi chegara **simulyatsiya to'rida** topiladi: `incremental_new_per_day` taxmini 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 125, 150 % ga ko'paytiriladi, har nuqta o'z juft nazoratiga solishtiriladi; chegara — stress farq ≥ 0 bo'lgan birinchi nuqta, "barqaror" — undan yuqori barcha nuqtalar ham ≥ 0.

**Stresslar:** "alohida" jadvalda har taxmin **yolg'iz** qo'llanadi. Bir nechta alohida stressdan o'tish ularning birgalikdagi holatidan o'tish emas — shuning uchun ikki qo'shma qator bor: half_repeat, triple_disputes, low_fares, full_redemption, half_incremental_users **birga**, va xuddi shu to'plam qo'shimcha foydalanuvchisiz.

**Seed tarqalishi** — model ichidagi tasodif (bir xil taxminlar, boshqa seed). Bu haqiqiy bozor ishonch oralig'i **emas**.

### Variant A: faqat yo'lovchi, mijoz -> mijoz, kichik mukofot (`variant_A`, jami)

- Nisbat bilan baho: kerak 61 qo'shimcha aktivlashgan, taxminda 115 → taxminning ~53 % i.
- Simulyatsiya to'ri: chegara **40 %** (barqaror); oldidagi nuqta 30 % → stress farq -8 500, chegarada → 94 500.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -40 000 | -367 500 | 0 | 0 |
| 10 % | 198 500 | -189 000 | 14 | 0 |
| 20 % | 311 500 | -136 000 | 24 | 0 |
| 30 % | 471 500 | -8 500 | 34 | 0 |
| 40 % | 606 500 | 94 500 | 43 | 0 |
| 50 % | 765 500 | 255 500 | 53 | 3 |
| 60 % | 972 500 | 467 500 | 69 | 14 |
| 70 % | 1 142 000 | 644 500 | 83 | 21 |
| 80 % | 1 344 250 | 814 250 | 94 | 37 |
| 90 % | 1 501 500 | 981 500 | 106 | 43 |
| 100 % | 1 651 000 | 1 141 500 | 115 | 55 |
| 125 % | 1 902 000 | 1 419 500 | 139 | 93 |
| 150 % | 2 274 000 | 1 779 000 | 167 | 129 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -40 000 | -367 500 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 765 500 | 255 500 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 1 432 000 | 887 500 | ✓ |
| nizolar va reversal'lar uch baravar | 1 602 000 | 1 095 000 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 1 609 000 | 1 107 000 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 980 000 | 470 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 406 500 | -146 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | -25 000 | -395 000 | ✓ |

- Seed tarqalishi (20 seed, 20260924–20260943): stress farq min 707 500, p10 773 000, mediana 1 055 000, p90 1 218 500, max 1 284 750; manfiy — 0/20. Marja farqi mediana 1 552 750 (min 1 237 500, max 1 802 250).

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: B dagi pochta qismi (1 000 + 1 000 so'm, 60 kun) (`parcel_base`, pochta qamrovi)

- Nisbat bilan baho: kerak 13 qo'shimcha aktivlashgan, taxminda 80 → taxminning ~16 % i.
- Simulyatsiya to'ri: chegara **40 %** (barqaror); oldidagi nuqta 30 % → stress farq -11 500, chegarada → 4 000.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -2 000 | -37 000 | 0 | 0 |
| 10 % | 19 000 | -27 000 | 10 | 0 |
| 20 % | 31 000 | -19 000 | 18 | 0 |
| 30 % | 53 500 | -11 500 | 28 | 0 |
| 40 % | 90 000 | 4 000 | 45 | 0 |
| 50 % | 115 500 | 21 500 | 56 | 0 |
| 60 % | 125 500 | 25 500 | 59 | 0 |
| 70 % | 134 000 | 30 000 | 64 | 0 |
| 80 % | 154 500 | 41 500 | 70 | 0 |
| 90 % | 172 000 | 53 000 | 74 | 0 |
| 100 % | 196 250 | 71 250 | 80 | 0 |
| 125 % | 259 250 | 119 250 | 100 | 0 |
| 150 % | 321 250 | 171 250 | 121 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -2 000 | -37 000 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 115 500 | 21 500 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 156 250 | 44 250 | ✓ |
| nizolar va reversal'lar uch baravar | 187 250 | 64 250 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 196 250 | 68 250 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 103 000 | -23 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 39 500 | -44 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -32 000 | ✓ |

- Seed tarqalishi (20 seed, 20260924–20260943): stress farq min -7 500, p10 33 000, mediana 60 250, p90 103 500, max 109 250; manfiy — 1/20. Marja farqi mediana 188 750 (min 143 250, max 239 250).

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; buyurtmalarning ko'pi past narx guruhida; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: kichikroq mukofot (500 + 500 so'm) (`parcel_small_reward`, pochta qamrovi)

- Nisbat bilan baho: kerak 7 qo'shimcha aktivlashgan, taxminda 80 → taxminning ~9 % i.
- Simulyatsiya to'ri: chegara **20 %** (barqaror); oldidagi nuqta 10 % → stress farq -3 500, chegarada → 6 500.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -1 000 | -18 500 | 0 | 0 |
| 10 % | 19 500 | -3 500 | 10 | 0 |
| 20 % | 31 500 | 6 500 | 18 | 0 |
| 30 % | 54 000 | 21 500 | 28 | 0 |
| 40 % | 91 500 | 48 500 | 45 | 0 |
| 50 % | 117 000 | 70 000 | 56 | 0 |
| 60 % | 126 500 | 76 500 | 59 | 0 |
| 70 % | 135 000 | 83 000 | 64 | 0 |
| 80 % | 155 500 | 98 000 | 70 | 0 |
| 90 % | 173 000 | 113 500 | 74 | 0 |
| 100 % | 197 250 | 134 750 | 80 | 0 |
| 125 % | 260 750 | 191 250 | 100 | 0 |
| 150 % | 323 750 | 248 250 | 121 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -1 000 | -18 500 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 117 000 | 70 000 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 156 750 | 100 750 | ✓ |
| nizolar va reversal'lar uch baravar | 188 250 | 126 750 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 197 250 | 133 250 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 103 000 | 40 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 39 500 | -2 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -16 000 | ✓ |

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: bonus amal muddati 120 kun (`parcel_long_validity`, pochta qamrovi)

- Nisbat bilan baho: kerak 14 qo'shimcha aktivlashgan, taxminda 80 → taxminning ~18 % i.
- Simulyatsiya to'ri: chegara **40 %** (barqaror); oldidagi nuqta 30 % → stress farq -11 500, chegarada → 3 000.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -2 000 | -38 000 | 0 | 0 |
| 10 % | 19 000 | -28 000 | 10 | 0 |
| 20 % | 31 000 | -20 000 | 18 | 0 |
| 30 % | 53 500 | -11 500 | 28 | 0 |
| 40 % | 90 000 | 3 000 | 45 | 0 |
| 50 % | 115 500 | 21 500 | 56 | 0 |
| 60 % | 125 500 | 24 500 | 59 | 0 |
| 70 % | 134 000 | 29 000 | 64 | 0 |
| 80 % | 154 500 | 38 500 | 70 | 0 |
| 90 % | 172 000 | 52 000 | 74 | 0 |
| 100 % | 196 250 | 68 250 | 80 | 0 |
| 125 % | 259 250 | 115 250 | 100 | 0 |
| 150 % | 321 250 | 162 250 | 121 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -2 000 | -38 000 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 115 500 | 21 500 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 156 250 | 43 250 | ✓ |
| nizolar va reversal'lar uch baravar | 187 250 | 61 250 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 196 250 | 68 250 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 103 000 | -27 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 39 500 | -44 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -32 000 | ✓ |

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; buyurtmalarning ko'pi past narx guruhida; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: takroriy jo'natmalar ko'proq (taxmin: repeat 0.6) (`parcel_more_orders`, pochta qamrovi)

- Nisbat bilan baho: kerak 15 qo'shimcha aktivlashgan, taxminda 86 → taxminning ~17 % i.
- Simulyatsiya to'ri: chegara **20 %** (barqaror); oldidagi nuqta 10 % → stress farq -16 500, chegarada → 2 500.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -2 000 | -37 000 | 0 | 0 |
| 10 % | 27 500 | -16 500 | 10 | 0 |
| 20 % | 55 500 | 2 500 | 19 | 0 |
| 30 % | 86 000 | 14 000 | 29 | 0 |
| 40 % | 127 500 | 32 500 | 46 | 0 |
| 50 % | 173 500 | 72 500 | 57 | 0 |
| 60 % | 194 000 | 85 000 | 62 | 0 |
| 70 % | 204 000 | 91 000 | 67 | 0 |
| 80 % | 223 500 | 104 500 | 74 | 0 |
| 90 % | 254 000 | 126 000 | 80 | 0 |
| 100 % | 294 250 | 160 250 | 86 | 0 |
| 125 % | 379 250 | 234 250 | 106 | 0 |
| 150 % | 463 250 | 301 250 | 127 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -2 000 | -37 000 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 173 500 | 72 500 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 172 750 | 53 750 | ✓ |
| nizolar va reversal'lar uch baravar | 284 500 | 152 500 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 293 750 | 157 750 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 166 500 | 29 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 45 750 | -46 250 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -36 000 | ✓ |

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: o'rta/yuqori narxli jo'natmalar ko'proq (taxmin: 20/50/30) (`parcel_richer_mix`, pochta qamrovi)

- Nisbat bilan baho: kerak 13 qo'shimcha aktivlashgan, taxminda 80 → taxminning ~16 % i.
- Simulyatsiya to'ri: chegara **20 %** (barqaror); oldidagi nuqta 10 % → stress farq -15 000, chegarada → 5 000.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -2 000 | -37 000 | 0 | 0 |
| 10 % | 31 000 | -15 000 | 10 | 0 |
| 20 % | 54 000 | 5 000 | 18 | 0 |
| 30 % | 86 000 | 23 000 | 28 | 0 |
| 40 % | 135 500 | 50 500 | 45 | 0 |
| 50 % | 176 000 | 83 000 | 56 | 0 |
| 60 % | 186 000 | 87 000 | 59 | 0 |
| 70 % | 200 500 | 97 500 | 64 | 0 |
| 80 % | 228 500 | 116 500 | 70 | 0 |
| 90 % | 249 500 | 132 500 | 74 | 0 |
| 100 % | 276 250 | 152 250 | 80 | 0 |
| 125 % | 358 750 | 219 750 | 100 | 0 |
| 150 % | 452 250 | 303 250 | 121 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -2 000 | -37 000 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 176 000 | 83 000 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 216 250 | 104 250 | ✓ |
| nizolar va reversal'lar uch baravar | 265 750 | 143 750 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 276 250 | 149 250 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 103 000 | -23 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 39 500 | -44 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -32 000 | ✓ |

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; buyurtmalarning ko'pi past narx guruhida; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

### Pochta: 500 + 500 so'm va 120 kun (`parcel_small_long`, pochta qamrovi)

- Nisbat bilan baho: kerak 7 qo'shimcha aktivlashgan, taxminda 80 → taxminning ~9 % i.
- Simulyatsiya to'ri: chegara **20 %** (barqaror); oldidagi nuqta 10 % → stress farq -4 000, chegarada → 6 000.

| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |
|---|---|---|---|---|
| 0 % | -1 000 | -19 000 | 0 | 0 |
| 10 % | 19 500 | -4 000 | 10 | 0 |
| 20 % | 31 500 | 6 000 | 18 | 0 |
| 30 % | 54 000 | 21 500 | 28 | 0 |
| 40 % | 91 500 | 48 000 | 45 | 0 |
| 50 % | 117 000 | 70 000 | 56 | 0 |
| 60 % | 126 500 | 76 000 | 59 | 0 |
| 70 % | 135 000 | 82 500 | 64 | 0 |
| 80 % | 155 500 | 97 500 | 70 | 0 |
| 90 % | 173 000 | 113 000 | 74 | 0 |
| 100 % | 197 250 | 133 250 | 80 | 0 |
| 125 % | 260 750 | 188 750 | 100 | 0 |
| 150 % | 323 750 | 244 250 | 121 | 0 |

| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |
|---|---|---|---|
| referral referralsiz ham kelmaydigan hech kimni olib kelmaydi | -1 000 | -19 000 | ✓ |
| qo'shimcha foydalanuvchilar taxmini ikki baravar kam | 117 000 | 70 000 | ✓ |
| takroriy buyurtmalar ikki baravar kam | 156 750 | 100 250 | ✓ |
| nizolar va reversal'lar uch baravar | 188 250 | 125 250 | ✓ |
| berilgan har bir bonus ishlatiladi (stress) | 197 250 | 133 250 | ✓ |
| buyurtmalarning ko'pi past narx guruhida | 103 000 | 38 000 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users | 39 500 | -2 500 | ✓ |
| **BIRGA:** half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users | 0 | -16 000 | ✓ |

**Nimada ishlamay qoladi:** referral referralsiz ham kelmaydigan hech kimni olib kelmaydi; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + half_incremental_users; BIRGA: half_repeat + triple_disputes + low_fares + full_redemption + no_incremental_users.

## 10. Variantlar bo'yicha qaror holati (foydalanuvchi, 24.09.2026)

- **A** — kelajakdagi yo'lovchi pilotini baholash uchun asosiy nomzod; summalar va 600 000 so'm budjet production uchun **tasdiqlanmagan**; yo'lovchi xizmatining huquqiy/texnik gate'lari (K7/Q5/Q89, Q48) saqlanadi.
- **B** — hozirgi ko'rinishida tasdiqlanmaydi; pochta qismi §6 da alohida.
- **C** — keyingi baholashga qoldirilgan.
- **Pochta bonusi (G20, 24.09.2026):** hozircha yoqilmaydi — **vaqtinchalik mahsulot qarori**, chunki haqiqiy qayta buyurtma va bonusdan foydalanish ma'lumotlari hali yo'q. §6 dagi ~9 % — **model natijasi**, pochta bonusining foydasizligi isboti emas. Mexanizm kodda saqlanadi, pochta kampaniyasi o'chiq.
- Bu qarorlar kampaniyani yoqish yoki mablag' ajratish ruxsati emas; mukofot, O, M, cap, muddat va budjet manbai haqiqiy pilot qarori bilan belgilanadi.

## 11. Simulyator tasdiqlamaydigan qarorlar

- **Q108 HMAC saqlash muddati** — huquqiy qaror; moliyaviy model bilan tanlanmaydi.
- **Rate-limit va review SLA** — trafik, bloklanish ehtimoli va operator ish hajmi bo'yicha alohida baho kerak.
- **48 soatlik risk oynasi** asosiy modelda o'zgarmagan; o'zgartiruvchi tajriba yo'q.
- Mukofot, budjet, O, M, cap'lar, muddatlar — **hammasi sintetik**.
