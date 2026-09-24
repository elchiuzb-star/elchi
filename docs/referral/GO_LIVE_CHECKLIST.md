# Referral / promo — go-live checklist (qaror uchun)

Holat: 24.09.2026 — **referral moduli lokal yakunlangan, production gate’lari yopilmagan.** `promotions_enabled = false`,
kampaniyalar `draft`. Bu hujjat ruxsat emas: qaysi dalil yig‘ilishi va kim qaror qilishi kerakligini ko‘rsatadi. Mas’ul **rol**
bilan yozilgan; aniq shaxs nomi berilmagan.

Belgilar: ✅ lokal dalil bor · ⏳ ochiq · ⛔ ishga tushirishni to‘sadi · ⚠️ pilotni cheklaydi.

Bog‘liq: [QA_REPORT.md](QA_REPORT.md), [simulation/REPORT.md](simulation/REPORT.md) (sintetik), [INFRA_HANDOFF.md](INFRA_HANDOFF.md),
[APP_LINKS_HANDOFF.md](APP_LINKS_HANDOFF.md), ADR-0023 §19–§20.2, AGENTS.md Q130–Q135.

## A. Bandlar

| # | Band | Holat | Zarur dalil | Mas’ul rol | Tekshirish usuli | Ta’sir |
|---|---|---|---|---|---|---|
| G1 | `promotions_enabled` production’da yoqish | ✅ o‘chiq; yoqish guard’i bor | approval reference + admin API markeri + Q48 gate | super_admin | gate’siz yoqish rad etiladi (PG testi) | ⛔ ataylab |
| G2 | Q48 gate production’da (Q36 DB rollari, balans guard, Q55, Q28 seed stavka) | ⏳ | `platform_q48_gate_passed()` = true production DB’da; deploy jurnali | infra + finance | `/health/ready`, gate funksiyasi | ⛔ v2 pul oqimi yo‘q |
| G3 | Yo‘lovchi xizmati (A varianti — faqat kelajakdagi pilot nomzodi, Q130) | ⏳ | K7/Q5/Q89 huquqiy tekshiruv, super_admin approval reference, Q87 support telefoni va ish vaqti | yuridik + super_admin + ops | koridor bo‘yicha `passenger_enabled`, approval reference | ⛔ |
| G4 | Telefon HMAC siyosati (Q108, Q118) | ⏳ **ochiq (Q133)** — muddat va huquqiy asos tasdiqlanmagan | maqsad, huquqiy asos, saqlash muddati, o‘chirish, kalit boshqaruvi hujjati; maxfiylik siyosati bandi | yuridik + xavfsizlik egasi | konfiguratsiyada muddat; kalit secret store’da | ⛔ production enrollment (mavjud cheklov saqlanadi); muddat simulyatsiya yoki texnik qulaylik bilan tanlanmaydi |
| G5 | Marketing parametrlari: mukofot, O, M, cap’lar, qualification oynasi, amal muddati, grace | ⏳ **tasdiqlanmagan (Q133)** | haqiqiy pilot qarori; tasdiqlangan kampaniya versiyasi (`approval_reference`) | mahsulot egasi + finance + super_admin | `missing_for_activation` bo‘sh, `validate_activation` o‘tadi | ⛔ sintetik qiymat production standarti emas |
| G6 | Budjet manbai va ajratma | ⏳ tasdiqlanmagan | aniq manba (kelajak daromadi emas); finance so‘rovi, katta summada ikkinchi finance tasdig‘i | finance (2 kishi) | `promo_budget_requests` posted | ⛔ |
| G7 | Rate-limit (kod tekshiruvi IP/daq., attribution foydalanuvchi/soat — taklif) | ⏳ **alohida ochiq band** | so‘rovlar soni **va** umumiy IP (operator NAT) ortidagi haqiqiy foydalanuvchilar, qayta urinishlar, halol foydalanuvchi bloklanish ehtimoli | ops + xavfsizlik | pilot jurnali / yuklama sinovi, `promo_rate_events` rad soni | ⚠️ mavjud himoya saqlanadi |
| G8 | Review SLA va operator ish hajmi | ⏳ **alohida ochiq band** (SLA sintetik 72 soat) | kutilgan review soni/kun, review navbatidagi ish hajmi, operator sig‘imi; eskalatsiya ishlashi | ops rahbari | hisobot `pending_review_minor`, navbat yoshi, `escalate_reviews` jurnali | ⛔ review qilinmasa mukofot kutadi (avtomatik grant yo‘q) |
| G9 | Xodim MFA faktorlari (kampaniya, budjet, review qarorlari real step-up talab qiladi) | ⏳ ADR-0021 Proposed | finance (2), super_admin, review qiluvchi admin’da faol TOTP | super_admin | step-up bilan budjet so‘rovi | ⛔ qarorlar yopiq |
| G10 | Havola: domen, DNS, TLS, rewrite, `landing/r.html` | ⏳ handoff tayyor | INFRA_HANDOFF’dagi `curl` natijalari, sertifikat zanjiri | infra | handoff buyruqlari | ⚠️ qo‘lda kod kiritish ishlaydi |
| G11 | Android App Links | ⏳ `android-app` muzlatilgan — Android dasturchi | release imzo SHA-256, `assetlinks.json`, qurilmada `pm get-app-links` | Android dasturchi | APP_LINKS_HANDOFF | ⚠️ |
| G12 | `mobile-app` release (promo UI, `promo_cash_v1`) | ⏳ | tarqatiladigan build; haqiqiy qurilmada rozilik → accept → naqd → capture | mobil jamoa + QA | qurilma sinovi yozuvi | ⛔ |
| G13 | Q127: siyosat qamramagan bonus tiklash holatlari | ⏳ **qaror jadvali §E** | har holat uchun kompensatsiya siyosati (bor/yo‘q) | mahsulot + finance | `restoration_uncovered` review’lari | ⚠️ erkin bonus berish yo‘q; admin texnik vakolati siyosat emas |
| G14 | Budjetni kamaytirishning pastki chegarasi | ✅ **lokal bajarildi (Q132, migratsiya 0090)** | `B ≥ S + L`; `funding_loss` alohida | — | `test_promo_budget_floor_pg.py` (8), `test_promo.py::test_g14_*` | production’da 0090 deploy qilinganda |
| G15 | Monitoring va ogohlantirishlar | ⏳ | `budget_shortfall`, review eskalatsiyasi, reconciliation bo‘sh emasligi, `pause_exhausted_campaigns` — production ogohlantirish kanalida | infra + ops | sinov ogohlantirishi | ⛔ incidentlarni aniqlab bo‘lmaydi |
| G16 | Finance navbati (Q74: har yakunlangan bron `finance_review`) | ⏳ | finance sig‘imi; capture kechikishi o‘lchanadi | finance | hisobot `net_commission_agreed` vs `captured` | ⚠️ |
| G17 | Kampaniya shartlari matni (disclosure) | ⏳ | yuridik ko‘rilgan matn | yuridik + mahsulot | ilova ekrani | ⛔ |
| G18 | Qo‘shimcha foydalanuvchini o‘lchash dizayni | ⏳ **tasdiqlanmagan (Q134)** — §B | tanlangan dizayn, metrika ta’riflari, qaror chegarasi | mahsulot + analitika | — | ⛔ pilotdan xulosa chiqmaydi |
| G19 | To‘xtatish mezonlari | ⏳ **umumiy tasdiqlanmagan (Q135)** — §C | texnik incidentlar ro‘yxati bor; biznes chegaralari dalil bilan alohida | mahsulot + finance + ops | pauza/suspend mashqi | ⛔ |
| G20 | Pochta referral bonusi | ✅ **qaror: hozircha yoqilmaydi (Q131)** — vaqtinchalik | haqiqiy qayta buyurtma va bonus foydalanish ma’lumoti paydo bo‘lgach qayta ko‘riladi | mahsulot egasi | — | pochta kampaniyasi o‘chiq; mexanizm kodda |

