# ADR-0023: Promotions & referral — bonus, kredit va budjet

**Holat:** Accepted — moliyaviy kontrakt (Q101–Q110), 1-bosqich (Q111–Q116), 2-bosqich (Q117–Q119), 3-bosqich talqinlari (Q120–Q122, §17), 23.09.2026. 4-bosqich (bron integratsiyasi) — §18; T4 qarorlari Q123–Q129 (§18.1). 5-bosqich — §19. 6-bosqich alohida tasdiqlanadi.
**Sana:** 23.09.2026 • **Topshiriq:** [`docs/referral/ELCHI_REFERRAL_TASK.md`](../../referral/ELCHI_REFERRAL_TASK.md) • **Reja:** [`REFERRAL_PLAN.md`](../../referral/REFERRAL_PLAN.md)
**Spec:** §9.2, §9.4, §11, §15, §16 (kengaytma — spec o‘zgartirilmaydi) • **Qarorlar:** Q16, Q17, Q48, Q55, Q60, Q101–Q129
**Migratsiya:** `20260923_0084_promotions_core` (1-bosqich), `20260923_0085_promotions_referral` (2-bosqich), `20260923_0086_promotions_qualification` (3-bosqich), `20260923_0087_promotions_booking` (4-bosqich), `20260923_0088_promotions_rate_events`, `20260923_0089_promotions_t4` (5-bosqich), `20260924_0090_promotions_budget_floor` (6-bosqich, G14) • **Modul:** `app/modules/promotions/` (models, service, identity, referral, qualification, jobs, booking, portal, api, schemas)
**Kontrakt:** [`app/contracts/promo.py`](../../../app/contracts/promo.py), `enums.Promo*`, `state_machines.PROMO_MACHINES`, `ErrorCode.PROMO_*`/`REFERRAL_*`; testlar `tests/contracts/test_promo.py`

## Kontekst
Spec §9.2 pilot rag‘batini faqat muddatli “0% yoki kamaytirilgan komissiya” kampaniyasi (`commission_policies.kind = campaign`, ADR-0009) sifatida ko‘radi. Referral, bonus va kredit spec’da yo‘q. Mijoz tashish haqini haydovchiga **naqd** to‘laydi; platformadagi yagona haqiqiy pul — haydovchining komissiya uchun oldindan to‘ldirgan balansi (wallet, ledger, Q55). Referral bu balansni ham, mijozning naqdini ham buzmasligi kerak.

## Qaror

### 1. Domen va chegaralar (Q101, Q102)
- Yangi modul `app/modules/promotions/` (AGENTS.md §4 ro‘yxatiga qo‘shiladi). Boshqa modul jadvallariga faqat ularning `service.py` orqali; bron orkestratori (A4) promotions servisini chaqiradi, aksincha emas.
- Hisoblash kontrakti — sof `app/contracts/promo.py`: DB, tarmoq, sozlama va soat yo‘q; barcha parametr aniq argument.
- Uch qiymat turi qat’iy ajratiladi:

| Tur | Qayerda | Nima | Nima emas |
|---|---|---|---|
| Driver prepaid balance | wallet, real ledger | tekshirilgan real pul kirimi, komissiya uchun | earnings hamyoni emas |
| Passenger Bonus | promotions, promo ledger | mijozning keyingi mos xizmatda naqd chegirma huquqi | pul emas, naqdlashtirilmaydi, o‘tkazilmaydi |
| Driver Credit | promotions, promo ledger | haydovchi komissiyasini kamaytirish huquqi | real balansga aylanmaydi, yechilmaydi |

- Pilotda referral uchun naqd payout yo‘q. Bonus tovar qiymati, haydovchi naqd tushumi yoki boshqa xizmatni moliyalashtirmaydi.

