# ADR-0013: PostGIS qabul qilish va Postgres image almashtirish xavfi

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §1, §6.3, §7, §13, §19.1, §19.2 • **AC:** AC13, AC14–AC17, AC40

## Kontekst
Prod: `postgres:16-alpine` (`docker-compose.prod.yml:12`, HEAD), volume `pgdata`. PostGIS alpine rasmiy image’da yo‘q; `postgis/postgis` image’lari Debian (glibc). Spec geo matching (`ST_DWithin` geography), GiST indekslar va trip overlap uchun exclusion constraint talab qiladi (btree_gist). Migratsiya deploy’da `alembic upgrade head` bilan (`scripts/deploy.sh:27`).

## Qaror
1. **Extension’lar:** `postgis`, `btree_gist` — migratsiya `0030` (egasi A10a), `CREATE EXTENSION IF NOT EXISTS`. Downgrade extension’ni o‘chirmaydi.
2. **Image:** PostgreSQL major versiyasi 16 saqlanadi; PostGIS’li Debian-based image. A0b test muhiti `postgis/postgis:16-3.5` (digest bilan pin, `docker-compose.test.yml`) ishlatadi; prod tag/digest A10a tomonidan shu bilan moslab tekshiriladi. Major upgrade bir vaqtda qilinmaydi. `0030` — `CREATE EXTENSION IF NOT EXISTS`.
3. **Collation xavfi:** musl (alpine) va glibc bir xil locale nomi bilan matnni boshqacha tartiblaydi. Alpine’da yaratilgan data directory’ni glibc image’ga to‘g‘ridan-to‘g‘ri ulash text B-tree indekslarini (`uq_users_phone`, `users.username`, `ix_districts_city_lower_name_uz`, `cities.name_uz`, `order_number`) yaroqsiz qilishi mumkin — dublikatlar va topilmaydigan qatorlar.
4. **Ko‘chirish rejasi (egasi A10a, runbook):**
   - Afzal: **logical dump/restore** — `pg_dump -Fc` eski konteynerdan → yangi PostGIS konteynerida bo‘sh cluster (`initdb` locale aniq belgilangan, masalan `C.UTF-8` yoki `en_US.UTF-8` — A10a qaror qiladi va hujjatlaydi) → `pg_restore` → `ANALYZE`.
   - Tekshiruv: jadval qator sonlari, unique indekslar (`amcheck` `bt_index_check`), `alembic current == 20260803_0029`, v1 smoke testlari.
   - Muqobil (tavsiya etilmaydi): volume’ni ulab barcha text indekslarini `REINDEX DATABASE` — noto‘g‘ri tartib davrida yozuvlar kelishi xavfi.
   - Rollback: eski alpine volume o‘zgarishsiz saqlanadi.
5. **Tartib:** image almashtirish + dump/restore → keyin `0030`+ deploy. `0030` image almashtirishdan oldin prod’ga chiqmaydi (`BASELINE_AUDIT.md` R4). Bu ish UZ hostingga ko‘chish bilan birlashtirilishi mumkin (ADR-0011).
6. **Testlar:** PG testlari PostGIS image’da (A0b `docker-compose.test.yml`). SQLite testlari geo/PostGIS qismini import qilmaydi.
7. **Geometriya konvensiyasi:** saqlash `geometry(Point|LineString, 4326)`; masofa `::geography` bilan metrda; GiST indeks geometry’da va kerak bo‘lsa `geography` expression indeksida (§6.3).
8. **Image qayta pin (Q34):** production switch’dan oldin PostGIS image qo‘llab-quvvatlanadigan Debian bazasida (bookworm yoki trixie), PostgreSQL ≥ 16.15, digest bilan pin — prod va test (`docker-compose.test.yml`) bir xil. Egasi A10a (test compose — A0b bilan kelishib).
9. **DB rollari (Q36):** alohida migration/owner roli (sxema obyektlari egasi, `alembic` shu rol bilan) va `NOSUPERUSER` app roli (faqat DML, trigger’larni chetlab o‘ta olmaydi); PostGIS texnik oynasida joriy etiladi. Test stack’dagi superuser `elchi_test` faqat test uchun.

## Muqobillar
- **PostGIS’siz (Haversine Python’da)** — §6.3 ga zid, masshtabda sekin.
- **Alpine’da PostGIS’ni o‘zi build qilish** — texnik xizmat yuki, collation muammosi baribir keyin.
- **Managed PG** — K3 va hosting noaniq.

## Implementatsiya (A10a, wave 1.5 — Q34, Q36)
- **Image (Q34):** qo‘llab-quvvatlanadigan Debian’da PG 16 + PostGIS 3.5 kombinatsiyali rasmiy tag yo‘q (`postgis/postgis:16-3.5` — bullseye EOL, PG 16.9). Shu sababli lokal quriladigan `docker/postgis/Dockerfile`: `postgres:16.15-trixie@sha256:f1c3376c…df6f94` + `postgresql-16-postgis-3=3.5.3+dfsg-2.pgdg13+1` (build versiyalarni tekshiradi) → `elchi-postgis:16.15-3.5.3-trixie`. Test stack (`docker-compose.test.yml`) endi prod bilan **bir xil image va initdb argumentlari**.
- **Launch-gate bandi:** prod image hostda quriladi — registry’ga push qilinmaguncha **registry digest yo‘q** (faqat base digest + deploy logidagi image ID). Production switch’dan oldin registry’ga push va digest pin (COVERAGE_MATRIX §6).
- **Rollar (Q36) — og‘ish:** `elchi_owner` (NOSUPERUSER) migratsiyalarni bajaradi (`ELCHI_MIGRATION_DATABASE_URL`, `alembic/env.py`), api/worker — `elchi_app`. **Extension’lar (postgis, btree_gist) superuser egaligida qoladi** — PostGIS untrusted extension, owner roli uni yarata olmaydi; `scripts/db_roles.py` bootstrap superuser sifatida yaratadi. `0030` `CREATE EXTENSION IF NOT EXISTS` mavjud extension’da no-op.
- **Parallel migratsiya (BR #21):** `alembic/env.py` PostgreSQL’da `pg_advisory_lock(0x656C6368696D6967 "elchimig")` ostida ishlaydi.
- Rehearsal (`docs/ops/rehearsal/rehearse_postgis_switch.sh`): alpine 16.15 restore, musl→glibc 1 ta `lower()` indeks reindex, 0030→0044 `elchi_owner` sifatida, ikkinchi ishga tushirish no-op — A10a hisobotiga ko‘ra PASSED (integrator qayta ishga tushirmadi).

## Oqibatlar
- Texnik oyna (downtime) kerak; hajm kichik (pilot).
- `btree_gist` trip/vehicle overlap va commission policy overlap uchun ishlatiladi.
