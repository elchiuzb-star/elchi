# ELCHI — Baseline testlar va PostgreSQL/PostGIS test infratuzilmasi (2-bosqich, A0b)

Sana: 2026-09-13. Commit: `4f468c3` (HEAD, `main`). Muallif: A0b (test-infratuzilma).

Bu hujjat uch narsani qayd etadi: (1) hozirgi kodning o‘zgartirilmagan holatdagi test natijalari (baseline), (2) spec §21.2 talab qilgan PostgreSQL 16 + PostGIS test muhiti va uning dizayni, (3) production DB image’ini almashtirish xavfi (§6). Barcha raqamlar haqiqatda ishga tushirilgan buyruqlardan olingan; ishga tushirilmagan narsa "o‘tdi" deb yozilmagan.

**Atamalar.** Bu hujjatda **K4-xavf** = prod’dagi `postgres:16-alpine` (musl libc) data katalogini glibc asosidagi `postgis/postgis` image’iga ko‘chirishda matn collation’i o‘zgarib, B-tree indekslar jim buzilishi xavfi (§6). Bu `AGENTS.md` §3 dagi foydalanuvchi qarorlari raqamlashidan (K1, K2, K3, K5…) **mustaqil** ichki yorliq. Muzlatilgan papkalar faqat `android-app/` va `frontend/`; `mobile-app/` muzlatilmagan — u 2-bosqich klienti (M4/S1).

---

## 1. Muhit

| Komponent | Qiymat |
|---|---|
| OS | Windows 11 Pro 10.0.26200 |
| Python (asosiy) | CPython 3.14 (`py`), global site-packages: FastAPI 0.115.12, SQLAlchemy 2.0.41, Alembic 1.16.2, psycopg 3.3.4, pytest 8.4.0, anyio 4.14.0 |
| Python (Dockerfile’ga mos) | CPython 3.12.13 (uv), scratchpad’dagi venv, `uv pip install -r requirements.txt` (anyio 4.15.1 tranzitiv ravishda o‘rnatildi) |
| Node / npm | Node 24, npm 11.9.0 |
| Docker | Docker Desktop, Engine 29.6.2 |
| Test DB image | `postgis/postgis:16-3.5@sha256:94146ac3…` → PostgreSQL **16.9** (Debian bullseye, glibc 2.31), PostGIS **3.5.2**, amcheck 1.3 |
| Redis image | `redis:7.4.5@sha256:90e7a336…` |
| Prod DB image (taqqoslash uchun) | `postgres:16-alpine` → PostgreSQL **16.15**, musl libc |

**Izolyatsiya.** Baseline boshqa agentlarning parallel tahrirlaridan ta’sirlanmasligi uchun HEAD’dan alohida detached worktree’da ishga tushirildi (`git worktree add --detach <scratchpad>/baseline HEAD`). Worktree’da untracked fayllar (masalan `.env`) yo‘q; asosiy repo’da ham `.env` yo‘q, shuning uchun natijaga lokal env ta’sir qilmagan. Ish tugagach `git worktree remove --force` qilindi, `git worktree list` faqat asosiy daraxtni ko‘rsatadi.

---

## 2. Backend baseline (pytest, SQLite in-memory)

Buyruq (worktree ildizida):

```bash
py -m pytest -p no:cacheprovider -rfEs --durations=5
<venv312>/Scripts/python.exe -m pytest -p no:cacheprovider -rfEs --durations=5
```

| Interpretator | Yig‘ilgan | Passed | Failed | Skipped | Errors | Warnings | Vaqt |
|---|---:|---:|---:|---:|---:|---:|---:|
| CPython 3.14 | 321 | 310 | 11 | 0 | 0 | 276 | 69.0 s |
| CPython 3.12.13 | 321 | 310 | 11 | 0 | 0 | 1 | 62.7 s |

Eslatma: vazifada "~246 test" deyilgan, haqiqiy yig‘ilgan son **321** (23 fayl, parametrize bilan).

Warnings:
- 3.14: 276 ta `DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated` (FastAPI 0.115 ichida, Python 3.16’da olib tashlanadi). Production 3.12’da ishlaydi, shuning uchun hozir xavf emas.
- 3.12: 1 ta `anyio.abc.BlockingPortal alias is deprecated` (starlette testclient + anyio 4.15.1). `anyio` pin qilinmagan tranzitiv paket.

### 2.1 Muvaffaqiyatsiz testlar va sababi

Ikkala interpretatorda ham aynan bir xil 11 ta test yiqiladi; sabab interpretator emas, **testlar koddagi ikki o‘zgarishdan keyin yangilanmagan** (mahsulot kodi xatosi emas, test qarzi):