### 2. Xizmatlar va flag’lar (Q101, Q109)
- Bitta umumiy mexanizm yo‘lovchi va pochtaga xizmat qiladi, lekin **kampaniya, qualification sharti va limitlar xizmat turi bo‘yicha alohida** (`CampaignTerms.service_type`). Lot faqat o‘z xizmat turida sarflanadi (`lot_usable_for`); xizmatlararo sarflash avtomatik yoqilmaydi.
- Pilot turlari: `referral_client_client`, `referral_driver_driver`, `referral_driver_client` (`PILOT_CAMPAIGN_KINDS`). `cashback`, `reactivation`, `corridor_bonus`, `loyalty` — tuzilma bor, aktivlashtirish rad (`FEATURE_DISABLED`).
- Yangi flag `promotions_enabled` (1-bosqich migratsiyasi): production default `false`. U hech bir mavjud flag’ni yoqmaydi; promo faqat tegishli xizmat flag’i (`passenger_enabled`/`parcel_enabled`) ham yoqiq joyda ishlaydi. Flag o‘chiq bo‘lsa bron oqimi aynan bugungidek (QA #23).
- Kampaniyalar `draft` holatida tug‘iladi; tasdiqlangan budjet va parametrlarsiz aktivlashtirilmaydi (Q105).

### 3. Moliyaviy model (Q110)
F kelishilgan narx, `C = money.commission_minor(F, fee_bps)`, P mijoz bonusi, H haydovchi krediti, O tasdiqlangan o‘zgaruvchan xarajat + rezerv, M minimal marja.

```
F_cash = F − P                    mijoz haydovchiga beradigan naqd
C_net  = C − P − H                haydovchining real balansidan hold/capture qilinadigan yagona summa
haydovchida qoladi = F_cash − C_net = F − C + H
```
Majburiy: `F_cash ≥ 0`, `C_net ≥ 0`, promo bronda `C_net − O ≥ M`, `P + H ≤ min(floor(C · share_bps/10000), per_booking_cap)`, P ≤ mijozning mos mavjud bonusi va roziligi, H ≤ haydovchining mos mavjud krediti.
- Yaxlitlash: C — `commission_minor` (half-up, o‘zgarmaydi); barcha chegaralar platforma foydasiga (cap — pastga, xarajat — yuqoriga). Float yo‘q.
- C = 0 (0 bps kampaniya) yoki `C − O − M ≤ 0` bo‘lsa chegirma 0; bonus egasida qoladi (QA #12).
- Aktivlashtirishda `M > 0` majburiy → promo bronda `C_net ≥ O + M > 0`, nol summali hold yo‘q.
- `None` parametr hech qachon 0 deb o‘qilmaydi → `PROMO_PARAMETERS_UNSET`.
- **Ogohlantirish:** bron darajasidagi marja qoidasi kompaniyaning umumiy foydasini kafolatlamaydi. Doimiy xarajatlar, firibgarlik, refund, noto‘g‘ri O bahosi va qaytmagan consumed bonuslar bu qoidadan tashqarida; 6-bosqich simulyatori ularni alohida ko‘rsatadi.

### 4. Yagona quote va rozilik (Q104)
- `quote_promo` P, H, O, M, share va cap’larni birgalikda hisoblaydi; P birinchi (mijoz tasdiqlagani saqlanadi), H qolgan imkoniyatni oladi.
- Mijoz taklif yuborayotganda yoki counter’ni qabul qilayotganda bonusni tanlaydi → `PassengerBonusConsent {proposal_version_id, F, P, F_cash, quote_fingerprint, expires_at}`. Haydovchi mijozsiz accept qilganda `quote_at_accept` aynan shu P ni qo‘llaydi; boshqacha natija (bonus kamaygan, muddat, narx, versiya) → `409 PROMO_QUOTE_STALE`, bron yaratilmaydi, mijozdan yangi rozilik. Naqd summa hech qachon yashirin oshmaydi (QA #13).
- H — oldindan e’lon qilingan qoida bo‘yicha accept’da avtomatik; u mijoz naqdini o‘zgartirmaydi. Haydovchiga H “X so‘mgacha” deb ko‘rsatiladi; C_net hech qachon C dan oshmaydi.
- Pochta pilotida bonus egasi = jo‘natuvchi = to‘lovchi. Qabul qiluvchi to‘laydigan buyurtmada jo‘natuvchi bonusi ishlatilmaydi (`passenger_bonus_allowed`).
- Quote’da `contract_version`; formula o‘zgarsa versiya oshadi va eski rozilik eskirgan hisoblanadi.
- Amendment: yangi quote qayta hisoblanadi; `amendment_reconfirmation` — F, P yoki F_cash o‘zgarsa mijoz, F_cash yoki C_net o‘zgarsa haydovchi qayta tasdiqlaydi. Narx kamayib cap tushgani sabab F_cash oshishi alohida test qilinadi.

### 5. Kim nimani ko‘radi (Q103, Q16)
- Mijoz: `fare_minor`, `passenger_discount_minor`, `cash_due_minor`, `currency` (`CLIENT_PROMO_VIEW_KEYS`). Stavka, C, H, O, M, formula va limit sabablari — API va event’da yo‘q; “nega kamroq” — umumiy matn (“safar shartlari bo‘yicha”).
- Haydovchi: naqd olinadigan summa, bazaviy komissiya, mijoz chegirmasi kompensatsiyasi, ishlatilgan kredit, undiriladigan komissiya, qoladigan summa (`DRIVER_PROMO_VIEW_KEYS`). O va M haydovchiga ham ko‘rsatilmaydi.
- Bu qoida komissiyani **bevosita** oshkor qilmaslikni bildiradi; mijoz uni hech qachon taxmin qila olmaydi degan kafolat berilmaydi. Narx yoki chegirma haqida noto‘g‘ri ma’lumot ko‘rsatilmaydi.

### 6. Ledger va hisobot
- Real ledger’ga faqat **C_net** hold/capture (`wallet_hold` manbasi, mavjud yo‘l). `LEDGER_SOURCE_TYPES` va Q55 trigger’i o‘zgarmaydi; referral real ledger’ga hech qachon kredit yozmaydi.
- Promo ledger (1-bosqich) — alohida double-entry jadval: budjet → va’da → berilgan → rezerv → consumed/released/expired/reversed. Har yozuv booking, lot, grant, kampaniya versiyasiga bog‘langan.
- Hisobot: gross commission (C) = net collected (C_net, real ledger) + passenger subsidy (P, promo ledger) + driver discount (H, promo ledger). Chegirma daromaddan bir marta ayriladi; reconciliation har bron uchun `C = C_net + P + H` ni tekshiradi (QA #24).
- **Q55/Q48 avtomatik yopilgan deb hisoblanmaydi:** 4-bosqich integratsiyasi booking, cash receipt, refund, finance review va gate tekshiruvlarini qayta isbotlaydi.
- Bronning promo moliyaviy snapshot’i (4-bosqich, §18): `bookings` jadvaliga ustun qo‘shilmadi — alohida append-only `promo_booking_terms` (F, bps, C, P, H, F_cash, C_net, O, M, fingerprint; `seq` 1 accept’da, har qabul qilingan amendment’da yangi qator). `bookings.commission_minor` = C bo‘lib qoladi, Q60 trigger’i o‘zgarmadi; bron `terms_snapshot.promo` markeri (muzlatilgan) promo shartlari borligini aytadi. Dastlabki reja (bookings ustunlari + Q60 kengaytmasi) o‘rniga shu tanlandi: A4 jadvali va muzlatish trigger’i tegilmaydi, amendment tarixi yo‘qolmaydi.
- Cash receipt summasi F_cash bilan solishtiriladi (`cash_receipt_matches`). Haydovchining “pul oldim” tasdig‘i bank settlement dalili emas.

### 7. Bekor qilish, muddat va reversal
- Xizmat boshlanmasdan bekor → redemption `released`, lot qiymati qaytadi, real hold C_net bo‘yicha bo‘shaydi.
- Adolatli tiklash (`restored_expiry`): haydovchi yoki platforma aybi bilan bo‘shagan va muddati tugagan/tugashiga `grace` dan kam qolgan qiymat `released_at + grace` gacha yashaydi. Mijoz aybida muddat uzaytirilmaydi. `grace` — kampaniya parametri.
- Reversal (`reversal_plan`): bo‘sh qism darhol budjetga qaytadi; bron’dagi rezerv shu bron bo‘shaganda reversal qilinadi; **consumed qism risk xarajati** — hech kimning real balansiga qarz yozilmaydi, budjetga qaytmaydi va qayta sarflanmaydi. Bir tarafning firibgarligi aloqasiz halol tarafni avtomatik jazolamaydi.
- Naqd refund platforma pul yubordi degani emas; bonus qaytishi naqd refund emas.

### 8. Budjet (Q105)
- Buckets (`BudgetPosition`): allocated, promised, granted (sarflanmagan, rezervdagilar bilan), consumed, released. `available_for_new = allocated − promised − granted − consumed`.
- Enrollment’da ikkala tomonning maksimal mukofoti (driver milestone’larda barcha bosqichlar) oldindan va’da rezerviga yoziladi; yetmasa `PROMO_BUDGET_EXHAUSTED` va kampaniya `paused` (`budget_exhausted`).
- Qualification → promise → granted (farq released). Sarflanganda granted → consumed bir marta. Consumed hech qachon qaytmaydi.
- Manba kamaysa (`reduce_allocation`) — `shortfall`: yangi enrollment to‘xtaydi, mavjud va’da va bonuslar saqlanadi, admin’da mas’ul bilan ko‘rsatiladi.
- Pauza mavjud bonus sarflashni taqiqlamaydi. Budjet manbai — tasdiqlangan marketing mablag‘i yoki allaqachon **olingan** komissiyaning ajratilgan qismi; top-up va kelajak LTV budjet emas.
- Lock (1-bosqichda aniqlashtirildi): har promo ledger yozuvi budjet qatorini **trigger ichida** yangilaydi (`promo_ledger_apply`), shuning uchun parallel yozuvlar shu qatorda navbatga turadi. Va’da va `reinstate` tekshiruvi qator yangilangandan keyin ishlaydi — ikki operatsiya oxirgi qoldiqni birga ola olmaydi (PG testi). Budjet qatori lock tartibida **oxirgi** promo guruh (13-band). Pilot hajmida bu issiq nuqta qabul qilinadi; kerak bo‘lsa consume uchun partitsiyalangan hisob keyinroq.

### 9. Attribution va identity (Q106, Q107, Q108)
- Bitta server-tasdiqlangan attribution, birinchisi yutadi; shu kod takror — idempotent; boshqa kod almashtirmaydi (`decide_attribution`). Operator tuzatishi faqat sabab + audit bilan.
- Oyna: telefon tasdiqlangan birinchi kirishdan 72 soat va birinchi bron accept’igacha, server vaqti. Akkauntni o‘chirib qayta ochish oynani yangilamaydi (boshlanish himoyalangan identifikator bo‘yicha saqlanadi).
- Uniqueness: `(identity_key, family)` — yo‘lovchi va pochta mijoz kampaniyalari `client_acquisition` oilasini bo‘lishadi; mavjud mijozning haydovchiga aylanishi `driver_acquisition` (driver onboarding’dan boshlanadigan alohida oyna, 2-bosqichda yoziladi). Reactivation mustaqil.
- Telefon HMAC (`crypto.derive_subkey(secret_key, "promo-identity")`): **anonim ma’lumot emas**, himoyalangan identifikator. Maqsad — yangi foydalanuvchi mukofotini takror olishning oldini olish. Saqlash muddati konfiguratsiya; qiymati huquqiy asos bilan tasdiqlanmaguncha production’da referral yoqilmaydi (go-live bandi). Moslik akkauntni va oddiy xizmatni bloklamaydi — faqat yangi foydalanuvchi mukofotini review’ga yuboradi (`identity_match_effect`), chunki raqam boshqa shaxsga berilgan bo‘lishi mumkin. Kalit rotatsiyasi N5 naqshida.
- Havola: `https://<ELCHI_REFERRAL_LINK_HOST>/r/<kod>` (default andoza `elchigo.uz`), kod tasodifiy, PII’siz. Ilova yo‘q/App Links ishlamasa — tushuntirish sahifasi va kodni qo‘lda kiritish. Domen, sertifikat va App Links tekshirilmaguncha “tayyor” deb yozilmaydi; `android-app` uchun faqat handoff hujjati.

### 10. Qualification (Q109, Q110)
- Barchasi shart: xizmat bajarilgan, naqd tasdiqlangan (`cash_status = acknowledged`), real balansdan **musbat C_net capture** qilingan, ochiq nizo yo‘q, bekor/refund yo‘q. Nominal 0% va chegirma sabab C_net = 0 bo‘lgan bronlar qualification bermaydi. GPS yoki “bajarildi” tugmasi yolg‘iz yetarli emas.
- Risk oynasi 48 soat — bajarilish, naqd tasdiq va capture’ning **eng oxirgisidan**; grant oldidan barcha holat qayta o‘qiladi. Oyna tugashi “firibgarlik yo‘q” degani emas.
- Taklif qiluvchi xizmat ko‘rsatgan bron attribution’ni hech bir taraf uchun qualify qilmaydi; oddiy bron sifatida taqiqlanmaydi.
- Yo‘lovchi: 1 ta mos bron; pochta: 2 ta mustaqil jo‘natma (Q113: alohida bron + o‘z qabul-topshirish qaydi + yetkazish dalili + capture; bitta trip’da bo‘lishi mumkin); bitta bronning ikki qutisi — bitta jo‘natma; bo‘lib yuborish shubhasi → review. Driver milestone: distinct trip, har trip’da referral zanjiriga bog‘lanmagan mijoz, `min_distinct_clients`.
- Review: SLA bilan (`review_due_at`), muddat o‘tsa eskalatsiya — avtomatik tasdiq ham, rad ham yo‘q. Operator review boshlaydi va izoh yozadi; qaror — admin+ (Q78 naqshi). Foydalanuvchiga progress va rad sababi tushunarli matnda, shikoyat yo‘li bilan.
- Antifraud signallari: versiyali `RISK_RULESET_V1` (Q113) — har signal uchun manba, ishonchlilik (eligibility / strong / weak), oqibat (reject / review / context / audit_only) va korrelyatsiya guruhi. Eligibility: o‘zini taklif, o‘zi bilan bitim → nomzod rad. Kuchli: identity kaliti mosligi, KYC/raqam qayta ishlatilishi, bog‘langan referral klasteri, GPS/vaqt ziddiyati → review. Kontekst: umumiy IP va shu IP tarmog‘i (bitta guruh), umumiy qurilma, oilaviy avtomobil, tez qayta ro‘yxat, takroriy juftlik, mantiqsiz xizmat, narx oshirish — faqat ≥2 **mustaqil** guruh → review. Hodisa replay — faqat audit (bizning retry). Bitta umumiy IP hech narsani o‘zgartirmaydi (QA #18). Yangi fingerprinting yoki biometrik baza yo‘q.

### 11. Eski klientlar (Q110)
- `X-Elchi-Client-Features: promo_cash_v1` — klient F_cash ni ko‘rsata olishini bildiradi; **xavfsizlik vakolati emas**, summa va huquq server qoidasidan.
- Yangi promo bitim faqat ikkala tomon klienti belgini e’lon qilgan bo‘lsa (`promo_new_deal_allowed`; qarshi tomon noma’lum → yo‘q). Mijoz roziligi bor, lekin qo‘llab bo‘lmasa → `PROMO_QUOTE_STALE` (bron yashirincha chegirmasiz yaratilmaydi).
- Mavjud promo bronda eski klient naqd bilan bog‘liq buyruqlarni (cash receipt, amendment) bajara olmaydi → `CLIENT_UPGRADE_REQUIRED`; chegirma olib tashlanmaydi.

### 12. Vakolatlar (Q105)
Yangi capability’lar (1-bosqich): `promo.campaign_manage` — yaratish, versiya, aktivlashtirish, pauza, yopish (super_admin); `promo.budget_allocate` — finance/super_admin, katta summa ikki **turli** xodim (Q17); `promo.fraud_review` — operator (review boshlash, izoh); `promo.fraud_decide` — admin+; `promo.report_read` — admin, finance, super_admin. Operator budjet yoki mukofot summasini o‘zgartira olmaydi. Budjetdan tashqari manual grant yo‘q. Admin sozlamasi arbitrary kod/SQL bajarmaydi. Har o‘zgarish `audit_logs`.

### 13. Lock tartibi (ADR-0017 kengaytmasi)
`… → bookings → booking bolalari → wallet_accounts → promo_campaigns (FOR SHARE / FOR NO KEY UPDATE) → promo_obligations → promo_lots (id ASC) → promo_redemptions → promo_budgets (faqat ledger trigger ichida) → wallet_holds / topup_requests / ledger_adjustment_requests`. Promo qatorlari FK ota bo‘lgani uchun `FOR NO KEY UPDATE` bilan olinadi (AGENTS.md §6). Accept (4-bosqich): sig‘im → booking → lot rezervlari → C_net hold — bitta tranzaksiya, `run_with_db_retry` ichida; rezerv budjet qatoriga tegmaydi. Capture yo‘lidagi `consume` wallet hold bilan tartibi 4-bosqichda PG race testi bilan isbotlanadi.

### 14. Idempotentlik
`reward_key(campaign_version, attribution, side, milestone)` va `qualification_event_key(kind, booking)` — DB unique; outbox `dedup_key` unique emasligi sababli dublikat himoyasi shu kalitlarga tayanadi. Redemption — booking bo‘yicha unique (`booking_id, lot_id`).

## 1-bosqich qarorlari (Q111–Q116, 23.09.2026)

- **Q111 — marja va yaxlitlash.** Promo qo‘llanadigan bronda `O ≥ 0`, `M > 0`, `C_net > 0` va `C_net − O ≥ M` — `PromoQuote.check_invariants` va kampaniya aktivlashtirish (servis + DB trigger + `ck_promo_campaign_versions_min_margin`). Oddiy va alohida tasdiqlangan 0 % bronlar bu qoidaga tushmaydi — ularga promo shunchaki qo‘llanmaydi. M o‘ylab topilmaydi; belgilanmagan bo‘lsa aktivlashtirish rad. Yaxlitlash: faqat **limitlar** pastga (share cap) / xarajat yuqoriga; tasdiqlangan mijoz chegirmasi hech qachon keyin kamaytirilmaydi — `quote_at_accept` rad etadi. Ledger, ekran va kvitansiya bitta `PromoQuote` butun sonlarini o‘qiydi. Bu umumiy foyda kafolati emas.
- **Q112 — taklif qiluvchi xizmati.** Taklif qiluvchi ko‘rsatgan bron ikkala tomon qualification’iga hisoblanmaydi, bu shart qo‘shilishdan **oldin** ko‘rsatiladi (`enrollment_disclosures`). Bunday bron referral’ni yopmaydi: qualification muddati ichida boshqa haydovchi bilan shart bajarilishi mumkin (`referral_can_still_qualify`). Attribution oynasi (72 soat) va qualification muddati — alohida tushunchalar.
- **Q113 — dalil va risk qoidalari.** Pochtada mustaqil jo‘natma = alohida bron + o‘z qabul-topshirish qaydi + yetkazish dalili + komissiya capture; bitta trip’dagi ikki haqiqiy jo‘natma ikkalasi hisoblanadi; bitta bronning qutilari — bitta. Bo‘lib yuborilgandek ko‘ringan bronlar review’ga (`SPLIT_SHIPMENT`), avtomatik chiqarilmaydi. Signallar sanalmaydi: `RISK_RULESET_V1` (versiyali) har signal uchun manba, ishonchlilik, oqibat va korrelyatsiya guruhini yozadi; bir guruhdagi signallar (IP + shu IP tarmog‘i) bitta dalil. Bitta umumiy IP hech narsani o‘zgartirmaydi; mustaqil kontekst guruhlari yoki kuchli dalil → review; aniq eligibility buzilishi (o‘zini taklif, o‘zi bilan bitim) → faqat nomzod rad, oddiy xizmat bloklanmaydi. Review natijasi, sababi va xodim harakati audit’da; SLA oshsa eskalatsiya — mukofot avtomatik yo‘qolmaydi va tekshiruvsiz berilmaydi. Risk oynasi 48 soat (Q110) — kampaniya parametri emas.
- **Q114 — ikki xodim qoidasi.** Budjet o‘zgarishi mavjud `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (100 000 000 tiyin = 1 000 000 so‘m; qat’iy **katta** bo‘lsa ikkinchi tasdiq; chegara teng — bir kishi) va Q69 `is_finance_approver` qoidasini qayta ishlatadi. Wallet’ning `ledger_adjustment_requests` jadvali real pul ledger’iga yozgani uchun uni promo budjetga ishlatib bo‘lmaydi — shuning uchun faqat shu qoidalarni takrorlovchi `promo_budget_requests` bor (yangi tasdiqlash mexanizmi emas): so‘rovchi ikkinchi tasdiqlovchi yoki rad etuvchi bo‘la olmaydi (DB CHECK), katta summa trigger darajasida ham tekshiriladi.
- **Q115 — bitta majburiyat bosqichlari.** Va’da rezervi, berilgan bonus va sarflangan bonus — bitta `promo_obligations` qatorining bosqichlari; budjetda promised → granted → consumed o‘tadi va bir marta sanaladi (`promo_obligation_reconciliation` view). Promo ledger o‘zgartirilmaydi (UPDATE/DELETE/TRUNCATE trigger bilan rad); tuzatish — yangi yozuv (`reduce_allocation`, `release_*`).
- **Q116 — bron’dan keyin bonus qo‘shilmaydi.** Bonus faqat dastlabki kelishuv va rozilik bilan qo‘llanadi. Amendment yo‘li saqlanadi: moliyaviy shartlar qayta hisoblanadi va qayta tasdiqlanadi; eski rezervni bo‘shatish, yangisini yaratish va rozilikni yangilash — bitta tranzaksiya, xatoda avvalgi kelishuv buzilmaydi (4-bosqich acceptance A4.6).

## 2-bosqich qarorlari (Q117–Q119, 23.09.2026)

- **Q117 — kod, attribution, enrollment.** Referral kodi — CSPRNG’dan 8 belgili ochiq identifikator (31 belgili noaniqliksiz alifbo), telefon/KYC/user_id’dan olinmaydi; DB’da unique, kolliziyada yangi kod bilan qayta urinish; egasi hech qachon o‘zgarmaydi (trigger); bekor qilish yoki almashtirish avvalgi attribution va majburiyatlarga tegmaydi. Kod tekshiruvi faqat `valid: bool` qaytaradi — noma’lum, bekor qilingan va faol bo‘lmagan egali kod bir xil javob beradi. **Attribution** = kim taklif qildi: `(referee, family)` bo‘yicha bitta, birinchisi yutadi, parallel ikki koddan bittasi (users lock + unique), 72 soat mijozda telefon tasdiqlangan ro‘yxatdan, haydovchida haydovchi roli olingan vaqtdan, birinchi qabul qilingan xizmatgacha; oyna chegaralari qatorda saqlanadi. Attribution va’da ham, rezerv ham emas. **Enrollment** = qaysi kampaniya versiyasi shartlari qabul qilindi: aniq kampaniya tanlanadi (hamma kampaniyada avtomatik emas), versiya, xizmat turi, oila, shartlar fingerprint’i, kirish vaqti va qualification muddati (kirishdan hisoblanadi) mahkamlanadi va trigger bilan o‘zgarmaydi; shu tranzaksiyada ikkala tomonning maksimal majburiyati rezerv qilinadi — budjet yetmasa enrollment ham, qisman va’da ham qolmaydi. Bir odam uchun oila bo‘yicha bitta tirik enrollment (identity va user bo‘yicha partial unique) — yo‘lovchi va pochta birgalikda; mijozning haydovchi bo‘lishi `driver_acquisition` oilasi orqali ochiq. Bir foydalanuvchining boshqa roli orqali o‘zini taklif qilishi — self-referral. Faol bo‘lmagan/bloklangan taklif qiluvchi bilan yangi enrollment yo‘q; avvalgilari o‘zgarmaydi. Birinchi xizmatdan keyin enrollment yo‘q (`referee_not_new`).
- **Q118 — idempotentlik va Q108 chegarasi.** Attribution va enrollment `Idempotency-Key` + so‘rov fingerprint’ini saqlaydi; bir xil kalit boshqa mazmun bilan — `IDEMPOTENCY_KEY_REUSED`. Telefon HMAC: normalizatsiya (`+998XXXXXXXXX`), `crypto.derive_subkey(secret, "promo-identity-key", version)`, `key_version`; kalit faqat xotirada. Rotatsiya: saqlangan eski versiyalar bilan qidiriladi, topilsa joriy versiya digest’i o‘sha identity’ga qo‘shiladi — tarix yo‘qolmaydi (eski versiyani konfiguratsiyadan olib tashlash tarixni yo‘qotadi — runbook bandi). Saqlash muddati tasdiqlanmagan (`APPROVED_RETENTION.after_deletion = None`): akkaunt o‘chirilganda digest’lar o‘chiriladi (v1 o‘chirish oqimidagi hook). Oqibat: o‘chirib qayta ochilgan akkaunt oldingi identity bilan bog‘lanmaydi — shuning uchun production’da enrollment Q108 tasdiqlanmaguncha **yopiq** (`enrollment_allowed`), identity kaliti yo‘q bo‘lsa hamma joyda yopiq; himoyani chetlab mukofot beradigan fallback yo‘q. Digest mosligi (qayta berilgan raqam ehtimoli) — akkaunt yoki xizmat bloklanmaydi, avtomatik enrollment yo‘q, review (3-bosqich).
- **Q119 — 1-bosqich dalillari aniqlashtirildi.** Migratsiya: toza bazada kutilgan obyektlar, 0083 → 0084 → 0085 bosqichma-bosqich upgrade toza o‘rnatish bilan bir xil katalog, head’da upgrade hech narsa ishlatmaydi — alohida testlar; stamp + qayta upgrade faqat kod idempotentligi, sxema dalili emas. DB himoyasi haqiqiy application roli bilan tekshirildi (15-band). Eskirgan chegirma faqat joriy accept urinishini rad etadi (`details.scope = "accept_attempt"`, `action = "requote"`); foydalanuvchi, e’lon va taklif rad etilmaydi.

### 15. Himoya chegarasi: DB va API
DB (application roli bilan tekshirilgan): budjet keshiga yozish (grant revoke + trigger), ledger’ni o‘zgartirish/o‘chirish/TRUNCATE, `session_replication_role`, trigger’ni o‘chirish, owner roliga o‘tish — rad; sessiya sozlamalari hech qanday vakolat bermaydi; nomlangan actor faol finance/super_admin bo‘lishi, katta o‘zgarishda ikki **turli** shaxs, ortiqcha sarf — DB’da majburiy; flag markeri va approval raqami production’da Q48 gate’siz yoqmaydi. **DB qila olmaydigan narsa:** application roli ulanishining ortida qaysi odam turganini autentifikatsiya qilish — ikki haqiqiy finance user nomi bilan yozilgan yozuvni DB qabul qiladi. Bu API qatlamining vazifasi (JWT sessiya, server hisoblagan capability, `promo.*` uchun MFA step-up) va har yozuv o‘zgarmas holda actor bilan qoladi (audit). Test bilan qayd etilgan (`test_boundary_the_db_cannot_authenticate_the_human_behind_an_app_connection`).

### 16. 5-bosqich uchun ommaviy kontrakt (hozir HTTP yo‘q)
- `GET /api/v2/me/referral-code` (auth) → `{code, share_url}`; `share_url` = `https://<ELCHI_REFERRAL_LINK_HOST>/r/<code>` (domen tekshirilmaguncha “tayyor” emas).
- `GET /api/v2/public/referral-codes/{code}` (auth’siz) → faqat `{valid}`; egasi haqida hech narsa; noma’lum/bekor/faol emas — bir xil javob va status; rate-limit: IP bo‘yicha daqiqasiga 30, global kuzatuv.
- `POST /api/v2/referrals/attribution` (auth, `Idempotency-Key`) `{code, audience}` → attribution public id; rad etilishi ro‘yxatdan o‘tishni bloklamaydi (klient xabar ko‘rsatadi, davom etadi); rate-limit: foydalanuvchi bo‘yicha soatiga 5.
- `GET /api/v2/referrals/campaigns/{id}/offer` → `EnrollmentOffer {campaign_version_id, terms_fingerprint, disclosures}`; `POST /api/v2/referrals/enrollments` (`Idempotency-Key`) `{attribution_id, campaign_id, campaign_version_id, terms_fingerprint}`; shartlar o‘zgargan bo‘lsa `409 VERSION_CONFLICT (campaign_terms_changed)` → klient yangi offer ko‘rsatadi.
- Xato kodlari: `REFERRAL_CODE_INVALID`, `REFERRAL_SELF_REFERRAL`, `REFERRAL_ALREADY_ATTRIBUTED`, `REFERRAL_WINDOW_CLOSED`, `REFERRAL_NOT_ELIGIBLE {reason}`, `PROMO_BUDGET_EXHAUSTED`, `FEATURE_DISABLED`, `IDEMPOTENCY_KEY_REUSED`; mijozga reason matni umumiy, shaxsiy ma’lumotsiz.
- Attribution ↔ birinchi bron poygasi: ikkalasi `users` qatorini birinchi bo‘lib `FOR NO KEY UPDATE` bilan oladi; 2-bosqichda stand-in bilan isbotlangan, `accept_proposal` bilan to‘liq test — 4-bosqich (A4.12).

### 17. 3-bosqich: qualification, grant, review, job’lar
Mavjud qarorlar (Q110, Q112, Q113, Q115, Q108) bajarildi. **T1–T3** foydalanuvchi tomonidan o‘zgartirishlar bilan tasdiqlandi (23.09.2026) — AGENTS.md §3 **Q120–Q122**; quyidagi matn tasdiqlangan shakl. 4-bosqichda kodga moslashtirildi.

- **T1 — dalil va vaqt.** Event (`promo_qualification_events`) yoki davriy sweep faqat tekshiruvni boshlaydi; qaror manba yozuvlaridan: `bookings.service_status = completed` + `completed_at`, `cash_receipts.status = acknowledged` + `decided_at` (va `bookings.cash_status`), `wallet_holds` (shu bron, `status = captured`) va unga bog‘langan `ledger_transactions` (`reference_kind = commission_capture`, `source = wallet_hold`, bir xil `booking_id`), `captured − reversed > 0`, ochiq `disputes_v2`, pochta uchun shu bronning `pickup_code`/`operator_evidence` va `delivery_code` proof’lari. Uch soat alohida: xizmat vaqti (manba), kelish (`received_at`), ishlov (`processed_at`). **Q120:** qualification muddati ichida bo‘lishi shart — xizmat bajarilishi va mijozning o‘z to‘lov sharti (naqd tasdig‘i). Platforma finance’i yoki worker’ning **kech capture’i foydalanuvchini diskvalifikatsiya qilmaydi**. Lekin haqiqiy musbat C_net capture bo‘lmaguncha grant yo‘q: enrollment kutilayotgan holatda qoladi va muddat tugadi deb rezervi avtomatik bo‘shatilmaydi (hold hali `held`). To‘lov vaqti tekshiriladigan manba yozuvidan: tasdiqlangan `cash_receipts.decided_at` (server vaqti); foydalanuvchi yozgan eski sana eligibility ochmaydi. Tasdiq muddatdan keyin, lekin server vaqti bilan yozilgan hisobot (`created_at`) muddat ichida bo‘lsa yoki `cash_status = acknowledged` bo‘lib tasdiq yozuvi topilmasa — real vaqt aniqlab bo‘lmaydi → **review** (`cash_time_unverified`). 48 soat xizmat, ishonchli naqd tasdig‘i va real capture’ning **eng oxirgisidan**; ma’nosi «48 soatdan oldin emas» (`now ≥ ready_at`), «aynan 48 soatda» emas. Muddat tugashida faqat hech narsa kutilmayotgan enrollment bo‘shatiladi; `waiting`/`review`/`qualified`, ochiq review, muddat ichida bajarilib capture yoki nizo kutayotgan xizmat bo‘lsa — rezerv saqlanadi.
- **T2 — sanash (Q121).** Yo‘lovchi: bitta haqiqiy bron; pochta: o‘z proof’lari va capture’i bo‘lgan ikkita bron (bir trip’da ham bo‘lishi mumkin); bir jo‘natuvchi, bir trip, bir marshrut, bir qabul qiluvchi (telefon faqat xotirada hash’lanadi, saqlanmaydi), 30 daqiqa ichida — `split_shipment` → review. 30 daqiqa — faqat **sintetik konfiguratsiya**, production default emas; signal review ochishi mumkin, hech qachon avtomatik firibgarlik belgisi emas. Haydovchi milestone birligi `distinct_trip` (kampaniya disclosure’ida `milestone_unit`); bir trip’dagi ko‘p bron — bitta qadam; `(enrollment, milestone)` bo‘yicha bitta qualification yozuvi, har obligation bir marta grant. Taklif qiluvchi xizmati hisoblanmaydi, enrollment yopilmaydi.
- **T3 — grant, review, reinstate, to‘xtatish (Q122).** Grant faqat enrollment’da va’da qilingan obligation’ni lot’ga aylantiradi (yangi budjet xarajati yo‘q); lot, promo ledger `grant`, holatlar va outbox `promo.reward_granted` bitta tranzaksiyada; lot `available_from` = grant vaqti, `expires_at = available_from + reward_validity` (review’da ushlangan lot’da muddat ozod qilinganda boshlanadi). Review: `promo_reviews` — tur, sabab kodlari, faqat `{table, id}` dalil havolalari, risk qoidalari versiyasi, SLA `due_at`, eskalatsiya vaqti, mas’ul, qaror, izoh, vaqtlar; `dedup_key` unique; qaror yakuniy (trigger). Identity review rad etilgan enrollment tranzaksiyasidan **mustaqil qisqa tranzaksiyada** yoziladi — rollback’da yo‘qolmaydi (domen funksiyasi commit qilmaydi qoidasidan ongli istisno: faqat `promo_reviews` va outbox). Bu tranzaksiya alohida ulanish: chaqiruvchining bron/wallet/promo rezervlarini commit qilmaydi; FK tekshiruvi KEY SHARE oladi (chaqiruvchining NO KEY UPDATE lock’i bilan to‘qnashmaydi) va `lock_timeout` bilan cheklangan — ilova darajasidagi o‘zaro kutish osilib qolmaydi (PG testi). Operator — `start_review` va izoh; qaror — admin+ (`promo.fraud_decide`); tasdiq mukofot yaratmaydi, faqat sababni tozalaydi, keyingi ishlov eligibility va invariantlarni qayta tekshiradi (masalan, bloklangan taklif qiluvchi tasdiqdan keyin ham to‘sadi). SLA oshsa — faqat `escalated_at` va staff event. Grant’dan keyingi nizo/refund/bekor → `post_grant_recheck` review va shu mukofot lot’larining **hali rezerv qilinmagan** qismi yangi sarfdan to‘xtatiladi (`available → pending_review`); allaqachon tasdiqlangan bron chegirmasi jimgina bekor qilinmaydi — rezerv o‘z broni bilan yakunlanadi. Poyga qoidasi: review ochish va rezerv ikkalasi lot qatorini `FOR NO KEY UPDATE` bilan oladi — kim birinchi bo‘lsa o‘sha; review keyin kelsa mavjud rezerv saqlanadi, rezerv keyin kelsa `PROMO_QUOTE_STALE` (faqat shu urinish). Tasdiq — lot qaytadan `available`; rad — sarflanmagan qism reversal, sarflangani risk xarajati. Reinstate — faqat muddat tugashidan bo‘shagan (`release_granted:expiry*`) yozuvga `reinstates_id` bilan bog‘langan yangi ledger yozuvi, bittadan ortiq emas, asl summadan oshmaydi, budjet xonasi trigger’da tekshiriladi; **qisman emas** — budjet yetmasa hech narsa yozilmaydi. Tasdiqlangan reinstate texnik rad bilan o‘chmaydi: mustaqil tranzaksiyada `reinstate_unfulfilled` review (darhol muddati o‘tgan → eskalatsiya) qoladi, qayta urinish mumkin. `processing_suspended_at` — operatsion to‘xtatish: hech narsa berilmaydi, bo‘shatilmaydi, o‘chirilmaydi; mavjud bron narxi o‘zgarmaydi, rezerv o‘z broni bilan capture/release bo‘ladi, ikki marta undirish yo‘q. Attribution’ni operator orqali almashtirish **yoqilmagan** — taklif: `docs/referral/ATTRIBUTION_CORRECTION_PROPOSAL.md`.
- **Lock tartibi:** `bookings` (FOR SHARE, id ASC) → `promo_campaigns` (FOR SHARE) → `promo_enrollments` → `referral_attributions` → `promo_qualifications` → `promo_obligations` → `promo_lots` → `promo_redemptions` → `promo_reviews` → `promo_budgets` (trigger). Job’lar har elementni savepoint ichida ishlaydi; deadlock/vaqtinchalik xato faqat o‘sha elementni qaytaradi va keyingi yurishda qayta ishlanadi.
- **Job’lar** (`app/worker` `SERVICE_JOBS`, `dispatch_outbox`dan oldin): `promotions.process_qualifications`, `recheck_granted`, `expire_enrollments`, `expire_lots`, `pause_exhausted_campaigns`, `escalate_reviews`, `purge_identity_digests`.
- **Integratsiya chegarasi:** dalil haqiqiy bron hayot siklidan olinadi; 4-bosqichdan boshlab bron oqimi `record_booking_event` ni o‘z tranzaksiyasi ichida chaqiradi (§18). HTTP va MFA ulanmagan (5-bosqich).

### 18. 4-bosqich: bron oqimi bilan integratsiya (23.09.2026)
Promotions A4 orkestratori ichida, uning tranzaksiyasida chaqiriladi (`app/modules/promotions/booking.py`); teskari yo‘nalish yo‘q, commit yo‘q.

| Nuqta | Nima bo‘ladi |
|---|---|
| `accept_proposal` | wallet account lock → `prepare_accept` (rozilik, lot’lar FOR NO KEY UPDATE, serverda qayta quote) → bron (`terms_snapshot.promo` markeri) → `commit_accept` (redemption `reserved`, `promo_booking_terms` seq 1, rozilik `used`) → **C_net** hold → outbox. Bittasi yiqilsa hammasi rollback. |
| `create_amendment` / `accept_amendment` | `prepare_amendment`: yangi F bo‘yicha qayta quote, mavjud rezervlar ichida (P/H faqat o‘zgarmaydi yoki kamayadi, Q116) → mijoz tasdig‘i (F/P/F_cash o‘zgarsa) → bron ustunlari → `commit_amendment` (`carry_reservation` bilan rezerv almashtirish, terms seq n) → `adjust_hold(C_net)`. Xatoda eski kelishuv saqlanadi. |
| cancel, `confirm_no_show`, `finalize_fee release` | wallet lock → `release_reservations` (aybdor tomon bo‘yicha adolatli tiklash) → hold release. Bekor qilish siyosati o‘zgarmadi. |
| `_complete` capture, `finalize_fee capture` | wallet lock → `consume_reservations` (bir marta) → ushlangan C_net capture; yangi stavka bilan qayta hisoblanmaydi; takror — `INVALID_STATE_TRANSITION`, qo‘shimcha yozuv yo‘q. |
| cash receipt | summa **F_cash** bilan solishtiriladi (`cash_receipt_matches`); eski klient promo bronda cash/amendment buyrug‘ini bajara olmaydi (`CLIENT_UPGRADE_REQUIRED`), chegirma olib tashlanmaydi. |
| `reverse_fee` | komissiya reversal — alohida hodisa: bonus tiklanmaydi, mijozga naqd qaytarilgan deb ko‘rsatilmaydi, faqat `commission_reversed` intake (post-grant review). Cap — capture qilingan C_net. |
| qualification intake | `booking_completed`, `cash_acknowledged`, `commission_captured`, `booking_cancelled`, `dispute_changed` — bron/nizo tranzaksiyasi ichida, faqat tirik enrollment bo‘lsa; rollback’da hodisa qolmaydi; sweep saqlanadi, dedup bilan ikki marta grant yo‘q. |

- **Rozilik (`promo_consents`):** user, proposal version (yoki amendment), xizmat turi, F, P, F_cash, fingerprint, muddat (versiya muddati), mijoz klientining e’lon qilgan imkoniyatlari. Boshqa user yoki versiya uchun ishlatilmaydi; bitta faol rozilik. Mijoz yuborgan raqamlar hech qachon summa sifatida olinmaydi — server quote’i bilan aynan teng bo‘lishi shart, aks holda `PROMO_QUOTE_STALE`.
- **Stale sabablari** (`details.reasons`, `scope=accept_attempt`): `fare`, `expired`, `proposal_version`, `passenger_bonus_changed`, `promotions_disabled`, `parameters_unset`, `ineligible`, `counterparty_client_outdated`. Faqat shu urinish rad; bron yuqoriroq naqd bilan jimgina yaratilmaydi. Driver Credit qo‘llab bo‘lmasa shunchaki qo‘llanmaydi (mijoz naqdini o‘zgartirmaydi).
- **Klient imkoniyati:** `promo_client_features` — foydalanuvchining oxirgi `X-Elchi-Client-Features` e’loni (vakolat emas), bron buyrug‘ining oxirgi yozuvi sifatida. P bor bitim uchun ikkala tomon ham `promo_cash_v1`; faqat H bor bitim uchun haydovchi (mijoz naqdi o‘zgarmaydi).
- **Marja siyosati:** bitta kampaniyaning bir necha versiyasi lot’lari — `strictest_margin_policy`; ikki turli kampaniya — faqat Q123 juftligi bilan `combined_margin_policy` (§18.1). `None` hech qachon boshqa qiymat bilan almashtirilmaydi.
- **Legacy va buzilgan snapshot:** marker yo‘q → legacy (P = H = 0). Marker bor, lekin terms yo‘q/zid → `INTEGRITY_CONFLICT`; DB’da deferred `promo_booking_terms_verify` commit’ni rad etadi (hold ≠ C_net, redemption ≠ P/H, terms ≠ bron F/bps/C, oddiy bronda tirik redemption).
- **Lock tartibi:** `users → trips → listings → proposal_threads → bookings → booking bolalari → wallet_accounts → promo_consents → promo_campaigns (FOR SHARE) → promo_lots (id ASC) → promo_redemptions → promo_booking_terms → promo_budgets (trigger) → wallet_holds → promo_client_features (oxirgi yozuv)`.
- **Hisobot:** `promo_booking_finance` view — F, C, P, H, F_cash, C_net, captured/reversed real pul, consumed P/H; `C = captured C_net + consumed P + consumed H` har bron uchun.
- **Kelishuvdan oldin ko‘rish:** `ProposalVersionDTO.promo_quote` (joriy ochiq versiya, hech narsa rezerv qilmaydi): mijozga bonusi shu narxda beradigan maksimal chegirma va F_cash; haydovchiga naqd olinadigan summa, ishlatiladigan H, undiriladigan C_net va qoladigan summa (mijozning yozilgan roziligi bo‘yicha). Marketplace submit/counter ham `promo_client_features` ni yozadi. Har rolga alohida obyekt (`view` diskriminatori): mijoz obyektida komissiya, kredit va qoladigan summa kalitlari **umuman yo‘q** (null ham emas) — `ProposalPromoClientDTO`/`BookingPromoClientDTO` = `CLIENT_PROMO_VIEW_KEYS`, haydovchiniki = `DRIVER_PROMO_VIEW_KEYS` (kontrakt testi); `AmendmentDTO.promo` ham shunday.
- **4-bosqich talqinlari T4 foydalanuvchi tomonidan o‘zgartirishlar bilan tasdiqlandi (23.09.2026) — Q123–Q129**, amalga oshirish §18.1 da.
- **Ochiq (klientga bog‘liq):** mijoz taklif yuborish/counter paytida rozilik berishning HTTP yo‘li (`record_consent` servis funksiyasi tayyor) va mobile-app ekranlari — 5-bosqich. Hozir HTTP orqali: accept’dagi rozilik (`AcceptRequest.promo_consent`), amendment rozilik maydonlari, bron/amendment/proposal DTO’laridagi `promo` bloklari.

#### 18.1 T4 qarorlari — Q123–Q129 (tasdiqlangan 23.09.2026, 5-bosqichda amalga oshirildi)
Foydalanuvchi T4 ni o‘zgartirishlar bilan tasdiqladi; qaror matni AGENTS.md §3 da. Bu yerda — kod, DB va dalil.
Migratsiya `20260923_0089_promotions_t4`. Faqat sintetik qiymatlar; hech bir marketing parametri tasdiqlanmagan.

- **Q123 — cheklangan kombinatsiya.** P bitta kampaniyadan, H bitta kampaniyadan (bir kampaniyaning bir nechta loti —
  mumkin). P kampaniyasi rozilik paytida tanlanadi (shu narxda eng katta P; teng bo‘lsa eng tez tugaydigan lot) va
  `promo_consents.passenger_campaign_id` ga yoziladi; accept faqat shu kampaniyadan oladi. Ikki turli kampaniya faqat
  `promo_campaign_combinations` qatori bilan (super_admin + MFA step-up, sabab, audit; `active → revoked`, o‘chirilmaydi):
  `cost_basis` aniq tanlanadi — `shared` (bir xil bron xarajati: O qismlari va M kattasi), `additive` (alohida xarajat:
  O qismlari qo‘shiladi, M kattasi); standart qiymat yo‘q. Umumiy cap’lar (C ulushi, bron cap’i) — eng qat’iysi; P cap P
  kampaniyasidan, H cap H kampaniyasidan (`contracts.promo.combined_margin_policy`). Tasdiqlanmagan juftlik → H
  qo‘llanmaydi. **Talqin (qaror matnidagi “yashirin kamaytirish emas”):** H qo‘shilishi rozilik berilgan P ni
  kamaytiradigan bo‘lsa, H qo‘llanmaydi va P aynan saqlanadi; P ning o‘zi mos kelmasa — `PROMO_QUOTE_STALE` (requote).
  Terms qatori `passenger_campaign_id`, `driver_campaign_id`, `combination_cost_basis` ni saqlaydi; amendment shu
  saqlangan asosni ishlatadi (juftlik keyin bekor qilinsa ham). DB: `ck_promo_booking_terms_campaigns` (NOT VALID —
  eski qatorlar tekshirilmaydi) va deferred `promo_booking_terms_verify` — tirik redemption terms’da nomlangan
  kampaniyadan bo‘lishi shart. *Dalil:* `test_promo_t4_pg.py::test_q123_*` (5 ta), `test_promo_booking.py::test_q123_*`,
  `test_promo_http_pg.py::test_q123_a_campaign_pairing_is_approved_only_with_a_real_step_up`.
  **Aniqlik (24.09.2026):** tanlash yagona sof funksiyalarda — `contracts.promo.choose_passenger_source`,
  `choose_driver_source` (bron oqimi ham, 6-bosqich simulyatori ham shularni chaqiradi). Natija
  `DriverCreditOutcome`: `applied`, `partial` (H P dan keyin qolgan joyni oladi — avvalgi “qolgan imkoniyat” qoidasi),
  `not_approved`, `would_reduce_p` (juftlik mos kelmaydi — H yo‘q, P aynan saqlanadi), `none`; `AcceptPlan.h_outcome`
  (ichki). Haydovchi accept’da ko‘rgan raqamlarini yuboradi (`AcceptRequest.promo_driver_ack`, mobile-app avtomatik);
  server natijasi boshqacha bo‘lsa (masalan, kredit muddati tugab C_net oshsa) bron yaratilmaydi —
  `PROMO_QUOTE_STALE driver_terms_changed` yangi raqamlar bilan; `ack` yuborilmasa (tasdiqlangan H yo‘q) H “X gacha”
  qoidasi bo‘yicha. Passiv haydovchi (mijoz accept qilganda) raqam tasdiqlamagan — faqat capability (Q126). *Dalil:*
  `test_promo_booking.py::test_q123_clarified_*` (2), `test_promo_t4_pg.py::test_q123_clarified_*` (2).
- **Q124 — faqat Driver Credit.** P = 0 bitimda mijoz klientidan capability so‘ralmaydi; mijoz DTO’sida `promo = null`
  (oddiy bron bilan bir xil), cash receipt F, eski mijoz klienti acknowledge/amendment qila oladi
  (`cash_terms_differ_for`: mijoz uchun faqat biror terms qatorida P > 0 bo‘lsa). Haydovchi klienti H va C_net ni
  ko‘rsatishi shart (accept va cash buyruqlarida). Amendment P ni qo‘sha olmaydi. *Dalil:* `test_q124_*` (2 ta),
  `test_promo_booking_pg.py::test_driver_credit_alone_never_changes_what_the_client_pays`.
- **Q125 — amendment.** Yangi lot tortilmaydi, mavjud rezervlar ichida P/H o‘zgarmaydi yoki kamayadi. Mijoz F/P/F_cash
  o‘zgarsa (bonus ishtirok etsa) roziligini beradi; haydovchining naqdi yoki C_net o‘zgarsa `promo_driver_ack`
  (`cash_to_collect_minor`, `commission_charged_minor`) bilan tasdiqlaydi — yaratishda ham, qabul qilishda ham;
  yo‘q bo‘lsa `PROMO_CONSENT_REQUIRED {party: driver, ...}`, mos kelmasa `PROMO_QUOTE_STALE (driver_terms_changed)`.
  Qabul qilinmaguncha eski kelishuv va rezervlar o‘zgarmaydi. Klient F kamayib naqd nisbatan kamroq kamaygan (yoki
  oshgan) holatni alohida matn bilan tushuntiradi (`promo.ts amendmentCashNote`). *Dalil:* `test_q125_*`,
  `test_promo_booking_pg.py::test_amendment_*`, `promoT4.test.ts`, skrinshot 390_47–49.
- **Q126 — capability dalili muddatli.** Harakat qiluvchi — shu so‘rov header’i. Passiv tomon: mijoz — rozilik
  (`session_ref`, versiya, muddat); haydovchi — `promo_party_readiness` (versiya yoki amendment, `session_ref` = JWT
  `sid`, muddat = versiya/amendment muddati), offer/counter paytida yoziladi. Yaroqlilik (`_evidence_valid`):
  capability, muddat, login sessiyasi tugamagan (`auth_service.login_session_state`), oxirgi e’lon capability bilan va
  boshqa **jonli** sessiyadan emas; token rotatsiyasi (`rotated`) davomiylik deb qabul qilinadi — zanjir yozilmagani
  uchun rotatsiyadan keyingi boshqa qurilmani ajratib bo‘lmaydi (**ma’lum chegara**; barcha eski versiyaga qaytish
  aniqlanadi deb da’vo qilinmaydi, o‘qish so‘rovlari e’lon yozmaydi). Eskirgan bo‘lsa: accept `PROMO_QUOTE_STALE
  (counterparty_confirmation_stale | counterparty_client_outdated)`, muallif `POST /proposals/{id}/promo-confirmation`
  yoki `POST /amendments/{id}/promo-confirmation` bilan qayta tasdiqlaydi (taklif o‘zgarmaydi);
  `ProposalVersionDTO.promo_confirmation` faqat muallifga `valid|stale`. Mavjud promo bron chegirmasi olib tashlanmaydi.
  *Dalil:* `test_q126_*` (3 PG), `test_promo_http_pg.py::test_q126_*`, skrinshot 390_45–46.
- **Q127 — reversal ≠ tiklash.** `wallet.reverse_fee` → `promotions.booking.after_commission_reversal` (post-grant
  intake + review); hal qilingan nizo → `note_dispute_resolved`. Sarflangan P/H bor bronda har ega uchun
  `restoration_uncovered` review (qaror faqat qayd — qiymat bermaydi ham, olmaydi ham). Umumiy “bonus berish” tugmasi
  yo‘q. **Mavjud siyosat qamramagan holatlar (alohida ko‘rsatiladi, avtomatik ega zarariga hal qilinmaydi):**
  (1) capture’dan keyingi komissiya reversal’i — sarflangan bonus/kredit; (2) capture’dan keyin hal qilingan nizo —
  sarflangan bonus/kredit; (3) sarflangan qiymatni qaytarishning o‘zi uchun mexanizm yo‘q — alohida qaror kerak.
  Qamralganlari: xizmatdan oldin bekor qilish (adolatli tiklash, §7, Q129), muddati o‘tgan qiymatni reinstate
  (Q122), fraud reversal — sarflangani risk xarajati (§7). *Dalil:* `test_q127_*`,
  `test_promo_booking_pg.py::test_partial_and_repeated_commission_reversal_*`.
- **Q128 — muddatidan keyingi release.** Summa expiry’ga o‘tadi (`release_granted:expiry-redemption:*`), grace (egasi
  aybdor emas) va reinstate saqlanadi; release va expiry job poygasi, ikki parallel reinstate — summa bir marta.
  *Dalil:* `test_q128_*`, `test_promo_lots_pg.py::test_a_release_after_the_end_expires_the_free_remainder_too`.
- **Q129 — sabab, actor emas.** `PromoFault` qiymatlari: `client`, `driver`, `platform`, `none` (asosli, hech kim
  aybdor emas), `undetermined`. Har ega alohida (`contracts.promo.holder_at_fault`, `restored_expiry(instrument=...)`):
  bonus egasi mijoz, kredit egasi haydovchi; faqat egasining **aniq** sababi uzaytmani oladi. Operator bekor qilishda
  `cancel_fault_side` (client/driver/platform/none, sabab matni bilan) — `bookings.fault_side` ga yoziladi (N3 “unless
  decided”); berilmasa `fault_side = none` (avvalgidek) va promo sababi `undetermined`. Operator/tizim trip bekor
  qilishi va `finalize_fee release` — `undetermined`. Tasdiqlangan mijoz no-show’i — `client`; `reject_no_show` →
  `driver`. `undetermined` huquqni olmaydi: uzaytma beriladi (`promo_redemptions.restored_from/until`) va uzaytma
  berilgan har ega uchun `cancel_fault` review; admin rad etsa (`withdraw_restoration`) faqat sarflanmagan uzaytma
  qaytariladi (o‘tib ketgan bo‘lsa darhol expiry, reinstate mumkin). Real pul natijasi o‘zgarmagan (release, jarima
  yo‘q). *Dalil:* `test_q129_*` (5 ta), `test_promo_booking.py::test_q129_*`,
  `test_promo_booking_pg.py::test_cancel_after_expiry_restores_by_fault_in_the_real_flow`.

### 19. 5-bosqich: HTTP himoyasi, klient va admin interfeysi (23.09.2026)
**Server (`app/modules/promotions/api.py`, `portal.py`):**
- Actor faqat autentifikatsiyalangan sessiyadan (`current_user_id`); body’da user, role yoki capability maydoni yo‘q (`extra="forbid"` → 422). Capability serverda hisoblanadi (`identity.get_capabilities`).
- Obyekt egaligi: begona attribution/enrollment/lot/listing preview — noma’lumdek `404` (oracle yo‘q).
- Qarorlar (kampaniya buyrug‘i, versiya, byudjet so‘rovi/qarori, review qarori, ishlovni to‘xtatish): capability **va** haqiqiy MFA step-up (faol TOTP faktor, `STEP_UP_MAX_AGE` ichida). Platformaning ADR-0021 audit-only rollout rejimi bu yerda **qo‘llanmaydi** — faktor bo‘lmasa amal yopiq (`FORBIDDEN step_up_required`). Klient header’i MFA dalili emas. Ikki xodim qoidasi mavjud servislarda (Q114): so‘rovchi o‘z so‘rovini tasdiqlay/rad eta olmaydi.
- Abuse limitlari mavjud mexanizmda (vaqt oynasidagi yozuvlarni sanash) `promo_rate_events` (0088) orqali: ochiq kod tekshiruvi — manba (IP) bo‘yicha, attribution — foydalanuvchi bo‘yicha; rad etilgan urinish ham sanaladi (`after_command`), idempotent replay sanalmaydi; manba faqat purpose-subkey HMAC. Qiymatlar (`referral_code_checks_per_ip_per_minute=30`, `referral_attributions_per_user_per_hour=5`) — §16 dagi taklif, **production uchun tasdiqlanmagan** konfiguratsiya.
- Pul hisoblanmaydi: endpointlar faqat `referral`, `service`, `qualification`, `booking` servislarini chaqiradi. `promotions_enabled` o‘chiq bo‘lsa kod, attribution, taklif va enrollment `FEATURE_DISABLED`; o‘z bonus holatini ko‘rish ochiq (hech narsa sarflanmaydi).
- Taklif yuborish/counter: `promo_consent` (ixtiyoriy, hech qachon oldindan to‘ldirilmaydi) — o‘sha buyruq tranzaksiyasida `record_consent_for_current_version`; mos kelmasa butun buyruq `PROMO_QUOTE_STALE` bilan rad (versiya ham qaytariladi). Narx yozilayotganda `GET /listings/{id}/promo-preview` — faqat bo‘lajak mijozga, faqat o‘z bonusi, hech narsa rezerv qilinmaydi.
**Klient (`mobile-app`):** har promo obyekt rolga alohida (`view` diskriminatori); `X-Elchi-Client-Features: promo_cash_v1` faqat ilova F_cash’ni hamma joyda ko‘rsata olgandan keyin yuboriladi; pul bilan bog‘liq accept bitta `Idempotency-Key` ni timeout/qayta bosish/qayta ochishda saqlaydi (`promo.ts actionKey`); `/r/<kod>` kodi login orqali saqlanadi va bonus ekranida aniq tasdiqlanadi.
**Admin (`mobile-app/src/app/AdminPromoPanel.tsx`):** kampaniya/versiya/holat, byudjet so‘rovlari, review navbati, solishtirish; `step_up_required` da autentifikator kodi so‘raladi; “bonus berish” tugmasi yo‘q.
**5-bosqich davomi (24.09.2026):**
- Haydovchi QR — qurilmada (`qrcode-generator` 2.0.4, ADR-0024), faqat server `share_url`; `share_url` yo‘q bo‘lsa QR yo‘q;
  kodni nusxalash va qo‘lda kiritish saqlangan.
- Progress: `EnrollmentDTO.progress` (faqat referee): `done` — to‘liq hisoblangan xizmat/safar, `in_review` — capture,
  48 soat yoki review kutayotgan (bajarilgan deb sanalmaydi), `remaining`; haydovchi uchun `milestones` (kampaniya
  versiyasi qiymatlari — ilova matnida marketing raqami yo‘q). `qualification.progress_for` grant bilan bir xil dalildan.
- “Nega chegirma yo‘q?”: `no_discount_reason` — `service_not_eligible`, `bonus_expired`, `bonus_reserved`,
  `bonus_on_hold`, `no_campaign`, `client_update_required`, `trip_terms` (komissiya/marja/cap/fraud tafsiloti yo‘q).
  `GET /listings/{id}/promo-preview` → `{quote, no_discount_reason}`; `ProposalVersionDTO.promo_unavailable_reason`.
- Admin: kampaniya juftligi (tasdiqlash/bekor qilish), `cancel_fault`/`restoration_uncovered` review’lari qaror
  ma’nosi bilan; admin yon menyusi 390 px’da yig‘iq.
- Tuzatishlar: yo‘lovchi o‘tirish kodi matnida “posilka” yo‘q (`proofCodes.ts`); bron o‘zgartirish tugmasi server
  qoidasiga mos (`confirmed`, `awaiting_pickup`); `scripts/seed_demo_v2.py` endi marshrut versiyasining o‘z bekatlarini
  ishlatadi (avval koridordagi barcha 6 bekatni qo‘yib `ROUTE_CHANGED stops_not_on_route_version` bilan yiqilardi).
- Handoff: `docs/referral/INFRA_HANDOFF.md`, `docs/referral/APP_LINKS_HANDOFF.md`.

**Ochiq:** havola domeni/DNS/TLS/deploy/App Links va qurilmada tekshiruv (handoff’lar tayyor, bajarilmagan); rate-limit va
marketing qiymatlarining production tasdig‘i; HMAC saqlash muddati (Q108); ADR-0021 (staff MFA) hali Proposed.

### 20. 6-bosqich: simulyator (24.09.2026) — **sintetik ssenariylar**
**Maqsad:** tasdiqlangan mexanizmning xarajati, budjet majburiyati, marjasi va foydalanuvchiga amaliy foydasini turli
taxminlarda hisoblash. Natija kiritilgan taxminlarga bog‘liq; foydalanuvchi o‘sishi yoki zararsizlik **isbot
qilinmaydi**. Haqiqiy ma’lumot yo‘q — har kirish va natija “sintetik ssenariy”; hech bir qiymat production
konfiguratsiyasiga ko‘chirilmaydi.

**Tuzilma (DB/tarmoq/sozlama yo‘q):** `app/modules/promotions/simulation/` — `config.py` (ssenariy; yo‘q kalit xato,
noma’lum doimiy xarajat `null`, hech qachon 0), `engine.py` (kunma-kun oqim), `report.py` (qatorlar, tengliklar, CAC,
sezgirlik, juft nazorat); CLI `scripts/promo_simulate.py`; kiritma `docs/referral/simulation/scenarios.json`; natija
`results.json` + `REPORT.md`. Takrorlash: `py scripts/promo_simulate.py` (`--check` — yangi progon bilan bayt-bayt
solishtiradi); hisobotda seed, har ssenariy konfiguratsiya barmoq izi va kod barmoq izi (simulyator + `promo.py`,
`money.py`, `enums.py`).

**Bitta formula:** har bron shartlari production funksiyalaridan — `choose_passenger_source`, `choose_driver_source`
(Q123 aniqligi bilan: qisman H, juftlanmagan kampaniya, P kamaytirilmaydi), `quote_at_accept`,
`combined_margin_policy`, `campaign_pair`; lot — `LotBalance`, budjet — `BudgetPosition` (va’da → grant → sarf bitta
majburiyat; `reinstate` ham), tiklash — `restored_expiry`, qualification — `evaluate_qualification`, milestone —
`milestones_reached`, faollashtirish — `validate_activation` (nol budjetli kampaniya faollashmaydi). Simulyator faqat
*nima bo‘lishini* tasodifiy oqim bilan tanlaydi, *qancha*ni emas.

**Hisob qoidalari (har snapshot’da tekshiriladi):** `F_cash = F − P`, `C_net = C − P − H` quote’dan; `C − P − H −
reversal = saqlangan C_net` alohida tekshiruv; sarflangan P + H = budjetdagi `consumed` (bir marta); F va F_cash — hajm,
tushum emas; haydovchi top-up modelda yo‘q; O bitta qator, qaytarilgan komissiya, qo‘shimcha marketing va firibgarlik
zarari (sarflangan rag‘bat ichida — qayta qo‘shilmaydi) alohida; doimiy xarajat/soliq noma’lum → biznes natijasi
hisoblanmaydi. Budjet manbai — aniq parametr. “Stress marja” = operatsion marja − qolgan majburiyat (va’da + sarflanmagan
bonus to‘liq sarflanadi deb): foyda bonus ishlatilmay qolishiga tayanmaydi.

**Sababiylik:** `base_new_per_day` (referralsiz ham keladi) va `attributed_share_of_base` (kod bilan kelgan, lekin
qo‘shimcha emas) `incremental_new_per_day` dan (faqat referral tufayli — ochiq taxmin) ajratilgan; qo‘shimcha kelish
faqat va’da bera oladigan faol kampaniya bo‘lsa. Har ssenariy **juft nazorat** bilan solishtiriladi (xuddi shu dunyo,
referral o‘chiq, `<nom>~control`); har odam va buyurtmaning tasodifiy sonlari barqaror identifikator bo‘yicha qat’iy
tartibda chiziladi — kampaniyasi yo‘q xizmat nazorat bilan bir xil chiqadi (test bilan).

**Qamrov:** kod → attribution → enrollment → qualification (48 soat, taklif qiluvchi xizmati hisoblanmaydi, pochtada 2
jo‘natma) → grant → sarf; birinchi/takroriy buyurtma va oralig‘i; bekor qilish (Q129 sababi), nizo, fee release,
reversal (Q127), kech capture, review; qisman sarf, expiry, grace, reinstate; haydovchi milestone’lari va mustaqil
mijozlar; P + H birga va alohida; koridorda haydovchi topilmasligi; past/o‘rta/yuqori narx; nol budjet; 30-kunda budjet
kesilishi. Natija xizmat, kampaniya oilasi va koridor bo‘yicha; 30/60/90 kun.

**Dalil:** `tests/contracts/test_promo_simulation.py` (determinizm, tengliklar, bitta majburiyat, nol budjet, budjet
kesilishi, stress, juft nazorat, bron shartlari = kontrakt quote’i, Q123 qisman H / juftlanmagan);
`tests/pg/promotions/test_promo_simulation_pg.py` — 7 bron holatida simulyator shartlari haqiqiy
`accept_proposal` natijasiga (`promo_booking_terms`, `promo_redemptions`) teng; va’da → grant → rad budjetda
`promo_budgets` va `BudgetPosition` bir xil. Q123 aniqligi: `test_promo_booking.py::test_q123_clarified_*`,
`test_promo_t4_pg.py::test_q123_clarified_*`.

**Sintetik natija xulosasi (tasdiq emas):** uchala pilot varianti (A: faqat yo‘lovchi mijoz→mijoz; B: yo‘lovchi + pochta
alohida budjet; C: haydovchi taklif qiladi + milestone) juft nazoratga nisbatan faqat `incremental_new_per_day` taxmini
to‘g‘ri bo‘lsa musbat; qo‘shimcha foydalanuvchi bo‘lmasa har biri sof xarajat (stress farq manfiy). `ops_delay_shortage`
da stress farq manfiy. Pochtada marja qoidasi (`C_net − O ≥ M`) past narxli jo‘natmada chegirmaga joy qoldirmaydi —
kichik bonus kam ishlatiladi. Raqamlar `REPORT.md` da.

**Simulyator hal qilmaydi:** Q108 HMAC muddati (huquqiy); rate-limit va review SLA (trafik, bloklanish, operator ish
hajmi tahlili kerak); 48 soatlik risk oynasi asosiy modelda o‘zgarmagan (`experiment` belgisi bilan faqat alohida
taqqoslash). Migratsiya yo‘q; `promotions_enabled` production’da `false`.

#### 20.1 A6.2 yakuni (24.09.2026)
**Variantlar bo‘yicha foydalanuvchi qarori:** A — kelajakdagi yo‘lovchi pilotini baholash uchun asosiy nomzod (summalar va
600 000 so‘m budjet tasdiqlanmagan; yo‘lovchi gate’lari saqlanadi); B — hozirgi ko‘rinishida tasdiqlanmaydi, pochta alohida;
C — keyinga qoldirildi. Bu kampaniyani yoqish yoki mablag‘ ajratish ruxsati emas.

**Cohort langari:** har ko‘rsatkich o‘z langari bilan — *enrollment* (qualification ulushi), *aktivlashish* (commission capture
qilingan birinchi bronning xizmat kuni: D30/D60 qaytish, D60 marja), *grant* (`available_from`: lot sarfi). Oynasi to‘lmagan
kuzatuv — **yetilmagan**, alohida sanaladi; yetilgan kuzatuv minimaldan (`cohort.min_matured_observations`, sintetik 20) kam
bo‘lsa qiymat `hali_baholab_bolmaydi`, hech qachon 0. Har ko‘rsatkichda hisob kuni, maxraj ta’rifi, yetilgan va yetilmagan
soni. Simulyator lotlari production qoidasi bilan `available_from` oladi (grant’da; review’dan chiqqanda qayta boshlanadi).

**Ishlatilmagan bonus sababi (lot bo‘yicha, egasi eng yaqin kelgan holat):** lot yetilmagan, bronda rezervda, egasi qaytmagan,
haydovchi topilmagan, komissiyada joy yo‘q (`C_net − O ≥ M`), qabul qiluvchi to‘laydi, mijoz tanlamagan, buyurtma bekor, fraud
reversal. Lotlar ulushi, bonus ishlatgan egalar ulushi va ishlatilgan qiymat ulushi alohida.

**Budjet ko‘rsatkichi:** limit (boshlang‘ich/yakuniy), majburiyat, ta’minlangan qism, kamomad va uning boshlanish kuni, foydalanish
cho‘qqisi **o‘sha lahzadagi** limitga. Avvalgi “104%” cho‘qqi majburiyatni kesilgan yakuniy limitga bo‘lgan edi. `reduce_allocation`
production’da mumkin (finance, katta summa ikki xodim); majburiyatdan pastga tushirish ataylab taqiqlanmagan — kamomadda yangi
va’da rad, eskilari bajariladi, `pause_exhausted_campaigns` to‘xtatadi, admin hisobotida `budget_shortfall` ogohlantirishi.
~~Ochiq savol: limitni sarflangan summadan pastga kamaytirish~~ — **G14 bilan yopildi (§20.2)**: oddiy kamaytirish endi
`B ≥ S + L` dan pastga tushmaydi; haqiqiy moliyalashtirish yo‘qolishi alohida `funding_loss`.

**Xulosa chegaralari:** zararsizlik endi simulyatsiya to‘rida (qo‘shimcha foydalanuvchi taxmini 0–150 %, har nuqta juft nazorat
bilan) topiladi; avvalgi nisbat faqat taqqoslash. Stresslar alohida va **birga** (takroriy buyurtma yarmi + nizolar ×3 + past narx
+ to‘liq sarf + yarim qo‘shimcha foydalanuvchi; va xuddi shu qo‘shimchasiz). Seed tarqalishi 20 seed — model tasodifi, bozor
ishonch oralig‘i emas. Pochta — alohida sintetik tajribalar (kichik mukofot, 120 kun, ko‘proq buyurtma, boyroq narx aralashmasi;
narx, haydovchi daromadi va M o‘zgarmagan).

**Operatsion hisobot:** `GET /api/v2/admin/promo/report?from&to&group_by=service|corridor|campaign_version|cohort`
(`app/modules/promotions/reporting.py`). `promo.campaign_view` **va** `finance.reports` (admin, finance, super_admin; operator
yo‘q — pul ko‘rsatkichi). Faqat o‘qiydi (so‘ng rollback), davr ≤ 366 kun (UTC kun chegarasi, oxiri ochiq), `statement_timeout`
10 s. `data_source = operational` — simulyator natijasi hech qachon bu yerda emas. Holat (`budgets`: limit, va’da rezervi,
berilgan-sarflanmagan, bronlardagi rezerv, sarflangan, bo‘shatilgan, majburiyat, kamomad, ta’minlangan, review’dagi summa,
ogohlantirishlar) va davr oqimlari (enrollment, grant, sarf, muddati tugagan, promo bronlar, C, P, H, kelishilgan/ushlab
qolingan C_net, reversal) alohida, har oqim qaysi vaqt ustuni bilan sanalishi (`period_basis`) bilan. Guruhga taalluqli
bo‘lmagan ko‘rsatkich `null` (masalan koridor bo‘yicha enrollment). Cohort — enrollment haftasi (Asia/Tashkent), `observed_days`,
`matured_d30/d60`. Shaxsiy ma’lumot yo‘q. Dalil: `tests/pg/promotions/test_promo_report_pg.py` (4).

**Dry-run endpoint (A6.1):** REFERRAL_PLAN A6.1 “dry-run endpoint/CLI” deydi — CLI yetarli deb qabul qilindi; HTTP dry-run
**keyinga qoldirildi** (kerak bo‘lsa: faqat sof simulyator, DB’ga yozmaydi, kiritma hajmi va vaqt chegarasi bilan).

#### 20.2 Referral yakuni: qarorlar va G14 (24.09.2026)
**Holat: lokal yakunlangan, production gate’lari yopilmagan.** `promotions_enabled` production’da `false`; hech bir kampaniya,
budjet yoki parametr tasdiqlanmagan.

**G14 — budjetni kamaytirishning pastki chegarasi (Q132, migratsiya 0090).** B — tasdiqlangan jami ajratma, S — hisobga olingan
sof sarf (`consumed`), L — hali bajarilmagan amaldagi majburiyatlar: va’da rezervi (`promised`) + berilgan sarflanmagan bonus
(`granted`, bronda band qilingan qism uning ichida — bir marta) + budjet joyini kutayotgan tasdiqlangan tiklashlar (ochiq
`reinstate_unfulfilled` review’lari, `promo_pending_reinstatements()`). Review yoki kech capture kutayotgan majburiyatlar
`promised`/`granted` da qoladi — hisobdan chiqmaydi. Oddiy `reduce_allocation` faqat `max(0, B − S − L)` gacha
(`BudgetPosition.reducible_minor`), aks holda `PROMO_BUDGET_BELOW_COMMITMENT` (409), budjet, ledger va so‘rovlar o‘zgarmaydi.
Servis oldindan tekshiradi, ledger trigger budjet qatori lock’i ostida qayta tekshiradi — xom ledger yozuvi, super_admin ham
chetlab o‘tolmaydi. S ni kamaytiradigan ledger turi yo‘q; budjet keshi faqat trigger orqali yoziladi; tuzatish — asoslangan
ledger operatsiyasi. Hisobot davri budjet holatini o‘zgartirmaydi (`budgets` doim to‘liq tarix); davriy budjet kerak bo‘lsa —
tarixni saqlagan alohida ajratma.
**Tashqi moliyalashtirish yo‘qolishi (`funding_loss`)** — oddiy kamaytirishdan alohida: `evidence_reference` bilan so‘rov
majburiy (DB CHECK + trigger), finance va katta summada ikki turli xodim; `B − S − L` dan pastga tushishi mumkin (haqiqiy
kamomad), hech bir majburiyatni bekor qilmaydi, kampaniya o‘sha tranzaksiyada pauzaga o‘tadi (`funding_loss` o‘tishi),
kamomad bor ekan qayta yoqilmaydi, audit `funding_loss_escalated`, hisobotda `budget_shortfall`. Admin UI: “Moliyalashtirish
yo‘qoldi” turi dalilsiz yuborilmaydi; “Kamaytirish mumkin (B − S − L)” ko‘rsatiladi. Simulyator: `budget_cut` endi faqat
`B − S − L` gacha kamaytiradi (qolgani rad), kamomad faqat `funding_loss` ssenariysida. Dalil:
`tests/pg/promotions/test_promo_budget_floor_pg.py` (8), `tests/contracts/test_promo.py::test_g14_*` (3),
`tests/contracts/test_promo_simulation.py`.

**Qarorlar (Q131–Q135):**
- **G20 / Q131:** pochta bonusi hozircha yoqilmaydi — vaqtinchalik mahsulot qarori (haqiqiy qayta buyurtma va foydalanish
  ma’lumoti yo‘q). Simulyatsiyadagi ~9 % — model natijasi, foydasizlik isboti emas. Mexanizm kodda saqlanadi, kampaniya o‘chiq.
  A varianti — faqat kelajakdagi yo‘lovchi pilotiga nomzod; summa va budjet tasdiqlanmagan.
- **Q108** ochiq; mavjud production cheklovi (identity kaliti va tasdiqlangan muddatsiz production enrollment yopiq) saqlanadi.
  Muddat simulyatsiya yoki texnik qulaylik asosida tanlanmaydi.
- **Marketing parametrlari va budjet** tasdiqlanmagan — haqiqiy pilot qarori bilan; sintetik qiymatlar production standarti
  emas. Yangi parametr variantlari qidirilmaydi; tayyor natijalar qaror hujjati sifatida saqlanadi.
- **Rate-limit va review SLA** — alohida ochiq band: trafik, umumiy IP ortidagi haqiqiy foydalanuvchilar, qayta urinishlar va
  review navbatidagi ish hajmi dalilisiz tasdiqlanmaydi; mavjud himoya saqlanadi.
- **Q127 / Q133:** siyosatsiz erkin bonus berish yo‘q, umumiy “bonus berish” tugmasi yo‘q. Siyosat tiklash huquqini aniq
  belgilagan holat bog‘langan operatsiya orqali (reinstate, cancel-fault grace); qamralmagan holatda operator dalil yig‘adi,
  vakolatli admin ko‘rib chiqadi — adminning texnik vakolati yangi kompensatsiya siyosati emas. Haqiqiy pul qarzi avtomatik
  yaratilmaydi. Ochiq holatlar jadvali: `docs/referral/GO_LIVE_CHECKLIST.md` §E.
- **Q134:** qo‘shimcha foydalanuvchini o‘lchash dizayni tasdiqlanmagan; koridor bo‘yicha nazorat variant sifatida saqlanadi,
  lekin 2–3 pilot koridorining talab, narx va haydovchi ta’minoti farqlari referral ta’siri bilan aralashishi mumkin. Attribution
  soni qo‘shimcha foydalanuvchi soni emas; nazorat berilgan va’dalarni buzmaydi.
- **Q135:** to‘xtatish mezonlari umumiy tasdiqlanmagan. Texnik incident — takroriy undirish, ruxsatsiz grant, ledger tafovuti,
  majburiyat chegarasining buzilishi: ta’sirlangan xavfli operatsiyalar cheklanadi (ishlovni `suspend`, kampaniya `pause`,
  kerak bo‘lsa yangi promo bitimlar uchun `promotions_enabled` o‘chiriladi), mavjud bron narxi o‘zgarmaydi, majburiyat
  o‘chmaydi. Biznes chegaralari (review navbati, CAC, refund ulushi) dalilga asoslangan alohida tasdiqni kutadi.

## Muqobillar
- Referral’ni `commission_policies` kampaniyasi bilan qilish — per-user va budjetli bo‘lmaydi.
- Bonusni real ledger’ga kredit sifatida yozish — Q55 ni buzadi, “pul berildi” taassurotini beradi.
- Mijoz chegirmasini haydovchi hisobidan berish — §4 da taqiqlangan.
- “5 safarga 0%” — cheksiz xarajat; o‘rniga chegaralangan Driver Credit.

## Oqibatlar va ochiq bandlar
- `ErrorCode` qo‘shildi: `PROMO_CONSENT_REQUIRED`, `PROMO_QUOTE_STALE`, `PROMO_PARAMETERS_UNSET`, `PROMO_BUDGET_EXHAUSTED`, `REFERRAL_SELF_REFERRAL`, `REFERRAL_ALREADY_ATTRIBUTED`, `REFERRAL_WINDOW_CLOSED`.
- 1-bosqich: `promotions_enabled` flag (production default `false`; production’da yoqish approval reference + admin API markeri + Q48 gate talab qiladi — yangi trigger, mavjud gate’lar o‘zgarmagan), yangi capability’lar, DB xato nomlari `db_errors.CONSTRAINT_RULES` da.
- Ochiq: HMAC saqlash muddati va huquqiy asosi (Q108) — production’da bu himoyaga bog‘liq oqimlar tayyor deb belgilanmaydi; mukofot summalari, budjet, O, M, share, per-booking cap — 6-bosqich simulyatsiyasidan keyin; review SLA, restoration grace, milestone qiymatlari — konfiguratsiya, hozir faqat sintetik, production qiymati tasdiqlanmagan; `elchigo.uz/r/<kod>` andozasi belgilangan, lekin domen egaligi, DNS, sertifikat va deploy — alohida texnik tekshiruv; Android App Links (handoff).
