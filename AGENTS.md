# Elchi — agentlar uchun majburiy qoidalar (2-bosqich)

Bu fayl shu repository’da ishlaydigan barcha dasturlash agentlariga tegishli. `android-app/` va `frontend/` **muzlatilgan**: hech bir agent ularni tahrirlamaydi. `android-app/` boshqa (Android) dasturchiga tegishli va o‘zining `android-app/AGENTS.md` qoidalariga ega; bu fayl u qoidalarga zid emas va hech kimga `android-app/`ni o‘zgartirish huquqini bermaydi.

## 1. Manba tartibi (ziddiyatda yuqorisi ustun)
1. `docs/architecture/ELCHI_PRODUCTION_ARCHITECTURE.md` — spetsifikatsiya (o‘zgartirilmaydi).
2. Foydalanuvchi qarorlari (§3) va ADR’lar: `docs/architecture/adr/` — 0001–0018 hammasi `Accepted` (Q19).
3. Kontraktlar: `app/contracts/`, `docs/architecture/API_V2_CONTRACT.md`, `STATE_MACHINES.md`, `DATA_MODEL.md`.
4. Mavjud kod. `docs/PROJECT_OVERVIEW.md` noaniq bo‘lishi mumkin — `BASELINE_AUDIT.md`ni ko‘ring.
5. `docs/archive/stage1/**` — faqat tarix; qoida emas.

Kontrakt o‘zgarishi faqat integrator (A0a) orqali, boshqa agentlarga yetkazilgandan keyin.

## 2. Taqiqlar
- **Muzlatilgan:** `android-app/`, `frontend/` — hech qachon tahrirlanmaydi.
- `/api/v1` backward compatible: yo‘l, javob shakli `{success, data, message}` / `{success:false, error:{code,message,details}}`, JWT `role` claim, OTP `role` parametri, `users.role` semantikasi o‘zgarmaydi. v1 xulq o‘zgarishi faqat tasdiqlangan qaror bilan (§3: Q2, Q10).
- `git commit`, `push`, `stash`, `reset`, `checkout`, `clean`, deploy, production’ga ulanish — **taqiq**. Barcha o‘zgarish lokal.
- O‘zga agent egaligidagi faylni tahrirlash taqiq (egalik — wave kartalarida).
- Production bazani reset qilish, downgrade’ni rollback sifatida ishlatish, legacy jadval/ustunni o‘chirish — taqiq (expand → migrate → switch → contract; tuzatish forward migration, spec §18.3).
- Tanlanmagan kutubxona versiyasini taxmin bilan kiritish taqiq; yangi dependency ADR yoki karta asosida, pin bilan.

## 3. Foydalanuvchi qarorlari
**Boshlang‘ich (13.09.2026):** K1 1-bosqich hujjatlari arxivda • K2 private upload’lar — H0 • K3 stage-2 production faqat O‘zbekistondagi hostingda, deploy host-agnostic • K5 komissiya admin paneldan versiyalangan policy, bron snapshot, fee-quote muzlatish (AC43), klientda qattiq foiz yo‘q • K6 store release 2-bosqichdan keyin • K7 yo‘lovchi xizmati quriladi, production’da `passenger_enabled=false` huquqiy tekshiruvgacha • M4/S1 stage-2 klient — `mobile-app/`, backend to‘liq (GPS ingestion ham).

**Wave 0.5 tasdiqlari (13.09.2026):**
- **Q1** 0% komissiya faqat aniq muddatli `campaign` policy sifatida va bronda snapshot. `wallet_required` production’da `false` bo‘la olmaydi; boshqa muhitda `false` faqat balans yetarliligi tekshiruvini o‘tkazib yuboradi — fee hisoblanadi, snapshot va hold qilinadi.
- **Q2** Commission policy’ni faqat `super_admin` yaratadi/o‘zgartiradi; `admin`, `operator` — faqat o‘qish. v1 settings PATCH ham shu qoidada, javob shakli o‘zgarmaydi.
- **Q3** Staff va marketplace (client/driver) akkauntlari alohida.
- **Q4** Legacy v1 buyurtmalar v2’da faqat read-only view/proyeksiya; v2 yozuv jadvallarida legacy qator yo‘q. v1 (Android) va v2 (mobile-app) pochta bozorlari parallel; v1 cutover 2-bosqichga kirmaydi.
- **Q5** Production’da har yangi xizmat (passenger, v2 parcel, driver listing, tracking) koridor bo‘yicha yoqilguncha o‘chiq; passenger uchun qo‘shimcha `super_admin` + huquqiy approval reference.
- **Q6** Cargo rasmi faqat buyurtma egasi va tayinlangan haydovchiga (staff — admin orqali). H0 bajaradi.
- **Q7** No-show’ni haydovchi faqat xabar qiladi; bron `awaiting_pickup`da pending review bilan qoladi; `no_show`ga faqat operator `confirm_no_show` o‘tkazadi; `reject_no_show` yo‘li bor.
- **Q8** OTP hozircha 4 xona (6 xona Android v2 klienti bilan). Review/store akkauntlari real foydalanuvchi va pulga yetmaydi — H1. Staff MFA rejasi — A12 (wave 3).
- **Q9** Legacy naive timestamp → `timestamptz` — wave 5 (A10b), avval v1 moslik tekshiruvi.
- **Q10** v1: operator admin order endpointlari orqali status majburlay, driver tayinlay, bekor qila olmaydi (admin+). Nizo yozuvisiz `disputed` taqiq. Egasi H1.
- **Q11** `mobile-app` — npm; `pnpm-lock.yaml` olib tashlanadi (A0b).

**Wave 1 tasdiqlari (13.09.2026):**
- **Q12** v1: nizo `open`/`under_review` bo‘lsa buyurtma statusini qo‘lda o‘zgartirish taqiq (409). Egasi H1.
- **Q13** v1: buyurtma statusini tiklaydigan/o‘zgartiradigan nizo hal qilish/rad etish — faqat admin+; operator ko‘rib chiqadi va izoh yozadi. Egasi H1.
- **Q14** v1: majburiy `confirmed` → `paid_manual` o‘zgarishsiz qoladi; kelajak moliyaviy hisobotlarda “tasdiqlanmagan” deb belgilanadi (A9/A13).
- **Q15** v1 `block_driver` faol v2 trip’li haydovchi uchun faqat yangi biznesni bloklaydi (v2 eligibility bloki); faol trip, GPS, support davom etadi. To‘liq favqulodda blok — faqat super_admin. Egasi A4/A12 (v2 trip’lar paydo bo‘lgach).
- **Q16** Komissiya holati mijozdan yashirin, mijozga yuboriladigan event’larda ham (N2).
- **Q17** Alohida `finance` staff roli: top-up tasdiqlash, `finalize_fee`, moliya hisobotlari; katta tuzatishlar ikki **turli** xodim bilan. Rol ulangunicha super_admin bajaradi. Egasi A1 (rol), A3 (capability tekshiruvi).
- **Q18** v1 `BID_NOT_ACTIVE` 409 saqlanadi.
- **Q19** Qolgan barcha ADR’lar qabul qilindi. Kampaniya standard’dan ustun, keyin eng aniq scope; boarding oynasi 60 daqiqa (konfiguratsiya); amendment bron fee snapshot’ini saqlaydi; request listing faqat driver/operator bekor qilgach, amal qiladigan oynada qayta ochiladi va mijozga xabar beriladi; pending no-show review davomida faqat operator bekor qila oladi.

**Wave 1.5 tasdiqlari (14.09.2026):**
- **Q20** Listing tahriri ochiq takliflarni faqat yo‘nalish, oyna, miqdor/`seat_count` yoki `price_basis` o‘zgarsa expire qiladi; birlik narxi, izoh, amal muddati, qulayliklar, maxsus yordam tahriri expire qilmaydi.
- **Q21** Bloklangan/eligible bo‘lmagan haydovchi trip_offer’iga mijoz taklifi rad (`DRIVER_NOT_ELIGIBLE`); A5 lentasi bunday takliflarni yashiradi.
- **Q22** Faol driver akkaunti tasdiqlashdan oldin yoki blokda ham wallet’ni ko‘ra va top-up so‘ray oladi (yangi biznes emas).
- **Q23** Operator boshqaning listing’ini `ops.booking_command` + audit qatori bilan bekor qiladi; `draft`ni bekor qila olmaydi.
- **Q24** Geoapify/hosted router production’da huquqiy/data-flow va provider shartlari tekshiruvigacha o‘chiq. Provider geometriyasini doimiy saqlash faqat shartlar ruxsat bersa; aks holda bekatlar, kumulyativ qiymatlar va request hash saqlanadi.
- **Q25** Bir oyoq (leg)da ikki detour rad (pilot cheklovi).
- **Q26** Bir scope darajasida ziddiyatli flag qatorlari → o‘chiq (xavfsiz default).
- **Q27** Pilotda bekat yaratuvchisi verifier hisoblanadi; koridor `pilot`ga o‘tishidan oldin bekatlarda meeting note yoki foto dalil bo‘lishi shart.
- **Q28** Faqat migratsiya seed global standard policy (`created_by IS NULL`) amal qilsa, production v2 quote/hold bloklanadi — super_admin stavkani tasdiqlaguncha/yaratguncha (go-live checklist).
- **Q29** 0036 noto‘g‘ri legacy stavkada qattiq yiqiladi; deploy oldi tekshiruv skripti (A10a).
- **Q30** Kichik tuzatishlarni bo‘lish moliya hisobotlarida belgilanadi; pilotda qat’iy kunlik limit yo‘q.
- **Q31** O‘chirilgan haydovchining qolgan prepaid balansi dalilli finance debit adjustment orqali qaytariladi (runbook).
- **Q32** DB head kod head’ining ma’lum avlodi bo‘lsa readiness 200 `degraded`, `migrations: ahead` (rollback holati); DB orqada yoki noma’lum revision — 503.
- **Q33** `/health/ready` Caddy’da monitoring IP’lariga cheklangan; `/health/live` ochiq.
- **Q34** PostGIS image qo‘llab-quvvatlanadigan Debian (bookworm/trixie), PG ≥ 16.15, digest pin — prod va test, production switch’dan oldin.
- **Q35** WAL shifrlanmaguncha production WAL/PITR yo‘q; faqat kundalik shifrlangan dump, RPO ≤ 24 soat.
- **Q36** Alohida migration/owner DB roli va NOSUPERUSER app roli — PostGIS texnik oynasida.
- **Q37** v1 admin cancel faol nizoda bloklangan qoladi (H1 kengaytmasi); resolve-then-cancel ish tartibi hujjatlanadi.
- **Q38** v1 operator nizoda faqat izoh bilan `under_review`ga o‘tkazadi; resolve/reject — admin+.
- **Q39** Telefonni review allowlist’dan olib tashlashdan oldin o‘sha akkaunt buyurtmalari yopiladi (procedure doc).

