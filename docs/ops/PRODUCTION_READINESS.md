# PRODUCTION_READINESS — launch gate holati

**Muallif:** wave 5 integratori • **Oxirgi yangilanish:** wave 7 (17.09.2026) • **Manba:** `AGENTS.md` §3 (Q-qarorlar), spec §18–§20,
`COVERAGE_MATRIX.md`, `WAVE1_CARDS.md` (wave 5).

Bu jadval **kod tayyorligini**, **sinov dalilini** va **tashqi qarorni** ataylab ajratadi. “Kod yozildi” ≠
“test o‘tdi” ≠ “dala/tashqi tasdiq olindi”. Holat ustuni faqat shu repo’dagi dalilga tayanadi; hech bir band
boshqa birovning ishini “bajarildi” deb yozmaydi.

Holatlar: **CODE_READY** (kod va testlar bor, muhitda qo‘llanmagan) · **VERIFIED** (shu repo’da dalil bilan
tasdiqlangan) · **BLOCKED** (tashqi bog‘liqlik: qaror, registry, huquq, buxgalteriya) · **NOT_RUN** (bajarilishi
mumkin, lekin hali bajarilmagan).


**QA auditi (17.09.2026, wave 11):** spetsifikatsiyaning barcha bo‘limlari `docs/architecture/QA_REQUIREMENTS_MATRIX.md` da tekshirildi; topilmalar va ularning holati `QA_FINDINGS.md` da; jonli tizimdagi dalil `QA_VERIFICATION_REPORT.md` da. **P0 topilma F-01** (routing provayderi o‘chiq bo‘lganda haydovchi safar yarata olmasligi) tuzatildi — G18 marshrut katalogi. Bu hujjatdagi gate’lar holati o‘zgarmadi.

## 1. Pul va ma’lumot yaxlitligi

| Gate | Talab | Amaldagi dalil | Holat | Mas’ul / keyingi amal |
|---|---|---|---|---|
| **Q48 / Q56** | Production’da v2 xizmat flag’lari va yangi pul biznesi gate o‘tmaguncha yopiq (7 tekshiruv) | `platform.service.q48_gate_status`, SQL `platform_q48_gate_passed()`; PG testlari (`tests/pg/wallet`, `tests/pg/ops/test_health_probes_pg.py`) gate’ning **fail-closed** ekanini ko‘rsatadi | CODE_READY | Ops: production DB’da rollarni ajratish va gate’ni o‘tkazish |
| **Q36** | Alohida owner/migration va NOSUPERUSER app roli | `scripts/db_roles.py` + `tests/pg/ops/test_db_roles.py` (owner butun zanjirni migratsiya qiladi, app roli DDL/TRUNCATE/replication qila olmaydi) | CODE_READY | Ops: PostGIS oynasida bootstrap’ni ishga tushirish |
| **Q55** | Har ledger qatori aniq bitta biznes manbaga bog‘langan | `0052` + PG testlari (xom INSERT commit’da rad etiladi) | VERIFIED | — |
| **Q28** | Faqat migratsiya seed stavkasi bo‘lsa production quote/hold bloklanadi | `0036`/`0055` gate tekshiruvi `seed_rate_confirmed` | CODE_READY | `super_admin` haqiqiy stavkani tasdiqlaydi (go-live checklist) |
| **Q69/Q70/Q71** | Top-up/adjustment tasdig‘i faqat faol `finance`/`super_admin`; gate o‘tmaguncha pul bloklangan | `0055` guard’lari + PG testlari | VERIFIED (kod/DB) | Ops: rol egalarini tayinlash |
| **Q4 / AC37** | Legacy buyurtmalar v2 yozuv jadvallarida yo‘q, faqat read-only view | `0065` + `tests/pg/ops/test_legacy_projection.py` (qayta qurish dublikat bermaydi; har rol uchun yozish rad etiladi) | VERIFIED | — |
| **Q9** | Legacy naive vaqtlar `timestamptz`, isbotlangan qoida bilan | `0066` + `tests/pg/ops/test_legacy_timestamps.py`; `scripts/legacy_timestamp_audit.py` | VERIFIED (sintetik ma’lumotda) | Ops: deploy oldidan audit skriptini **production nusxasida** (read-only) ishga tushirish |

## 2. Deploy, rollback va backup

