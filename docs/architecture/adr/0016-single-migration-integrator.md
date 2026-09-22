# ADR-0016: Yagona migratsiya integratori va raqamlash

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §13, §18.1, §18.3 (“downgrade rollback emas”), §21.1 • **BR:** D12

## Kontekst
Head `20260803_0029`; tarixda parallel branch va avtogeneratsiya `ac62a9c9e9e2` (`BASELINE_AUDIT.md` §2.11). Wave 1’da bir necha agent sxema qo‘shadi. Spec §18.3: yangi moliyaviy yozuvdan keyin tiklash forward migration yoki tekshirilgan recovery orqali; downgrade rollback emas.

## Qaror
1. **Integrator:** A0a (mavjud bo‘lmasa A4). Agent migratsiyani faqat reyestrdagi raqam va `down_revision` bilan yozadi.
2. **Reyestr:** `DATA_MODEL.md` §5.
3. **Nomlash:** revision `YYYYMMDD_NNNN` (0030 dan uzluksiz), fayl `YYYYMMDD_NNNN_<module>_<slug>.py`.
4. **Qoidalar:**
   - Bitta head; merge migratsiyasi yo‘q.
   - Avtogeneratsiya qo‘lda ko‘rib chiqiladi; mavjud jadval/indeks o‘chirilmaydi (expand-only).
   - **`upgrade` idempotent:** `CREATE EXTENSION IF NOT EXISTS`, `CREATE TABLE/INDEX IF NOT EXISTS` yoki inspector bilan tekshiruv; backfill qayta ishga tushirilsa dublikat yo‘q; `CREATE OR REPLACE VIEW`.
   - **Downgrade rollback vositasi emas.** `downgrade` yozish ixtiyoriy va faqat dev/test qulayligi uchun; production’da bajarilmaydi; DoD talab qilmaydi. Tuzatish — forward migration.
   - Katta jadvallarda `CREATE INDEX CONCURRENTLY`, CHECK `NOT VALID` + `VALIDATE`.
   - PG-ga xos obyektlar `op.execute` bilan; SQLite unit testlari ularni talab qilmaydi, PG testlarida tekshiriladi.
5. **Tekshiruv (har wave, A0b PG infra’sida):** toza PostGIS DB’da `alembic upgrade head`; ikkinchi marta `upgrade head` no-op; `alembic check` diff’i bo‘sh; bitta head.
6. `0030` (extensions) prod image almashmaguncha production’ga chiqmaydi (ADR-0013).
7. H1 (wave 0.5) migratsiya talab qilmaydi; kerak bo‘lib qolsa integrator navbatdagi bo‘sh raqamni beradi va reyestr qayta tartiblanadi.

## Muqobillar
- Modul bo‘yicha `branch_labels` — merge muammosini takrorlaydi.
- Downgrade’ni rollback deb test qilish — §18.3 ga zid, soxta xavfsizlik hissi.

## Extension va rollar (A10a, wave 1.6 — Q36)
- Extension’lar (`postgis`, `btree_gist`) **superuser egaligida**; migratsiyalar faqat `CREATE EXTENSION IF NOT EXISTS` bajarishi mumkin (mavjud extension’da no-op). `ALTER EXTENSION … UPDATE` faqat `scripts/db_roles.py --update-extensions` orqali (bootstrap superuser, texnik oynada).
- Migratsiyalar `elchi_owner` (NOSUPERUSER) sifatida `ELCHI_MIGRATION_DATABASE_URL` bilan; `deploy.sh` migratsiyadan keyin `db-roles`ni qayta ishga tushiradi (yangi obyektlar egaligi va app roli grant’lari).
- SECURITY DEFINER funksiyali migratsiyalar (masalan 0047) owner/migrator roli bilan bajariladi.

## Launch-gate bandi: revision lineage (Q50, 14.09.2026)
- Hozir: DB head’dan eskiroq image’ga rollback’da readiness `migrations: unknown` → 503 — **qabul qilingan** (monitoring toqat qiladi; ADR-0012 readiness).
- Launch’dan oldin: har migratsiya `upgrade()` oxirida (yoki `alembic/env.py` hook’i) `schema_revision_lineage (revision PK, down_revision, applied_at)` jadvaliga yozadi; eski image readiness tekshiruvi DB head’ni o‘z skriptlarida topa olmasa, lineage bo‘ylab o‘z head’iga yetib borsa `ahead` (200 `degraded`) deb biladi. Dizayn va raqam — A0a (reyestr) + A10a (readiness), keyingi wave; COVERAGE_MATRIX G12.

## Oqibatlar
- Rollback rejasi flag + forward-fix + restore runbook (A10a/A10b).