**Wave 1.6 tasdiqlari (14.09.2026) — R1/R2 va qayta ko‘rib chiqish:**
- **Q40 (R1, ADR-0019 Accepted)** Mijoz request listing’ida (passenger va parcel) listing’ni ko‘ra oladigan eligible driverlar raqobatchi **joriy** takliflarning anonim ro‘yxatini ko‘radi: yorliq “Haydovchi #3” (listing ichida barqaror, user id’dan olinmaydi), jami va birlik narx, pickup oynasi/segment, avtomobil klassi va o‘rin sig‘imi, reyting bucket’i + bajarilganlar soni, yangilangan vaqt; o‘z taklifi ajratiladi. Ko‘rinmaydi: ism, foto, davlat raqami, telefon, aniq avtomobil.
- **Q41** Mijoz ↔ bitta driver counter shartlari shu juftlikka xususiy; boshqalar har driverning faqat joriy taklifini ko‘radi.
- **Q42** Koridor segmenti bo‘yicha operator sozlaydigan narx floor/ceiling. **Q90 (18.09.2026) bilan yumshatildi:** band endi taklifni bloklamaydi — u ogohlantirish va ranking signali; hard reject faqat `enforced` band va texnik yaroqsizlikda.
- **Q43 (R2, ADR-0020 Accepted — spec §16 dagi “tasdiqlanganda telefon ochiladi” qoidasini foydalanuvchi qarori bilan almashtiradi)** Accept’dan oldin hech bir DTO’da telefon, to‘liq ism, davlat raqami, aniq manzil yo‘q. Barcha erkin matnlar (listing izohi, taklif izohi, chat, parcel tavsifi, reyting matni, profil maydonlari) `app.contracts.contact_filter` orqali: moslik maskalanadi va ogohlantirish qaytadi (telefon har formatda, bo‘shliqli raqamlar, o‘zbek/rus son so‘zlari lotin va kirillda; e-mail, @handle; t.me/telegram/whatsapp/instagram; “qo‘ng‘iroq qiling” naqshlari).
- **Q44** Accept’dan xizmat boshlanguncha (passenger: boarding code/onboard; parcel: `picked_up`) aloqa faqat ilova chati + tezkor javoblar, tracking oynasida haydovchining jonli joylashuvi va “keldim” signali. Ishtirokchi telefonlari start’da ochiladi, yakunlangandan 24 soat keyin yana yashiriladi. Parcel qabul qiluvchi telefoni driverga faqat pickup’dan keyin; jo‘natuvchi telefoni hech qachon. Support/SOS har doim; maskalangan qo‘ng‘iroq keyinroq.
- **Q45** Pilotda jarima yo‘q. Filtr mosligi → ogohlantirish → strike → operator navbati; shu navbatga chat aloqasidan keyin tez bekor qilish va bir juftlikning takroriy bekor qilishlari signallari. Rasmlar — operator tanlab tekshiradi, OCR keyin. v1/muzlatilgan Android o‘zgarmaydi (ma’lum bo‘shliq).
- **Q46** Production’da routing provayderi yo‘q → detour match bo‘lmaydi, faqat tasdiqlangan bekat match’lari; mahsulot matni shuni aytadi.
- **Q47** Pilot/active koridorda ≥ 2 faol bekat va bekat dalili (Q27) uzluksiz majburiy (faqat o‘tishda emas).
- **Q48** DB rollari ajratilmaguncha (Q36) va balans guard tuzatishi kirmaguncha production v2 pul oqimi yo‘q (launch gate).
- **Q49** Adjustment reject — faqat `finance.adjustment_approve`li **boshqa** foydalanuvchi; so‘rovchi faqat withdraw.
- **Q50** Eski image’ga rollback’da readiness 503 hozircha qabul (monitoring toqat qiladi). Launch’dan oldin migratsiyalar revision lineage (revision → parent) jadvaliga yozadi, eski image “ahead”ni taniydi — launch gate, dizayn ADR-0012/0016 da, egasi A0a/A10a.
- **Q51** Oldindan qurilgan PostGIS image O‘zbekistondagi private registry’da, digest bilan pin; deploy serverda db image qurmaydi.

**Wave 2 tasdiqlari (15.09.2026):**
- **Q52** Pilotda narx band’ini tahrirlash — admin+ (`ops.corridor_manage`). Operatorlarga kerak bo‘lsa keyin alohida `ops.price_band_manage`.
- **Q53** Koridor bo‘yicha band — keng xavfsizlik chegarasi; aniq segment band — real narx. Band faqat submit/counter’da baholanadi, accept’da qayta baholanmaydi; narxni o‘zgartirmaydigan counter uni o‘tkazib yuboradi. **Q90:** natija rad emas, ogohlantirish.
- **Q54** Accept `proposal_versions.listing_terms_version`ni `listings.terms_version` bilan solishtiradi (`listings.version` emas). `ListingDTO.terms_version` ochiq; accept body’dagi `expected_listing_version` shunga ishora qiladi (kontraktda additiv alias `expected_listing_terms_version`).
- **Q55** Har ledger posting (`ledger_transactions`) DB’da aniq bitta biznes manbaga bog‘lanadi: tasdiqlangan top-up, posted adjustment, commission hold capture/release yoki captured charge reversal. Reconciliation orphan posting’larni ham tekshiradi. Q48 launch gate’ining qismi. Egasi A3.
- **Q56** Q48 deploy’da (A10a) va runtime/DB’da majburiy: production’da v2 xizmat flag’lari (`passenger_enabled`, `parcel_enabled`, `driver_listing_enabled`, `corridor_matching_enabled`, `tracking_enabled`, `card_payments_enabled`) Q48 gate o‘tmaguncha yoqilmaydi. Gate shartlari: app roli superuser/bypassrls emas, app roli `ledger_account_balances`ga yoza olmaydi, balans guard `pg_trigger_depth` bilan, Q55 manba bog‘lanishlari majburiy, Q28 seed stavka tasdiqlangan. Gate holati production invariant ham. Egalar: A3 (gate funksiyasi), A2 (flag yoqish guard’i + DB trigger), A10a (deploy `--v1-only`).
- **Q57** Q28 tasdiqlanmagan seed eslatmasi `/health/ready`da faqat ma’lumot, hech qachon 503 emas (A10a).
- **Q58** UZ registry paydo bo‘lgach `tests/pg` va `restore_drill` `ELCHI_POSTGIS_IMAGE` (registry digest) ishlatadi; lokal build faqat dev zaxirasi (A10a).

**Wave 2.1 tasdiqlari (15.09.2026):**
- **Q59** A4 `app/modules/bookings/bridges.py` (A1 jadvallariga vaqtinchalik ko‘prik) faqat 2.1-bosqich oxirigacha; A1 public servis funksiyalarini chiqaradi, ko‘prik o‘chiriladi.
- **Q60** Bron snapshot’ida faqat miqdor, narx, jami, komissiya va o‘rin ustunlari o‘zgaradi — faqat qabul qilingan amendment orqali; qolgan snapshot ustunlari DB’da muzlatiladi (trigger).
- **Q61** Mashina tasdig‘i bekor bo‘lsa faqat yangi bronlar bloklanadi (accept’da mashina holati qayta tekshiriladi); mavjud bronlar majburiyat sifatida davom etadi.
- **Q62** Detour va AC13 pilotda qoldiriladi (Q46): accept detour quote’ni barcha muhitlarda rad etadi.
- **Q63** Trip’da bironta allocation bo‘lsa (qaytarilgan/inactive ham) bekatlarni o‘zgartirish taqiq.
- **Q64** Davlat raqami: accept’dan keyin maskalangan raqam + model + rang; to‘liq raqam trip `boarding` holatida yoki pickup’ga ≤ 30 daqiqa qolganda.
- **Q65** Delivery kodi pilotda jo‘natuvchiga “faqat qabul qiluvchiga bering” ogohlantirishi bilan ko‘rsatiladi. `delivered` bronni avtomatik yakunlamaydi: jo‘natuvchi tasdiqlaydi yoki 24 soatda operator navbatiga tushadi. Chatdagi 6 xonali kodlar maskalanadi. Keyin kod qabul qiluvchiga havola/SMS orqali.
- **Q66** Nizo moduli (A12) yo‘q bo‘lsa 503 o‘rniga xizmat yakunlanadi, komissiya hold’da qoladi va finance navbatiga tushadi.
- **Q67** Counter’da narx band’i narx **yoki** pickup/dropoff bekati o‘zgarsa qayta baholanadi (Q53 aniqlashtirilgan). **Q90:** baholash natijasi ogohlantirish, bloklash emas.
- **Q68** Jo‘natma turi va qulayliklar — kontraktdagi qat’iy enum.
- **Q69** Top-up va adjustment’ni faqat faol `finance` yoki `super_admin` xodimi tasdiqlaydi; DB’da majburlanadi va Q48 gate’ining qismi.
- **Q70** Q48 gate o‘tmaguncha production’da top-up tasdiqlash va kredit adjustment’lar ham bloklanadi.
- **Q71** Q48 gate app roli hech qanday DB ob’ektining egasi emasligini ham tekshiradi.
- **Q72** v2 flag’lar faqat ilova/admin API orqali yoqiladi; psql yoki migratsiya orqali yoqib bo‘lmaydi (DB guard).
- **Q73** Registry tayyor bo‘lgach restore drill faqat digest bilan pin qilingan image ishlatadi.

