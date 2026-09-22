# Elchi — Loyihaning to'liq tavsifi

**Elchi** — shaharlararo yuk/pochta yetkazib berish marketplace'i (MVP).
Mijoz buyurtma yaratadi → tasdiqlangan haydovchilar narx taklif qiladi (auksion) →
mijoz haydovchini tanlaydi → haydovchi yetkazadi → mijoz tasdiqlaydi va baholaydi.
To'lov faqat **naqd** (cash), platforma komissiyani hisoblaydi.

> Hujjat kod bo'yicha yig'ilgan: `app/` (backend), `frontend/`, `mobile-app/`,
> `android-app/`, `alembic/`, `tests/`, `scripts/`.

---

## 1. Texnologiyalar va tuzilma

| Qatlam | Texnologiya | Papka |
|---|---|---|
| Backend API | Python 3 + FastAPI 0.115 + SQLAlchemy 2.0 + Pydantic v2 | [app/](../app/) |
| Ma'lumotlar bazasi | PostgreSQL (psycopg 3), migratsiya — Alembic | [alembic/](../alembic/) |
| Auth | JWT (python-jose, HS256) + bcrypt | [security.py](../app/core/security.py) |
| Veb frontend | React + Vite + TypeScript + MUI/Radix + Google Maps | [frontend/](../frontend/) |
| Mobil veb | React + Vite + TypeScript | [mobile-app/](../mobile-app/) |
| Native Android | Expo 57 + React Native 0.86 + NativeWind + react-native-maps | [android-app/](../android-app/) |
| SMS | Eskiz.uz | [sms_service.py](../app/services/sms_service.py) |
| Geo | Google Maps Geocoding + Yandex Geocoder | [google_maps_service.py](../app/services/google_maps_service.py) |
| Deploy | Docker + docker-compose + Caddy | [Dockerfile](../Dockerfile) |
| Testlar | pytest (24 ta test moduli) | [tests/](../tests/) |

### Backend papka tuzilishi

```
app/
├── main.py              # FastAPI app, CORS, xavfsizlik header'lari, xatolik handler'lari
├── core/
│   ├── config.py        # Barcha sozlamalar (ELCHI_ prefiksli env)
│   └── security.py      # JWT yaratish/tekshirish, parol hash
├── db/                  # Base, Session
├── models/              # 19 ta SQLAlchemy modeli
├── schemas/             # Pydantic so'rov/javob sxemalari
├── api/
│   ├── deps.py          # get_current_user, require_roles(...)
│   └── v1/              # 21 ta router fayli
├── services/            # Biznes-logika (18 ta servis)
└── utils/               # api_response, file_storage, file_validation, order_number
```

---

## 2. Rollar va huquqlar

| Rol | Kirish usuli | Vazifasi |
|---|---|---|
| `client` | SMS OTP | Buyurtma yaratish, takliflarni ko'rish, haydovchi tanlash, tasdiqlash, baholash, nizo ochish |
| `driver` | SMS OTP | Profil + hujjat topshirish, yo'nalish qo'shish, lenta (feed), narx taklif qilish, status yangilash |
| `operator` | username + parol | Buyurtma/haydovchilarni **ko'rish**, nizolarni ko'rib chiqish, audit |
| `admin` | username + parol | Operator huquqlari + haydovchini tasdiqlash/rad etish/bloklash, buyurtmani qo'lda boshqarish, shahar/tuman/tarif CRUD |
| `super_admin` | username + parol | Barcha huquqlar + xodim (operator/admin) yaratish, komissiya foizini o'zgartirish |

Huquq tekshiruvi: [app/api/deps.py](../app/api/deps.py) — `require_client`, `require_driver`,
`require_operator_or_admin`, `require_admin`, `require_super_admin`, `require_admin_or_super_admin`.

---

## 3. Ma'lumotlar modellari (19 jadval)

Barcha modellar `TimestampMixin` dan `created_at` / `updated_at` (timezone-aware) meros oladi.

### 3.1 `users` — [app/models/user.py](../app/models/user.py)

Platformadagi barcha shaxslar (mijoz, haydovchi, xodim) shu jadvalda.

| Maydon | Tur | Izoh |
|---|---|---|
| `id` | int, PK | |
| `phone` | str(32), **unique**, index | `+998XXXXXXXXX` formatida |
| `username` | str(64), unique, nullable | Faqat xodimlar uchun |
| `password_hash` | str(255), nullable | Faqat xodimlar (bcrypt, 12 rounds) |
| `full_name` | str(255), nullable | |
| `role` | str(32), index | `client` \| `driver` \| `operator` \| `admin` \| `super_admin` |
| `status` | str(32) | `active` \| `blocked` \| `deleted` |
| `is_phone_verified` | bool | OTP tasdiqlangach `true` |
| `last_login_at` | datetime, nullable | |

Aloqalar: `client_profile` (1:1), `driver_profile` (1:1).

### 3.2 `client_profiles` — [app/models/client_profile.py](../app/models/client_profile.py)

`id`, `user_id` (FK users, unique, CASCADE), `full_name`.

### 3.3 `driver_profiles` — [app/models/driver_profile.py](../app/models/driver_profile.py)