| # | Test | Belgi | Asosiy sabab |
|---|---|---|---|
| 1 | `test_auth.py::test_client_login_flow` | `'1234' == '12345'` | R1 |
| 2 | `test_auth.py::test_non_staff_cannot_update_full_name_through_auth_me` | verify-otp `12345` bilan 400 | R1 |
| 3 | `test_auth.py::test_driver_login_flow_creates_driver_profile` | 400 | R1 |
| 4 | `test_auth.py::test_existing_driver_missing_profile_is_repaired_on_verify` | 400 | R1 |
| 5 | `test_auth.py::test_client_login_flow_creates_client_profile` | `user is None` (verify o‘tmadi) | R1 |
| 6 | `test_auth.py::test_otp_cooldown_send_limit_expiry_used_and_attempts` | `len(dev_otp) == 5` → 4 | R1 |
| 7 | `test_auth.py::test_used_otp_and_too_many_attempts_are_rejected` | 400 | R1 |
| 8 | `test_auth.py::test_existing_staff_can_login_but_blocked_inactive_deleted_cannot` | staff `request-otp` → 400 | R2 |
| 9 | `test_auth.py::test_token_types_refresh_rotation_and_logout` | `KeyError: 'access_token'` | R1 |
| 10 | `test_stage20_final_qa.py::test_full_mvp_happy_path_and_database_consistency` | helper `dev_otp == "12345"` | R1 |
| 11 | `test_stage20_final_qa.py::test_stage20_core_permission_regressions` | helper `dev_otp == "12345"` | R1 |

- **R1** — commit `419ee5e` ("Switch OTP to 4 digits…") `app/core/config.py`da `otp_length 5→4`, `dev_mock_otp "12345"→"1234"`, `mock_otp_code "00000"→"0000"` qildi, lekin `tests/test_auth.py` va `tests/test_stage20_final_qa.py` hali 5 xonali `"12345"` kutadi.
- **R2** — commit `2ba7f0b` ("Replace staff OTP login with username and password") `request_otp` ichida staff rollari uchun `400 PASSWORD_LOGIN_REQUIRED` qaytaradi (ataylab); test 8 hali staff OTP login’ini kutadi. Yangi xulq `tests/test_staff_password_login.py`da qamrab olingan (u o‘tadi).

Tavsiya (A0b egaligida emas, shuning uchun o‘zgartirilmadi): testlar `settings.dev_mock_otp`/`settings.otp_length`dan o‘qisin; test 8 staff uchun 400 kutib, login’ni `/auth/staff-login` orqali tekshirsin. Wave 1’dan oldin yashil baseline uchun shu 11 test egasi tomonidan tuzatilishi kerak.

### 2.2 SQLite suite nimani tekshirmaydi

- Har bir test fayli `Base.metadata.create_all` bilan o‘z SQLite engine’ini quradi — **Alembic migratsiyalari hech qachon ishga tushmaydi**.
- `20260626_0024_make_audit_logs_immutable` faqat `postgresql` dialektida trigger yaratadi; SQLite’da no-op. DB darajasidagi immutability faqat `tests/pg`da tekshiriladi.
- `FOR UPDATE`, row lock, `SKIP LOCKED`, partial unique index, exclusion constraint, PostGIS — SQLite’da yo‘q yoki boshqacha. Shuning uchun AC06–AC09, AC19–AC21, AC41 testlari `tests/pg`da yoziladi.

---

## 3. Alembic grafi (DB’siz, script darajasida)

```bash
py -m alembic heads      # 20260803_0029 (head)
py -m alembic branches
py -m alembic history
```

- **Yagona head:** `20260803_0029` (users.username / password_hash).
- 28 ta revision. Branchpoint va mergepoint’lar:

```text
20260618_0014 (branchpoint)
 ├─> ac62a9c9e9e2 "First migration" (autogenerate nomi, 2 ta unique/constraint tuzatish)
 └─> 20260620_0015 (branchpoint, add order coordinates)
       ├─> 20260622_0016 (mergepoint: 0015 + ac62a9c9e9e2)
       └─> 20260622_0020 → 20260622_0021
20260622_0021 + 20260622_0016 → 20260625_0022 (mergepoint)
20260625_0022 → 0023 → 0024 → 0025 → 0026 → 0027 → 0028 → 0029 (head)
```

- Revision raqamlarida 0017–0019 yo‘q (bo‘shliq, xato emas).
- `ac62a9c9e9e2` nomlash konvensiyasiga mos emas; yangi migratsiyalar `YYYYMMDD_NNNN` formatini davom ettirishi kerak.

---

## 4. mobile-app build natijasi

Worktree ichida (`node_modules` worktree bilan birga o‘chirildi):

| Buyruq | Natija | Vaqt |
|---|---|---|
| `npm ci` | exit 0; "5 vulnerabilities (1 moderate, 3 high, 1 critical)" | 36 s |
| `npm run build` (`tsc --noEmit && vite build`, vite 6.4.3) | exit 0; 1730 modul; `index-*.js` 650.85 kB (gzip 155.38 kB) | 25 s |
| `npm run lint` (`tsc --noEmit`) | exit 0 | — |
| `npm audit --omit=dev` | 4 (1 moderate, 3 high): `baseline-browser-mapping`, `browserslist`, `nanoid`, `postcss` — hammasi `npm audit fix` bilan tuzatiladi | — |