| Gate | Talab | Amaldagi dalil | Holat | Mas’ul / keyingi amal |
|---|---|---|---|---|
| **Q50** | Eski image yangi schema’ni tanishi (rollback paytida 503 emas) | `0067` `alembic_revision_lineage` + `alembic/env.py` yozuvchisi + `health_probes.classify_with_lineage`; `tests/pg/ops/test_revision_lineage.py` (eski image → `ahead` 200; begona revisiya → 503) | VERIFIED | Deploy: 0067 qo‘llangandan keyin lineage to‘ladi |
| **Q32/Q33** | Readiness holati va monitoring IP cheklovi | `health_probes` testlari; Caddy konfiguratsiyasi | CODE_READY | Ops: Caddy’da monitoring IP ro‘yxati |
| **Q34/Q51/Q73** | PostGIS image UZ private registry’da, digest bilan pin | `docker/postgis/Dockerfile`, `ELCHI_POSTGIS_IMAGE` qo‘llab-quvvatlanadi; `scripts/restore_drill.sh --print-image` pin bo‘lmasa ogohlantiradi | BLOCKED | Registry yaratilgach digestni `.env`ga kiritish va drill’ni qayta bajarish |
| **AC40** | Backup’dan tiklash, RPO/RTO o‘lchanadi | Dev rehearsal o‘tdi (sintetik 669 KB dump, jami 13.3 s) — `WAVE1_CARDS.md` wave 5 | NOT_RUN (rasmiy) | Deploy hostida `scripts/backup.sh --local-only` manifest+uploads bilan, pin qilingan image’da |
| **Q35** | WAL shifrlanmaguncha PITR yo‘q; kundalik shifrlangan dump, RPO ≤ 24 soat | `scripts/backup.sh` (gpg oqimi), `docs/ops/BACKUP_RESTORE.md` | CODE_READY | Ops: gpg kaliti va off-box manzil; shifrlangan dump → decrypt → restore yo‘lini bir marta bajarish |
| **§19.3 SLO/yuklama** | Feed p95 < 1 s, accept p95 < 2 s, tracking 95% < 30 s | **Wave 6:** ilova endi o‘z so‘rovlarini o‘lchaydi (`feed_p95_seconds`, `booking_accept_p95_seconds`, `server_error_rate`, `outbox_oldest_pending_seconds`) — bitta worker jarayoni doirasida; profil bo‘yicha yuklama sinovi hali bajarilmagan | CODE_READY / NOT_RUN | Harness **tayyor va lokal smoke bilan tekshirilgan** (`docs/ops/LOAD_PROFILE_RUNBOOK.md`); §19.3 profilining o‘zi **NOT_RUN** — foydalanishga ruxsat berilgan staging va 100 000 e’lonli sintetik fixture seed’i kerak |

## 2a. Ishonch va kuzatuv (wave 6 da qo‘shildi)

| Gate | Talab | Amaldagi dalil | Holat | Mas’ul |
|---|---|---|---|---|
| §8.1 blok | Bloklangan juftlik saralashdan oldin filtrlanadi | `user_blocks` + feed/proposal filtri; PG testlari | VERIFIED | — |
| §17.3 signal | Shikoyat va fraud signali, avtomatik hukmsiz | `abuse_reports`, `fraud_signals`, `scan_fraud_signals`; PG testlari | VERIFIED | Operator navbatini kuzatish |
| §17.6 sessiya | Revoke qilingan sessiya real-time kanalda yopiladi | `sid` claim + v2/WS tekshiruvi; PG testlari | VERIFIED (v2/WS) | v1 tomoni — foydalanuvchi qarori |
| §19.2 kuzatuv | Access log (duration, booking_id), 5xx, outbox lag | `app/ops/metrics.py`, access logger; PG testlari | VERIFIED | Prod’da log yig‘ish/monitoringga ulash |
| §10.8 kvota | 70 % ogohlantirish, 85 % cheklash | `provider_usage_daily` + `/admin/metrics/provider-quota` | VERIFIED (hisob) | Provayder yoqilganda chegaralarni kuzatish |
| §5.2 pilot limitlari | Pochta o‘lcham chegaralari | publish guard + PG testlari | VERIFIED | — |
| **§5.2 taqiqlangan jo‘natmalar** | Ro‘yxat versiyalangan, ko‘rsatiladigan va e’lon yaratishda qo‘llanadigan bo‘lsin | `0070`, `assert_parcel_policy_ready`, `GET /parcel-policy`, `tests/pg/marketplace/test_parcel_policy_pg.py` (8 test — 13 bandli tasdiqlangan ro‘yxat DB qoidalaridan o‘tadi va tasdiqlangach pochta biznesi ochiladi) | **Mexanizm: VERIFIED · Matn: tasdiqlangan · Production’da: NOT_RUN** | (1) **Yurist xulosasi — hamon ochiq**; (2) `super_admin` draft yuklaydi (`scripts/seed_parcel_policy_draft.py`), (3) **boshqa** `super_admin` `…/confirm` bilan faollashtiradi |
| **§20.4 KPI to‘liqligi** | 11 metrikaning hammasi o‘lchanadigan bo‘lsin | `0071` + `operations.service` (`booked_seat_km_ratio` + `seat_km_route_coverage`, `net_commission_per_corridor`); `tests/pg/ops/test_kpi_seatkm_commission_pg.py` (5 test, manba qatorlari va ledger bilan solishtirilgan); `missing_metrics` endi **bo‘sh** | VERIFIED (sintetik ma’lumotda) | Real ma’lumotda qamrov (`seat_km_route_coverage`) kuzatiladi — past qamrov nisbatni ishonchsiz qiladi |