**Wave 2.1 yakuni tasdiqlari (15.09.2026):**
- **Q74 (Q66 aniqlashtirish)** A12 dispute probe ro‘yxatdan o‘tmaguncha (jadval bor-yo‘qligidan qat’i nazar) har yakunlangan bron capture’siz: commission `held`, `finance_review` navbati. Egasi A4; A12 probe ulangach qayta ko‘riladi.
- **Q75** Wave 2.1 talqinlari qabul: pending no-show review’da trip cancel hamma uchun rad; Q68 qiymatlari (`ParcelType`: documents, box, bag, electronics, clothing, other; `Amenity`: air_conditioning, phone_charger, no_smoking, pets_allowed, large_trunk, wifi); proof reissue self-service 2 daqiqa oraliq va 24 soatda 3, operator limitsiz; Q70 dan debit adjustment va commission reversal ozod; darhol post bo‘ladigan kichik adjustment so‘rovchisi finance/super_admin; Q64 30 daqiqa `pickup_window_start`dan, cancelled/no_show’da to‘liq raqam yo‘q; Q65 capture jo‘natuvchi yoki operator tasdig‘igacha, qabul qiluvchi tasdiqlay olmaydi; `interrupted` trip’da board/pick_up rad; o‘rinni oshiradigan amendment yangi biznes (driver + vehicle eligibility qayta tekshiriladi); Q72 guard cheklovi hujjatlangan holda qabul.
- **Q76** Test stack porti Windows excluded range’dan tashqariga ko‘chiriladi (A0b; `docker-compose.test.yml`, conftest default URL, `scripts/test-pg.*`).

**Wave 3.1 tasdiqlari (16.09.2026):**
- **Q77 (M1)** Nizo ochilganda safar xom GPS nuqtalari alohida dalil jadvaliga (`tracking_evidence_points`) ko‘chiriladi; nusxalanmagan hold’li partition tashlanmaydi. Nizo yopilgach hold bo‘shatiladi va nusxa `EVIDENCE_RETENTION_AFTER_RELEASE` (30 kun) dan keyin o‘chadi. Xom nuqtalarning umumiy 7 kunlik retention’i o‘zgarmaydi. Egalar A6 + A12.
- **Q78** v2 nizo qarori (`resolve`/`reject`) — faqat **admin+** (`ops.dispute_decide`), v1 Q13/Q38 bilan bir xil; operator `start_review` va izoh bilan qoladi (izoh audit qatorida). Naqd natija nizo qarorining o‘z maydoni (`DisputeCommand.cash_outcome`): `resolution_code` bilan zid bo‘lsa rad, `contested` kvitansiyali payment nizosi natijasiz yopilmaydi. `resolve_contested_cash_receipt` ham `ops.dispute_decide` talab qiladi.
- **Q79 (W21-4)** Trip-offer parcel’da qabul qiluvchi majburiy: mijoz taklifida so‘raladi (counter oldingi qabul qiluvchini saqlaydi), `pick_up` qabul qiluvchisiz rad etiladi.
- **Q80 (U5)** v1 staff kirishi effektiv rollarni (`users.role` + faol `user_roles`) tan oladi, **doira faqat `admin_drivers.py`**; Q3 saqlanadi (marketplace akkaunt staff bo‘lmaydi), javob kodi/matni/shakli o‘zgarmaydi.
- **Q81 (U1)** Parcel jo‘natuvchisi haydovchining jonli joylashuvini **pickup’dan keyin** ko‘radi (kontraktdagi konservativ qoida saqlanadi).
- **Q82 (U3)** Push provayderi tanlanmaguncha faqat ilova ichidagi xabarlar; `communications.push_delivery` vazifasi ulangan, provayder o‘chiq bo‘lsa DB’ga tegmaydi. Provayder — alohida ADR.
- **Q83 (U4)** Pilot sonlari: strike — 7 kunda 1 ta bepul moslik, 30 kunda 3 ta → operator navbati; chat — daqiqasiga 20 xabar, bron yopilgach 24 soat; saqlangan qidiruv — 10 ta, 60 kunlik oyna; support — soatiga 5 so‘rov; quick-cancel 1 soat, juftlik 30 kunda 2 bekor; push dedup 10 daqiqa; tracking grant TTL 15 daq–24 soat.
- **Q84 (U8)** Nizo hal bo‘lgach avtomatik capture yo‘q: bron `finance_review` navbatiga `dispute_resolved` sababi bilan tushadi, finance `finalize_fee` bilan qo‘lda yakunlaydi (pilot).
- **Q85 (L7)** Chatdagi 6 xonali son (`proof_code` kategoriyasi) faqat maskalanadi — strike va review sanog‘iga kirmaydi.
- **Q86 (W3-3)** Kuzatuv oynasi yopiq bo‘lsa ham xodim oxirgi nuqtani audit qatori bilan ko‘ra oladi (operatsion vazifa doirasi, §10.6).

- **Q87 (U7)** Pilotda real support telefoni **yo‘q**: `ELCHI_SUPPORT_PHONE` bo‘sh qoladi, S13 `available=false` qaytaradi, ilovada raqam ko‘rsatilmaydi va hech qanday javob vaqti va’da qilinmaydi (§5.2, §16). Support faqat ilova ichidagi ticket/SOS orqali. **Passenger xizmatini yoqishdan oldin** javob beriladigan raqam va rost ish vaqti matni kiritilishi shart — go-live checklist bandi (A10a runbook).

**Wave 13 qarori (18.09.2026):**
- **Q88 (foydalanuvchi qarori, spec §6.1/§6.2 dan chekinish)** Mijoz yo'nalish uchidagi joyni **xaritadan ixtiyoriy
  nuqta** sifatida belgilaydi: hudud → tuman → xaritada joy. Tasdiqlangan bekat tanlash **shart emas**. Sabab:
  katalogda 170 tumandan atigi 6 tasida faol bekat bor, shuning uchun bekatga majburlash mijozni amalda
  bloklaydi.

  Xavotir bildirildi va foydalanuvchi qarorni tasdiqladi. Spec bilan ziddiyat ochiq yoziladi: §6.1/§6.2 va
  46/55/186-qatorlar tuman markazi bo'yicha moslashtirishni ataylab rad etgan; bu qaror o'sha rad etishni
  qisman qaytaradi. Shuning uchun quyidagi cheklovlar **majburiy** qilinadi, aks holda «tekshirilmagan joy»
  butun moslik va bron modelini buzadi:

  1. Nuqta **tasdiqlangan marshrutga proyeksiya** qilinadi (`ST_LineLocatePoint`, spec §6.3 4-qadam shu
     mexanizmni allaqachon nazarda tutadi). Marshrutdan ruxsat etilgan radiusdan uzoq nuqta qabul qilinmaydi
     (`ROUTE_MISMATCH`); radius — operator sozlaydigan pilot qiymati.
  2. Sig'im baribir **segment** bo'yicha taqsimlanadi: proyeksiya nuqtasi tushgan segment `pickup_occurrence_seq`
     ni beradi, ya'ni `booking_allocations` modeli o'zgarmaydi.
  3. Tartib saqlanadi: pickup proyeksiyasi dropoff proyeksiyasidan oldin bo'lishi shart.
  4. Bekat uchi **olib tashlanmaydi** — u qoladi va tasdiqlangan bekat tanlangan e'lon `exact` moslik oladi;
     ixtiyoriy nuqta esa eng yaxshi holatda `on_route` bo'ladi va mahsulot matnida shunday ataladi.
  5. «Keldim» va proof kodlari kelishilgan nuqtada bajariladi; bekat dalili (Q27) faqat bekat uchlariga
     tegishli bo'lib qoladi.

  Q47 (koridorda ≥2 faol bekat) **o'zgarmaydi**: u koridorning ishga tushishi sharti, mijoz uchi emas.
- **Q89** Yo'lovchi xizmati klientda quriladi (K7: «yo'lovchi xizmati quriladi»). Bosh sahifada «Yuk yuborish»
  yonida yo'lovchi rejimi; `passenger_enabled` flag koridor doirasida o'chiq bo'lsa rejim ko'rinmaydi va
  ochilmaydi. Production'da flag huquqiy tekshiruvgacha `false` bo'lib qoladi (K7/Q5).

**Wave 15 qarori (18.09.2026) — arxitektura driftini tuzatish:**
- **Q90 (Q42/Q53/Q67 ning *hard reject* semantikasini bekor qiladi)** ELCHI — ikki tomonlama **auksion**
  marketplace: narxni tomonlar kelishuvi shakllantiradi, platforma emas. Shuning uchun koridor narx bandi
  taklif yoki qarshi taklifni **bloklamaydi**. Band endi **maslahat signali**: javobda ogohlantirish
  (`PRICE_OUT_OF_BAND` kodi `ApiWarning` sifatida), ranking va anomaliya/fraud signali uchun ishlatiladi.

  Hard reject faqat texnik yoki huquqiy jihatdan yaroqsiz holatlarda qoladi: `unit_price_minor <= 0`,
  butun son chegarasidan oshish, noto'g'ri valyuta, `price_basis` ziddiyati (Q53 ALLOWED_PRICE_BASIS) va
  **admin alohida tasdiqlagan** abuse/safety chegarasi (`corridor_price_bands.enforced = true`).

  Sabab: `Mijoz 300k → Driver 350k → Mijoz 320k → Driver 330k → ACCEPT` ketma-ketligida bron jami **330 000**
  bo'lishi shart; platforma uni «hisoblangan tarif» bilan almashtirmaydi va oraliq qadamlarni bloklamaydi.