Ogohlantirishlar: Vite "Some chunks are larger than 500 kB" (code-splitting yo‘q). Alohida typecheck/eslint script’i yo‘q; `lint` = `tsc --noEmit`.

**Lock fayl (baseline paytida):** `package-lock.json` va `pnpm-lock.yaml` (lockfileVersion 9.0) ikkalasi ham bir xil commit’da (`cbf2875`, "clean import") qo‘shilgan va shundan beri o‘zgarmagan edi. README `npm install`ni ko‘rsatadi va `npm ci` `package-lock.json` bilan toza o‘tdi. Baseline worktree’da hech narsa o‘zgartirilmadi. Keyingi qaror va o‘zgarishlar — §4.1.

### 4.1 Wave 0.5: npm yagona paket menejeri (foydalanuvchi qarori 11)

1. **Havolalar tekshiruvi** (`node_modules`dan tashqari butun repo, `pnpm` bo‘yicha qidiruv). `mobile-app/` ichidagi README, `vite.config.ts`, `tsconfig.json`, `.npmrc`, `.gitignore`, `package.json` va `scripts/`da pnpm fayllariga havola yo‘q. Tahrirlanmagan qoldiq eslatmalar (boshqa egalar yoki tarix):
   - `docs/architecture/BASELINE_AUDIT.md:110` — "Ikki lockfile …" (A0a; endi eskirgan);
   - `docs/architecture/adr/0010-client-strategy-openapi-typescript.md:21` — bitta menejer tanlash bandi (A0a; qaror bajarildi);
   - `docs/mobile_app_stage.md:1304-1308` — "or if pnpm is used: pnpm install" (1-bosqich hujjati);
   - `.gitignore:24` — `.pnpm-store/` (zararsiz);
   - `frontend/package.json:93` — `"pnpm"` bloki (muzlatilgan `frontend/`, `mobile-app`ga aloqasi yo‘q).
2. `mobile-app/pnpm-lock.yaml` va `mobile-app/pnpm-workspace.yaml` o‘chirildi. `package-lock.json` yagona lock.
3. `npm audit fix` (`--force`siz): `package.json` o‘zgarmadi; `package-lock.json`da 9 ta tranzitiv paket yangilandi, **major bump yo‘q**:

   | Paket | Oldin → keyin | Advisory / severity | Turi |
   |---|---|---|---|
   | `tar` | 7.5.16 → 7.5.22 | critical | dev (`@tailwindcss/vite` zanjiri) |
   | `postcss` | 8.5.15 → 8.5.28 | high | `vite` orqali (build vaqti) |
   | `nanoid` | 3.3.12 → 3.3.19 | high | `postcss` orqali (build vaqti) |
   | `browserslist` | 4.28.2 → 4.28.9 | high | `@vitejs/plugin-react`/babel orqali (build vaqti) |
   | `baseline-browser-mapping` | 2.10.38 → 2.11.23 | moderate | `browserslist` orqali (build vaqti) |
   | `caniuse-lite`, `electron-to-chromium`, `node-releases`, `update-browserslist-db` | patch/minor | advisory yo‘q, birga yangilandi | build vaqti |

   Eslatma: `vite` va `@vitejs/plugin-react` `package.json`da `dependencies` ichida turgani uchun npm ularning zanjirini "runtime" (dev=false) deb hisoblaydi; amalda ular faqat build vaqtida ishlaydi va brauzer bundle’iga kirmaydi.
4. Natija: `npm audit` → **0 vulnerabilities**. Qolgan advisory yo‘q.

### 4.2 Wave 0.5 tekshiruvi (`mobile-app/`, asosiy daraxt)

| Buyruq | Natija |
|---|---|
| `npm ci` | exit 0; 103 paket; "found 0 vulnerabilities" |
| `npm run build` | exit 0; 1730 modul; `index-*.js` 650.85 kB (gzip 155.38 kB) — bundle baseline bilan bir xil hash; 500 kB chunk ogohlantirishi qoladi |
| `npm run lint` (`tsc --noEmit`) | exit 0 |

`dist/` tekshiruvdan keyin o‘chirildi; `node_modules/` (gitignore’da) qoldirildi.

---

## 5. PostgreSQL + PostGIS test infratuzilmasi

### 5.1 Fayllar