Lokal bajarilgan (production dalili emas): QA #1–#24 — [QA_REPORT.md](QA_REPORT.md); simulyator (sintetik); operatsion admin
hisobot `GET /api/v2/admin/promo/report`; to‘xtatish mexanizmlari (kampaniya `pause`, ishlovni `suspend`, avtomatik
`pause_exhausted_campaigns`, `funding_loss` pauzasi); G14.

## B. Qo‘shimcha foydalanuvchini o‘lchash (Q134 — dizayn tasdiqlanmagan)

Kod bilan kelgan har bir foydalanuvchi qo‘shimcha emas; attribution soni qo‘shimcha jalb qilinganlar soni deb olinmaydi.
Simulyatsiyada A varianti faqat qo‘shimcha foydalanuvchi taxmini yetarli bo‘lsa o‘zini oqlaydi — shuning uchun o‘lchash pilotdan
oldin tanlanadi.

**Variantlar (hech biri tanlanmagan):**
1. **Koridor bo‘yicha nazorat** — kampaniya bir koridorda, boshqasi nazorat, oldingi davr bilan farqlar farqi. **Cheklov:** pilotdagi
   2–3 koridor talab hajmi, narx darajasi, haydovchi ta’minoti va mavsumiylikda farq qiladi; bu farqlar referral ta’siri bilan
   aralashadi, 2–3 birlik esa statistik ishonch bermaydi. Kamaytirish yo‘llari: oldingi davr trendini tekshirish, koridorlar
   bo‘yicha navbatma-navbat yoqish (stepped rollout), oldingi davr ko‘rsatkichlari bo‘yicha solishtirish — baribir to‘liq ajratmaydi.
