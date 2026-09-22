# §19.3 yuklama profili — ishga tushirish qo‘llanmasi

**Holat:** harness tayyor va lokal smoke bilan tekshirilgan; **to‘liq §19.3 profili — NOT_RUN** (staging muhiti
yo‘q). • **Tayyorladi:** wave 7 agenti • **Sana:** 17.09.2026 • **Spec:** §19.3
**Skript:** [`scripts/load_profile.py`](../../scripts/load_profile.py)

> Bu hujjatdagi hech bir raqam production capacity kafolati emas. §19.3 ning o‘zi aytadi: bu **sinov profili**,
> natija emas.

## 1. Nima o‘lchanadi va nima o‘lchanmaydi

| O‘lchanadi | Izoh |
|---|---|
| Server tomonidagi p50/p95/p99, req/s, status taqsimoti | Harness o‘zi o‘lchaydi (klient tomondan) |
| Ilova ichidagi `feed_p95_seconds`, `booking_accept_p95_seconds`, `server_error_rate` | Wave 6 dan: `GET /api/v2/admin/metrics/slo` (bitta worker jarayoni doirasida) |
| `outbox_oldest_pending_seconds` | Shu endpointdan |
| GPS `tracking_freshness` | Shu endpointdan (saqlangan nuqtalardan) |

| O‘lchanmaydi (halol ro‘yxat) | Sabab |
|---|---|
| 50 haydovchining real GPS oqimi | Haqiqiy qurilma yoki simulyator kerak (§10.5) |
| Accept p95 real yuklamada | Accept — pul buyrug‘i; tayyorlangan plan va izolyatsiyalangan staging kerak |
| 100 000 e’lonli katalog | Baza shunday hajmda bo‘lishi kerak (pastdagi fixture bandiga qarang) |
| Android tarmoq sifati, batareya | Bu repo doirasidan tashqarida |

## 2. Oldindan shartlar (staging)

1. **Staging** — production **emas**: `ELCHI_ENVIRONMENT != production` va DB markeri `production` emas.
2. Boshqa sinov yoki migratsiya ishlamayotgan bo‘lsin (PG test stack bilan ustma-ust ishlatilmaydi).
3. Ma’lumot: sintetik. Haqiqiy telefon, hujjat yoki GPS tarixi ishlatilmaydi.
4. Tokenlar: `--token-file` da har satrda bitta bearer token (sintetik akkauntlar).
5. Resurs: §19.1 dagi 2–4 vCPU / 4–8 GB farazi; o‘lchov paytida boshqa yuk bo‘lmasin.

## 3. Fixture (100 000 e’lon) — tayyorlash yo‘li

Katalogni katta qilish uchun mavjud seed skriptlari ishlatiladi; yangi “soxta” e’lon generatori kiritilmaydi:

```bash
# 1) geo katalogi va koridorlar
ELCHI_DATABASE_URL=... py scripts/seed_geo_fixtures.py --actor-user-id <staff_id>
# 2) marketplace demo ma'lumoti (v1 buyurtmalar + foydalanuvchilar)
ELCHI_DATABASE_URL=... py scripts/seed_admin_required_data.py
ELCHI_DATABASE_URL=... py scripts/seed_demo_marketplace_data.py
```

**Ochiq band:** hozircha v2 e’lonlarini ommaviy (100 000) yaratadigan seed skripti **yo‘q**. U yozilmaguncha
feed profili faqat kichik katalogda o‘lchanadi va natija shunday belgilanadi. Skript yozilsa, u ham sintetik
ma’lumot bilan ishlashi va `parcel_policy` gate’iga bo‘ysunishi kerak.

## 4. Ishga tushirish

```bash
# sog'liq (harness tekshiruvi)
py scripts/load_profile.py --base-url https://staging.example --scenario health \
    --duration 60 --warmup 10 --concurrency 20 --note "<commit> <head> <cpu/ram>"

# feed (§19.3 asosiy maqsad: p95 < 1 s)
py scripts/load_profile.py --base-url https://staging.example --scenario feed \
    --token-file tokens.txt --duration 300 --warmup 30 --concurrency 200 \
    --min-samples 200 --note "<commit> <head> <cpu/ram> <dataset size>"

# natijani ilova o'lchovi bilan solishtirish
curl -s https://staging.example/api/v2/admin/metrics/slo -H "Authorization: Bearer <staff>"
```

Hisobotga yoziladigan majburiy kontekst: commit/diff identifikatori, `alembic heads`, image, mashina resursi,
dataset hajmi, warm-up va o‘lchash davri, concurrency, natija (p50/p95/p99, xato ulushi), hamda
“o‘lchanmadi” ro‘yxati.

## 5. Bajarilgan lokal smoke (§19.3 emas)

| Band | Qiymat |
|---|---|
| Buyruq | `py scripts/load_profile.py --base-url http://127.0.0.1:8000 --scenario health --duration 10 --warmup 2 --concurrency 10` |
| Muhit | Ishchi noutbuk, lokal uvicorn (demo), PG test stack yonida ishlayapti |
| Natija | 4266 so‘rov, 100 % `200`, p50 0.018 s / p95 0.037 s / p99 0.099 s (~427 req/s), `reportable: true` |
| Nima isbotlaydi | Harness ishlaydi: o‘lchaydi, foizlarni sanaydi, namuna kichik bo‘lsa foizni bermaydi |
| Nima isbotlamaydi | Feed/accept p95, GPS oqimi, 100 000 e’lonli katalog, production capacity |

## 6. Holat

**§19.3 to‘liq profili: NOT_RUN.** Bloklovchi bog‘liqliklar:

1. Foydalanish mumkin bo‘lgan staging muhiti (bu topshiriqda deploy qilinmaydi).
2. 100 000 e’lonli sintetik katalog uchun seed skripti.
3. Tracking oqimi uchun qurilma simulyatori (yoki bu qism ataylab o‘lchanmaydi deb qayd etiladi).