| Fayl | Vazifa |
|---|---|
| `docker-compose.test.yml` | `name: elchi-test`; `postgis` (tag+digest pin, `127.0.0.1:45432`, maintenance DB `elchi_test`, tmpfs data, healthcheck, fsync/sync-commit/full_page_writes off, `max_connections=300`) va `redis` (7.4.5, tag+digest, `127.0.0.1:36379`, persistence yo‘q; wave 0.5’da 56379 dan ko‘chirildi — Windows `excludedportrange` 56351–56450 ni band qilgan edi). Doimiy volume yo‘q, faqat lokal test login/parol. Postgis porti (Q76, wave-2): 55432 dan 45432 ga ko‘chirildi — Windows `excludedportrange` 55401–55800 ni band qilgan edi. Port tanlashdan oldin `netsh interface ipv4 show excludedportrange protocol=tcp` bilan tekshirib, 49152 dan past va ro‘yxatda yo‘q port tanlash kerak. |
| `tests/pg/conftest.py` | `pg_server`, `pg_template`, `pg_db`, `pg_empty_db` fixture’lari; `validate_test_pg_url` xavfsizlik guard’i; `run_alembic`, `script_heads` helper’lari |
| `tests/pg/test_url_guards.py` | guard va skip/fail siyosati testlari (`pg` marker’siz — Docker’siz ham oddiy suite’da ishlaydi) |
| `tests/pg/harness.py` | `run_concurrently(n, fn, engine=...)` → `ConcurrencyReport` |
| `tests/pg/test_migrations_smoke.py` | Alembic PG16’da, trigger, ORM drift |
| `tests/pg/test_postgis_smoke.py` | PostGIS geography/ST_DWithin/GiST |
| `tests/pg/test_concurrency_harness.py` | lock isboti va negative control |
| `scripts/test-pg.ps1`, `scripts/test-pg.sh` | stack’ni ko‘tarish, healthy kutish, `pytest -m pg tests/pg`, ixtiyoriy teardown |
| `pyproject.toml` | faqat `markers = ["pg: ..."]` qo‘shildi |

Yangi dev dependency kerak bo‘lmadi (`psycopg`, `SQLAlchemy`, `alembic`, `pytest` allaqachon `requirements.txt`da).

### 5.2 Windows’da ishga tushirish

Docker Desktop ishlayotgan bo‘lishi kerak.

PowerShell (5.1 va 7):

```powershell
.\scripts\test-pg.ps1                      # up --wait, pytest -m pg tests/pg, stack qoladi
.\scripts\test-pg.ps1 -Down                # oxirida docker compose down -v
.\scripts\test-pg.ps1 -- -k harness -x     # qo‘shimcha pytest argumentlari
$env:PYTHON = "C:\...\venv\Scripts\python.exe"; .\scripts\test-pg.ps1
```

Git Bash:

```bash
scripts/test-pg.sh
scripts/test-pg.sh --down
scripts/test-pg.sh -- -k migrations
PYTHON=/c/path/venv/Scripts/python.exe scripts/test-pg.sh
```

Qo‘lda:

```bash
docker compose -f docker-compose.test.yml up -d --wait
ELCHI_TEST_PG_REQUIRED=1 ELCHI_TEST_PG_URL=postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test py -m pytest -m pg tests/pg
docker compose -f docker-compose.test.yml down -v
```

Muhit o‘zgaruvchilari:

| O‘zgaruvchi | Default | Ma’nosi |
|---|---|---|
| `ELCHI_TEST_PG_URL` | `postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test` | CREATE DATABASE huquqi bor maintenance DB. Faqat bir martalik server! |
| `ELCHI_TEST_PG_REQUIRED` | yo‘q (skriptlar `1` qo‘yadi) | `1`: server ulanmasa har `pg` test **ERROR** bo‘ladi (skip emas) |
| `ELCHI_TEST_PG_ALLOW_REMOTE` | yo‘q | `1`: localhost/127.0.0.1/::1 dan boshqa host’ga ruxsat (faqat bir martalik server uchun) |
| `ELCHI_TEST_PG_KEEP` | yo‘q | `1` bo‘lsa yaratilgan DB’lar debug uchun o‘chirilmaydi |
| `PYTHON` | `py` → `python3` → `python` | skriptlar ishlatadigan interpretator |

**Skip va fail siyosati:**

| Holat | `ELCHI_TEST_PG_REQUIRED` yo‘q | `ELCHI_TEST_PG_REQUIRED=1` (skriptlar) |
|---|---|---|
| Server ulanmaydi (3 s timeout) | har `pg` test **skipped**, sabab: `PostgreSQL not reachable at …` | har `pg` test **error**: `[ELCHI_TEST_PG_REQUIRED=1] PostgreSQL not reachable at …`, exit ≠ 0 |
| Guard buzilgan (remote host / DB nomi) | **error** `[tests/pg safety guard] …` | **error** (xuddi shunday) |
| PG major ≠ 16 yoki PostGIS yo‘q | **error** | **error** |

Ulanish sessiyada bir marta sinaladi (session fixture natijasi keshlanadi), shuning uchun barcha testlar bitta bir xil xabarni ko‘rsatadi.

**Xavfsizlik guard’i** (`validate_test_pg_url`, har doim yoqilgan): testlar DB yaratadi va `DROP DATABASE … WITH (FORCE)` qiladi, shuning uchun:
- host (URL authority va `?host=`/`?hostaddr=` query parametrlari) faqat `localhost`, `127.0.0.1`, `::1` bo‘lishi mumkin; aks holda `ELCHI_TEST_PG_ALLOW_REMOTE=1` aniq qo‘yilishi shart; host ko‘rsatilmagan URL rad etiladi;
- URL’dagi maintenance DB nomida alohida `test` tokeni bo‘lishi shart (`elchi_test`, `test`, `elchi-test-2` — ha; `postgres`, `elchi`, `elchi_prod`, `contest`, `latest` — yo‘q). `ALLOW_REMOTE` bu qoidani yumshatmaydi;
- faqat PostgreSQL URL; yaratish/o‘chirish faqat `elchi_pgtest_` prefiksli DB’larga ruxsat etiladi (kodda qo‘shimcha assert).

