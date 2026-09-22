# ADR-0004: Vaqt — timestamptz UTC, offset majburiy, Asia/Tashkent displey

**Holat:** Accepted (Q9, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §5.2, §6.3, §10.4, §14 • **AC:** AC15, AC18, AC27, AC28, AC44
**Kontrakt:** `app/contracts/timeutil.py`, `app/contracts/dto.py` (`UtcDateTime`), `tests/contracts/test_timeutil.py`

## Kontekst
`TimestampMixin` aware (`app/models/common.py:8-18`), lekin 10 ta legacy ustun naive (`BASELINE_AUDIT.md` §2.7). Servislar `datetime.now(timezone.utc)` yozadi. Spec §14: ISO 8601 offset bilan, DB’da UTC, UI’da `Asia/Tashkent`; “ertaga 13:00” aniq sana bo‘lib keladi.

## Qaror
1. Barcha yangi ustunlar `timestamptz`. Ilovada faqat aware datetime; `utc_now()`.
2. API kirishi: offset’siz yoki faqat sana → `400 VALIDATION_ERROR` (Pydantic `AwareDatetime`/`parse_iso_datetime`). Qiymat UTC’ga normallashtiriladi.
3. API chiqishi: UTC, `Z` suffiks (`to_iso_utc`). Listing/trip’da alohida `timezone` maydoni (`"Asia/Tashkent"`) — klient displey uchun.
4. Displey zonasi `Asia/Tashkent`; IANA bazasi image’da bo‘lmasa qat’iy `+05:00` fallback (O‘zbekistonda DST yo‘q). Server matn (SMS/push) shu helper bilan formatlaydi.
5. Intervallar yarim ochiq `[start, end)` (`windows_intersect`); PG’da `tstzrange(start, end, '[)')`.
6. GPS: `captured_at` (qurilma) va `received_at` (server) alohida; `captured_at` kelajakda > 2 daqiqa bo‘lsa shubhali (§10.4) — A6.
7. **Legacy naive ustunlar:** 
   - A10a production’da `SHOW timezone;` va app sessiyasi TimeZone’ini tekshiradi va natijani runbook’ka yozadi.
   - UTC tasdiqlansa, A10b migratsiyasi `ALTER COLUMN … TYPE timestamptz USING col AT TIME ZONE 'UTC'` (jadval qayta yoziladi; kichik jadvallar, texnik oynada).
   - **Q9:** konvertatsiya wave 5 da (A10b), avval v1 moslik tekshiruvi: muzlatilgan klientlar offset’li qiymatni to‘g‘ri ko‘rsatadimi; bo‘lmasa v1 serializer naive ko‘rinishni saqlaydi.
   - Konvertatsiyagacha legacy qiymat o‘qilganda `legacy_naive_as_utc`.

## Muqobillar
- **Tashkent lokal vaqtni saqlash** — kelajak DST/zona o‘zgarishi va koridorlar bo‘yicha xato; spec §14 ga zid.
- **Offset’siz inputni Tashkent deb qabul qilish** — yashirin taxmin; spec “aniq sana” talab qiladi.

## Oqibatlar
- Klient “ertaga 13:00”ni `2026-09-14T13:00:00+05:00` qilib yuboradi.
- `tzdata` dependency qo‘shilmaydi (fallback bor).
- Legacy konvertatsiya — alohida tasdiqlanadigan qadam.
