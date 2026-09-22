# Klient API qamrovi — F-05 auditi va ulash tartibi

**Sana:** 19.09.2026 (wave 15 yakuni) • **Usul:** `mobile-app/src/api/v2/*.api.ts` dagi chaqiruvlar ↔
`mobile-app/src/api/generated/openapi-v2.json` yo'llari solishtirildi; har bir bo'shliq `app/modules/*/api.py`
da o'qib tekshirildi.

**Holat:** v2 da **152** yo'l, klient **82** tasini chaqiradi, **70** tasi qolgan (43 admin, 27 boshqa).
Wave 11 dagi o'lchov 68/150 edi; farq — wave 15/16 da ulangan M2 matches, amendment, saqlangan qidiruv, nizo
dalili va admin narx referensi.

Tasnif:

| Yorliq | Ma'nosi |
|---|---|
| **CORE-P0** | Auksion yadrosining o'zida: e'lon → taklif → qarshi taklif → qabul → bron. Bo'lmasa oqim uziladi yoki odam platformadan chiqib ketadi. |
| **P1** | Mahsulot uchun muhim, lekin yadro usiz ham yopiladi. |
| **ADMIN** | Operator/moliya yuzasi, foydalanuvchi oqimiga tegmaydi. |
| **EXTERNAL** | Kod tayyor; qolgani tashqi qaror, credential yoki qurilma. |

---

## 1. Foydalanuvchi yuzasidagi 11 ta bo'shliq

| # | Endpoint | Modul | Tasnif | Nega |
|---|---|---|---|---|
| 1 | `GET/POST /proposals/{id}/messages` | communications | **CORE-P0** | Bron paydo bo'lishidan **oldin**, muzokara davomida yozishma. Hozir chat faqat bronda bor — ya'ni narx kelishayotgan ikki odam «bir soat kechroq bo'ladimi?» deb so'rash uchun platformadan chiqishi kerak. ADR-0020 aynan shuni oldini olish uchun yozilgan; Q44 xizmat boshlangunча aloqani ilova ichida deb belgilaydi. |
| 2 | `POST /listings/{id}/pause` | marketplace | **CORE-P0** | Egasi o'z e'lonini vaqtincha to'xtata olmaydi. Yagona yo'l — bekor qilish, u esa qaytarib bo'lmaydi va ochiq threadlarni yopadi. |
| 3 | `POST /listings/{id}/resume` | marketplace | **CORE-P0** | 2-bandning juftligi; `pause` siz ma'nosiz. |
| 4 | `GET /commission/quote` | wallet | **P1** | Haydovchi narx taklif qilishdan oldin komissiyani ko'rmaydi. Bitim uchun shart emas (kvota taklifda muzlatiladi), lekin haydovchi ko'r-ko'rona narx qo'yadi. `proposal.submit_as_driver` talab qiladi. |
| 5 | `POST/GET/DELETE /blocks` | trust_support | **P1** (xavfsizlik) | §8.1: bloklangan juftlik boshqa uchrashmaydi. Server buni lentada va takliflarda allaqachon majburlaydi — yetishmayotgani odamning bloklash imkoni. Jim va idempotent (bloklangan tomon bilmaydi). |
| 6 | `POST /reports` | trust_support | **P1** (xavfsizlik) | Foydalanuvchi ustidan shikoyat. 5-band bilan juft: bloklash «men ko'rmayman», shikoyat «operator ko'rsin». |
| 7 | `GET /me/reports` | trust_support | **P1** | Yuborilgan shikoyatning holati. Javobsiz shikoyat — ishonchni yo'qotadigan narsa. |
| 8 | `POST /bookings/{id}/codes/{kind}/reissue` | bookings | **P1** | Kod egasi kodni qayta chiqaradi (B5a). Bo'lmasa yo'qolgan kod darhol operator ishiga aylanadi. Q75 cheklovlari (2 daqiqa oraliq, 24 soatda 3) allaqachon serverda. |
| 9 | `POST/DELETE /bookings/{id}/tracking-grants` | tracking | **P1** | Kuzatuvni uchinchi shaxsga (oila) ulashish, §10.6 oynasi ichida. |
| 10 | `GET /parcel-policy` | marketplace | **P1** (matni **EXTERNAL**) | Jo'natuvchi nimani yubora olmasligini ko'rmaydi. Ekran — P1; ro'yxatning **mazmuni** yurist xulosasiga bog'liq (§5.2, Q28), ya'ni EXTERNAL. |
| 11 | `GET /users/{id}/reputation` | trust_support | **P1** | Profil reytingi. Diqqat: Q40 bo'yicha accept'gacha haydovchi anonim — bu endpoint o'z profili va accept'dan keyingi ko'rinish uchun. U6 bo'yicha sun'iy reyting yo'q. |