**DoD hisobotlari uchun qoida.** "N passed" umumiy yig‘indisi yetarli emas, chunki PG yo‘q mashinada `pg` testlar jim skip bo‘ladi. Hisobotda **PG natijasi alohida** keltiriladi: `scripts/test-pg.ps1` yoki `scripts/test-pg.sh` buyrug‘i va uning `X passed` qatori (masalan `20 passed`), shuningdek to‘liq suite’dagi `skipped` soni. Concurrency/idempotency/pul AC testlari uchun 0 skipped talab qilinadi.

### 5.3 Fixture dizayni

```text
session  pg_server    → ulanishni tekshiradi (yoki skip), server_version, postgis versiyasi
session  pg_template  → CREATE DATABASE elchi_pgtest_tpl_<uuid>
                        CREATE EXTENSION postgis
                        subprocess: python -m alembic upgrade head  (ELCHI_DATABASE_URL=<tpl>)
                        ALTER DATABASE … ALLOW_CONNECTIONS false IS_TEMPLATE true
function pg_db        → CREATE DATABASE elchi_pgtest_t_<uuid> TEMPLATE <tpl> STRATEGY FILE_COPY
                        engine(pool_size=50, max_overflow=10) → test → dispose → DROP DATABASE … WITH (FORCE)
function pg_empty_db  → PostGIS’siz bo‘sh DB (hozirgi prod’ga o‘xshash)
```

**Nega har test uchun template’dan klon (TRUNCATE yoki tranzaksiya-rollback emas):**
- Concurrency testlari ko‘p mustaqil ulanishda haqiqiy `COMMIT` qiladi — umumiy o‘rab turuvchi tranzaksiya bu testlarni ma’nosiz qiladi.
- TRUNCATE uchun jadvallar ro‘yxati, sequence reset va FK tartibini qo‘lda yuritish kerak; har yangi migratsiyada buziladi. Test ichida yaratilgan qo‘shimcha jadvallar/extension’lar ham qolib ketadi.
- `audit_logs` immutability trigger’i kabi DB obyektlari o‘zgarmay qoladi.
- O‘lchangan narx: bitta klon ≈ **0.1 s** (tmpfs, `FILE_COPY`); sessiyaga bir marta migratsiya ≈ 2–3 s. 15 test ≈ 14.5 s, uning katta qismi ataylab qo‘yilgan `sleep`lar.
- `pytest-xdist` qo‘shilsa ham DB nomlari UUID’li, to‘qnashuv yo‘q.

**Nega Alembic subprocess’da:** `app.core.config.settings` import vaqtida keshlanadi va `alembic/env.py` URL’ni `settings.database_url`dan oladi. Subprocess `ELCHI_DATABASE_URL`ni import’dan oldin aniq o‘rnatadi va pytest jarayonidagi `app` holatini ifloslantirmaydi. Bu prod’dagi haqiqiy CLI yo‘lining o‘zi.

### 5.4 Concurrency harness

```python
from tests.pg.harness import run_concurrently

def take(worker: int, session: Session) -> bool:
    ...                      # o‘z tranzaksiyasi; saqlanishi kerak bo‘lsa session.commit()

report = run_concurrently(20, take, engine=pg_db.engine)
report.successes / report.failures / report.values() / report.errors_of(OperationalError)
```

- Har worker: alohida `Session` + alohida ulanish; ulanish **barrier’dan oldin** olinadi, shuning uchun hamma critical section’ga bir vaqtda kiradi.
- Istisnolar worker bo‘yicha yig‘iladi (qayta ko‘tarilmaydi) — test "1 success, 19 conflict"ni aniq tekshiradi.
- Worker barrier’ga yetmasa `barrier.abort()` — test osilib qolmaydi.
- Engine pool’i `n` ta bir vaqtdagi ulanishga yetishi kerak (`pg_db` 60 gacha beradi).
- Kelajakdagi foydalanish: AC06 (2 driver bitta demand), AC07 (20 so‘rov oxirgi o‘ringa), AC08/AC09 (idempotency kaliti), AC19 (hold va available), AC41 (admin block vs accept, lock tartibi).

### 5.5 Smoke test natijalari (haqiqatda ishga tushirilgan)

Buyruq: `py -m pytest -m pg tests/pg -p no:cacheprovider -rA --durations=10` → **15 passed in 14.50 s**. Keyin `scripts/test-pg.ps1` (Windows PowerShell 5.1) → **15 passed**, exit 0. `scripts/test-pg.sh --down` (Git Bash) → **15 passed**, stack o‘chirildi. Barqarorlik: `test_concurrency_harness.py` ketma-ket **10 marta** → har safar 4/4 passed (negative control ham har safar poygani ko‘rsatdi; `xfail` kerak bo‘lmadi).

