# ADR-0012: Outbox, hodisalar, worker va Redis roli

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §1, §6.6, §10.3, §15, §16, §19 • **AC:** AC33, AC34
**Kontrakt:** `app/contracts/events.py`, `EventType`

## Kontekst
Joriy tizimda xabarnoma tranzaksiya ichida `notifications` qatori (`app/services/notification_service.py`), push/worker/Redis/WebSocket yo‘q (`BASELINE_AUDIT.md` §2.5). Uvicorn 2 worker (`Dockerfile:39`).

## Qaror
### Outbox
1. `outbox_events(id, event_id UUID UNIQUE, event_type, aggregate_type, aggregate_id BIGINT, aggregate_public_id, aggregate_version, occurred_at, payload JSONB, attempts, next_attempt_at, dispatched_at, last_error, dead_lettered_at)`; partial indeks `(next_attempt_at) WHERE dispatched_at IS NULL AND dead_lettered_at IS NULL`. Jadval va `platform.enqueue_event(session, EventEnvelope)` — A3 (wave 1), dispatch — A7.
2. Domen buyrug‘i hodisani **o‘sha tranzaksiyada** yozadi. Payload `EventEnvelope` validatsiyasidan o‘tadi: **har event turi uchun allowlist** (`EVENT_PAYLOAD_ALLOWLIST`), faqat skalyar qiymatlar; ro‘yxatda yo‘q kalit, ichma-ich obyekt yoki float rad (BR D17). Yangi kalit — kontrakt o‘zgarishi.
3. `consumer_receipts(consumer, event_id)` unique — consumer dublikatni yo‘qotadi (at-least-once).

### Worker
4. Jarayon: `python -m app.worker` (shu image). Tsikl: `SELECT … FOR UPDATE SKIP LOCKED LIMIT n` → consumer’lar → `dispatched_at` yoki `attempts+1`, eksponensial backoff (1m, 5m, 15m, 1h, 6h), 10 urinishdan keyin `dead_lettered_at` + operator navbati.
5. Rejalashtirilgan ishlar (shu worker): listing/proposal expiry, awaiting_pickup o‘tkazish, 24 soat tasdiqlash oynasi → operator navbati, hold eskalatsiyasi 48 soat (avtomatik capture/release **yo‘q**), tracking stale, GPS partition yaratish/retention, idempotency/receipt tozalash, kechki ledger reconciliation. Har ish idempotent va `pg_try_advisory_lock` bilan bitta nusxada.
6. Celery/APScheduler kiritilmaydi — PG navbat va oddiy tsikl yetarli (dependency yo‘q).

### Redis
7. Redis — **durable emas**: oxirgi ishonchli GPS nuqta cache’i, WebSocket fan-out (Pub/Sub, 2+ uvicorn worker orasida), rate-limit hisoblagichlari. Bron, pul, outbox, idempotency Redis’da **saqlanmaydi**. Redis o‘chsa: GPS snapshot PG’dan, WS o‘rniga HTTP polling 10–15 s, rate-limit PG/konservativ fallback; `/health/ready` `degraded` qaytaradi (AC34). Readiness semantikasi (BR N1, Q32): 503 faqat DB yo‘q, DB head koddan orqada yoki noma’lum revision; DB head kod head’ining ma’lum avlodi → 200 `degraded` (`migrations: ahead`); Redis → `degraded`; production invariant buzilishi → `production_invariants: fail` + alert, pul buyruqlari `503 PRODUCTION_INVARIANTS_FAILED`.
8. Python client `redis` paketi — A10a/A6 aniq versiya bilan pin qiladi (yangi dependency, shu ADR asosida).

### Push va real vaqt
9. Kanal adapterlari: in-app (`notifications`), Web Push (mobile-app, VAPID) — A7; FCM (Android) — keyin Android dasturchi bilan. Push payload faqat `event_type`, `aggregate_id`, qisqa matn kaliti.
10a. **Auditoriya (BR N2, Q16):** har yetkazishdan oldin `events.payload_for_audience(event_type, payload, audience)` — `EVENT_AUDIENCES` bo‘yicha `wallet.*` va `commission.*` faqat driver va staff’ga; `commission.policy.*` faqat staff; mijoz nusxasidan `CLIENT_REDACTED_PAYLOAD_KEYS` (`commission_status`, `fee_bps`, summalar) olib tashlanadi; `booking.status_changed` (`machine=commission`) mijozga yuborilmaydi. A7 consumer’lari va `GET /api/v2/events` shu funksiyadan o‘tadi.
10. WebSocket: `GET /api/v2/ws` (A6 gateway), REST bilan bir xil scope; qayta ulanishda `GET /api/v2/events?after=cursor` + snapshot (§15).
11. Dublikat nazorati: foydalanuvchi + `dedup_key` (masalan yo‘nalish+sana) oynasida bitta push (§6.6).

## Muqobillar
- **Redis Streams/Celery navbat** — durable kafolat PG tranzaksiyasi bilan bog‘lanmaydi; §15 ga zid.
- **Tranzaksiya ichida push** — §15 taqiqlaydi.
- **Kafka** — §1 rad etadi.

## Readiness va rollback (Q32, Q50, Q57 — 15.09.2026)
- DB head kod head’ining ma’lum avlodi → `/health/ready` 200 `degraded`, `migrations: ahead` (Q32). Kod DB head’ni tanimasa (eski image’ga rollback) → `unknown` → **503; launch’gacha qabul qilingan** (Q50), monitoring toqat qiladi.
- **Launch gate (Q50):** migratsiyalar revision lineage (revision → parent) jadvaliga yozadi; eski image lineage bo‘ylab o‘z head’ini topsa `ahead` deb biladi. Dizayn — ADR-0016 “Launch-gate bandi”, egalari A0a (reyestr) + A10a (readiness); COVERAGE_MATRIX G12.
- Q28 tasdiqlanmagan seed stavka eslatmasi (`notices: unconfirmed_seed_policy_active`) readiness’da faqat ma’lumot — hech qachon 503 emas (Q57). Q56 Q48 gate holati `production_invariants` tarkibida.

## Oqibatlar
- Worker crash’dan keyin yuborish davom etadi (AC33); PG testida isbotlanadi.
- Outbox lag/retries metrikalari (§19.2) — A13.