- **Q91 (Q7 ni aniqlashtiradi)** Q7 — **faqat rollout flag'i**, arxitektura qarori emas. `request + passenger`
  modeli, proposal oqimi, API kontrakti va domen invariantlari **hech qachon olib tashlanmaydi**.
  Production'da `passenger_enabled=false` bo'lsa faqat yangi passenger request UI navigatsiyasi yopiladi.
  Wave 13 dagi «klientda passenger oqimi umuman bo'lmasin» degan qo'riqchi test **xato** edi va olib
  tashlandi.

- **Q92** To'rtala listing turi ham mahsulot doirasida va **har ikki tomonda kirish nuqtasi bo'lishi shart**:
  `request+passenger`, `request+parcel` (muallif — mijoz/jo'natuvchi), `trip_offer+passenger`,
  `trip_offer+parcel` (muallif — haydovchi). Haydovchi faqat javob beruvchi emas: u o'z safarini narx bilan
  e'lon qiladi; mijoz o'z narxini taklif qiladi. Feed ikki tomonlama: haydovchi `side=requests`, mijoz
  `side=offers` ko'radi.

- **Q93** Koridor/marshrut/proyeksiya — **ichki matching qatlami**: mos safarni topish, pickup/dropoff
  tartibi, segment sig'imi, ETA/detour va rollout uchun. Foydalanuvchi oqimi «koridor tanlang → tizim narx
  beradi → bron» emas, balki «A nuqta + B nuqta → mos e'lonlar → taklif/qarshi taklif → qabul → bron».

**Wave 16 qarori (22.09.2026) — haydovchi oqimi:**
- **Q94 (v1 xulqini ataylab o'zgartiradi; §2 dagi «v1 xulq o'zgarishi faqat tasdiqlangan qaror bilan» bandi
  asosida)** Haydovchi avtomobil ma'lumotlarini (model, rang, davlat raqami, o'rin va yuk sig'imi) **bir
  marta** kiritadi. Birinchi saqlashdan keyin maydon qulflanadi — **tasdiqlashni kutmasdan**, chunki
  «pending» holatda almashtirilgan mashina ham mijozga ko'rinmay qoladi. O'zgartirish faqat operator yoki
  admin orqali: `PATCH /api/v1/admin/drivers/{driver_id}/vehicle` (audit qatori bilan).
  - v1: `DRIVER_VEHICLE_LOCKED` endi `approved` emas, **qiymat mavjud** bo'lganda qaytadi. Ma'lum ta'sir:
    muzlatilgan `android-app/` haydovchisi ham tasdiqdan oldin xatosini o'zi tuzata olmaydi — operatorga
    murojaat qiladi.
  - v2: ro'yxatdan o'tgan avtomobil qatori o'zgarmas (update endpointi yo'q). Ikkinchi avtomobil qo'shish
    taqiqlanmaydi, chunki u `pending` holatda tug'iladi va xodim tasdiqlamaguncha na safar, na bron uchun
    ishlatiladi — ya'ni yangi mashina baribir operator/admin orqali o'tadi. Klientda profil formasi faqat
    bitta avtomobil yaratadi.
- **Q95 (Q40 ni klientda amalga oshirish)** Raqobat takliflari taxtasi haydovchining taklif berish ekranida
  ko'rsatiladi (`ListingOfferDTO`, anonim). Auksionda taklif beruvchi kitobni ko'rmasa narx shakllanmaydi
  (Q90). Endpoint yopiq bo'lsa (flag/koridor → 404) taxta ko'rsatilmaydi, lekin taklif berish bloklanmaydi.
- **Q96 (D16 ning klient tomoni)** Tasdiqlanmagan haydovchiga `driver-feed`, `driver-bid`, `driver-routes`
  va `driver-offer-create` ekranlari sababni va keyingi qadamni aytadi; `rejected`/`blocked` holatda
  qo'llab-quvvatlashga yo'naltiradi. Server allaqachon `DRIVER_NOT_ELIGIBLE` bilan rad etadi — bu qo'shimcha
  qatlam, almashtirish emas.

**Wave 17 qarori (22.09.2026) — tavsiya etilgan (muqobil) e'lonlar:**
- **Q97 (foydalanuvchi qarori)** Klient endi uchala topish yo'lida ham `include_alternatives=true` yuboradi:
  haydovchi lentasi (`side=requests`), mijoz lentasi (`side=offers`) va `GET /listings/{id}/matches`.
  Sabab: mexanizm serverda bor edi, lekin hech bir klient chaqiruvi flagni yoqmagani uchun aniq yo'nalishida
  e'lon topmagan haydovchi bo'sh ekran ko'rardi. Server standarti `false` bo'lib **qoladi** — bu klient
  qarori, kontrakt o'zgarishi emas.
  - Muqobil natijalar hech qachon asosiy natijalar bilan aralashtirilmaydi: alohida «Tavsiya etilgan e'lonlar»
    sarlavhasi ostida, punktir ramka va sababi bilan (`time_differs` → «Vaqti boshqa», `nearby_stop` →
    «Yaqin bekat»). Ajratish `mobile-app/src/app/feedGroups.ts` da — sof modul, `auction.ts` kabi.
  - Q46 saqlanadi: kengaytirish o'lchangan detourni anglatmaydi; `confirmed_stops` ogohlantirishi o'z
    o'rnida qoladi.

