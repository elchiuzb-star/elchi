# Handoff — ADR-0026 va muzlatilgan klientlar (`android-app/`, `frontend/`)

**Kimga:** `android-app/` egasi (Android dasturchi) va `frontend/` bo'yicha keyingi qaror egasi.
**Holat:** lokal o'zgarish, deploy qilinmagan. Muzlatilgan papkalarga hech narsa yozilmagan.

## 1. Qisqacha: hozir sizdan hech narsa talab qilinmaydi
- Ikkala muzlatilgan klient faqat **`/api/v1`** ni chaqiradi. ADR-0026 v1 ga **tegmaydi**: yo'llar, javob shakli
  (`{success, data, message}` / `{success:false, error:{...}}`), JWT `role`, OTP (4 xona, Q137), v1 buyurtma va v1 nizo
  xulqi o'zgarmagan (AGENTS §2, Q4).
- v1 buyurtmalar v2 da faqat o'qish uchun proyeksiya (Q4) — v1 bozor parallel ishlaydi.

## 2. v2 da nima o'zgardi (klient v2 ga o'tsa bilishi kerak)
| Mavzu | Olib tashlandi | O'rniga |
|---|---|---|
| Haydovchi e'loni (Q138) | `POST /listings` `kind=trip_offer` → `409 DRIVER_LISTING_RETIRED`; `GET /feed?side=offers`; `side=offers` saqlangan qidiruv; `GET /listings/{id}/matches` | Mijoz `kind=request` beradi; haydovchi `GET /feed?side=requests` → `POST /listings/{id}/proposals`; mijoz takliflarni solishtirib `accept` qiladi |
| Saqlangan talab (ADR-0025) | `POST/PATCH /me/trip-intents` → `409 TRIP_INTENT_RETIRED` | Oddiy mijoz e'loni |
| Pochta kodlari (Q139) | `pickup_code`/`delivery_code`/`return_code`, haydovchining `pick_up`/`deliver`/... amallari, jo'natuvchining `complete` amali, pochta `cash-receipts` | Trip `depart` → `in_transit` (tizim); «yetkazildi»/«yakunlandi» faqat operator (`mark_delivered`, `complete_with_evidence`) |
| O'lcham kiritish (Q140) | `parcel.weight_g/length_cm/width_cm/height_cm/volume_ml` kiritish | `GET /parcel-categories` → `parcel.category_id`; bron `parcel_category` ni saqlaydi |
| Nizo formasi (Q141) | `POST /bookings/{id}/disputes`, `GET /me/disputes`, `GET /disputes/{id}`, `POST /disputes/{id}/evidence` | «Shikoyat qilish»: `POST /bookings/{id}/support-thread` (qayta bosish shu chatni qaytaradi), `GET /support-threads/{id}`, `POST /support-threads/{id}/messages`, `GET /me/support-threads` |

Yo'lovchi `boarding_code` va uning oqimi o'zgarmagan.

## 3. Klient uchun muhim qoidalar
- Pochta toifasi: katalog `confirmed=false` bo'lsa pochta e'lonini berish mumkin emas — ekranda sababni ayting,
  raqamli forma ko'rsatmang. `synthetic=true` katalog — demo qiymatlar (belgi bilan ko'rsating).
- Chat holati `staff_status`: `waiting` (navbatda) / `assigned` / `answered` / `closed`. Javob vaqtini va'da qilmang
  (Q87). Chat ochilishi pul qaytarmaydi va bonus bermaydi — matnda shunday deng.
- Pochta bronida «to'ladim / pulni oldim» tugmasi yo'q; kelishilgan narx va to'lanadigan summa ko'rsatiladi.
- Xato kodlari: `DRIVER_LISTING_RETIRED` (409), `TRIP_INTENT_RETIRED` (409), `SUPPORT_THREAD_CLOSED` (409),
  `PARCEL_CATEGORY_REQUIRED` (400), `PARCEL_CATALOG_UNCONFIRMED` (503).
- To'liq sxema: `mobile-app/src/api/generated/openapi-v2.json` (qayta generatsiya qilingan).

## 4. Ochiq savollar (foydalanuvchi qarori kerak)
- **D-1** Pochtani yakunlash qoidasi — hozir faqat operator (ADR-0026 §1). Android v1 pochta oqimiga ta'sir qilmaydi.
- Muzlatilgan klientni v2 ga o'tkazish rejasi — K6/Q4 dan keyin alohida qaror.