| Maydon | Tur | Izoh |
|---|---|---|
| `user_id` | FK users, unique, CASCADE | |
| `full_name`, `car_model`, `car_color` | str | |
| `plate_number` | str(32), **unique** | Davlat raqami |
| `plate_number_normalized` | str(32), index | Qidiruv uchun normallashtirilgan |
| `verification_status` | str(32) | `new` → `pending` → `approved` \| `rejected` \| `blocked` |
| `is_available` | bool | Haydovchi "onlayn"mi |
| `rating_avg` | Numeric(3,2) | Baholar o'rtachasi (avtomatik qayta hisoblanadi) |
| `total_orders`, `completed_orders`, `cancelled_orders`, `dispute_count` | int | Statistika |

Aloqalar: `documents` (1:N), `routes` (1:N).

### 3.4 `driver_documents` — [app/models/driver_document.py](../app/models/driver_document.py)

`driver_id` (FK, CASCADE), `document_type`, `file_url`, `status` (`pending`/`approved`/`rejected`),
`rejection_reason`, `reviewed_by` (FK users), `reviewed_at`.

**Majburiy hujjat turlari:** `passport`, `selfie`, `license`, `car_document`, `car_photo`.

### 3.5 `driver_routes` — [app/models/driver_route.py](../app/models/driver_route.py)

`driver_id`, `from_city_id`, `to_city_id`, `from_district_id`, `to_district_id`,
`status` (`available`/`disabled`). **Constraint:** `from_city_id <> to_city_id`.

### 3.6 `cities` — [app/models/city.py](../app/models/city.py)

`name`, `name_uz` (**unique**), `name_ru`, `region`, `type` (default `region`),
`requires_district` (bool), `display_order`, `is_active`.

### 3.7 `districts` — [app/models/district.py](../app/models/district.py)

`city_id`, `name_uz`, `name_ru`, `is_active`, `display_order`, `center_lat`, `center_lng` (Numeric(10,7)).
**Unique index:** `(city_id, lower(name_uz))`.

### 3.8 `route_tariffs` — [app/models/route_tariff.py](../app/models/route_tariff.py)

`from_city_id`, `to_city_id`, `suggested_price`, `min_price`, `max_price`, `is_active`.

Constraint'lar: shaharlar har xil; narxlar manfiy emas;
`min_price <= suggested_price <= max_price`;
har bir yo'nalish uchun faqat **bitta aktiv** tarif (partial unique index).

### 3.9 `orders` — [app/models/order.py](../app/models/order.py) — markaziy model

| Guruh | Maydonlar |
|---|---|
| Identifikator | `order_number` (unique, `ORD-XXXXXXXXXX`), `client_id` (FK users) |
| Yo'nalish | `from_city_id`, `to_city_id`, `from_district_id`, `to_district_id` |
| Manzillar | `pickup_address`, `dropoff_address` (1024) |
| Koordinatalar | `pickup_lat/lng`, `dropoff_lat/lng` — Numeric(10,7) |
| Aloqa | `sender_phone`, `receiver_phone` |
| Yuk | `cargo_photo_url`, `cargo_type`, `comment` |
| Narx | `suggested_price` (tarifdan), `client_price` (mijoz taklifi), `final_price` (tanlangan taklif) |
| Moliya | `system_fee_rate` (Numeric(5,4)), `system_fee`, `driver_income` |
| To'lov | `payment_method` = `cash`, `payment_status` = `unpaid`/`paid` |
| Holat | `status` (index), `cancel_reason`, `cancelled_by` |
| Bog'lanish | `assigned_driver_id` (FK driver_profiles), `accepted_bid_id` (FK bids) |
| Vaqt belgilari | `published_at`, `accepted_at`, `picked_up_at`, `in_transit_at`, `delivered_at`, `confirmed_at`, `cancelled_at` |

**Constraint:** `order_number` unique, `from_city_id <> to_city_id`.

### 3.10 `bids` — [app/models/bid.py](../app/models/bid.py)

`order_id` (CASCADE), `driver_id`, `price` (Numeric(12,2)), `comment`,
`status` (`active`/`accepted`/`closed`), `price_update_count`.
**Constraint:** `(order_id, driver_id)` unique; `price > 0`.
Narxni o'zgartirish limiti: **maksimum 3 marta** (`MAX_BID_PRICE_UPDATES`).

### 3.11 `order_offers` — [app/models/order_offer.py](../app/models/order_offer.py)

Buyurtma qaysi haydovchiga ko'rsatilganini kuzatadi (matching audit).
`order_id`, `driver_id`, `status`, `result` (`shown`/`bid_sent`/`rejected`), `shown_at`, `responded_at`.
**Constraint:** `(order_id, driver_id)` unique.

### 3.12 `status_history` — [app/models/status_history.py](../app/models/status_history.py)

`order_id`, `old_status`, `new_status`, `changed_by_user_id`, `changed_by_role`, `reason`.

### 3.13 `ratings` — [app/models/rating.py](../app/models/rating.py)

`order_id` (**unique** — bir buyurtmaga bitta baho), `client_id`, `driver_id`,
`rating` (1–5, CHECK), `comment`.

### 3.14 `disputes` — [app/models/dispute.py](../app/models/dispute.py)

`order_id`, `opened_by_user_id`, `reason`, `comment`, `status`,
`previous_order_status` (nizo yopilganda tiklash uchun), `resolution`, `resolved_by`, `resolved_at`.