**Wave 17 qarori (22.09.2026) — ko'rishlar soni:**
- **Q98 (foydalanuvchi qarori)** Har e'londa **ko'rishlar soni** bo'ladi va u **odamlar** sonini bildiradi:
  `listing_views` jadvali PK `(listing_id, viewer_user_id)`, `listings.view_count` esa faqat qator yaratgan
  insert'da oshadi (migratsiya 0083). Bitta foydalanuvchi necha marta ochsa ham — 1 ta ko'rish.
  - **Sanalmaydi:** e'lon egasi (o'z e'lonini tekshirishi qiziqish bo'lib ko'rinmasligi uchun), xodim
    (operator navbat bilan ishlaydi, talab emas) va **anonim o'quvchi**, shu jumladan ommaviy share sahifasi —
    identifikatsiya yo'q joyda dedublikatsiya ham yo'q, qayta yuklash bilan ko'tariladigan son esa o'ylab
    topilgan signal (§9). Taxminiy son aniq son sifatida ko'rsatilmaydi.
  - Yozish `GET /api/v2/listings/{id}` ichida (feed'dagi `record_search` va xodim kontakt auditi kabi).
    `version`, `terms_version`, `updated_at` **tegilmaydi** — o'qish tahrir emas, aks holda e'lonni ochgan
    odam undagi barcha ochiq takliflarni bekor qilgan bo'lardi (Q54).
  - Son ikkala DTO'da (`ListingDTO`, `ListingPublicDTO`) — kimligini oshkor qilmaydi, faqat son.
- **Q99 (Q92 ning klient tomoni)** Bitta safarga ikkala xizmat e'lonini qo'yish DB'da allaqachon ruxsat etilgan
  (`uq_listings_open_trip_offer` — `(trip_id, service_type)`). Klient endi e'lon formasini safar **hali
  e'lon qilmagan** xizmat turida ochadi; ikkalasi ham bor bo'lsa tugma ko'rsatilmaydi. Qoida sof modulda:
  `mobile-app/src/app/tripOffers.ts` (indeks predikati bilan bir xil: `cancelled`/`expired` xizmatni
  bo'shatadi).

**Wave 17 qarori (22.09.2026) — chat oqimi:**
- **Q100 (foydalanuvchi qarori; Q44 ni klientda mustahkamlaydi)** Narx muzokarasi va suhbat **ikki alohida
  mexanizm**. Klient **faqat bron chatini** ochadi: `POST/GET /proposals/{id}/messages` mavjud (xodim va
  kelajakdagi qaror uchun), lekin ilova unga **murojaat qilmaydi** — aks holda narx erkin matnda kelishiladi
  va muzlatilgan `proposal_versions` tarixi to'liq yozuv bo'lishdan to'xtaydi.
  - **Chat qabul qilish bilan ochiladi:** ikkala accept yo'li ham (mijoz haydovchini tanlaganda va haydovchi
    mijoz narxini qabul qilganda) bronni yuklab, to'g'ridan-to'g'ri chat ekraniga o'tadi.
  - **Safar tugagach read-only:** `chat_writable` bo'yicha bron chati terminal holatdan keyin 24 soat yoziladi
    (`CHAT_WRITABLE_AFTER_TERMINAL`), keyin yopiladi. Yangi `GET /api/v2/bookings/{id}/chat` →
    `ChatThreadDTO {writable, writable_until, message_count}` klientga kompozitorni chizishdan **oldin**
    holatni aytadi; yopilgan chatda yozish maydoni o'rniga tushuntirish, yozishmalar o'qish uchun qoladi.
  - **Tezkor javoblar** (§16) klientda: haydovchida `arriving_in_5_min`, `at_stop`, `clarify_stop`; mijozda
    `at_stop`, `clarify_stop`. `price_agreed` bron chatida **taklif qilinmaydi** — narx allaqachon kelishilgan,
    uni qayta tasdiqlash tugmasi savdolashishga taklif bo'lardi (va §16 bo'yicha shartni o'zgartirmaydi ham).

**Referral 0-bosqich qarorlari (23.09.2026) — promotions & referral (ADR-0023):**
- **Q101 (D1)** Referral/bonus/kredit — spec §9.2 dan tashqari yangi domen, ADR-0023 bilan (spec o‘zgartirilmaydi).
  Bitta mexanizm yo‘lovchi va pochtaga xizmat qiladi, lekin kampaniya, qualification sharti va limitlar xizmat
  turi bo‘yicha alohida. Referral qo‘shilishi hech bir mavjud xizmat yoki production flag’ini yoqmaydi; o‘z flag’i
  `promotions_enabled` production’da `false`, kampaniyalar `draft`.
- **Q102 (D2)** Modul `app/modules/promotions`; hisob — sof `app/contracts/promo.py` (DB/tarmoq/sozlama/soat yo‘q,
  parametrlar aniq argument). Driver prepaid balance (real pul), Passenger Bonus va Driver Credit (chegirma
  huquqi, pul emas, naqdlashtirilmaydi, o‘tkazilmaydi) alohida hisoblanadi; referral real ledger’ga yozmaydi.
- **Q103 (D3, Q16 talqini)** Mijoz kelishilgan narx, qo‘llangan chegirma va yakuniy naqdni ko‘radi; stavka, C, H, O,
  M va formula mijoz API/event’ida yo‘q. Haydovchi naqd olinadigan summa, undiriladigan komissiya va ishlatilgan
  kreditni ko‘radi. Bu bevosita oshkor qilmaslik; taxmin qilib bo‘lmaslik kafolati berilmaydi; noto‘g‘ri narx yoki
  chegirma ko‘rsatilmaydi.
- **Q104 (D4)** Passenger Bonus faqat aniq oldindan rozilik bilan: taklif yuborishda yoki counter’ni qabul qilishda,
  taklif versiyasi, F, P, F_cash va muddat bilan bog‘langan. Haydovchi mijozsiz accept qilsa aynan shu shartlar;
  aks holda `PROMO_QUOTE_STALE` va yangi rozilik — naqd hech qachon yashirin oshmaydi. Amendment moliyaviy
  shartlari qayta tasdiqlanadi. H accept’da avtomatik, umumiy limit yetmasa avval tasdiqlangan P saqlanadi.
  Pochta pilotida bonus egasi = jo‘natuvchi = to‘lovchi; qabul qiluvchi to‘laydigan buyurtmada ishlatilmaydi.
- **Q105 (D5)** Budjet ajratish — alohida moliyaviy capability (`promo.budget_allocate`, finance/super_admin, katta
  summa ikki turli xodim); kampaniya aktivlashtirish — super_admin (`promo.campaign_manage`). Operator budjet yoki
  mukofot summasini o‘zgartirmaydi. Hamma o‘zgarish audit’da. Tasdiqlanmagan parametr hech qachon nol emas
  (`PROMO_PARAMETERS_UNSET`); summa/budjet/O/M simulyatsiyadan keyin. Va’da paytida ikkala tomon maksimal
  majburiyati rezerv qilinadi; budjet tugashi faqat yangi ishtirokchilarni to‘xtatadi.
- **Q106 (D6)** Attribution oynasi 72 soat — telefon tasdiqlangan birinchi ro‘yxatdan o‘tishdan, birinchi bron
  accept’igacha, server vaqti. Birinchi attribution almashtirilmaydi; akkauntni qayta ochish oynani yangilamaydi.
  Yo‘lovchi va pochta orqali “yangi mijoz” mukofoti bir marta (`client_acquisition` oilasi); reactivation alohida.
  Mijozning haydovchiga aylanishi — driver onboarding’ga bog‘langan alohida attribution qoidasi.
- **Q107 (D7)** Havola `elchigo.uz/r/<kod>`, domen konfiguratsiyada, PII’siz kod. Ilova yo‘q/App Links ishlamasa —
  tushuntirish sahifasi va kodni qo‘lda kiritish. Domen, sertifikat, App Links tekshirilmaguncha “tayyor” emas;
  `android-app` — faqat handoff.
- **Q108 (D8)** Telefon HMAC mexanizmi tasdiqlangan; **24 oylik muddat tasdiqlanmagan** — muddat konfiguratsiya,
  kodga doimiy qiymat kiritilmaydi. HMAC anonim emas — himoyalangan identifikator; maqsad, huquqiy asos, muddat,
  o‘chirish va kalit boshqaruvi yoziladi (production yoqish sharti). Moslik akkaunt yoki xizmatni bloklamaydi —
  faqat yangi foydalanuvchi mukofotini review’ga yuboradi.
- **Q109 (D9)** Taklif qiluvchi xizmat ko‘rsatgan bron attribution’ni qualify qilmaydi (oddiy bron sifatida
  taqiqlanmaydi); boshqa tasdiqlangan haydovchining xizmati hisoblanadi. Yo‘lovchi — 1 mos safar; pochta — 2 ta
  mustaqil (alohida bron va trip) yetkazilgan jo‘natma, bitta bronning qutilari bitta jo‘natma. Mukofot o‘sha
  xizmat kampaniyasidan va o‘sha xizmatda sarflanadi; xizmatlararo sarflash avtomatik yoqilmaydi.
- **Q110 (D10)** Qualification: xizmat bajarilgan + naqd tasdiqlangan + real balansdan musbat C_net capture + ochiq
  nizo yo‘q; 48 soatlik risk oynasi shu shartlarning eng oxirgisidan, grant oldidan qayta tekshiruv. 0% va
  chegirma sabab C_net = 0 bronlar hisoblanmaydi; GPS yoki “bajarildi” yolg‘iz yetarli emas. `F_cash = F − P`,
  `C_net = C − P − H`, haydovchida `F − C + H`; promo bronda `F_cash, C_net ≥ 0`, `C_net − O ≥ M`, P + H umumiy
  limit ichida, float yo‘q. Real balansdan faqat C_net hold/capture; cash receipt F_cash bilan tekshiriladi;
  Q55/Q48 avtomatik yopilgan hisoblanmaydi. `X-Elchi-Client-Features` xavfsizlik vakolati emas; mos kelmaydigan
  klient yangi promo bitim tuzmaydi, mavjud chegirma olib tashlanmaydi. Bron marjasi qoidasi umumiy foyda kafolati
  emas.

**Referral 1-bosqich qarorlari (23.09.2026) — ADR-0023:**
- **Q111** Promo qo‘llanadigan bronda `O ≥ 0`, `M > 0`, `C_net > 0` va `C_net − O ≥ M` (pilot). Oddiy va alohida
  tasdiqlangan 0 % bronlar ishlashda davom etadi — ularga promo qo‘llanmaydi. M o‘ylab topilmaydi; belgilanmasa
  kampaniya aktivlashtirilmaydi. Faqat chegirma **limitlari** pastga yaxlitlanadi; tasdiqlangan mijoz chegirmasi keyin
  kamaytirilmaydi; ledger, ekran va kvitansiya bir xil `PromoQuote` summalarini ko‘rsatadi. Umumiy foyda kafolati emas.
- **Q112** Taklif qiluvchi bajargan bron ikkala tomon qualification’iga hisoblanmaydi (pilot); shart qo‘shilishdan oldin
  ko‘rsatiladi; mijoz o‘sha haydovchidan oddiy xizmat oladi. Bunday bron referral’ni yopmaydi — qualification muddati
  ichida boshqa haydovchi orqali shart bajarilishi mumkin. Attribution oynasi va qualification muddati alohida.
- **Q113** Mustaqil jo‘natma = alohida haqiqiy bron + o‘z qabul-topshirish qaydi + yetkazish dalili + komissiya
  capture; bitta trip’dagi ikki mustaqil jo‘natma chiqarilmaydi; bitta bronning ikki qutisi — bitta. Sun’iy bo‘lish
  shubhasi → review. Risk qoidalari versiyalangan (`promo.RISK_RULESET_*`): har signal — manba, ishonchlilik, oqibat,
  korrelyatsiya guruhi; bog‘liq signallar (IP + shu IP tarmog‘i) bitta dalil; bitta umumiy IP bloklamaydi va review
  qilmaydi; eligibility buzilishi (o‘zini taklif) alohida rad sababi. Review natijasi, sababi va xodim harakati
  audit’da; SLA oshsa eskalatsiya, mukofot avtomatik yo‘qolmaydi va tekshiruvsiz berilmaydi. Risk oynasi 48 soat (Q110).
- **Q114** Budjet ajratish/kamaytirish mavjud `TWO_PERSON_APPROVAL_THRESHOLD_MINOR` (tiyin, qat’iy katta bo‘lsa ikkinchi
  tasdiq) va Q69 finance-approver qoidasi bilan; so‘rovchi o‘zining ikkinchi tasdiqlovchisi bo‘la olmaydi (DB CHECK +
  trigger). Real-pul `ledger_adjustment_requests` ishlatilmaydi — o‘sha qoidalarni takrorlovchi `promo_budget_requests`.
- **Q115** Va’da rezervi, berilgan bonus va sarflangan bonus — bitta majburiyat (`promo_obligations`) bosqichlari;
  budjetda bir marta sanaladi. Promo ledger o‘zgarmas; tuzatish — yangi yozuv. Budjet keshi faqat ledger trigger’i
  orqali yoziladi; unique, lock va deferred tekshiruvlar DB darajasida.
- **Q116** Bron yaratilgandan keyin bonus oddiy qo‘shilmaydi. Tasdiqlangan amendment moliyaviy shartlarni qayta
  hisoblaydi va qayta tasdiqlatadi: eski rezervni bo‘shatish, yangisini yaratish va rozilikni yangilash — bitta
  tranzaksiya, xatoda avvalgi kelishuv buzilmaydi. Review SLA, tiklash grace va milestone qiymatlari — konfiguratsiya
  (hozir sintetik, production qiymati tasdiqlanmagan); `elchigo.uz/r/<kod>` domen/DNS/sertifikat/deploy tekshiruvi va
  HMAC muddati (Q108) ochiq — production’da ularga bog‘liq oqim tayyor deb belgilanmaydi.

**Referral 2-bosqich qarorlari (23.09.2026) — ADR-0023:**
- **Q117** Referral kodi — CSPRNG’dan olingan ochiq identifikator, DB’da unique, egasi o‘zgarmaydi; bekor qilish avvalgi
  attribution va majburiyatlarga tegmaydi; kod tekshiruvi egasi haqida hech narsa oshkor qilmaydi. Attribution (kim
  taklif qildi) `(referee, family)` bo‘yicha bitta, birinchisi yutadi, 72 soat server vaqti bilan, birinchi xizmatgacha;
  va’da ham, rezerv ham emas. Enrollment (qaysi kampaniya versiyasi shartlari qabul qilindi) versiya, xizmat, shartlar
  fingerprint’i, kirish vaqti va qualification muddatini mahkamlaydi va ikkala tomon majburiyatini bitta tranzaksiyada
  rezerv qiladi; budjet yetmasa enrollment yaratilmaydi. Bir odam oila bo‘yicha bitta tirik enrollment; boshqa rol orqali
  o‘zini taklif — self-referral; faol bo‘lmagan taklif qiluvchi bilan yangi enrollment yo‘q, eskilari saqlanadi.
- **Q118** Bir xil idempotency kaliti boshqa mazmun bilan — konflikt. Telefon HMAC (normalizatsiya, versiyali kalit,
  xotirada) — rotatsiyada tarix saqlanadi; Q108 saqlash muddati tasdiqlanmaguncha o‘chirilgan akkaunt digest’i
  o‘chiriladi va production enrollment yopiq; identity kaliti yo‘q bo‘lsa enrollment hamma joyda yopiq (fallback yo‘q).
  Digest mosligi akkaunt/xizmatni bloklamaydi — review.
- **Q119** 1-bosqich dalillari: migratsiya toza bazada, oldingi head’dan va head’da no-op alohida tekshiriladi (stamp —
  faqat idempotentlik). DB himoyasi haqiqiy application roli bilan tekshiriladi; DB application ulanishi ortidagi odamni
  autentifikatsiya qila olmaydi — bu API (JWT, capability, MFA step-up) va o‘zgarmas audit chegarasi. Eskirgan chegirma
  faqat joriy accept urinishini rad etadi va qayta hisoblashni talab qiladi.

**Referral 3-bosqich talqinlari tasdig‘i (23.09.2026) — ADR-0023 §17:**
- **Q120 (T1)** Qualification muddati ichida xizmat bajarilgan va mijozning o‘z to‘lov sharti (naqd tasdig‘i) bajarilgan bo‘lishi
  shart; platforma/worker’ning kech capture’i diskvalifikatsiya qilmaydi. Haqiqiy musbat C_net capture bo‘lmaguncha grant yo‘q —
  enrollment kutadi, muddat tugashi bilan rezervi avtomatik bo‘shatilmaydi. To‘lov vaqti tekshiriladigan manba yozuvidan;
  foydalanuvchining tasdiqlanmagan eski sanasi eligibility ochmaydi; kech to‘lovning real vaqti aniqlab bo‘lmasa — review.
  48 soat xizmat, ishonchli naqd tasdig‘i va real capture’ning eng oxirgisidan; ma’nosi «48 soatdan oldin emas».
- **Q121 (T2)** Haydovchi milestone birligi `distinct_trip`; bitta trip’dagi ikki mustaqil jo‘natma hisoblanishi mumkin; 30 daqiqalik
  split signali faqat sintetik konfiguratsiya (production default emas), review ochishi mumkin, avtomatik firibgarlik belgisi emas.
- **Q122 (T3)** Avtonom review tranzaksiyasi chaqiruvchining bron/wallet/promo rezervlarini commit qilmaydi va lock kutishga
  tushmaydi. Operator izoh yozadi, vakolatli admin qaror qiladi; qaror grant yaratmaydi va attribution’ni almashtirmaydi (API
  auth/MFA — ochiq cheklov). Grant’dan keyingi review’da mukofotning hali rezerv qilinmagan qismi yangi sarfdan to‘xtatiladi;
  tasdiqlangan bron chegirmasi jimgina bekor qilinmaydi; review/rezerv/sarf poygasi lot qatori lock’i bilan hal qilinadi.
  Budjet yetmasa reinstate qisman bajarilmaydi; tasdiqlangan reinstate texnik rad bilan o‘chmaydi — bajarilmagan holat va
  eskalatsiya qoladi. Ishlovni to‘xtatish mavjud bron narxini o‘zgartirmaydi, majburiyatni o‘chirmaydi, ikki marta undirmaydi.

**Referral T4 qarorlari (23.09.2026) — ADR-0023 §18.1:**
- **Q123 (T4a, cheklangan kombinatsiya)** Bitta bronda P va H birga ishlashi mumkin, lekin ixtiyoriy sondagi kampaniya emas:
  P uchun bitta, H uchun bitta kampaniya manbasi (bitta kampaniyaning bir nechta loti mumkin). Ikki turli kampaniya faqat
  aniq tasdiqlangan juftlik (`promo_campaign_combinations`, super_admin + MFA, audit) bilan uchrashadi; tasdiqlanmagan
  juftlik avtomatik ruxsat etilmaydi (H shunchaki qo‘llanmaydi). Umumiy chegirma cap’lari — eng qat’iysi; P cap P
  kampaniyasidan, H cap H kampaniyasidan. O va M: juftlik `shared` (bir xil bron, bir xil xarajat asosi) — kattasi;
  `additive` (har kampaniyaning o‘z qo‘shimcha xarajati) — O qismlari qo‘shiladi, M kattasi; asos tanlanmasa kombinatsiya
  yo‘q. Har chegirma o‘z kampaniyasi, loti va budjetiga bog‘lanadi (terms’da kampaniya id’lari, DB tekshiruvi). Tasdiqlangan
  P ni qoidalar o‘zgartirishi kerak bo‘lsa — yashirin kamaytirish emas: P o‘zi mos kelmasa requote; H qo‘shilishi P ni
  kamaytirsa H qo‘llanmaydi (P saqlanadi).
  **Aniqlik (24.09.2026, foydalanuvchi tasdig‘i):** mijoz tasdiqlagan P ustuvor — bu qoida yangi hisob tayyorlanayotganda
  ishlaydi. H “qolgan ruxsat etilgan imkoniyat” doirasida hisoblanadi: sig‘sa qisman qo‘llanadi (`partial`); juftlik
  tasdiqlanmagan (`not_approved`) yoki P ni kamaytiradigan (`would_reduce_p`) holat — alohida, H umuman yo‘q. Haydovchi H
  bor hisobni ko‘rib tasdiqlagan bo‘lsa (accept’da `promo_driver_ack`), H yashirincha olib tashlanmaydi va C_net
  oshirilmaydi: yangi raqamlar bilan `PROMO_QUOTE_STALE (driver_terms_changed)`, qayta tasdiq kerak. Tasdiqlangan bron
  snapshot’i o‘zgarmaydi.
- **Q124 (T4b)** P = 0 va F_cash = F bo‘lgan faqat-H bitimda mijoz klientining promo imkoniyati talab qilinmaydi; eski mijoz
  klientida narx, receipt va tasdiqlash semantikasi o‘zgarmaydi (mijoz DTO’sida promo yo‘q, cash buyruqlari F bilan).
  Haydovchi klienti H va C_net ni ko‘rsatishi shart. Keyin P qo‘shiladigan oqim bu istisnodan foydalana olmaydi (amendment
  P ni qo‘shmaydi, rozilik har doim capability talab qiladi).
- **Q125 (T4c, pilot)** Amendment’da yangi lot tortilmaydi, avvalgi P va H dan ortiq bonus ishlatilmaydi — o‘zgarishsiz yoki
  kamayadi. Bu avtomatik tasdiq emas: yangi F, P, F_cash mijozga ko‘rsatiladi va rozilik olinadi; haydovchining naqd yoki
  komissiyasi o‘zgarsa uning ham tasdig‘i (`promo_driver_ack`) olinadi. Yangi kelishuv qabul qilinmaguncha eski kelishuv va
  rezervlar saqlanadi. F kamayib F_cash nisbatan oshadigan holat klientda alohida tushuntiriladi.
- **Q126 (T4d)** Muddatsiz capability tasdiqlanmadi. Har accept va moliyaviy buyruqda amalni bajarayotgan klient imkoniyati
  shu so‘rovdan tekshiriladi; passiv tomon tayyorligi aniq login sessiyasi (`sid`), quote/proposal versiyasi (yoki
  amendment) va uning muddati bilan bog‘lanadi (`promo_party_readiness`, rozilikda `session_ref`). Dalil eskirgan yoki
  yo‘q — qayta tasdiq (`PROMO_QUOTE_STALE`, keyin `.../promo-confirmation`). Aniqlangan o‘zgarish (sessiya tugashi, boshqa
  jonli login’dan e’lon, capability’siz e’lon) eski dalilni bekor qiladi. Capability autentifikatsiya yoki vakolat emas;
  eski versiyaga qaytish har doim aniqlanadi deb da’vo qilinmaydi (token rotatsiyasi zanjiri yozilmaydi). Mavjud promo
  bronning chegirmasi hech qachon olib tashlanmaydi.
- **Q127 (T4e)** Komissiya reversal’i bonusni avtomatik tiklamaydi. Komissiya reversal’i, buyurtma refund’i, bonusni tiklash
  va mijozga naqd qaytarish — alohida operatsiyalar. Bu "har refund’da bonus yo‘qoladi" degani emas: tiklash huquqi mavjud
  tasdiqlangan siyosatdan (bekor qilishda adolatli tiklash, reinstate) aniqlanadi va o‘sha bog‘langan operatsiya bilan
  bajariladi; umumiy "bonus berish" tugmasi yo‘q. Siyosat qamramagan holatlar (sarflangan bonus/kredit bor bronda
  komissiya reversal’i yoki hal qilingan nizo) `restoration_uncovered` review sifatida alohida ko‘rsatiladi va avtomatik
  egasi zarariga hal qilinmaydi.
- **Q128 (T4f)** Muddati o‘tgan lotdan rezerv bo‘shatilganda summa oddiy mavjud bonusga aylanmaydi — expiry hisobiga o‘tadi;
  tasdiqlangan grace yoki reinstate huquqi saqlanadi. Release, expiry va reinstate parallel kelganda summa bir marta
  bo‘shatiladi va bir marta tiklanadi (lot qatori lock’i, ledger unique kalitlari; PG testi).
- **Q129 (T4g, o‘zgartirilgan)** Bekor qilgan actor va sabab alohida. "Operator bekor qildi → platforma aybi" olib
  tashlandi: operator sababni aniq belgilaydi (`cancel_fault_side`: client/driver/platform/none — sabab matni bilan,
  booking’da yoziladi); belgilanmasa sabab `undetermined`. "Mijoz kelmadi" faqat operator tasdiqlagan mijoz no-show’ida
  mijoz sababi; haydovchi kelmagani yoki bahsli holat mijozga yozilmaydi. Noaniq/nizoli sabab — huquq avtomatik
  yo‘qolmaydi (grace vaqtincha beriladi) va har egaga alohida `cancel_fault` review; admin egasi aybdor deb qaror qilsa
  faqat sarflanmagan uzaytma qaytariladi. Mijoz bonusi va haydovchi krediti har egaga nisbatan alohida baholanadi. Real pul
  bo‘yicha bekor qilish siyosati o‘zgarmaydi (release, jarima yo‘q).

**Referral 6-bosqich qarori (24.09.2026) — ADR-0023 §20.1:**
- **Q130** Simulyatsiya pilot variantlari: **A** (faqat yo‘lovchi, mijoz → mijoz) — kelajakdagi yo‘lovchi pilotini baholash uchun
  asosiy nomzod; uning summalari va 600 000 so‘m budjeti production uchun **tasdiqlanmagan**, yo‘lovchi xizmatining huquqiy va
  texnik gate’lari (K7/Q5/Q89, Q48) saqlanadi. **B** (yo‘lovchi + pochta) hozirgi ko‘rinishida tasdiqlanmaydi; pochta alohida
  baholanadi va umumiy musbat natija pochta bonusining kam ishlatilishini yashirmaydi. **C** (haydovchi taklifi + milestone)
  keyingi baholashga qoldirildi. Bu qarorlar kampaniyani yoqish yoki mablag‘ ajratish ruxsati **emas**.

**Referral yakuniy qarorlari (24.09.2026) — ADR-0023 §20.2; holat: lokal yakunlangan, production gate’lari yopilmagan:**
- **Q131 (G20)** Pochta referral bonusi hozircha yoqilmaydi — **vaqtinchalik mahsulot qarori**: haqiqiy qayta buyurtma va bonusdan
  foydalanish ma’lumotlari yo‘q. Simulyatsiyadagi ~9 % — model natijasi; “pochta bonusi foydasiz” deb yozilmaydi. Mexanizm kodda
  saqlanadi, kampaniya o‘chiq. A varianti faqat kelajakdagi yo‘lovchi pilotiga nomzod (Q130); summa va budjet tasdiqlanmagan.
- **Q132 (G14)** Oddiy `reduce_allocation` budjetni sarflangan summa va bajarilmagan majburiyatlardan pastga tushirmaydi:
  `B ≥ S + L`, kamaytirish mumkin — `max(0, B − S − L)`. B — tasdiqlangan jami ajratma, S — hisobga olingan sof sarf, L — va’da
  rezervi + berilgan sarflanmagan bonus (bronda band qilingan qism uning ichida, bir marta) + budjet joyini kutayotgan tasdiqlangan
  tiklashlar; review yoki kech capture kutayotganlar L dan yashirincha chiqmaydi. S oddiy adjustment bilan kamaytirilmaydi; tuzatish —
  asoslangan ledger operatsiyasi. Yangi hisobot davri eski sarf/majburiyatni o‘chirmaydi (davriy budjet — alohida ajratma). Tashqi
  moliyalashtirish yo‘qolishi — alohida `funding_loss` (dalil bilan): kamomad qoldirishi mumkin, majburiyatni bekor qilmaydi, yangi
  va’dalarni to‘xtatadi va eskalatsiya qilinadi. Servis va DB (0090) darajasida.
- **Q133** Q108 (HMAC muddati, huquqiy asos) ochiq — mavjud production cheklovi saqlanadi; muddat simulyatsiya yoki texnik qulaylik
  bilan tanlanmaydi. Mukofot, O, M, cap, muddatlar, budjet va mablag‘ manbai tasdiqlanmagan — haqiqiy pilot qarori bilan; sintetik
  qiymat production standarti emas; yangi parametr variantlari qidirilmaydi. Rate-limit va review SLA — trafik, umumiy IP ortidagi
  haqiqiy foydalanuvchilar, qayta urinishlar va review ish hajmi dalilisiz tasdiqlanmaydi. Q127: siyosatsiz erkin bonus berish va
  umumiy “bonus berish” tugmasi yo‘q; qamralmagan holatda operator dalil yig‘adi, vakolatli admin ko‘rib chiqadi — adminning texnik
  vakolati yangi kompensatsiya siyosati emas; haqiqiy pul qarzi avtomatik yaratilmaydi.
- **Q134** Qo‘shimcha foydalanuvchini o‘lchash dizayni tasdiqlanmagan; koridor nazorati — variant (koridorlar talab, narx va haydovchi
  ta’minotida farq qiladi — referral ta’siri bilan aralashadi). Pilotdan oldin dizayn tanlanadi; attribution soni qo‘shimcha
  foydalanuvchi soni emas; nazorat berilgan va’dalarni buzmaydi.
- **Q135** To‘xtatish mezonlari umumiy tasdiqlanmagan. Takroriy undirish, ruxsatsiz grant, ledger tafovuti yoki majburiyat chegarasi
  buzilishi — incident: ta’sirlangan xavfli operatsiyalar cheklanadi, mavjud bron narxi o‘zgarmaydi, majburiyat o‘chmaydi. Review
  navbati, CAC, refund ulushi kabi biznes chegaralari dalilga asoslangan alohida tasdiqni kutadi.

**Saqlangan safar/jo‘natma talabi (24.09.2026) — ADR-0025:**
- **Q136 (foydalanuvchi qarori)** Mijoz yo‘nalish, vaqt, odamlar soni/jo‘natma ma’lumotini bir marta kiritadi (`trip_intents`,
  shaxsiy, e’lon emas, o‘zi hech kimga taklif yubormaydi); har haydovchi e’loniga taklif shu talabdan to‘ldiriladi, lekin har taklif
  mustaqil kelishuv: o‘z narxi, promo quote’i va roziligi. Bitta talab — bitta bekor qilinmagan bron (servis + DB unique); parallel
  accept’da yutqazgan sig‘im, promo yoki hold qoldirmaydi, qolgan takliflar texnik sabab bilan yopiladi (jarima/strike/reyting yo‘q).
  Muhim tahrir ochiq takliflarni faqat mijoz roziligidan keyin yopadi; muddati o‘tgan sana surilmaydi; bekor qilingan bron eski
  takliflarni qayta ochmaydi — «qayta qidirish» aniq amal. Talab yaratish referral attribution, “yangi mijoz” yoki birinchi bron
  tarixiga tegmaydi. Avtomatik ommaviy taklif, yangi kampaniya yoki to‘lov usuli qo‘shilmaydi; production flag’lari o‘zgarmaydi.

**OTP yakuniy qarori (24.09.2026):**
- **Q137 (Q8 ni yakunlaydi)** OTP kodi **4 xona**. Backend standarti (`Settings.otp_length = 4`), `mobile-app` zaxira qiymati
  (`VITE_OTP_LENGTH || 4`) va `.env.example` fayllari bir xil; kontrakt testi kod standartlarini solishtiradi, lokal `.env` ni emas.
  Muhitda `ELCHI_OTP_LENGTH` va `VITE_OTP_LENGTH` o‘rnatilsa, ikkalasi 4 bo‘lishi shart.

**Wave 3.1 dan keyin ochiq qolgan uch band yopilgan (24.09.2026 audit):** U6 `rating_bucket` — A-variant; ADR-0021 staff MFA — **Accepted** (faqat xodim faktorlarini ulash va `enforce_privileged` rejimi — go-live bandi); dalil fayllari — imzolangan havola bilan.

## 4. Kod tuzilishi
- Yangi domen: `app/modules/<name>/` (`identity`, `marketplace`, `trips`, `bookings`, `geo`, `wallet`, `tracking`, `communications`, `trust_support`, `operations`, `platform`, `promotions` — Q102). Ichida: `models.py`, `service.py` (tashqi domen API), `schemas.py`, `api.py` (v2 router), `repository.py` (ixtiyoriy).
- Modul boshqa modul jadvaliga to‘g‘ridan-to‘g‘ri yozmaydi — faqat uning `service.py` funksiyasi orqali. Bir DB session/tranzaksiya ulashiladi; domen funksiyasi `commit` qilmaydi.
- v1 kodi v2 modul **servislarini** chaqirishi mumkin (ADR-0006: akkaunt o‘chirish read-only tekshiruvlari, settings adapteri), lekin v2 jadvallariga to‘g‘ridan-to‘g‘ri yozmaydi.
- Pul/o‘rin/holat o‘zgartiradigan accept/cancel/amend tranzaksiyasi — faqat A4 orkestratori.
- `app/contracts/` — dependency-free: DB model, router, settings, I/O yo‘q.
- Legacy `app/services/` birdaniga ko‘chirilmaydi.

## 5. Migratsiyalar
- Yagona migratsiya integratori: A0a (ADR-0016). Raqam `DATA_MODEL.md` reyestridan; `alembic heads` doim bitta.
- Revision id `YYYYMMDD_NNNN`, fayl `YYYYMMDD_NNNN_<module>_<slug>.py`, `down_revision` — reyestrdagi oldingi raqam.
- `upgrade` idempotent va qayta ishga tushirilsa dublikat yaratmaydi. `downgrade` rollback vositasi emas; yozish ixtiyoriy va faqat dev/test uchun.
- PostGIS migratsiyasi (`0030`) prod image almashtirilmaguncha deploy qilinmaydi (ADR-0013).

## 6. Konvensiyalar
- **Pul:** `BIGINT` minor unit (UZS: 1 so‘m = 100 tiyin), API’da `*_minor` integer + `currency`. Float taqiq. Stavka — integer bps. Komissiya faqat `app.contracts.money.commission_minor`. `exempt` faqat 0 bps snapshot’dan (`initial_commission_status`); `wallet_required` ma’nosi — `balance_check_required`.
- **O‘lchov birliklari:** og‘irlik `*_g`, hajm (bagaj ham, yuk ham) `*_ml`, o‘lcham `*_cm`, masofa `*_m`, davomiylik `*_s`/`*_minutes` — hammasi integer.
- **Vaqt:** `timestamptz` UTC; aware datetime; API kirishida offset majburiy (`timeutil.parse_iso_datetime`, DTO’da `UtcDateTime`); chiqishda `Z`; displey `Asia/Tashkent`.
- **ID:** jadval ichida `BIGINT` identity PK; API’da faqat `public_id` (`ids.format_public_id`). Noto‘g‘ri/yashirin id → `404 NOT_FOUND`. `public_id` sir emas.
- **Sirlar:** `settings.secret_key` bevosita ishlatilmaydi — `crypto.derive_subkey(secret_key, purpose)`. Link/share token’lar `crypto.new_secret_token` (≥128 bit `secrets.token_bytes`), bazada faqat hash. uuid4 token emas (ADR-0018).
- **API v2:** `/api/v2`, envelope `app.contracts.dto`, xato kodi `ErrorCode`, buyruqlarda `Idempotency-Key` (domen 4xx savepoint naqshi — ADR-0005), versiyali agregatda `expected_version`, cursor pagination. Har v2 endpoint `response_model` bilan.
- **Holat:** har status yozuvi `state_machines.<MACHINE>.assert_transition(..., command=...)` orqali; DB’da CHECK.
- **Global lock tartibi (ADR-0017):** `users → trips → listings → proposal_threads → trip_intents (ADR-0025) → bookings → booking bolalari (amendments, no_show_reviews, custody_cases, cash_receipts, disputes) → wallet_accounts → wallet_holds/topup_requests/ledger_adjustment_requests`; har guruh ichida id o‘sish tartibida. Bola id bilan kelgan buyruq avval lock’siz o‘qib ota id’larini topadi, keyin tartib bo‘yicha lock oladi va qayta tekshiradi.
- **Lock rejimi:** `users`, `trips`, `listings`, `proposal_threads` (va boshqa FK ota qatorlari) `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`) yoki `FOR SHARE` bilan; **oddiy `FOR UPDATE` emas** — FK insert’larining key-share lock’lari bilan deadlock bo‘ladi. Yagona istisno: unique ustun o‘zgarsa (`users.phone`/`username`, `driver_profiles.plate_number`) qator boshidanoq `FOR UPDATE`. Qator har doim boshidanoq yakuniy rejimda olinadi (kuchaytirish yo‘q). v1: `orders → users → driver_profiles → wallet`; akkaunt o‘chirish `users`/profil `FOR UPDATE`; token refresh `users FOR SHARE` → session `FOR UPDATE` (ADR-0017 §12–13).
- **Retry:** har v2 buyrug‘i `platform.service.run_with_db_retry` ichida (deadlock/serialization, ≤3).
- **Release kontrakti:** A4 `booking_allocations.active`ni trip lock ostida true→false o‘tkazadi va `trips.release`ni faqat shu o‘tishda chaqiradi (ikki marta release yo‘q).
- **Detour:** trip detour hisoblagichlari soniyada; snapshot — `app.contracts.detour.DetourQuote`.
- **Production aniqlash:** geo va boshqa modullar `platform.service.is_production(db)` (DB markeri + env), faqat env satri emas.
- **Muhit:** `ELCHI_ENVIRONMENT` allowlist’dan tashqari qiymat app va migratsiyani ishga tushirmaydi (`app/core/config.py`).
- **Eligibility (D16):** driver bloklanishi yoki hujjat muddati tugashi faqat yangi bron va yangi listing/trip’ni to‘xtatadi; faol trip’da tracking, proof va support davom etadi (`NEW_BUSINESS_CAPABILITIES` vs `OBLIGATION_CAPABILITIES`).
- **Legacy:** v1 buyurtmalar v2’da faqat read-only view (Q4).
- **Finance (Q17):** `Role.FINANCE` staff roli (`STAFF_ROLE_CAPABILITIES`); `finalize_fee` → `finance.fee_finalize`; katta tuzatish ikkinchi, boshqa xodimning `finance.adjustment_approve` tasdig‘i bilan.
- **Event auditoriyasi (N2, Q16):** yuborishdan oldin `events.payload_for_audience`; `wallet.*`/`commission.*` mijozga bormaydi, mijoz nusxasida komissiya maydonlari yo‘q.
- **Production invariantlari (N1):** DB darajasida (trigger + muhit markeri, A3). Readiness 503 faqat DB yo‘q, DB head koddan orqada yoki noma’lum revision bo‘lsa (DB head kod head’ining ma’lum avlodi → 200 `degraded`, `migrations: ahead`, Q32); `/health/ready` faqat monitoring IP’lariga (Q33); Redis → `degraded`; invariant buzilishi → `production_invariants: fail` + alert, pul buyruqlari `503 PRODUCTION_INVARIANTS_FAILED`.
- **Ledger manbasi (Q55):** har `ledger_transactions` qatori `source_type` + `source_id` bilan aniq bitta biznes manbaga bog‘lanadi (`topup_request`, `ledger_adjustment_request`, `wallet_hold`); xom ledger INSERT faqat to‘g‘ri manba bilan (DB commit’da rad etadi). Yangi top-up/adjustment qatori faqat pending holatda yaratiladi.
- **Promo budjet (Q132):** oddiy `reduce_allocation` ≥ `S + L` (`BudgetPosition.reducible_minor`, trigger 0090); haqiqiy moliyalashtirish yo‘qolishi — faqat dalilli `funding_loss`; budjet keshi faqat ledger trigger’i orqali.
- **Q48 gate (Q56):** `platform.service.q48_gate_status` / SQL `platform_q48_gate_passed()`; production’da v2 xizmat flag’larini yoqish va yangi pul biznesi (`hold_fee`) gate o‘tmaguncha rad (`503 PRODUCTION_INVARIANTS_FAILED`); `/health/ready` `notices` faqat ma’lumot (Q57).
- **Kalit rotatsiyasi (N5):** proof kodlar `crypto.build_keyring` + `verify_proof_code` (oldingi kalit `KEY_ROTATION_VERIFICATION_WINDOW` davomida qabul).
- **Tashqi API** (SMS, xarita, push) DB tranzaksiyasi ichida chaqirilmaydi.

