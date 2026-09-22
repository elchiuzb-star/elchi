# ADR-0005: API v2 konvensiyalari — envelope, xato kodlari, Idempotency-Key, expected_version, cursor

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §13, §14, §14.2, §15, §17.6 • **AC:** AC04, AC08, AC09, AC39
**Kontrakt:** `app/contracts/dto.py`, `errors.py`, `idempotency.py`, `cursor.py`

## Kontekst
v1: `{success, data, message}` / `{success:false, error:{code,message,details}}` (`app/utils/api_response.py:4-13`, `app/main.py:73-110`); validatsiya xatosi 400; routerlar `response_model=None` → OpenAPI javob sxemasiz. Idempotency, versiya, cursor yo‘q. Klientlar envelope’ni ochadi (`mobile-app/src/api/http.ts:17-27`).

## Qaror
### 1. Prefiks va versiya
`/api/v2`. v1 va v2 bir ilovada. Health: `/health/live`, `/health/ready` (prefikssiz, A10a).

### 2. Envelope
v1 shakli saqlanadi, `meta` qo‘shiladi: muvaffaqiyat `{"success": true, "data": …, "message": null, "meta": {"next_cursor": …, "limit": 20}}`; xato `{"success": false, "error": {"code", "message", "details", "request_id"}}`. HTTP status asosiy. Har endpoint `response_model=Envelope[DTO]` — OpenAPI to‘liq bo‘lishi uchun majburiy.
*Sabab:* `mobile-app/src/api/http.ts` o‘zgarishsiz ishlaydi; bir xil xato ishlovi; generatsiya qilingan TS tiplari generic wrapper bilan ishlaydi.

### 3. Xato kodlari
`ErrorCode` + `ERROR_CATALOGUE` (HTTP status bilan). Spec §14.2: `IDEMPOTENCY_KEY_REUSED`, `PROPOSAL_CHANGED`, `CAPACITY_UNAVAILABLE`, `INSUFFICIENT_COMMISSION_BALANCE`, `ROUTE_CHANGED` — 409; ruxsat yo‘q — 403; ko‘rinmas obyekt — 404; limit — 429. Validatsiya 400 (v1 bilan bir xil). Domen `DomainError` ko‘taradi; v2 exception handler envelope’ga aylantiradi. Yangi kod — kontrakt o‘zgarishi.

### 4. Idempotency-Key
- **Majburiy:** holat/pul/bron yaratadigan har `POST` buyruq (API_V2_CONTRACT’da `Idem=Y`). Yo‘q → `400 IDEMPOTENCY_KEY_REQUIRED`. Format `^[A-Za-z0-9._:-]{8,128}$` (UUID tavsiya).
- **Kalit doirasi:** `(actor_user_id, "METHOD route_template", key)` unique.
- **Hash:** `sha256(canonical_json({method, route, path_params, body}))`.
- **Oqim (bitta DB tranzaksiyasi, §15; savepoint naqshi — BR D8):**
  1. `BEGIN`; `INSERT INTO idempotency_records (…, state='processing') ON CONFLICT (actor_user_id, route, idem_key) DO NOTHING`. Qator allaqachon bor bo‘lsa uni `SELECT … FOR UPDATE` bilan o‘qiymiz (commit qilinmagan parallel so‘rov tugaguncha kutadi): hash farqli → `409 IDEMPOTENCY_KEY_REUSED`; `completed` → saqlangan status+body, header `Idempotent-Replayed: true`; `lock_timeout` → `409 IDEMPOTENCY_IN_PROGRESS` + `Retry-After`.
  2. `SAVEPOINT command` (SQLAlchemy `session.begin_nested()`); domen buyrug‘i shu savepoint ichida (lock’lar ADR-0017 tartibida).
  3. Muvaffaqiyat → `RELEASE SAVEPOINT`; javob (2xx) yozuvga saqlanadi (`state='completed'`); `COMMIT`.
  4. `DomainError` (4xx) → **`ROLLBACK TO SAVEPOINT command`** — domen yozuvlari va savepoint’dan keyin olingan lock’lar bekor bo‘ladi; yozuvga shu 4xx status va body saqlanadi (`state='completed'`); `COMMIT` — faqat idempotency yozuvi commit bo‘ladi. Takror so‘rov domen o‘zgarishisiz aynan shu 4xx’ni oladi.
  5. Kutilmagan xato/5xx → butun tranzaksiya `ROLLBACK` (yozuv ham yo‘q; kalit qayta ishlatilishi mumkin). Deadlock/serialization → butun rollback va ichki retry (ADR-0017).
