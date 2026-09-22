# ADR-0010: Klient strategiyasi — mobile-app, muzlatilgan klientlar, OpenAPI → TypeScript

**Holat:** Accepted (Q11, Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §10.5, §12, §21 A8/A9 • **AC:** AC27–AC32 (klient qismi), AC39 • **Qarorlar:** M4/S1, K6

## Kontekst
- `mobile-app/`: Vite + React 19 + TS 5.8 (`mobile-app/package.json`); qo‘lda yozilgan tiplar, 11/13 fayl `frontend/src/types` nusxasi; backend maydonlari yo‘q (`BASELINE_AUDIT.md` §2.16); ikki lockfile.
- `frontend/`, `android-app/` muzlatilgan.
- v1 OpenAPI javob sxemalarisiz (`response_model=None`).
- Spec §12: DTO/enum qo‘lda ko‘paytirilmaydi, OpenAPI’dan generatsiya.

## Qaror
1. **mobile-app — yagona stage-2 klienti:** mijoz, haydovchi (GPS’dan tashqari) va operator oqimlari; GPS uchun faqat foreground viewer (kuzatuvchi ko‘rinishi). Web/PWA fon tracker sifatida taqdim etilmaydi (§10.5).
2. **Muzlatilgan klientlar:** tahrir yo‘q; v1 backward compatible (ADR-0006).
3. **Generatsiya vositasi: `openapi-typescript`** (faqat tiplar, devDependency, runtime’siz) + mavjud `src/api/http.ts` ustida yupqa typed wrapper.
   - Sabab: runtime dependency qo‘shmaydi; envelope/xato ishlovi saqlanadi; React Query majburlamaydi; TS 5.8 bilan ishlaydi.
   - Aniq versiya A8 o‘rnatganda lockfile bilan pin qilinadi (taxmin qilinmaydi). **Bajarildi (wave 4b, 16.09.2026):** `openapi-typescript` devDependency sifatida o‘rnatildi va `package-lock.json`da pin qilindi; `npm audit` 0 zaiflik.
4. **Oqim:** backend `scripts/export_openapi.py` (A8 so‘raydi, egasi integrator) → `mobile-app/src/api/generated/openapi-v2.json` → `npm run gen:api` → `src/api/generated/v2.ts`. Generatsiya qilingan fayllar commit qilinadi (review’da diff ko‘rinadi). **Bajarildi (wave 4):** skript `--check` bilan eskirganini 3-kod bilan bildiradi; `tests/test_mobile_v2_client_contract.py` sxema ilova bilan mos ekanini va klient chaqirgan har yo‘l real v2 yo‘li ekanini tekshiradi.
5. **Faqat v2** generatsiya qilinadi. v1 ekranlari mobile-app’da v2’ga ko‘chguncha mavjud qo‘lda tiplar bilan qoladi, yangi qo‘lda DTO yozilmaydi.
6. **Enum va stavka:** statuslar, xato kodlari generatsiyadan; komissiya foizi hech qachon hard-code emas (K5).
7. **Lockfile — bajarildi (Q11):** mobile-app paket menejeri — **npm** (`package-lock.json`). A0b `pnpm-lock.yaml` va `pnpm-workspace.yaml`ni olib tashladi; A0b hisobotiga ko‘ra `npm audit` 0 zaiflik, build va lint o‘tdi. `openapi-typescript` shu npm lockfile’ga pin qilinadi.
8. **Pul/vaqt UI:** `*_minor` → so‘m formatlash va `Asia/Tashkent` displey bitta util’da (`src/utils/money.ts`, `date.ts` qayta yoziladi).

## Muqobillar
| Vosita | Nega yo‘q |
|---|---|
| `orval` | React Query/axios generatsiyasi — ortiqcha runtime va arxitektura qarori |
| `openapi-generator` (Java) | JVM talab, og‘ir klient kodi |
| `openapi-fetch` | Mumkin, lekin mavjud http qatlami bilan dublikat; kerak bo‘lsa A8 ADR bilan |
| Qo‘lda tiplar | §12 ga zid |

## Oqibatlar
- Backend DTO o‘zgarsa klient build’i yiqiladi — maqsad shu.
- v2 routerlarda `response_model` majburiy (ADR-0005).