## 7. Testlar
- Concurrency, idempotency, pul/ledger, sig‘im, lock tartibi, exclusion constraint — **PostgreSQL** testlari (A0b infra, `tests/pg/`). SQLite bu invariantlarni isbotlamaydi.
- Sof domen hisoblari — unit test. Kontrakt testlari: `py -m pytest tests/contracts -q`.
- “Test mavjud” va “test o‘tdi” farqlanadi; hisobotda buyruq va natija.
- Real Android qurilma sinovlari (spec §10.5, AC27 dala qismi, AC32) Android dasturchiga tegishli va stage-2 backend doirasidan tashqarida; hech bir hisobot ularni “o‘tdi” deb yozmaydi. AC27 backend qismi — A6.

## 8. Definition of Done (spec §21.2)
Har o‘zgarish hisobotida: muammo va yangi xulq; ta’sir doirasi; migratsiya (idempotent upgrade) va backward compatibility; biznes invariant testlari (qaysi AC); OpenAPI/types; xato holatlari; audit/metrics; maxfiylik; feature flag va rollback (flag/forward-fix, downgrade emas); ochiq cheklovlar; qo‘llangan buyruqlar natijasi. BR reviewer spec bo‘limi/AC ID bo‘yicha tekshiradi; wave oxirida foydalanuvchi tasdig‘i.

## 9. Biznes-rostgo‘ylik qoidalari
- “Taklif berdim” ≠ “bron qilindi”: taklif o‘rin/balansni band qilmaydi (§5.3).
- Soxta haydovchi, soxta reyting, soxta taklif, soxta GPS marker, yolg‘on “GPS faol” — taqiq (§6.6, §10.5).
- Yangi haydovchiga sun’iy “4.5” ko‘rsatilmaydi (§8.2).
- Hisoblangan komissiya tushgan pul deb ko‘rsatilmaydi; top-up skrinshoti pul emas (§9.2).
- `wallet_required=false` komissiyani jimgina nolga tushirmaydi (Q1).
- Legacy `system_fee` haydovchi qarzi qilinmaydi (§18.2).
- GPS — haydovchi telefoni, pochta qurilmasi emas (§10.3).
- 24/7 operator yoki sug‘urta va’da qilinmaydi (§5.2, §16).
- Event/push payload’i faqat allowlist kalitlari (`events.EVENT_PAYLOAD_ALLOWLIST`): telefon, pasport, ism, manzil, koordinata, kod yo‘q (§15).
