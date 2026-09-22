# ADR-0002: v2 identifikatorlari — BIGINT PK + prefiksli opaque public id

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §13 (cursor tie-breaker), §14 (“Barcha ID’lar klient uchun opaque”), §15 (lock tartibi ID bo‘yicha)
**Kontrakt:** `app/contracts/ids.py`, testlar `tests/contracts/test_cursor_idempotency_ids.py`

## Kontekst
v1 jadvallari `int` autoincrement PK va API’da ochiq integer id (`/client/orders/{order_id}`) ishlatadi — ketma-ket, sanab chiqiladigan. Spec §15 lock’larni “ID bo‘yicha” tartiblaydi; §13 cursor tie-breaker talab qiladi. Docker Python 3.12 (`Dockerfile:1`) — stdlib’da UUIDv7 yo‘q (3.14’da bor); yangi dependency qo‘shish istalmaydi.

## Qaror
1. Har yangi v2 jadvali: `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` — FK, join, lock tartibi, cursor tie-breaker uchun. API’da **hech qachon** chiqmaydi.
2. Tashqi obyektlar: `public_id UUID NOT NULL UNIQUE`, ilovada `uuid.uuid4()` (`new_public_uuid`) bilan yaratiladi. DB default qo‘yilmaydi (SQLite unit testlari uchun ham ishlaydi).
3. API ko‘rinishi: `<prefix>_<26 belgili kichik harf base32>` (`bkg_…`, 30 belgi). Prefikslar `PublicIdPrefix` enum’ida.
4. Parse: noto‘g‘ri format, boshqa prefiks, katta harf, kanonik bo‘lmagan kodlash → `DomainError(NOT_FOUND)` (404), 400 emas — id tekshiruvi obyekt mavjudligini oshkor qilmaydi.
5. Legacy v1 id’lar o‘zgarmaydi. v2 legacy obyektni faqat read-only view orqali ko‘rsatadi (ADR-0006, Q4) va uni `order_number` bilan belgilaydi; integer id chiqmaydi.
6. `users` jadvaliga `public_id` qo‘shiladi (A1, migratsiya `0032`) — v2’da foydalanuvchi `usr_…`.
7. `tracking_points`, `ledger_entries`, `booking_allocations` kabi ichki jadvallarga `public_id` kerak emas.

## Muqobillar
| Variant | Nega tanlanmadi |
|---|---|
| UUID PK (v4) | Lock tartibi va indeks lokalligi yomonroq; FK hajmi 2x; spec §15 “ID bo‘yicha” tartib baribir ishlaydi, lekin v1 bilan aralash |
| UUIDv7 PK | Python 3.12 stdlib’da yo‘q → dependency yoki o‘z implementatsiyasi; vaqt sizadi |
| Hashids/Sqids (bigint obfuskatsiya) | Dependency; kriptografik emas; kalit sizsa hamma id ochiladi |
| Integer id’ni ochiq qoldirish | §14 ga zid, sanab chiqish |

## Oqibatlar
- Har v2 jadvalida qo‘shimcha unique indeks (16 bayt). Pilot hajmida ahamiyatsiz.
- Router qatlami `public_id → id` resolve qiladi; domen servislari ichki `id` bilan ishlaydi.
- Random UUID indeks yozish lokalligini pasaytiradi; `public_id` faqat qidiruv uchun, PK emas.
- Cursor ichida ichki `id` bo‘lishi mumkin (imzolangan, opaque, ADR-0005) — id sifatida ishlatilmaydi.
- `public_id` (UUIDv4) **sir emas**: ruxsat bermaydi. Share/tracking token’lari `crypto.new_secret_token` (≥128 bit `secrets.token_bytes`) bilan, bazada hash (ADR-0018).