2. **Taklif qiluvchi darajasida holdout** — kod berish imkoniyati tasodifiy ulushga shartlar *ko‘rsatilmasdan oldin* ochiladi.
   Cheklov: tarmoq aralashuvi.
3. **Qo‘shimcha signallar** (sabab emas): ro‘yxatdan o‘tishdan oldingi faollik, telefon digest mosligi (Q108 doirasida), birinchi
   bron tezligi.

**Har qanday dizaynda:** nazorat tashkil qilish allaqachon berilgan va’da, bonus yoki kelishilgan chegirmani buzmaydi (shartlarni
ko‘rgan hech kim nazoratga o‘tkazilmaydi); metrika langarlari A6.2 bo‘yicha oldindan qayd etiladi; D60 yetilmagan cohort bo‘yicha
xulosa chiqarilmaydi; simulyatorning seed tarqalishi haqiqiy ishonch oralig‘i o‘rnini bosmaydi.

## C. To‘xtatish (Q135 — umumiy mezonlar tasdiqlanmagan)

**Texnik incidentlar** — bitta holat ham incident (sonli chegara emas):
- takroriy undirish (bitta bronda ikki capture/consume, hold ≠ kelishilgan C_net, naqd kvitansiya ≠ F_cash);
- ruxsatsiz grant (qualification yoki tasdiqlangan review’siz lot, va’dasiz lot);
- ledger tafovuti (`GET /admin/promo/reconciliation` bo‘sh emas, `promo_budget_cache_mismatch`);
- majburiyat chegarasining buzilishi (`funding_loss` qayd etilmagan holda `B < S + L`, manfiy bucket).

Javob: ta’sirlangan xavfli operatsiyalar cheklanadi — kampaniya ishlovi `suspend` (qualification/grant/expiry to‘xtaydi),
kampaniya `pause` (yangi enrollment yo‘q), kerak bo‘lsa yangi promo bitimlar uchun `promotions_enabled` o‘chiriladi. **Mavjud bron
narxi o‘zgarmaydi, majburiyatlar va berilgan bonuslar o‘chirilmaydi**, sabab aniqlanguncha tuzatish faqat asoslangan ledger
operatsiyasi bilan.

