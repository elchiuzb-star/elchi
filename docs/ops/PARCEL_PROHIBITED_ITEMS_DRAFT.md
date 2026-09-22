# Taqiqlangan va cheklangan jo‘natmalar — ro‘yxat **matni tasdiqlangan**, production’da **faollashtirilmagan**

**Holat:** ✅ **Matn tasdiqlandi** (mahsulot egasi, 17.09.2026) · ⏳ **Production’da faol emas.**
Ikkisi bir xil narsa emas va ataylab ajratilgan:

| Bosqich | Holat |
|---|---|
| Ro‘yxat **matni** (13 band) | Mahsulot egasi 17.09.2026 da tasdiqladi |
| **Yurist xulosasi** | Hamon **ochiq** — bu tashqi band, agent bajara olmaydi (pastdagi huquqiy izohga qarang) |
| Bazaga **qoralama** sifatida yuklash | `py scripts/seed_parcel_policy_draft.py --actor-user-id <super_admin> --label <label>` |
| **Faollashtirish** | Faqat **boshqa** `super_admin` `POST /api/v2/admin/parcel-policies/{id}/confirm` orqali. Muallif o‘z qoralamasini tasdiqlay olmaydi va skript buni production’da qila olmaydi |

Ya’ni matn tasdiqlangani ikki kishilik nazoratni bekor qilmaydi: production’da ro‘yxatni kim yoqqani
autentifikatsiyalangan va audit qatoriga yozilgan bo‘lishi kerak.

**Muallif:** wave 7 agenti • **Matn tasdiqlandi:** 17.09.2026 • **Manbalar tekshirilgan sana:** 17.09.2026
**Spec:** §5.2 (“Pilot limiti va taqiqlangan jo‘natmalar ro‘yxati admin sozlamasida beriladi”), AGENTS §9.

> **Muhim huquqiy izoh.** Quyidagi bandlar ochiq rasmiy manbalardan olingan **texnik loyiha**dir. Bu yuridik
> xulosa emas. Elchi — litsenziyalangan pochta operatori emas, balki shahar aro avtomobil yuk/yo‘lovchi
> marketplace’i, shuning uchun pochta qoidalari **avtomatik** qo‘llanmaydi (pastdagi “Nega bu manba” ustuniga
> qarang). **Mahsulot egasi matnni tasdiqladi, lekin yurist xulosasi hamon olinmagan** — bu band go-live
> checklist’ida ochiq turibdi va uni dasturchi agent yopa olmaydi.

## 1. Nima uchun mexanizm allaqachon yopiq holatda

| Savol | Javob (kod bilan) |
|---|---|
| Ro‘yxat qayerdan olinadi? | `parcel_policy_versions` + `parcel_policy_items` (migratsiya `20260917_0070`) — versiyalangan, `super_admin` tasdiqlaydi |
| Qanday versiyalanadi? | Bir vaqtda faqat **bitta** `active` versiya (partial unique indeks); yangisi tasdiqlanganda eskisi `superseded` bo‘ladi |
| Foydalanuvchiga qanday ko‘rsatiladi? | `GET /api/v2/parcel-policy` — autentifikatsiyasiz o‘qiladi, chunki jo‘natuvchi e’lon yozishdan **oldin** ko‘rishi kerak |
| E’lon yaratishda qanday qo‘llanadi? | Pochta e’lonini **nashr qilish** va yangi pochta **broni** (accept) tasdiqlangan siyosat bo‘lmasa production’da `503 PARCEL_POLICY_UNCONFIRMED` bilan rad etiladi |
| Bo‘sh ro‘yxat “hammasi mumkin” degani emasmi? | Yo‘q: `approved=false` holatida **yangi** pochta biznesi yopiladi (fail-closed). Mavjud bronlar, yetkazish, dalil, nizo va support yo‘llari tegilmaydi (D16 majburiyat qoidasi) |
| Nima uchun “prohibited” bandiga manba majburiy? | DB CHECK: `category='prohibited'` qatorida `legal_basis` va `source_ref` bo‘lmasa yozib bo‘lmaydi — platforma “bu taqiqlangan” deb asossiz aytmaydi |

## 2. Manbalar (17.09.2026 da tekshirilgan)