### Ulash tartibi

**Birinchi to'lqin (CORE-P0, auksion yadrosi):** 1 → 2 → 3.
Uchalasi bitta ekran guruhida: taklif kartasiga yozishma, e'lon tafsilotiga «To'xtatish/Davom ettirish».

**Ikkinchi to'lqin (P1, xavfsizlik va ishonch):** 5 → 6 → 7 → 8.
Bloklash va shikoyat bitta «Muammo» oqimi; kod qayta chiqarish bron ekranida.

**Uchinchi to'lqin (P1, qulaylik):** 4 → 9 → 10 → 11.

---

## 2. Ataylab ulanmaganlar (bo'shliq emas)

| Endpoint | Sabab |
|---|---|
| `POST /tracking/sessions`, `.../points:batch`, `.../close` | GPS haydovchining **Android** ilovasidan keladi (§10.3/§10.5). Web klient GPS manbai emas. |
| `POST /devices/push-token`, `DELETE /devices/{id}` | FCM yoqilmagan (ADR-0022 qabul qilingan, provayder ulanmagan). Q82: hozircha faqat ilova ichidagi xabarlar. |
| `POST /routes/preview`, `POST /routes/{id}/confirm` | Routing provayderi Q24/Q46 bo'yicha o'chiq. Tasdiqlangan marshrutlarni o'qish (G18) klientda bor. |
| `GET /events` | Diagnostika/integratsiya yuzasi, foydalanuvchi ekrani emas. |
| `GET /public/tracking/{token}`, `GET /share-links/{id}` | Ommaviy ulashish sahifasi (`/e/{token}`) allaqachon bor; bu ikkisi uning ichki chaqiruvlari. |

---

## 3. Admin: production-operability qismi

43 ta admin yo'lidan **hammasini birdan** ulash kerak emas. Production'ni **boshqarib bo'ladigan** qilish uchun
minimal to'plam — **19 yo'l**:

| Guruh | Yo'llar | Nega shu birinchi |
|---|---|---|
| **Feature flag** | `GET /admin/feature-flags`, `GET /admin/feature-flags/{key}/history`, `PUT /admin/feature-flags/{key}/scopes/{type}/{ref}` | Koridor bo'yicha xizmatni yoqish/o'chirish — rollout'ning yagona dastagi (Q5). Hozir faqat SQL yoki probe orqali. |
| **Top-up tasdiqlash** | `GET /admin/topups`, `POST /admin/topups/{id}/approve`, `POST /admin/topups/{id}/reject` | Haydovchi balansi tasdiqlanmasa yangi bron ochilmaydi (§9.1). Q69: faqat `finance` yoki `super_admin`. |
| **Komissiya policy** | `GET/POST /admin/commission-policies`, `GET /admin/commission-policies/{id}`, `POST .../confirm`, `POST .../end` | Q28: production'da faqat seed stavka bo'lsa v2 quote/hold bloklanadi — ya'ni bu ekran **go-live sharti**. |
| **Reconciliation** | `GET /admin/finance/reconciliation` | Q55: manbasiz posting'larni ko'rish. Moliyaviy ishonchning asosi. |
| **Moliyaviy tuzatishlar** | `GET/POST /admin/ledger/adjustments`, `GET /admin/ledger/adjustments/{id}`, `POST .../approve`, `POST .../reject`, `POST .../withdraw` | Q17/Q49: katta tuzatish **ikkinchi, boshqa** xodim tasdig'i bilan. Ikki kishilik qoida UI'siz bajarilmaydi. |
| **Outbox ko'rinishi** | `GET /admin/outbox`, `POST /admin/outbox/{id}/retry` | Yetkazilmagan event — jim nosozlik. Ko'rinmasa, bilinmaydi. |

**Keyinga qoladigan 24 ta admin yo'li:** koridor/bekat CRUD (narx referensi paneli wave 16 da ulandi),
legacy arxiv tafsiloti, fraud signallari, trust strike'lari, chat moderatsiyasi, `listings/on-behalf`,
provider kvotasi, `geo/checks/q47`, moliya hisobot fayllari, `drivers/{id}/eligibility`.

---

## 4. Nima o'lchandi

```
py -c "<solishtirish skripti>"        →  152 yo'l, 82 chaqiriladi, 70 qolgan (43 admin, 27 boshqa)
```

Har bir qolgan yo'l `app/modules/*/api.py` da ochib ko'rildi — 11 tasi foydalanuvchi yuzasidagi haqiqiy
bo'shliq, 8 tasi ataylab ulanmagan, qolgani admin.