**Biznes chegaralari** — review navbati hajmi, CAC, refund/reversal ulushi, budjet ogohlantirish foizi: sonli qiymatlar
**tasdiqlanmagan**; pilot ma’lumoti va operator/finance sig‘imi dalili bilan alohida tasdiqlanadi.

## D. Foydalanuvchidan kerak bo‘lgan qarorlar (ochiq)

G4 (Q108 HMAC muddati va huquqiy asos) · G5–G6 (parametrlar, budjet manbai) · G7–G8 (rate-limit, review SLA — trafik va sig‘im
dalilidan keyin) · G13 (§E jadvalidagi siyosatlar) · G18 (o‘lchash dizayni) · G19 (biznes to‘xtatish chegaralari) · G3 va G12
(yo‘lovchi va klient release gate’lari).

## E. Q127 — siyosat qamramagan bonus tiklash holatlari (qaror jadvali)

Umumiy “bonus berish” tugmasi yo‘q. Siyosat aniq belgilagan holatlar bog‘langan operatsiya orqali bajariladi (pastdagi “qamralgan”).
Qamralmagan holatda operator dalil yig‘adi, vakolatli admin ko‘rib chiqadi; review qarori o‘zi qiymat ko‘chirmaydi va adminning
texnik vakolati yangi kompensatsiya siyosati hisoblanmaydi. Haqiqiy pul qarzi avtomatik yaratilmaydi (QA #16).

| # | Sabab | Bonus egasi | Sarflangan / rezerv qismi | Mavjud siyosat | Yetishmayotgan qaror |
|---|---|---|---|---|---|
| E1 | Komissiya reversal’i (qisman yoki to‘liq), bronda P sarflangan (`restoration_uncovered`, `commission_reversed`) | mijoz (P) | sarflangan P (capture bilan `consumed`); rezerv yo‘q | reversal bonusni tiklamaydi (Q127); review ochiladi | P qaytariladimi, qaysi holatda (kimning aybi), qaysi budjetdan, qanday dalil bilan |
| E2 | Xuddi shu, bronda H sarflangan | haydovchi (H) | sarflangan H | xuddi E1 | H qaytariladimi; haydovchi reversal’da real pulni olgan bo‘lsa, kreditni ham qaytarish ikki marta kompensatsiya emasmi |
| E3 | Nizo hal qilindi, bronda P/H sarflangan (`dispute_resolved`) | mijoz va/yoki haydovchi (har ega alohida) | sarflangan P/H | nizo naqd natijasi — alohida (Q78, Q84); bonus bo‘yicha review | nizo natijasiga qarab bonus tiklash qoidasi (g‘olib/aybdor tomon bo‘yicha) |
| E4 | Grant’dan keyingi fraud reversal, keyin review “firibgarlik emas” deb topdi | lot egasi | reversal paytidagi sarflanmagan qism `reversed` (terminal); sarflangan qism risk xarajati | `reversed` holat qaytarilmaydi | noto‘g‘ri reversal uchun kompensatsiya: yangi majburiyat (budjetdan, auditli) yoki yo‘q |
| E5 | Tasdiqlangan reinstate budjet joyi yo‘qligi sabab bajarilmagan (`reinstate_unfulfilled`) | lot egasi | muddati o‘tgan summa; L ga kiradi (G14) | reinstate faqat budjet joyi bilan, qisman emas (Q122); eskalatsiya | budjetga qo‘shimcha ajratma qilinadimi yoki rad etiladimi — finance qarori |

**Qamralgan (siyosat bor, bog‘langan operatsiya):** bekor qilishda adolatli tiklash va `undetermined` sabab uchun grace (Q129,
`cancel_fault` review); muddati o‘tgan qiymatni reinstate (Q122, budjet joyi bilan); nizo/reversal’dan tashqari oddiy bekor
qilishda rezervni qaytarish (QA #14).