## 3. Xizmat yoqish va huquqiy

| Gate | Talab | Amaldagi dalil | Holat | Mas’ul |
|---|---|---|---|---|
| **K7** | `passenger_enabled=false`, huquqiy tekshiruvgacha | Flag guard’lari (`0053`, `0057`), Q56 gate | BLOCKED | Foydalanuvchi + huquqshunos |
| **Q87 / U7** | Javob beriladigan support raqami va rost ish vaqti | `ELCHI_SUPPORT_PHONE` bo‘sh → S13 `available=false`; **wave 7 dan majburlangan**: production’da `passenger_enabled`ni yoqish raqamsiz `VALIDATION_ERROR` bilan rad etiladi (`geo.service.set_flag_value`), `tests/pg/ops/test_push_support_hardening_pg.py` | BLOCKED (kod tomoni VERIFIED) | Foydalanuvchi (passenger yoqilishidan oldin majburiy) |
| **Q24/Q46** | Routing provayderi huquqiy tekshiruvgacha o‘chiq | Flag o‘chiq; detour accept’da rad etiladi (Q62) | BLOCKED | Foydalanuvchi + provayder shartlari |
| **Q47** | Pilot koridorda ≥ 2 faol bekat va bekat dalili | `0046` guard’lari | CODE_READY | Operatorlar: real bekat ma’lumoti va dalil |
| **§9.4** | Soliq/fiskal siyosati | — | BLOCKED | Buxgalter (dev agent tasdiq bermaydi) |
| **Q8 / AC27 dala / AC32** | 6 xonali OTP, Android dala sinovlari | Backend tomoni tayyor; dala qismi bu repo’da tekshirilmaydi | BLOCKED | Android dasturchi |
| **ADR-0021** | Staff MFA | **Accepted** (17.09.2026) va wave 8 da yozildi: `0074`, `identity/mfa.py`, `pyotp==2.10.0`, step-up 7 ta pul/flag capability’sida, staff token 15 daqiqa; `tests/pg/identity/test_staff_mfa_pg.py` (13 test). Wave 9 da API va admin UI qo‘shildi (I6–I11, “Xavfsizlik (MFA)” bo‘limi, `tests/pg/identity/test_staff_mfa_api_pg.py` — 9 test): endi omilni ulash, tasdiqlash va bekor qilish ekrandan bajariladi. **Enforcement standart holda o‘chiq** (`staff_mfa_mode=audit_only`) | CODE_READY | Ops: (1) production’da ≥ 2 faol `super_admin`, (2) xodimlar omilni ekran orqali ro‘yxatdan o‘tkazadi va bir-birinikini tasdiqlaydi, (3) shundan keyin `staff_mfa_mode=enforce_privileged` |
| **U3 / Q82** | Push provayderi | **FCM tanlandi** (ADR-0022, 17.09.2026). Adapter, shifrlangan token ustuni (`0073`) va 13 test yozildi; **provayder yoqilmagan** — `DisabledPushProvider` amalda, akkaunt ochilmagan, tashqi trafik yo‘q | CODE_READY / BLOCKED | **K3 huquqiy tekshiruv** (ochiq), Firebase loyihasi va credential (Ops), klientda xom token ro‘yxati (A8/Android) |
| **U6** | `rating_bucket` chegaralari | **A-variant tasdiqlandi** (17.09.2026) va yozildi: 4 guruh, minimal 3 baho, `rating_count` har doim yonida. Sun’iy reyting yo‘q; ichki `adjusted_rating` hamon ko‘rsatilmaydi | VERIFIED | Mobil UI matni (A8) |
| **§17.6 v1 tomoni** | Logout’dan keyin access token darhol bekor bo‘lsinmi | **A-variant tasdiqlandi** (17.09.2026) va yozildi: `0072` + `get_current_user` `sid` tekshiruvi. `rotated` sababli bekor bo‘lgan sessiya v1 da eski tokenni o‘ldirmaydi (muzlatilgan klient uchun), `logout`/`admin_revoke` esa darhol rad etadi; v2/WS avvalgidek qat’iy. `tests/test_v1_session_revocation.py` (7 test) | VERIFIED | Deploy’dan keyin bir martalik ≤ 60 daqiqalik o‘tish oynasi kuzatiladi |