| Test | Nima isbotlanadi | Natija |
|---|---|---|
| `test_upgrade_head_from_empty_matches_single_script_head` | Bo‘sh PG16 + PostGIS’da `alembic upgrade head` o‘tadi; `alembic_version` = yagona script head `20260803_0029` | passed |
| `test_upgrade_head_on_fresh_database_without_preinstalled_extensions` (wave 0.5’da qayta nomlandi) | Extension oldindan o‘rnatilmagan bo‘sh DB’da upgrade head o‘tadi va head = script head. PostGIS bor/yo‘qligi ataylab tekshirilmaydi | passed |
| `test_template_is_at_head_and_has_postgis` (wave 0.5) | Test template’i head’da va unda PostGIS o‘rnatilgan (`ST_SRID` ishlaydi) | passed |
| `test_alembic_current_reports_head_on_clone` | Klon DB’da `alembic current` → `20260803_0029 (head)` | passed |
| `test_audit_log_immutability_trigger_exists_on_postgres` | 0024 trigger’i UPDATE/DELETE’ni DB darajasida rad etadi | passed |
| `test_orm_metadata_matches_migrated_schema` | `app.models` va migratsiya qilingan sxema orasida drift yo‘q (`compare_metadata` = `[]`). Detektor ishlashi alohida tekshirildi: sun’iy `DROP COLUMN users.username` + ortiqcha jadval → 3 diff topildi | passed |
| `test_postgis_extension_installed` | PostGIS 3.5.2, SRID 4326 mavjud | passed |
| `test_st_dwithin_geography_meters[1500/1100/900/500]` | Toshkent markazi va 0.009° shimoldagi nuqta (~1.0 km): 1500 m, 1100 m → true; 900 m, 500 m → false | 4 passed |
| `test_geography_distance_and_gist_index` | `ST_Distance` 990–1010 m; `geography` GiST indeksi `ST_DWithin` rejasida ishlatiladi | passed |
| `test_select_for_update_lets_exactly_one_worker_take_last_unit` | 20 worker, `SELECT … FOR UPDATE` + shartli kamaytirish → aniq 1 success, 19 false, `remaining=0`, 1 claim | passed |
| `test_conditional_update_is_also_atomic` | `UPDATE … WHERE remaining > 0 RETURNING` → aniq 1 success | passed |
| `test_nowait_conflicts_are_reported_per_worker` | `FOR UPDATE NOWAIT` → 1 success, 19 `LockNotAvailable` (409 conflict yo‘li) | passed |
| `test_negative_control_unlocked_read_then_write_oversells` | Lock’siz read→sleep→write: bir nechta worker "yutadi", `claims > 1` — harness haqiqiy overlap yaratishining isboti | passed |

**Wave 0.5 natijalari (2026-09-13, +05:00, asosiy daraxt — boshqa agentlar parallel tahrir qilmoqda):**

| Vaqt | Buyruq | Natija |
|---|---|---|
| 21:14:46 | `.\scripts\test-pg.ps1 -- -p no:cacheprovider -rA` (skript `ELCHI_TEST_PG_REQUIRED=1` qo‘yadi) | **PG: 16 passed**, 25 deselected (`test_url_guards.py`, marker’siz), 0 skipped, exit 0, 21.5 s |
| 21:15:24–21:17:34 | `py -m pytest -o addopts="" -q -p no:warnings -p no:cacheprovider -rfEs` (stack ishlab turgan) | **11 failed, 511 passed, 0 skipped** (125 s). 511 ichida `tests/pg` ning 41 testi (16 pg + 25 guard) bor; boshqa agentlarning yangi testlari ham kiradi. 11 ta yiqilish — §2.1 dagi aynan o‘sha testlar (R1/R2); ular H1 tomonidan tahrirlanmoqda, vaqtga qarab o‘zgarishi mumkin |
| — | `py -m pytest tests/pg/test_url_guards.py -o addopts="" -q` (Docker o‘chiq paytida) | 25 passed |
| — | `scripts/test-pg.ps1` Docker o‘chiq paytida | darhol `Docker daemon is not reachable…`, exit 1 (skip emas) |

`alembic downgrade` ataylab test qilinmaydi: spec §18.3 bo‘yicha downgrade rollback strategiyasi emas. Deploy rollback ≠ data rollback; tuzatish forward migration yoki tekshirilgan recovery orqali.

### 5.6 Mavjud migratsiyalar PG16’da

