# ADR-0011: Ma’lumot joylashuvi va hosting launch gate

**Holat:** Accepted (K3) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §17.7, §19.1, §19.2 • **AC:** AC40 • **Qarorlar:** K3

## Kontekst
Production hozir Hetzner (Germaniya) umumiy serverida; `docs/SERVER_MIGRATION.md:7-10` bu shaxsiy ma’lumotni mamlakatdan chiqarishini qayd etgan. K3: O‘zbekiston qonuni shaxsiy hujjatlarni O‘zbekistondagi serverda saqlashni talab qiladi. Backup ham shu serverda (`scripts/backup.sh`). Spec §17.7 huquqiy tekshiruvni launch oldidan talab qiladi; bu ADR huquqiy xulosa emas.

## Qaror
1. **Launch gate:** stage-2 production (har qanday v2 foydalanuvchi ma’lumoti, driver hujjatlari, GPS) faqat O‘zbekistondagi hostingda ishga tushadi. Gate bajarilmaguncha stage-2 faqat lokal/test muhitda, soxta/sintetik ma’lumot bilan.
2. **Host-agnostic deploy:** 
   - Hamma konfiguratsiya env orqali (`ELCHI_*`); provayderga xos API (Hetzner volume/API, managed S3 xususiyatlari) ishlatilmaydi.
   - Compose: `api`, `worker`, `postgres-postgis`, `redis`, `caddy` — oddiy Linux + Docker’da ishlaydi.
   - Fayl saqlash: lokal persistent volume (H0) yoki S3-compatible interfeys orqali, faqat O‘zbekiston ichidagi endpoint.
   - TLS: Caddy ACME; DNS provayderdan mustaqil.
3. **Backup residency:** backup nusxalari ham O‘zbekiston ichida, boshqa nosozlik domenida (§19.1). RPO/RTO restore mashqi bilan o‘lchanadi (AC40).
4. **Tashqi xizmatlarga uzatiladigan maydonlar ro‘yxati** (A10a runbook’da, huquqiy tekshiruv uchun): SMS (Eskiz — telefon, OTP matni), push (FCM/Web Push — PII’siz payload, ADR-0012), xarita/routing provayderi (koordinatalar, manzil qidiruvi), Google/Yandex geocoding (mavjud: `app/services/google_maps_service.py`, `yandex_maps_service.py`). Har biri uchun yuboriladigan maydon va minimallashtirish.
5. **Mavjud v1 production** (Germaniya): bu xavf `BASELINE_AUDIT.md` R2 da; hal qilish muddati foydalanuvchi qarori. A10a UZ hosting runbook’i v1 ko‘chishiga ham qo‘llanadi.
6. **Retention:** raw GPS 7 kun, siyraklashtirilgan iz 30 kun, receipt 8 kun (§10.7, §13) — taklif; huquqiy tekshiruvdan keyin tasdiqlanadi.
7. **Muhit identifikatsiyasi va readiness (BR N1):** host-agnostic deploy production’ni hostname’dan emas, DB’dagi muhit markeridan (A3 loyihasi, deploy yozadi) va `ELCHI_ENVIRONMENT`dan aniqlaydi; ikkisi mos kelmasa — `production_invariants: fail`. `/health/ready`: **503 faqat** DB yetib bo‘lmasa yoki DB migration head kod head’iga mos kelmasa; Redis yo‘q → `degraded`; invariant ma’lumot buzilishi → `production_invariants: fail` + alert (200/`degraded`), pul buyruqlari rad etiladi.
8. **Readiness tuzatishi (Q32):** DB head kod head’ining **ma’lum avlodi** bo‘lsa (masalan deploy rollback’dan keyin kod eskiroq) → 200 `degraded`, `checks.migrations: "ahead"`; DB head koddan orqada yoki noma’lum revision → 503.
9. **Readiness kirishi (Q33):** `/health/ready` Caddy’da faqat monitoring IP’lariga ruxsat; `/health/live` ochiq (A10a).
10. **Tashqi routing (Q24):** Geoapify/hosted router production’da huquqiy/data-flow va provider shartlari tekshiruvigacha o‘chiq (`ELCHI_GEO_ROUTING_PROVIDER=disabled`). Provider’dan olingan marshrut geometriyasini doimiy saqlash faqat shartlar ruxsat bersa; aks holda bekatlar, kumulyativ masofa/vaqt va request hash saqlanadi. **Implementatsiya (A2, wave 1.5):** production’da routing provayderi umuman qurilmaydi (`build_routing_provider(settings, *, production)` → disabled); uni yoqish yangi ADR va kod o‘zgarishini talab qiladi (sozlama bilan yoqib bo‘lmaydi). `RouteVersionDTO.attribution` provayder atributsiyasini ko‘rsatadi.
11. **Backup (Q35):** WAL shifrlash yo‘q ekan production WAL/PITR yoqilmaydi (`PG_ARCHIVE_MODE=off`); faqat kundalik shifrlangan dump, O‘zbekistonda, RPO ≤ 24 soat deb e’lon qilinadi.

## Muqobillar
- **Germaniyada qolish + shifrlash** — K3 ga zid (saqlash joyi talabi).
- **Gibrid (hujjatlar UZ, qolgani DE)** — murakkab, GPS va telefon ham shaxsiy ma’lumot.

## Oqibatlar
- Stage-2 production sanasi hosting tayyorligiga bog‘liq.
- A10a: UZ hosting runbook, compose, Postgres migratsiya rejasi (ADR-0013).