### 3.15 `notifications` — [app/models/notification.py](../app/models/notification.py)

`user_id`, `order_id`, `type`, `title`, `message`, `channel` (`in_app`), `is_read`, `sent_at`,
`entity_type`, `entity_id`.

### 3.16 `otp_codes` — [app/models/otp_code.py](../app/models/otp_code.py)

`phone`, `role`, `otp_hash`, `expires_at`, `used_at`, `attempt_count`,
`send_count_window_start`, `ip_address`. Kod **hech qachon ochiq saqlanmaydi**.

### 3.17 `refresh_sessions` — [app/models/refresh_session.py](../app/models/refresh_session.py)

`user_id`, `jti` (unique), `token_hash`, `is_revoked`, `expires_at`, `revoked_at`,
`user_agent`, `ip_address`. Refresh token rotatsiyasi shu yerda boshqariladi.

### 3.18 `audit_logs` — [app/models/audit_log.py](../app/models/audit_log.py)

`actor_id`, `entity_type`, `entity_id`, `action`, `details` (JSON).
**Immutable:** SQLAlchemy event orqali `UPDATE`/`DELETE` bloklangan
(+ DB darajasida trigger, migratsiya `0024`).

### 3.19 `system_settings` — [app/models/system_setting.py](../app/models/system_setting.py)

`key` (PK), `value`, `description`, `updated_by_user_id`.
Hozirgi kalit: `driver_commission_rate` (default **0.15 = 15%**).

---

## 4. Buyurtma hayot sikli (status flow)

```
draft ──publish──► published ──birinchi taklif──► bidding ──haydovchi tanlandi──► accepted
                                                                                     │
                                                          haydovchi: picked_up ◄─────┘
                                                                   │
                                                              in_transit
                                                                   │
                                                              delivered
                                                                   │
                                          mijoz tasdiqlaydi ──► confirmed  (yakuniy)

Istalgan nuqtada: ──► cancelled   |   nizo ochilsa: ──► disputed ──► oldingi statusga qaytadi
```

**10 ta status:** `draft`, `published`, `bidding`, `accepted`, `picked_up`, `in_transit`,
`delivered`, `confirmed`, `cancelled`, `disputed`.

### Kim qaysi o'tishni bajaradi

| O'tish | Kim | Endpoint |
|---|---|---|
| `draft → published` | mijoz | `POST /client/orders/{id}/publish` |
| `published → bidding` | tizim (birinchi taklif kelganda) | avtomatik |
| `bidding → accepted` | mijoz | `POST /client/orders/{id}/select-driver` |
| `accepted → picked_up` | tayinlangan haydovchi | `POST /driver/orders/{id}/picked-up` |
| `picked_up → in_transit` | haydovchi | `POST /driver/orders/{id}/in-transit` |
| `in_transit → delivered` | haydovchi | `POST /driver/orders/{id}/delivered` |
| `delivered → confirmed` | mijoz | `POST /client/orders/{id}/confirm` |
| `* → cancelled` | mijoz / haydovchi / admin | mos `cancel` endpoint |
| `* → disputed` | mijoz / haydovchi / admin | `POST /orders/{id}/disputes` |
| Qo'lda istalgan o'tish | admin / super_admin (sabab majburiy) | `PATCH /admin/orders/{id}/status` |

**Bekor qilish qoidalari** ([order_service.py](../app/services/order_service.py)):

- Mijoz bekor qila oladi: `draft`, `published`, `bidding`, `accepted`.
- `picked_up` dan keyin mijoz bekor qila olmaydi — faqat nizo ochadi.

**Nizo qoidalari** ([dispute_service.py](../app/services/dispute_service.py)):

- Foydalanuvchi nizo ochishi mumkin: `accepted`, `picked_up`, `in_transit`, `delivered`.
- Admin qo'shimcha: `published`, `bidding`, `confirmed`.
- Nizo statuslari: `open`, `under_review`, `resolved`, `rejected`.
- Sabablar: `delayed`, `lost`, `damaged`, `receiver_denied`, `wrong_address`,
  `payment_issue`, `prohibited_item`, `other`.
- Nizo yopilganda buyurtma `previous_order_status` ga qaytariladi.

---

## 5. Asosiy biznes-funksiyalar (services)

### 5.1 Autentifikatsiya — [auth_service.py](../app/services/auth_service.py)

| Funksiya | Vazifa |
|---|---|
| `request_otp()` | Telefonni normallashtiradi, rate-limit tekshiradi, OTP yaratib SMS yuboradi |
| `verify_otp()` | Kodni tekshiradi, foydalanuvchi yaratadi/topadi, profil ochadi, token beradi |
| `login_staff_with_password()` | Xodimlar uchun username+parol; timing-attack himoyasi (dummy hash) |
| `refresh_tokens()` | Refresh token rotatsiyasi (eskisini bekor qiladi, yangisini beradi) |
| `logout_refresh_session()` | Sessiyani revoke qiladi |
| `create_admin_user()` | super_admin operator/admin yaratadi |
| `create_profile_if_needed()` | Rolga qarab `client_profile` yoki `driver_profile` ochadi |

**OTP xavfsizlik limitlari** ([config.py](../app/core/config.py)):