- 28 revision bo‘sh PostgreSQL 16.9’da (PostGIS bilan ham, usiz ham) xatosiz `upgrade head` qiladi. Branch/merge’lar muammo bermadi.
- SQLite’ga xos xulqqa tayanadigan migratsiya topilmadi: `batch_alter_table` yo‘q; `op.execute` ichidagi SQL (`UPDATE … SET … = true`, `CASE`) PG’da to‘g‘ri.
- Dialektga bog‘liq joylar: `0024` faqat PG’da trigger yaratadi (SQLite’da no-op — SQLite suite uni tekshirmaydi); `0013` `postgresql_where` partial index; `ac62a9c9e9e2` `postgresql_nulls_not_distinct=False`.
- ORM ↔ sxema drift: yo‘q (yuqorida).
- **A10a’ga topshiriq (PostGIS migratsiyasi `0030`, ADR-0013):** wave 0.5 gacha smoke test "upgrade head PostGIS o‘rnatmaydi" deb tekshirardi — bu 0030 bilan ataylab buzilardi. Endi test faqat head = script head va template’da PostGIS mavjudligini tekshiradi, shuning uchun 0030 qo‘shilganda o‘zgartirish kerak emas. A10a uchun shartlar: (1) `CREATE EXTENSION IF NOT EXISTS postgis` ishlatilsin — `pg_template` extension’ni migratsiyadan oldin o‘rnatadi, `IF NOT EXISTS`siz migratsiya yiqiladi; (2) `pg_empty_db` testi extension’siz bazadan o‘tishi kerak (test user superuser, image’da PostGIS mavjud); (3) prod’da extension yaratish huquqi va image almashtirish — §6 (K4-xavf) bajarilmaguncha 0030 deploy qilinmaydi; (4) 0030 qo‘shilgach `scripts/test-pg.ps1` natijasi hisobotda keltirilsin.
- Cheklov: faqat **bo‘sh bazadan** migratsiya tekshirildi. Prod’dagi haqiqiy ma’lumotli bazada data-migratsiya qadamlari (0003, 0004, 0006, 0010, 0014, 0020) boshqacha natija berishi mumkin; bu A10 staging restore mashqida tekshiriladi.

---

## 6. K4-xavf: `postgres:16-alpine` (musl) data katalogini `postgis/postgis` (glibc) image’iga ko‘chirish

"K4-xavf" — shu bo‘limning ichki nomi (ta’rif hujjat boshida); u `AGENTS.md` §3 foydalanuvchi qarorlari raqamlashiga kirmaydi.

### 6.1 Muammo

Prod DB `postgres:16-alpine` (musl libc). PostGIS image’lari Debian (glibc). Ikkalasida ham `datcollate = en_US.utf8` ko‘rinadi, lekin **tartiblash qoidalari boshqa**: musl `en_US.utf8`ni amalda codepoint/bayt tartibida solishtiradi, glibc esa lingvistik tartibda (katta-kichik harf va tinish belgilarini birinchi darajada e’tiborsiz qoldiradi). B-tree indeksidagi matn kalitlarining tartibi collation’ga bog‘liq. Eski alpine data katalogini glibc image bilan ochish = **indekslar yangi qoidaga nisbatan noto‘g‘ri tartibda** qoladi:

- indeks orqali qidiruv mavjud qatorni **topmaydi** (jim noto‘g‘ri natija);
- unique indeks dublikatni o‘tkazib yuborishi mumkin (`uq_users_phone`, `ix_users_username`, `uq_orders_order_number`, `ix_refresh_sessions_jti` …);
- ORDER BY natijasi ilova uchun ko‘rinadigan tarzda o‘zgaradi.

Migratsiya qilingan sxemada **24 ta** text/varchar B-tree indeks bor, ulardan **8 tasi unique** (`users.phone`, `users.username`, `orders.order_number`, `refresh_sessions.jti`, `driver_profiles.plate_number`, `cities.name_uz`, `system_settings.key`, `alembic_version`).

Qo‘shimcha farqlar: postgres UID alpine’da `70`, Debian’da `999` (entrypoint root sifatida `chown` qiladi); image minor versiyasi `16.15` → `16.9` (minor downgrade — texnik ishlaydi, lekin tavsiya etilmaydi); musl collation versiyasini bermaydi (`datcollversion = NULL`), shuning uchun PostgreSQL’ning "collation version mismatch" ogohlantirishi **ishlamaydi** — xato jim o‘tadi.

### 6.2 Aniqlash

```sql
SELECT datname, datcollate, datctype, datlocprovider, datcollversion,
       pg_database_collation_actual_version(oid)
FROM pg_database;
-- alpine: en_US.utf8 | en_US.utf8 | c | NULL
-- glibc : … actual_version = 2.31 (recorded NULL → mismatch aniqlanmaydi)

CREATE EXTENSION IF NOT EXISTS amcheck;
SELECT bt_index_check('people_name_idx', true);        -- heapallindexed
SELECT bt_index_parent_check('uq_users_phone', true);  -- kuchliroq, ShareLock oladi
```

```bash
pg_amcheck -U <user> -d <db> --heapallindexed          # barcha B-tree indekslar
```

### 6.3 Xavfsiz yo‘l