- **Nima saqlanadi:** yozuv olingandan keyingi deterministik javoblar — 2xx va domen 4xx. 5xx saqlanmaydi. Yozuv olishdan oldingi 400/401 (sxema validatsiyasi, auth) saqlanmaydi.
- **Muqobil (rad etilgan):** 4xx’ni alohida commit qilingan yozuvda saqlash (ikkinchi connection) — ikki tranzaksiya orasida holat nomuvofiqligi va murakkablik; savepoint bitta tranzaksiyada yetarli.
- **Retry:** deadlock/serialization xatosi server ichida cheklangan (3) marta shu kalit bilan qayta bajariladi.
- **TTL:** 24 soat (`IDEMPOTENCY_RECORD_TTL`); worker tozalaydi.

### 5. expected_version
Versiyali agregat (listing, trip, booking, amendment, topup, commission policy end, corridor, flag qiymati) buyruq body’sida `expected_version` (int ≥1). Mos kelmasa `409 VERSION_CONFLICT`, `details.current_version`. Accept’da spec bo‘yicha `proposal_version_id` + `expected_listing_version`; versiya joriy bo‘lmasa `409 PROPOSAL_CHANGED`. Har muvaffaqiyatli mutatsiya `version = version + 1`. `If-Match`/ETag ishlatilmaydi (body yetarli, klient oddiy).

### 6. Pagination
Cursor: `?limit=1..100 (default 20)&cursor=…`; javob `meta.next_cursor` (oxirida `null`). Tartib har doim `(sort_key…, id)` — `id` ichki BIGINT, barqaror tie-breaker (§13). Cursor HMAC-SHA256 bilan imzolanadi va “scope” (endpoint + normallashtirilgan filtrlar)ga bog‘lanadi; boshqa so‘rovda → `400 INVALID_CURSOR`. Kalit `crypto.derive_subkey(settings.secret_key, "cursor-signing-key")` (ADR-0018). Offset pagination v2’da yo‘q.

### 7. Boshqa
- Vaqt/pul/id — ADR-0002/0003/0004.
- `request_id`: `X-Request-ID` (kelsa) yoki UUID; log va xato body’sida. **Wave 1 implementatsiyasi:** yagona v2 handler (`app.api.v2.web.domain_error_handler`, `app.main`da faqat `/api/v2` yo‘llariga) header bo‘lsa uni qaytaradi, bo‘lmasa `request_id` maydoni yo‘q; UUID yaratuvchi request-id middleware — A10a/A13 keyingi ish.
- Rate-limit: `429 RATE_LIMITED` + `Retry-After`.
- Obyekt ko‘rinishi: egasi/ishtirokchisi bo‘lmagan → 404.
- Legacy obyektni v2 orqali o‘zgartirish → `409 LEGACY_OBJECT_READ_ONLY`; v1 klient v2 obyektiga → `409 CLIENT_UPGRADE_REQUIRED` (ADR-0006).
- WebSocket va REST bir xil scope tekshiruvi (§17.6).

## Muqobillar
- **RFC 7807 problem+json** — standart, lekin klient helper’lari va v1 bilan ikki xil xato shakli.
- **Envelope’siz (faqat data)** — OpenAPI’da toza, lekin mobile-app http qatlami ikki rejimda ishlashi kerak.
- **Idempotency Redis’da** — spec §1: Redis o‘chishi bron/pulni yo‘qotmasligi kerak; PG tranzaksiyasi ichida bo‘lishi shart.

## Oqibatlar
- Klientlar har buyruq uchun UUID kalit yaratadi va retry’da qayta ishlatadi.
- `idempotency_records` jadvali (A3, `0031`) wave 1’da tayyor bo‘lishi kerak.