| # | Manba | Nega bu manba | Elchi’ga munosabati |
|---|---|---|---|
| M1 | [Pochta aloqasi to‘g‘risida, O‘RQ-777, 09.06.2022](https://lex.uz/uz/docs/-6058066) | Pochta jo‘natmalarida taqiqlangan/cheklangan predmetlar ro‘yxati shu qonun asosida tasdiqlanadi | **Bilvosita**: Elchi pochta operatori emas; ro‘yxat mazmuni namuna sifatida olinadi |
| M2 | [Pochta aloqasi xizmatlarini ko‘rsatish qoidalari, 2219-son, 18.04.2011 — 3-ilova](https://lex.uz/docs/-1772402) | “Jo‘natilishi taqiqlangan va cheklangan predmetlar va moddalar ro‘yxati” aynan shu ilovada | **Bilvosita**, lekin toifalar manbai |
| M3 | [Xavfli yuklarni avtomobil transportida tashish qoidalari, VM 35-son, 16.02.2011](https://lex.uz/uz/docs/-1746717) | Elchi aynan avtomobil transporti; xavfli yuk uchun ruxsatnoma, belgilash, haydovchi tayyorgarligi talab qilinadi | **Bevosita**: pilotda xavfli yuk umuman qabul qilinmaydi |
| M4 | [Qurol to‘g‘risida, O‘RQ-550, 29.07.2019](https://lex.uz/docs/-4445288) | Qurol va o‘q-dorilar muomalasi | **Bevosita** taqiq asosi |
| M5 | Giyohvandlik vositalari va psixotrop moddalar to‘g‘risidagi qonunchilik ([sud amaliyoti sharhi](https://lex.uz/docs/-3203265)) | Nazorat ostidagi moddalar | **Bevosita** taqiq asosi |

**Tekshirilmagan/aniqlanmagan:** 2219-son qoidalarning 3-ilovasi to‘liq matni ochiq sahifadan mashina o‘qiy
oladigan holda olinmadi (PDF/tuzilma cheklovi). Shu sababli quyidagi jadval **toifalar darajasida** tuzilgan;
har band matnini yurist asl ilova bilan solishtirishi kerak.

## 3. Loyiha ro‘yxat (tasdiqlanmagan)

Toifalar: **prohibited** — qonun bilan taqiqlangan; **restricted** — ruxsat/shart bilan mumkin (pilotda qabul
qilinmaydi, keyin ochilishi mumkin); **business_declined** — qonun taqiqlamaydi, lekin Elchi pilotda olmaydi.

| Kod | Toifa | Qamrov | Foydalanuvchiga ko‘rinadigan tavsif | Asos | Manba |
|---|---|---|---|---|---|
| `weapons_ammunition` | prohibited | all | Qurol, o‘q-dori, pnevmatik va sovuq qurol, elektroshoker | Qurol muomalasi qonun bilan tartibga solingan; maxsus ruxsatsiz tashish taqiqlanadi | M4, M2 |
| `explosives_pyrotechnics` | prohibited | all | Portlovchi moddalar, portlatish qurilmalari, pirotexnika | Portlovchi moddalar — xavfli yuk; maxsus ruxsat va jihoz talab qilinadi | M3, M2 |
| `narcotics_psychotropic` | prohibited | all | Giyohvandlik vositalari, psixotrop moddalar va prekursorlar | Nazorat ostidagi moddalar muomalasi taqiqlangan | M5, M2 |
| `radioactive_toxic` | prohibited | all | Radioaktiv, zaharli va kuchli ta’sir qiluvchi moddalar | Xavfli yuk sinflari; maxsus tashish rejimi | M3, M2 |
| `flammable_gas_fuel` | prohibited | all | Yonuvchi suyuqlik va gaz (benzin, ballon, aerozol, o‘t oldiruvchi) | Xavfli yuk; oddiy yengil avtomobilda tashish ruxsat etilmaydi | M3 |
| `live_animals` | restricted | all | Tirik hayvonlar | Veterinariya hujjati va maxsus shart talab qilinadi; pilotda qabul qilinmaydi | M2 |
| `human_remains_biological` | prohibited | all | Inson qoldiqlari, biologik namunalar va tibbiy chiqindi | Maxsus tartib va ruxsat talab qilinadi | M2 |
| `cash_bearer_valuables` | business_declined | all | Naqd pul, bank kartalari, qimmatbaho metall va toshlar, zargarlik | Elchi javobgarlikni sug‘urtalamaydi; nizo xavfi yuqori (§5.2 “e’lon qilingan qiymat sug‘urta emas”) | Elchi siyosati |
| `documents_originals_critical` | restricted | parcel | Pasport, diplom va boshqa asl hujjatlar | Yo‘qolganda tiklab bo‘lmaydi; pilotda faqat ogohlantirish bilan, keyin alohida shart | Elchi siyosati |
| `alcohol_tobacco_excise` | restricted | parcel | Aksiz osti tovarlari (alkogol, tamaki) | Aksiz markasi va savdo qoidalari talab qilinadi | M2 (tekshirish kerak) |
| `medicines_prescription` | restricted | parcel | Retsept bo‘yicha beriladigan dori vositalari | Dori muomalasi litsenziyalangan; pilotda qabul qilinmaydi | M2 (tekshirish kerak) |
| `perishable_unpackaged` | business_declined | parcel | Tez buziladigan, sovutish talab qiladigan mahsulot | Sovutish zanjiri yo‘q; sifat kafolatlanmaydi | Elchi siyosati |
| `oversized_over_pilot_limit` | business_declined | parcel | Pilot chegarasidan katta yuk (50 kg, 150 sm, 0,5 m³ dan ortiq) | Haydovchi yolg‘iz yuklay olmaydi; alohida transport kerak | Elchi siyosati (`app/contracts/marketplace.py`) |

**Qamrov haqida:** M3 (xavfli yuk) avtomobil tashishga bevosita tegishli, shuning uchun `all`. Aksiz, dori va
hujjat kabi bandlar **faqat pochta jo‘natmasiga** (`parcel`) qo‘yilgan — yo‘lovchining shaxsiy bagajiga
avtomatik tatbiq etilmaydi, chunki bu boshqa huquqiy munosabat.

## 4. Qaror uchun savollar

1. Ro‘yxat toifalari va matnlari tasdiqlanadimi (yurist tekshiruvidan keyin)?
2. `restricted` bandlar pilotda **butunlay yopiq** bo‘lsinmi yoki ogohlantirish bilan ochiqmi?
3. `business_declined` bandlar (naqd pul, tez buziladigan mahsulot) shu holicha qoladimi?
4. Ro‘yxat tasdiqlangunicha pochta xizmati production’da **yopiq** turishi qabul qilinadimi? (Hozirgi xulq shu.)

## 5. Tasdiqlashdan keyingi qadamlar

```bash
# 1. Qoralama yuklash (super_admin A)
py scripts/seed_parcel_policy_draft.py --actor-user-id <A> --label "pilot-2026-09"
# 2. Boshqa super_admin (B) tasdiqlaydi
#    POST /api/v2/admin/parcel-policies/{policy_id}/confirm  {"expected_version": 1}
# 3. Tekshirish: GET /api/v2/parcel-policy -> approved=true, items ro'yxati
```