1. **Tavsiya: logical ko‘chirish.** `pg_dump -Fc` (alpine) → yangi, bo‘sh `postgis` volume → `pg_restore --exit-on-error`. Indekslar restore paytida glibc qoidasi bilan qayta quriladi. Keyin: jadval bo‘yicha qator sonlari, `pg_amcheck --heapallindexed`, `alembic current`, ilova smoke. Eski alpine volume o‘zgarmay qoladi — orqaga qaytish yo‘li saqlanadi.
2. **Muqobil (tavsiya etilmaydi):** eski katalogni glibc image bilan ochib, darhol ilovasiz `REINDEX DATABASE` (yoki kamida barcha text indekslar) + `pg_amcheck`. Unique indeks qayta qurilayotganda dublikat chiqsa, avval ma’lumotni tozalash kerak. Qaytish yo‘li yo‘q (katalog o‘zgaradi), shuning uchun avval volume snapshot.
3. Ikkala holatda ham ORDER BY semantikasi o‘zgaradi — ro‘yxatlarni nom bo‘yicha saralaydigan API’lar (shahar/tuman) tekshiriladi. Deterministik tartib kerak bo‘lsa ustunga `COLLATE "C"` yoki ICU collation ongli ravishda tanlanadi.

`docker-compose.prod.yml` o‘zgartirilmadi; prod’ga ulanilmadi.

### 6.4 Lokal repetitsiya (haqiqatda bajarildi, 2 marta)

Skript scratchpad’da (`k4_rehearsal.sh`); nomlari `k4r-*`, port ochilmaydi, oxirida container va volume’lar o‘chiriladi (tekshirildi).

1. `postgres:16-alpine` (16.15, musl): `people(name text)`, `people_name_idx`, `people_name_id_uq(name,id)`, 20 000 qator (lotin/kirill, katta-kichik harf, `_`, `-`, `‘`, `Ç`). `datcollate=en_US.utf8`, `datlocprovider=c`, `datcollversion=NULL`. `pg_dump -Fc` (94 KB).
2. **Xavfli yo‘l:** shu volume `postgis/postgis:16-3.5` bilan ishga tushirildi — server muammosiz ko‘tarildi (UID 70→999 chown), ogohlantirish yo‘q.
   - `WHERE name = 'Ali 1'` (indeks orqali, reja: `Bitmap Index Scan on people_name_id_uq`) → **0 qator**;
   - `WHERE name || '' = 'Ali 1'` (indekssiz) → **9 qator** ⇒ jim noto‘g‘ri natija isbotlandi;
   - `bt_index_check` → `ERROR: item order invariant violated for index "people_name_idx"` (va `people_name_id_uq`);
   - `pg_amcheck --heapallindexed` → exit 2, ikkala indeks buzilgan;
   - `REINDEX TABLE people` → `bt_index_check` toza.
3. **Xavfsiz yo‘l:** yangi postgis volume’ga `pg_restore --no-owner --exit-on-error` → exit 0; 20 000 = 20 000 qator; `bt_index_check` toza; `CREATE EXTENSION postgis` → 3.5.2. ORDER BY o‘zgardi:
   - alpine: `-z 1 | A-1 1 | ALI 1 | Ali 1 | B 1 | … | _x 1 | a 1 | …`
   - glibc: `a 1 | a1 1 | A-1 1 | a b 1 | ab 1 | ali 1 | Ali 1 | ALI 1 | B 1 | …`

---

## 7. Ma’lum cheklovlar

- Test image PostgreSQL **16.9**, prod alpine **16.15** (bir xil major). `postgis/postgis:16-3.5` tag’i Debian bullseye asosida va eskiroq minor’da qolgan; prod PostGIS image’i tanlanganda (A10) test image ham shu tag+digest’ga moslanadi. Digest yangilansa `tests/pg` qayta ishga tushiriladi.
- Test konteyneri `fsync=off`, `synchronous_commit=off`, `full_page_writes=off` bilan ishlaydi — crash-durability testlari uchun yaroqsiz; faqat mantiq/concurrency uchun.
- Negative control `sleep(0.15 s)` bilan poyga oynasini kengaytiradi; juda sekin/yuklangan mashinada ham barqaror bo‘lishi kutiladi (10/10), lekin bu vaqtga bog‘liq test — yiqilsa `xfail(strict=False)` qilinadi, o‘chirilmaydi.
- Redis servisi faqat ko‘tariladi va healthcheck’dan o‘tadi; unga hali test yo‘q.
- `tests/pg` testlari `-m pg`siz oddiy `py -m pytest`da ham yig‘iladi: server bo‘lmasa `pg` testlar skip bo‘ladi (agar `ELCHI_TEST_PG_REQUIRED=1` bo‘lmasa), bo‘lsa ishlaydi. Wave 0 tekshiruvi: ulanib bo‘lmaydigan URL bilan to‘liq suite → `11 failed, 310 passed, 15 skipped` (baseline bilan bir xil + 15 skip). `test_url_guards.py` (25 test) marker’siz va Docker’siz ham ishlaydi; uning 3 ta end-to-end testi bola `pytest` jarayonini ishga tushiradi (~10 s).
- Faqat bo‘sh bazadan migratsiya tekshirildi; real prod ma’lumotli upgrade va backup restore — A10/AC40.
- CI yo‘q; skriptlar lokal Windows (PowerShell 5.1, Git Bash) da tekshirildi. Linux CI’da `scripts/test-pg.sh` ishlashi kutiladi, lekin sinalmagan.
- 11 ta mavjud test yiqilishi (R1/R2) tuzatilmagan — A0b egaligida emas.