## 4. Go-live checklist (qisqa)

1. PostGIS oynasi: `scripts/db_roles.py` bootstrap (Q36) → `alembic upgrade head` (owner roli bilan).
2. `scripts/legacy_timestamp_audit.py` production nusxasida — natija `UTC` bo‘lishi shart (Q9).
3. `super_admin` komissiya stavkasini tasdiqlaydi (Q28).
4. Q48 gate holati `/health/ready` va `platform_q48_gate_passed()` orqali tekshiriladi.
5. UZ registry digesti kiritiladi (Q34/Q51/Q73), rasmiy AC40 mashqi manifest+uploads bilan bajariladi.
6. Support raqami va ish vaqti matni kiritiladi (Q87) — passenger yoqilishidan **oldin**.
7. Har xizmat flag’i alohida, koridor bo‘yicha yoqiladi (Q5); passenger uchun qo‘shimcha huquqiy approval reference.
8. **Taqiqlangan jo‘natmalar ro‘yxati tasdiqlanadi** (§5.2): `super_admin` draft yaratadi, **boshqa** `super_admin` tasdiqlaydi. Tasdiqlanmaguncha production’da yangi pochta biznesi ochilmaydi.
9. §19.3 yuklama profili staging’da bajariladi (`docs/ops/LOAD_PROFILE_RUNBOOK.md`) — natija hisobotga kontekst (commit, head, resurs, dataset) bilan yoziladi.
10. **Kamida ikkita faol `super_admin`** yaratiladi va ikkalasi ham MFA omilini ro‘yxatdan o‘tkazadi (bir-birinikini tasdiqlaydi) — shundan **keyin** `staff_mfa_mode=enforce_privileged` (ADR-0021). Bir super_admin bo‘lsa enforcement baribir qo‘llanmaydi.
11. Push yoqilishidan oldin: K3 huquqiy xulosasi + Firebase credential (ADR-0022). Ularsiz `DisabledPushProvider` amalda qoladi va hech qanday tashqi trafik yo‘q.
12. **Geo katalog: viloyat va tuman** (wave 10). Yo‘nalish *viloyat → tuman → bekat* bo‘lib tanlanadi, shuning uchun v2 katalogda viloyatlar va tumanlar bo‘lishi kerak:

    ```bash
    py scripts/import_legacy_districts.py --create-regions              # hisobot (hech narsa yozmaydi)
    py scripts/import_legacy_districts.py --create-regions --apply      # yozadi; qayta ishga tushirish no-op
    ```

    Skript legacy v1 `cities`/`districts` jadvalidan ko‘chiradi va hech qanday nom o‘ylab topmaydi: ISO kodi
    noma’lum viloyat yoki mos kelmagan shahar **hisobotga chiqadi va o‘tkazib yuboriladi**. Toshkent shahri
    (`UZ-TK`) `requires_district = false` bilan yaratiladi — unda tuman so‘ralmaydi. Keyin **operator ishi**:
    (a) `legacy_city_mappings` qatorlarini `unverified` dan tasdiqlangan holatga o‘tkazish, (b) tumanlarga
    tekshirilgan bekat (Q27 dalili) biriktirish. Bekatsiz tuman qidiruvda ko‘rinadi, lekin `stops_count = 0`
    bilan — mijozga olib ketish va’da qilinmaydi.