| Sozlama | Default |
|---|---|
| Kod uzunligi | 4 raqam |
| Amal qilish muddati | 180 s |
| Bir raqamga max yuborish | 5 ta / 30 daqiqa |
| Qayta yuborish kutish vaqti | 60 s |
| Max tekshirish urinishi | 5 ta |
| Bitta IP uchun limit | 15 ta / 60 daqiqa |
| Kunlik global limit (SMS-pumping himoyasi) | 2000 ta |

Qo'shimcha: `review_login_phones` + `review_login_otp` — Google/Apple store
tekshiruvchilari uchun ruxsat etilgan raqamlar (har bir foydalanish audit'ga yoziladi).

### 5.2 Buyurtma — [order_service.py](../app/services/order_service.py)

| Funksiya | Vazifa |
|---|---|
| `create_order_draft()` | Qoralama yaratadi, shahar/tuman va tarifni tekshiradi |
| `update_order()` | `draft`/`published`/`bidding` holatida tahrirlash |
| `validate_order_complete()` | Publish oldidan: manzil, koordinata, telefon, shahar-tuman muvofiqligi |
| `publish_order()` | E'lon qiladi + mos haydovchilarga offer/xabar tarqatadi |
| `list_client_orders()`, `order_detail_to_dict()`, `order_card_to_dict()` | O'qish |
| `list_order_bids()` | Buyurtmaga kelgan takliflar |
| `select_driver_for_order()` | **Tranzaksion**: `SELECT ... FOR UPDATE`, final_price, komissiya, boshqa takliflarni yopish, xabarnoma |
| `cancel_order()` | Mijoz bekor qilishi |
| `confirm_delivered_order()` | Yetkazilganini tasdiqlash, statistika yangilash |
| `create_order_rating()` | 1–5 baho + izoh |
| `recalculate_driver_rating()` | Haydovchi o'rtacha reytingini qayta hisoblash |
| `validate_client_price()` | Mijoz narxi tarif `min`/`max` chegarasida ekanini tekshiradi |

### 5.3 Haydovchi va lenta — [driver_order_service.py](../app/services/driver_order_service.py)

| Funksiya | Vazifa |
|---|---|
| `list_driver_feed()` | Faqat haydovchi yo'nalishiga mos `published`/`bidding` buyurtmalar |
| `limited_order_to_dict()` | Taklif berishdan oldin **cheklangan** ma'lumot (to'liq manzil/telefon yashirin) |
| `full_order_to_dict()` | Tayinlangandan keyin to'liq ma'lumot |
| `create_bid()` | Taklif yaratadi; birinchi taklif buyurtmani `bidding` ga o'tkazadi |
| `update_bid()` | Narxni yangilash — max 3 marta |
| `reject_order()` | Buyurtmani rad etish (offer `rejected` bo'ladi) |
| `mark_driver_order_status()` | `picked_up` / `in_transit` / `delivered` o'tishlari |
| `cancel_assigned_order_by_driver()` | Haydovchi tayinlangan buyurtmani bekor qiladi |
| `ensure_driver_eligible()` | `approved` + `active` tekshiruvi |
| `ensure_order_visible()` | Haydovchi shu buyurtmani ko'rish huquqiga egami |

### 5.4 Matching — [matching_service.py](../app/services/matching_service.py)

`find_matched_drivers_for_order()` — buyurtma e'lon qilinganda mos haydovchilarni topadi.
**Mezonlar (hammasi bir vaqtda):**

- `driver_routes.from_city_id` va `to_city_id` buyurtma bilan mos,
- tuman ham mos (buyurtmada tuman bo'lsa),
- `driver_routes.status == "available"`,
- `driver_profiles.verification_status == "approved"`,
- `driver_profiles.is_available == true`,
- `users.status == "active"`.

`create_order_offers_for_published_order()` — har bir mos haydovchi uchun `order_offers`
yozuvi yaratadi va `order_published` xabarnomasini yuboradi (dublikatlarni o'tkazib yuboradi).

### 5.5 Haydovchi profili — [driver_service.py](../app/services/driver_service.py)

`get_or_create_driver_profile()`, `update_driver_profile()`, `submit_driver_document()`,
`list_driver_documents()`, `update_availability()`, `create_driver_route()`,
`list_driver_routes()`, `update_route_status()`, `update_driver_route()`, `disable_driver_route()`,
`normalize_plate_number()` (davlat raqamini normallashtirish va dublikat nazorati).

### 5.6 Admin — haydovchilar — [admin_driver_service.py](../app/services/admin_driver_service.py)

`list_admin_drivers()`, `get_admin_driver_detail()`, `approve_driver()`, `reject_driver()`,
`block_driver()`, `update_driver_vehicle()`, `missing_required_documents()`,
`mark_documents_reviewed()`.

Tasdiqlash uchun **5 ta hujjat** to'liq bo'lishi shart; rad etish/bloklash uchun **sabab majburiy**.

### 5.7 Admin — buyurtmalar — [admin_order_service.py](../app/services/admin_order_service.py)

`list_admin_orders()` (filtr + pagination), `get_admin_order_detail()`,
`update_admin_order_status()` (qo'lda status, sabab majburiy),
`assign_driver_manually()` (haydovchini qo'lda tayinlash + narx belgilash),
`cancel_order_manually()`, `close_active_bids()`, `driver_has_available_route()`.

### 5.8 Moliya / komissiya — [system_settings_service.py](../app/services/system_settings_service.py)

```
system_fee    = final_price × driver_commission_rate
driver_income = final_price − system_fee
```

- `driver_commission_rate` — `system_settings` jadvalida, default **0.15**.
- `apply_order_commission()` — haydovchi tanlanganda buyurtmaga yoziladi.
- `update_driver_commission()` — faqat **super_admin**, foizda (0–100) beriladi.
- Yaxlitlash: stavka 4 xona (`0.0001`), pul 2 xona (`0.01`).

### 5.9 Shahar / tuman / tarif — [city_service.py](../app/services/city_service.py)

`list_cities()`, `create_city()`, `update_city()`, `list_districts()`, `create_district()`,
`update_district()`, `list_tariffs()`, `create_tariff()`, `update_tariff()`,
`validate_tariff_prices()`, `active_tariff_exists()`, `validate_active_city_district_pair()`.

### 5.10 Geo — [geo_service.py](../app/services/geo_service.py)

- `distance_km()` — Haversine formulasi.
- `nearest_district()` — koordinataga eng yaqin tuman markazi.
- `validate_location_payload()` — tanlangan nuqta tanlangan viloyat/tumanga mos keladimi.
- `DISTRICT_CENTER_MAX_KM = 75.0` — tuman markazidan maksimal masofa.
- Geokodlash provayderlari: Google va Yandex — ikkalasida `reverse_geocode()` va `geocode()`.

### 5.11 Xabarnomalar — [notification_service.py](../app/services/notification_service.py)

Kanal: `in_app`. **16 ta tur:**
`order_published`, `new_bid`, `driver_selected`, `picked_up`, `in_transit`, `delivered`,
`confirmed`, `cancelled`, `disputed`, `rating_received`, `driver_approved`, `driver_rejected`,
`driver_blocked`, `admin_order_status_updated`, `admin_driver_assigned`, `admin_order_cancelled`.

### 5.12 Audit — [audit_service.py](../app/services/audit_service.py)

`write_audit_log()` — har bir muhim amalni yozadi.
`SENSITIVE_AUDIT_KEYS` — parol/token kabi qiymatlar `redact_sensitive_value()` bilan yashiriladi.
`NOISY_AUDIT_ACTIONS` — shovqinli amallar filtrlanadi.
O'qish: [admin_audit_log_service.py](../app/services/admin_audit_log_service.py).

### 5.13 Akkaunt o'chirish — [account_deletion_service.py](../app/services/account_deletion_service.py)

`delete_own_account()` — GDPR / Play Store talabi.

- `IN_FLIGHT_ORDER_STATUSES` bo'yicha faol buyurtma bo'lsa — o'chirishga ruxsat yo'q.
- Telefon "tombstone" qiymatga almashtiriladi (`_tombstone_phone`).
- Yuklangan fayllar o'chiriladi (`_remove_upload`).

### 5.14 Fayl yuklash — [file_validation.py](../app/utils/file_validation.py)

| Qoida | Qiymat |
|---|---|
| Ruxsat etilgan turlar | `cargo_photo`, `passport`, `selfie`, `license`, `car_document`, `car_photo` |
| Faqat rasm | `cargo_photo`, `selfie`, `car_photo` |
| Rasm + PDF | `passport`, `license`, `car_document` |
| Kengaytmalar | `jpg`, `jpeg`, `png`, `webp` (+ `pdf` hujjatlar uchun) |
| Bloklangan | `exe`, `bat`, `cmd`, `sh`, `php`, `js`, `html`, `svg`, `zip`, `rar`, `7z` |
| Maksimal hajm | rasm 5 MB, hujjat 10 MB |

### 5.15 SMS — [sms_service.py](../app/services/sms_service.py)

Eskiz.uz API: `_login()` → token (kesh bilan), `send_sms()`.
`sms_enabled=false` bo'lsa faqat dev-mock rejim; `sms_test_mode=true` — Eskiz tasdiqlagan
test shabloni ishlatiladi.

---

## 6. API endpointlari

Bazaviy prefiks: **`/api/v1`**. Javoblar `{success, data, message}` yoki xatoda
`{success: false, error: {code, message, details}}` ko'rinishida.

### Health

| Metod | Yo'l | Kirish |
|---|---|---|
| GET | `/health` | ochiq |

### Auth — [auth.py](../app/api/v1/auth.py)

| Metod | Yo'l | Kirish | Vazifa |
|---|---|---|---|
| POST | `/auth/request-otp` | ochiq | OTP so'rash |
| POST | `/auth/verify-otp` | ochiq | OTP tasdiqlash → token |
| POST | `/auth/staff-login` | ochiq | Xodim: username + parol |
| POST | `/auth/refresh` | ochiq | Token yangilash |
| POST | `/auth/logout` | auth | Sessiyani yopish |
| GET | `/auth/me` | auth | Joriy foydalanuvchi |
| PATCH | `/auth/me` | auth | Ism o'zgartirish |
| DELETE | `/auth/me` | auth | Akkauntni o'chirish |

### Admin foydalanuvchilar (xodimlar)

| Metod | Yo'l | Kirish |
|---|---|---|
| POST | `/admin/users` | super_admin |
| GET | `/admin/users` | admin+ |
| GET | `/admin/users/{user_id}` | admin+ |
| PATCH | `/admin/users/{user_id}` | super_admin |
| POST | `/admin/users/{user_id}/block` | super_admin |
| POST | `/admin/users/{user_id}/unblock` | super_admin |

### Fayllar / Geo / Shaharlar

| Metod | Yo'l | Kirish |
|---|---|---|
| POST | `/files/upload` | auth |
| POST | `/geo/validate-location` | ochiq |
| POST | `/geo/reverse-geocode` | ochiq |
| POST | `/geo/geocode` | ochiq |
| GET | `/cities` | ochiq |
| GET | `/cities/{city_id}/districts` | ochiq |
| GET | `/route-tariffs/suggested-price` | auth |

### Mijoz — [client_orders.py](../app/api/v1/client_orders.py), [client_profile.py](../app/api/v1/client_profile.py)

| Metod | Yo'l | Vazifa |
|---|---|---|
| GET / PATCH | `/client/profile` | Profil |
| POST | `/client/orders` | Qoralama yaratish |
| PATCH | `/client/orders/{id}` | Tahrirlash |
| POST | `/client/orders/{id}/publish` | E'lon qilish |
| GET | `/client/orders` | Ro'yxat (filtr + pagination) |
| GET | `/client/orders/{id}` | Tafsilot |
| GET | `/client/orders/{id}/bids` | Takliflar |
| POST | `/client/orders/{id}/select-driver` | Haydovchi tanlash |
| POST | `/client/orders/{id}/confirm` | Yetkazilganini tasdiqlash |
| POST | `/client/orders/{id}/rating` | Baholash (1–5) |
| POST | `/client/orders/{id}/cancel` | Bekor qilish |

### Haydovchi — [driver.py](../app/api/v1/driver.py)

| Metod | Yo'l | Vazifa |
|---|---|---|
| GET | `/driver/orders/feed` | Yo'nalishga mos buyurtmalar lentasi |
| GET | `/driver/orders` | Tayinlangan buyurtmalar |
| GET | `/driver/orders/{id}` | Tafsilot (cheklangan yoki to'liq) |
| POST | `/driver/orders/{id}/bids` | Narx taklif qilish |
| PATCH | `/driver/bids/{bid_id}` | Taklif narxini yangilash (max 3) |
| POST | `/driver/orders/{id}/reject` | Rad etish |
| POST | `/driver/orders/{id}/picked-up` | Yukni oldim |
| POST | `/driver/orders/{id}/in-transit` | Yo'ldaman |
| POST | `/driver/orders/{id}/delivered` | Yetkazdim |
| POST | `/driver/orders/{id}/cancel` | Bekor qilish |
| GET / PATCH | `/driver/profile` | Profil |
| GET / POST | `/driver/documents` | Hujjatlar |
| PATCH | `/driver/availability` | Onlayn/oflayn |
| POST / GET | `/driver/routes` | Yo'nalishlar |
| PATCH | `/driver/routes/{id}` | Yo'nalishni tahrirlash |
| PATCH | `/driver/routes/{id}/status` | Holat |
| DELETE | `/driver/routes/{id}` | O'chirish (disable) |

### Nizolar — [disputes.py](../app/api/v1/disputes.py)

| Metod | Yo'l | Kirish |
|---|---|---|
| POST | `/orders/{order_id}/disputes` | client / driver / admin |
| GET | `/disputes` | auth (o'zining nizolari) |
| GET | `/admin/disputes` | operator+ |
| GET | `/admin/disputes/{id}` | operator+ |
| PATCH | `/admin/disputes/{id}` | operator+ (hal qilish) |

### Xabarnomalar

| Metod | Yo'l |
|---|---|
| GET | `/notifications` |
| PATCH | `/notifications/{id}/read` |
| PATCH | `/notifications/read-all` |

### Admin panel

| Metod | Yo'l | Kirish |
|---|---|---|
| GET | `/admin/orders`, `/admin/orders/{id}` | operator+ |
| PATCH | `/admin/orders/{id}/status` | admin+ (sabab majburiy) |
| POST | `/admin/orders/{id}/assign-driver` | admin+ |
| POST | `/admin/orders/{id}/cancel` | admin+ |
| GET | `/admin/drivers`, `/admin/drivers/{id}` | operator+ |
| PATCH | `/admin/drivers/{id}/vehicle` | admin+ |
| POST | `/admin/drivers/{id}/approve` \| `/reject` \| `/block` | admin+ |
| GET | `/admin/clients`, `/admin/clients/{id}` | operator+ |
| POST | `/admin/clients/{id}/block` \| `/unblock` | admin+ |
| GET | `/admin/audit-logs`, `/admin/audit-logs/{id}` | admin+ |
| POST/GET/PATCH | `/admin/cities`, `/admin/cities/{id}` | admin+ |
| POST/GET/PATCH | `/admin/districts`, `/admin/districts/{id}` | admin+ |
| POST/GET/PATCH | `/admin/route-tariffs`, `/admin/route-tariffs/{id}` | admin+ |
| GET | `/admin/settings` | admin+ |
| PATCH | `/admin/settings/driver-commission` | super_admin |

---

## 7. Frontend'lar

### 7.1 `frontend/` — asosiy veb (React + Vite + MUI/Radix)

URL tuzilishi ([routes.tsx](../frontend/src/app/routes.tsx)):

| Yo'l | Nima |
|---|---|
| `/` | Auth: splash → onboarding → rol tanlash → telefon → OTP |
| `/driver` | Haydovchi ilovasi |
| `/client` | Mijoz ilovasi |
| `/admin` | Admin desktop paneli |

Xaritalar: [components/maps/](../frontend/src/components/maps/) —
`LocationPicker`, `MapView`, `RouteMap`, `AdvancedMapMarker`, `useMapsLoader`.

### 7.2 `mobile-app/` — mobil veb

Admin panellari: `AdminOverviewPanel`, `AdminOrdersPanel`, `AdminDriversPanel`,
`AdminClientsPanel`, `AdminUsersPanel`, `AdminCitiesPanel`, `AdminTariffsPanel`,
`AdminNotificationsPanel`, `AdminAuditLogsPanel`, `AdminProfilePanel`.

Xarita komponentlari: `GoogleMapPicker`, `ClientMapCanvas`, `RoutePreviewMap`, `ReadOnlyOrderMap`.

`admin-overview.api.ts` boshqa admin endpointlarini birlashtirib moliyaviy
ko'rsatkichlarni (umumiy summa, tizim foydasi, haydovchi daromadi, kunlik/o'rtacha) hisoblaydi.

### 7.3 `android-app/` — native Android (Expo)

**Auth ekranlari:** `SplashScreen`, `OnboardingScreen`, `RoleSelectScreen`, `PhoneScreen`, `OtpScreen`.

**Mijoz ekranlari:** `ClientHomeScreen`, `CitySelectScreen`, `DistrictSelectScreen`,
`MapPickerScreen`, `ContactsScreen`, `CargoPhotoScreen`, `OrderReviewScreen`,
`OrderSuccessScreen`, `ClientOrdersScreen`, `ClientOrderDetailScreen`, `ClientBidsScreen`,
`ConfirmDeliveryScreen`, `RatingScreen`, `DisputeScreen`, `ClientNotificationsScreen`,
`ClientProfileScreen`, `ClientSupportScreen`.

**Haydovchi ekranlari:** `DriverApp`, `DriverAddRoute`, `DriverDocuments`,
`DriverEditProfile`, `DriverOrderBids`, `BidSheet`.

Qo'shimcha: `i18n` (uz/ru), `ThemeProvider` + dizayn `tokens`,
`secureStorage` (expo-secure-store), `YandexMap` / `MapPanel`, haptics.

Uchala klient bir xil API qatlamiga (`src/api/*.api.ts`) va bir xil tip
fayllariga (`src/types/*`) ega.

---

## 8. Xavfsizlik choralari

1. **JWT** — access (60 daq) + refresh (30 kun), refresh rotatsiyasi va revoke.
2. **Parollar** — bcrypt, 12 rounds, max 72 bayt.
3. **OTP** — hash holda saqlanadi, muddat, urinish/IP/global limitlar.
4. **Timing-attack** — xodim login'ida dummy hash bilan vaqt tenglashtiriladi.
5. **Rol nazorati** — har bir endpointda `require_roles(...)`.
6. **Audit loglar immutable** — model event + DB trigger.
7. **Xavfsizlik header'lari** — `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`.
8. **Fayl validatsiyasi** — kengaytma + MIME + hajm + xavfli format bloki.
9. **Tranzaksion tanlov** — `SELECT ... FOR UPDATE` race-condition'ga qarshi.
10. **CORS** — aniq ro'yxat + lokal tarmoq uchun regex.
11. **Maxfiy qiymatlarni redaksiya qilish** — audit loglarda.

---

## 9. Migratsiyalar (Alembic, 29 ta)

| Fayl | Mazmuni |
|---|---|
| `0001_initial_setup` | Boshlang'ich |
| `0002_database_models` | Asosiy modellar |
| `0003_cities_route_tariffs` | Shaharlar va tariflar |
| `0004_driver_profile_fields` | Haydovchi profili |
| `0005_client_order_lifecycle_fields` | Buyurtma hayot sikli |
| `0006_order_offers_matching_fields` | Matching |
| `0007_driver_feed_bids_fields` | Lenta va takliflar |
| `0008_dispute_fields` | Nizolar |
| `0009_driver_document_review_fields` | Hujjat ko'rib chiqish |
| `0010_notifications_api_fields` | Xabarnomalar |
| `0011_audit_log_read_indexes` | Audit indekslari |
| `0012_auth_hardening_otp_refresh` | Auth mustahkamlash |
| `0013_stage5_city_tariff_hardening` | Tarif constraint'lari |
| `0014_driver_profile_lifecycle_hardening` | Haydovchi holati |
| `0015`, `0016` | Buyurtma koordinatalari (+ merge) |
| `0020_add_districts`, `0021_add_district_centers` | Tumanlar va markazlari |
| `0022_system_commission_settings` | Komissiya sozlamasi |
| `0023_add_order_pickup_available_at` | Olib ketish vaqti |
| `0024_make_audit_logs_immutable` | Audit trigger |
| `0025_add_order_cargo_type` | Yuk turi |
| `0026_add_order_client_price` | Mijoz narxi |
| `0027_add_bid_price_update_count` | Taklif yangilash hisoblagichi |
| `0028_otp_ip_address` | OTP IP limiti |
| `0029_user_username_password` | Xodim login'i |

---

## 10. Testlar ([tests/](../tests/), 24 modul)

`test_auth`, `test_staff_password_login`, `test_security_hardening`,
`test_client_orders`, `test_client_profile`, `test_client_confirm_rating`,
`test_select_driver_transaction`, `test_driver_feed_bids`, `test_driver_order_status`,
`test_driver_profile_documents_routes`, `test_matching_order_offers`,
`test_admin_orders`, `test_admin_clients`, `test_admin_driver_verification`,
`test_admin_audit_logs`, `test_disputes`, `test_notifications`,
`test_cities_route_tariffs`, `test_files`, `test_models`, `test_health`,
`test_api_docs_collection`, `test_stage20_final_qa`.

Ishga tushirish: `pytest`

---

## 11. Skriptlar ([scripts/](../scripts/))

| Skript | Vazifa |
|---|---|
| `create_super_admin.py` | Super admin yaratish |
| `set_staff_password.py` | Xodimga parol o'rnatish |
| `seed_cities.py`, `seed_districts.py` | Shahar/tuman ma'lumotlari |
| `seed_admin_required_data.py` | Admin uchun zarur boshlang'ich data |
| `seed_bidding_demo.py`, `seed_demo_marketplace_data.py` | Demo ma'lumotlar |
| `seed_review_accounts.py` | Store tekshiruvchilari uchun akkauntlar |
| `make_store_screenshots.py` | Play Store skrinshotlari |
| `dev.sh` | Lokal ishga tushirish |
| `deploy.sh`, `server_bootstrap.sh` | Serverga deploy |
| `backup.sh` | Zaxira nusxa |

---

## 12. Konfiguratsiya (env, `ELCHI_` prefiksi)

| Guruh | Kalitlar |
|---|---|
| Umumiy | `ELCHI_ENVIRONMENT`, `ELCHI_DEBUG`, `ELCHI_API_V1_PREFIX` |
| DB | `ELCHI_DATABASE_URL` |
| JWT | `ELCHI_SECRET_KEY`, `ELCHI_ACCESS_TOKEN_EXPIRE_MINUTES`, `ELCHI_REFRESH_TOKEN_EXPIRE_DAYS`, `ELCHI_JWT_ALGORITHM` |
| OTP | `ELCHI_OTP_LENGTH`, `ELCHI_OTP_EXPIRE_SECONDS`, `ELCHI_OTP_MAX_SEND_REQUESTS`, `ELCHI_OTP_SEND_WINDOW_MINUTES`, `ELCHI_OTP_RESEND_COOLDOWN_SECONDS`, `ELCHI_OTP_MAX_VERIFY_ATTEMPTS`, `ELCHI_OTP_MAX_REQUESTS_PER_IP`, `ELCHI_OTP_IP_WINDOW_MINUTES`, `ELCHI_OTP_GLOBAL_DAILY_CAP`, `ELCHI_DEV_MOCK_OTP` |
| Store review | `ELCHI_REVIEW_LOGIN_PHONES`, `ELCHI_REVIEW_LOGIN_OTP` |
| SMS | `ELCHI_SMS_ENABLED`, `ELCHI_SMS_TEST_MODE`, `ELCHI_ESKIZ_BASE_URL`, `ELCHI_ESKIZ_EMAIL`, `ELCHI_ESKIZ_PASSWORD`, `ELCHI_ESKIZ_FROM`, `ELCHI_OTP_MESSAGE_TEMPLATE` |
| Fayllar | `ELCHI_UPLOAD_DIR`, `ELCHI_MAX_IMAGE_UPLOAD_MB`, `ELCHI_MAX_DOCUMENT_UPLOAD_MB`, `ELCHI_PUBLIC_UPLOAD_BASE_URL` |
| Xarita | `ELCHI_GOOGLE_MAPS_API_KEY`, `ELCHI_GOOGLE_MAPS_COUNTRY`, `ELCHI_YANDEX_GEOCODER_API_KEY` |
| CORS | `ELCHI_CORS_ORIGINS`, `ELCHI_CORS_ORIGIN_REGEX` |

Frontend: `VITE_API_BASE_URL`, `VITE_GOOGLE_MAPS_API_KEY`, `VITE_OTP_LENGTH`.
Android: `EXPO_PUBLIC_*` ekvivalentlari.

---

## 13. Ishga tushirish

```bash
# Backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload          # http://127.0.0.1:8000
# Swagger: http://127.0.0.1:8000/docs

# Veb frontend
cd frontend && npm install && npm run dev     # http://localhost:5173

# Mobil veb
cd mobile-app && npm install && npm run dev

# Android
cd android-app && npm install && npx expo start
```

Batafsil: [START.md](../START.md), [RUNNING.md](../RUNNING.md),
[docs/API_GUIDE.md](API_GUIDE.md), [docs/SERVER_MIGRATION.md](SERVER_MIGRATION.md),
[docs/PLAY_STORE_RELEASE.md](PLAY_STORE_RELEASE.md).
