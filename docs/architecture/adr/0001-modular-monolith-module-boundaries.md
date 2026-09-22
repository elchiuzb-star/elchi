# ADR-0001: Modular monolith, modul chegaralari va kod egaligi

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §1, §12, §15, §21.1

## Kontekst
Joriy backend — bitta FastAPI ilova: `app/models` (19 model), `app/services` (18 servis), `app/api/v1` (20 router) (`BASELINE_AUDIT.md` D9). Servislar bir-birining jadvallarini erkin o‘zgartiradi (masalan `order_service.select_driver_for_order` bid, offer, notification, audit yozadi — `app/services/order_service.py:604-700`). Spec §1 bitta kod bazasi, API + worker, Kubernetes/Kafka yo‘q; §12 modul egaligi; §15 bitta relational tranzaksiya.

## Qaror
1. Bitta repository, bitta Docker image, ikki jarayon: `api` (uvicorn) va `worker` (`python -m app.worker`, ADR-0012).
2. Yangi kod `app/modules/<name>/` ostida. Modullar va egalari:

| Modul | Jadvallar | Tashqi API (`service.py`) | Egasi |
|---|---|---|---|
| `platform` | `idempotency_records`, `outbox_events`, `consumer_receipts` | `acquire_idempotency`, `store_response`, `enqueue_event` | A3 (jadval/API), A7 (dispatch) |
| `identity` | `user_roles`, `users.public_id` (legacy `users` A1 bilan kelishib) | `get_capabilities`, `ensure_driver_eligible`, `lock_user_eligibility` | A1 |
| `geo` | regions, settlements, corridors, stops, route_versions, routing cache, `feature_flag_*` | `find_candidates`, `evaluate_route_match`, `is_flag_enabled` | A2 |
| `trips` | vehicles, trips, stop occurrences, segment resources | `check_capacity`, `reserve`, `release`, `lock_trip` | A1 |
| `marketplace` | listings, details, proposal threads/versions, saved searches (A5) | `publish_listing`, `submit_proposal`, `counter`, `lock_listing` | A1 (+A5) |
| `wallet` | wallet accounts, holds, ledger, topups, commission policies | `hold_fee`, `capture_fee`, `release_fee`, `reverse_fee`, `quote_fee` | A3 |
| `bookings` | bookings, allocations, proofs, cash receipts, amendments, no-show reviews, custody cases | `accept_proposal`, `cancel_booking`, `apply_action`, `lock_booking` | A4 |
| `tracking` | sessions, points, receipts, grants | `ingest_batch`, `read_latest`, `revoke_grants_for_booking` | A6 |
| `communications` | device tokens, notification deliveries, chat | `deliver`, `acknowledge` | A7 |
| `trust_support` | ratings v2, disputes v2, blocks, reports, fraud signals | `open_dispute`, `resolve`, `reputation` | A12 |
| `operations` | share links, rollout, KPI read models | vakolatli admin API | A13 |

3. Qoidalar: modul boshqa modul jadvaliga faqat uning `service.py` orqali ta’sir qiladi; ORM relationship modul chegarasidan o‘tmaydi (FK bor, relationship yo‘q); bir `Session` ulashiladi va tranzaksiyani chaqiruvchi (router yoki A4 orkestratori) boshqaradi — domen funksiyasi `commit` qilmaydi.
4. v2 router’lar `app/api/v2/__init__.py`da yig‘iladi; modul `api.py` o‘z `APIRouter`ini eksport qiladi. `app/main.py`ga ulash — H0 bo‘shatgandan keyin integrator.
5. Modellar `app/modules/__init__.py` orqali import qilinadi, `alembic/env.py` uni import qiladi (integrator o‘zgartiradi).
6. Legacy `app/services/` o‘z joyida; v1 → v2 adapterlari faqat A10b rejasiga ko‘ra.

## Muqobillar
- **Mikroservislar** — spec §1 rad etadi; atomar accept (hold + allocation) taqsimlangan tranzaksiya talab qiladi.
- **Mavjud `app/services`ga qo‘shish** — egalik va parallel wave’lar uchun fayl to‘qnashuvi; §12 ga zid.
- **Modul bo‘yicha alohida DB schema (PG schema)** — hozircha foyda kam, migratsiya murakkabligi oshadi; keyin ko‘rib chiqiladi.

## Oqibatlar
- Parallel agentlar alohida papkalarda ishlaydi; umumiy fayllar (`app/api/v2/__init__.py`, `alembic/env.py`, `app/modules/__init__.py`) faqat integratorda.
- Chegara intizomi kod review’da (BR) tekshiriladi; avtomatik import-linter keyin qo‘shilishi mumkin (hozir dependency qo‘shilmaydi).
- Jarayonlar alohida scale qilinmaydi — pilot uchun yetarli (§19.1).
