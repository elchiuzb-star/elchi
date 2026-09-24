> **Manba:** foydalanuvchi bergan `elchi_referal.md` topshirig‘i (23.09.2026), so‘zma-so‘z saqlangan.
> Bajarish rejasi, bosqichlar va ochiq savollar: [`REFERRAL_PLAN.md`](REFERRAL_PLAN.md).
> Bu fayl topshiriq matni; u AGENTS.md §1 manba tartibida spetsifikatsiya yoki qaror emas —
> undagi talablar foydalanuvchi tasdig‘idan o‘tgach `AGENTS.md §3` ga Q-qaror sifatida yoziladi.

---

Siz Elchi loyihasining referral, bonus va rag‘batlantirish tizimini ishlab chiquvchi backend, moliyaviy mantiq va QA agentisiz.

Vazifangiz — yangi mijozlar va haydovchilarni jalb qiladigan, real foydalanishni rag‘batlantiradigan, xarajati nazorat qilinadigan referral tizimini mavjud Elchi arxitekturasiga integratsiya qilish.

Tizim faqat ro‘yxatdan o‘tish sonini oshirmasin: haqiqiy yakunlangan xizmatlar, qayta foydalanish va platformaning komissiya daromadiga xizmat qilsin. Foydalanuvchiga berilgan va’dalar tushunarli va bajariladigan bo‘lsin.

Faqat reja bilan cheklanmang. Repository’ni tekshiring, zarur model, migratsiya, servis, API, ruxsat etilgan interfeys, admin boshqaruvi va testlarni amalga oshiring. Production kampaniyasini yoqish bilan funksiyani ishlab chiqishni alohida boshqaring.

## 1. Mavjud arxitekturani saqlang.

AGENTS.md, ELCHI_PRODUCTION_ARCHITECTURE.md, DATA_MODEL.md, qarorlar reyestri, amaldagi ADR’lar, wallet/ledger, booking, outbox, notification va feature flag modullarini o‘qing.

Elchi’da mijoz hozir tashish haqini haydovchiga naqd to‘laydi. Haydovchining platformadagi haqiqiy balansi komissiya uchun oldindan kiritilgan mablag‘dir. Uni haydovchining barcha naqd daromadi yoki yechib olinadigan earnings hamyoni deb talqin qilmang.

Referral tizimini mavjud modular monolith ichida alohida domen moduli sifatida yarating. Zaruratsiz mikroservis, Kafka, ML antifraud yoki tashqi attribution platformasi qo‘shmang.

Oldingi lokal o‘zgarishlarni saqlang. Commit, push, production deploy va tashqi xizmat xaridini bajarmang. Amaldagi papka cheklovlariga rioya qiling; muzlatilgan klientlar uchun backend kontrakti va aniq UI handoff tayyorlang. Ularni implementatsiya qilingan deb ko‘rsatmang.

## 2. Iqtisodiy himoyani tizimning asosiy qoidasi qiling.

Bonusni naqd yechib bo‘lmasligi uning iqtisodiy xarajati yo‘qligini anglatmaydi. Komissiya chegirmasi platforma daromadini kamaytiradi. Shu sabab har qanday mukofot va undan foydalanish nazorat qilinadigan budjetga bog‘lansin.

Tizim ikki himoyaga ega bo‘lsin:

Birinchisi — kampaniya darajasida yangi va’dalar, berilgan bonuslar va ishlatilgan chegirmalar uchun cheklangan budjet.

Ikkinchisi — har bir bronda barcha chegirmalardan keyin qoladigan komissiya tasdiqlangan o‘zgaruvchan xarajatlar va minimal marjani qoplashi.

Bu nazoratlar kompaniyaning umumiy foydasini mutlaq kafolatlamaydi. Hisobotda doimiy xarajatlar, firibgarlik, refund va taxminiy xarajat parametrlarining ta’sirini ochiq ko‘rsating.

Kelajakdagi taxminiy LTV yoki hali tushmagan daromadni mavjud bonus budjeti deb hisoblamang.

## 3. Uch xil mablag‘ni qat’iy ajrating.

Haqiqiy driver prepaid balance — tekshirilgan real pul kirimi asosidagi komissiya balansi.

Passenger Bonus — mijozning keyingi mos xizmatida chegirma olish huquqi. Naqdlashtirilmaydi, boshqa foydalanuvchiga o‘tkazilmaydi va haqiqiy pul balansi hisoblanmaydi.

Driver Credit — haydovchining kelajakdagi komissiyasini kamaytiradigan huquq. Naqdlashtirilmaydi va haqiqiy prepaid balance’ga aylantirilmaydi.

Pilotda referral uchun naqd pul payout’i bo‘lmasin. Mijoz tovar qiymatini, haydovchi naqd tushumini yoki boshqa xizmatlarni bu bonus bilan moliyalashtirish qo‘shilmasin.

Bonusni foydalanuvchiga so‘mdagi chegirma imkoniyati sifatida tushunarli ko‘rsating. Masalan, “10 000 so‘mgacha safar chegirmasi”. “Sizga 10 000 so‘m pul berildi” deb yozmang.

Ichki hisob mavjud loyiha pul birligiga mos integer qiymatlarda bo‘lsin. Float ishlatmang.

## 4. Naqd to‘lovda mijoz chegirmasini haydovchi hisobidan bermang.

Quyidagi modelni mavjud komissiya kontraktiga moslab amalga oshiring:

- F — kelishilgan tashish haqi.
- C — chegirmalarsiz hisoblangan platforma komissiyasi.
- P — shu bronda ishlatiladigan Passenger Bonus.
- H — shu bronda ishlatiladigan Driver Credit.
- O — tasdiqlangan o‘zgaruvchan xarajatlar va zarur rezervlar.
- M — platformada qolishi kerak bo‘lgan minimal hissa marjasi.

Mijozning naqd to‘lovi:

    F_cash = F − P.

Haydovchining haqiqiy balansidan undiriladigan komissiya:

    C_net = C − P − H.

Majburiy shartlar:

- C_net ≥ 0.
- C_net − O ≥ M.
- P + H kampaniyaning bir bron uchun umumiy chegirma limitidan oshmasin.
- P mijozga tegishli mavjud va mos bonusdan oshmasin.
- H haydovchiga tegishli mavjud va mos kreditdan oshmasin.

Shunda haydovchining komissiyadan keyingi tushumi:

    F_cash − C_net = F − C + H.

Demak, mijoz chegirmasi haydovchining kelishilgan asosiy tushumini kamaytirmaydi; Driver Credit esa unga qo‘shimcha foyda beradi.

Faqat hisobni tushuntiruvchi misol:

- F = 200 000 so‘m.
- C = 20 000 so‘m.
- P = 5 000 so‘m.
- H = 3 000 so‘m.

Mijoz 195 000 so‘m naqd to‘laydi.
Haydovchidan 12 000 so‘m komissiya undiriladi.
Haydovchining komissiyadan keyingi tushumi 183 000 so‘m bo‘ladi.

Bu raqamlarni production tarifiga aylantirmang.

Komissiya yetmasa bonusning faqat ruxsat etilgan qismi ishlatilsin. Qolgan bonus saqlansin va foydalanuvchiga oldindan ko‘rsatilsin. Yetishmagan summani haydovchiga zarar sifatida yuklamang yoki tekshirilmagan haqiqiy balans krediti yaratib qoplamang.

C = 0 bo‘lgan safarda ushbu komissiya hisobidan chegirma modeli ishlamasligini hisobga oling.

## 5. Chegirmalar birgalikda hisoblanadigan yagona quote yarating.

Passenger Bonus, Driver Credit, komissiya kampaniyasi va boshqa promo’lar alohida-alohida tekshirilib, yakunda umumiy limitni buzmasin.

Yagona server funksiyasi quyidagilarni hisoblasin:

Asl narx, bazaviy komissiya, mijoz bonusi, haydovchi krediti, boshqa ruxsat etilgan chegirmalar, mijoz to‘laydigan naqd summa, undiriladigan komissiya va platformada qoladigan marja.

Boshlang‘ich konservativ siyosat sifatida jami chegirmani komissiyaning ma’lum ulushi bilan cheklash variantini tayyorlang. Masalan, 50% — faqat sinov konfiguratsiyasi; production qiymati tasdiqlangan siyosatdan olinsin.

Xarajat parametri noma’lum bo‘lsa uni yashirin nolga tenglashtirmang. Moliyaviy parametrlar to‘ldirilmagan kampaniya aktivlashtirilmasin.

Quote versiyasi va muddati bo‘lsin. Mijoz va haydovchi bir xil moliyaviy snapshot’ni ko‘rsin. Narx yoki shart o‘zgarsa qayta tasdiq talab qilinsin.

Bonus ishlamay qolganida foydalanuvchining roziligisiz kattaroq naqd summa bilan bron yaratilmang.

## 6. Pilot uchun uchta referral oqimini quring.

**Mijoz → mijoz:**

Yangi foydalanuvchi referral orqali keladi, telefonini tasdiqlaydi va kampaniyaga qabul qilinadi. Birinchi mos xizmat haqiqatan bajarilib, zarur tekshiruvlardan o‘tgach yangi mijoz va taklif qiluvchiga alohida bonus beriladi.

Bu bonus keyingi mos xizmat uchun bo‘lsa, UX aynan shuni aytsin. Uni “birinchi safaringizga chegirma” deb reklama qilmang.

**Haydovchi → haydovchi:**

Yangi haydovchi shaxs va transport tekshiruvidan o‘tadi. Mukofot tasdiqlangan bosqichlar bo‘yicha beriladi: masalan, 5 va 10 ta mos safar.

Bitta avtomobil safaridagi ko‘p bronni bir nechta safar deb sanamang. Bosqichlar uchun takrorlanmaydigan trip, turli haqiqiy mijozlar va undirilgan komissiya mezonlari bo‘lsin.

Taklif qiluvchi va yangi haydovchi mukofoti Driver Credit bo‘lsin.

**Haydovchi → mijoz:**

Haydovchiga referral havola va QR kod beriladi. Yangi mijoz ro‘yxatdan o‘tib, mos xizmatni bajargach mijozga Passenger Bonus, haydovchiga Driver Credit beriladi.

Pilotdagi konservativ qoida: taklif qilgan haydovchining o‘zi bajargan xizmat haydovchiga referral mukofoti chiqarish uchun yetarli bo‘lmasin. Mustaqil keyingi xizmat orqali qualification variantini aniq hujjatlashtiring va kampaniya shartida oldindan ko‘rsating.

10 000, 15 000 yoki 50 000 so‘mlik summalarni raqobatchidan ko‘chirib production default qilmang. Mukofotlar kampaniya budjeti va iqtisodiy simulyatsiya bilan asoslanadigan konfiguratsiya bo‘lsin.

## 7. Nazoratsiz “5 safarga 0%” o‘rniga chegaralangan Driver Credit ishlating.

Pilotda safar narxi va komissiya miqdoridan qat’i nazar ishlaydigan cheksiz 0% kampaniya bo‘lmasin.

Driver Credit uchun jami summa, bir bron limiti, komissiya ulushi, amal qilish muddati va mos xizmatlar belgilansin. Mijoz bonusi bilan birga ishlatilganda ham umumiy marja talabi saqlansin.

“5 safarga 0%” va’dasi berilsa, uning haqiqiy moliyalashtirilishi va cheklovlari kerak bo‘ladi. Hozirgi topshiriqda buning o‘rniga tushunarli “komissiya uchun X so‘mgacha kredit” modelini tayyorlang.

Umumiy cashback, reactivation, corridor bonus va loyalty darajalari uchun kengayadigan tuzilma yarating, lekin pilotda barchasini birdan yoqmang.

## 8. Budjet va foydalanuvchiga berilgan va’dalarni boshqaring.

Kampaniya budjeti tasdiqlangan marketing mablag‘i yoki allaqachon olingan komissiyaning xarajat va rezervlardan keyingi ajratilgan qismidan shakllansin.

Haydovchining oddiy top-up’i platforma foydasi emas; uni referral budjetiga o‘tkazmang.

Quyidagilar alohida hisobga olinsin:

- Ajratilgan budjet.
- Shartlari bajarilsa berilishi va’da qilingan mukofotlar rezervi.
- Berilgan, ammo hali ishlatilmagan bonuslar rezervi.
- Ishlatilgan chegirmalar.
- Muddati tugab yoki qonuniy bekor qilinib bo‘shagan rezerv.
- Yangi majburiyat uchun mavjud budjet.

Foydalanuvchi kampaniyaga qabul qilinib, unga aniq mukofot va’da qilinishidan oldin tegishli maksimal majburiyat rezerv qilinsin. Ikki tomonlama referral’da ikkala mukofot ham hisobga olinsin.

Qualification’dan keyin rezerv shunchaki yo‘qolmasin: u va’da rezervidan berilgan bonus rezerviga o‘tsin. Sarflanganda bir marta xarajatga o‘tsin. Bir bonus ikki marta rezerv yoki xarajat qilib sanalmasin.

Budjet tugasa yangi qatnashuvchilar uchun kampaniya yopilsin yoki pauza qilinsin. Oldin qabul qilingan shartlar va berilgan bonuslar yashirin bekor qilinmasin.

Kampaniyaga kirish limiti, qualification muddati va bonus muddati oldindan ko‘rsatilsin. Kampaniya pauzasi mavjud bonusni sarflashni avtomatik taqiqlamasin.

Budjet manbai keyingi refund sabab kamayganda yangi majburiyatlarni to‘xtatish, mavjud majburiyatlar va yetishmovchilikni mas’ulga ko‘rsatish mexanizmi bo‘lsin.

## 9. Attribution’ni aniq va suiiste’molga chidamli quring.

Faqat referral_code ustuni bilan cheklanmang.

Referral havola Elchi domenida ishlasin. Kod telefon yoki boshqa shaxsiy ma’lumotni oshkor qilmasin. Link mavjud ilovani ochishi, ilova yo‘q bo‘lsa tushunarli web sahifaga olib borishi va kodni qo‘lda kiritish imkonini berishi kerak.

Android App Links uchun domen va ilova bog‘lanishini rasmiy usulda tekshiring. Ilova o‘rnatilgandan keyin attribution saqlanishini sinovsiz kafolatlamang. ([developer.android.com][1])

Server tasdiqlagan referral attribution bitta bo‘lsin. Birinchi tasdiqlangan kodni keyingi link bilan yashirin almashtirmang. Operator tuzatishi sababli va auditli bo‘lsin.

Bir odamning mijoz va haydovchi rollari mavjudligini hisobga oling. Yangi akkaunt bilan yangi xizmat rolini bir xil tushuncha deb olmang. Bir odam qayta ro‘yxatdan o‘tib acquisition mukofotini qayta olmasin.

Account, role, campaign family va qualification event bo‘yicha aniq uniqueness qoidalari bo‘lsin. Bekor qilingan yoki o‘chirilgan akkauntlar uchun antifraud ma’lumotlarini saqlash mavjud maxfiylik siyosatiga mos bo‘lsin.

## 10. Qualification va mukofot holatlarini ajrating.

Referral attribution, qualification, mukofot va redemption alohida hayot sikllariga ega bo‘lsin.

Referral uchun attributed, qualifying, qualified, rejected va expired kabi holatlar.

Mukofot uchun pending_review, available, exhausted, expired va reversed kabi holatlar.

Bonus summasi bo‘yicha available, reserved va consumed alohida hisob bo‘lsin. Bitta bonusning qisman ishlatilishi mumkin bo‘lsin. Taklif qiluvchi va yangi foydalanuvchining mukofotlari mustaqil yozuvlar bo‘lsin.

Naqd to‘lovda haydovchining “pul oldim” tugmasini bank settlement dalili deb hisoblamang.

Qualification mavjud xizmat dalillari, yakuniy holat, cash confirmation, komissiyaning haqiqiy capture’i, nizo holati va risk tekshiruviga tayansin. Komissiya real balansdan undirilmagan bo‘lsa, iqtisodiy shart bajarildi deb olinmasin.

24–48 soatlik risk oynasini sozlanadigan boshlang‘ich siyosat sifatida qo‘llang. Oyna tugashi avtomatik “firibgarlik yo‘q” degani emas.

Bosqich progress’i va rad sabablari foydalanuvchiga tushunarli ko‘rinsin. Ochiq tekshiruv cheksiz davom etmasin: review muddati, mas’ul va shikoyat yo‘li bo‘lsin.

## 11. Antifraud’ni birinchi versiyada kiriting.

Quyidagilarni tekshiring:

- O‘zini o‘zi taklif qilish.
- Bir shaxsning ko‘p akkauntlari.
- Bir KYC yoki litsenziyadan qayta foydalanish.
- Juda tez takror ro‘yxatdan o‘tish.
- Takroriy passenger–driver juftliklari.
- Sun’iy qisqa yoki mantiqsiz xizmatlar.
- Kelishilgan narxni sun’iy oshirish.
- GPS, vaqt va xizmat dalillari o‘rtasidagi ziddiyat.
- Ko‘p referral’ning bir-biriga bog‘langan hisoblar orqali qualification olishi.
- Bir qurilmadagi noodatiy faollik.
- Mukofot chiqaruvchi hodisani qayta yuborish.

OWASP referral orqali ko‘p akkaunt yaratib kredit yig‘ishni biznes oqimidan suiiste’mol qilish misoli sifatida ko‘rsatadi; faqat endpoint rate-limit’i bilan cheklanmang. ([OWASP API Security Top 10][2])

IP, umumiy qurilma yoki oilaviy avtomobilni yakka o‘zi firibgarlik isboti deb olmang. Kuchli dalil bilan zaif signalni ajrating. Shubhada mukofotni review’ga o‘tkazing; foydalanuvchining qonuniy asosiy xizmatini avtomatik bloklamang.

Hozir karta ishlatilmagani sabab payment fingerprint yo‘qligini xato deb hisoblamang. Ortiqcha shaxsiy ma’lumot, yashirin device fingerprinting yoki yangi biometrik baza yaratmang.

## 12. Tranzaksiya, ledger va parallel ishlashni to‘g‘ri quring.

Mavjud nomlashga mos quyidagi tushunchalarni modelga kiriting:

- Campaign va uning o‘zgarmas versiyasi.
- Referral code va attribution.
- Campaign enrollment va va’da rezervi.
- Qualification event va milestone progress.
- Reward grant va bonus lot.
- Promo ledger va redemption.
- Campaign budget harakatlari.
- Fraud review va audit.

Bonusning manbasi, egasi, shartlari, muddati, campaign version’i va asos bo‘lgan hodisasi kuzatiladigan bo‘lsin.

Referral grant uchun unique reward key; eventlar uchun deduplication; redemption uchun idempotency bo‘lsin. Worker retry yoki parallel so‘rov ikkinchi mukofotni yaratmasin.

Bron qabul qilishda o‘rin/sig‘im, Passenger Bonus rezervi, Driver Credit rezervi va C_net bo‘yicha haqiqiy komissiya hold’i mavjud atomar tranzaksiyaga mos ishlasin.

Ikki parallel bron bir bonusning o‘zini ikki marta ishlatmasin. Lock tartibi, deadlock retry va limitlar tekshirilsin.

Promo ledger haqiqiy pul ledger’idan ajratilsin, lekin booking va moliyaviy yozuvlarga bog‘lansin. Hisobotda gross commission, passenger subsidy, driver discount va net collected commission alohida ko‘rinsin. Chegirma ikki marta daromaddan ayirilmasin.

## 13. Bekor qilish, refund va reversal foydalanuvchini adolatsiz jazolamasin.

Bron xizmat boshlanmasdan bekor qilinsa tegishli bonus, driver credit va pul hold’i to‘g‘ri bo‘shasin.

Platforma yoki haydovchi aybi bilan foydalanilmagan bonus yo‘qolmasin. Jarayon davomida bonus muddati tugab qolishi uchun adolatli, oldindan belgilangan tiklash siyosati bo‘lsin.

Naqd refund’ni platforma pul yuborgan deb avtomatik belgilamang. Mijozning naqd to‘lagan qismi bilan bonus qismi alohida boshqarilsin. Bonusning qaytarilishi naqd refund emas.

Qualification bergan safar keyin bekor qilinsa yoki firibgarlik aniqlansa, sarflanmagan tegishli mukofot reversible bo‘lsin.

Allaqachon sarflangan bonus sabab foydalanuvchining haqiqiy pul balansiga avtomatik qarz yozmang. Bunday holat review va risk xarajati sifatida ko‘rilsin. Bir tarafning firibgarligi uchun aloqasiz halol tarafni avtomatik jazolamang.

Ishlatilgan bonus reversal qilingani uchun budjetga pul haqiqatan qaytmagan bo‘lsa, uni yangi sarflash imkoniyati sifatida tiklamang.

## 14. Mijoz, haydovchi va admin uchun ishlaydigan boshqaruv yarating.

Mijoz ko‘rsin:

- Referral kodi va ulashish havolasi.
- Do‘stiga va o‘ziga beriladigan haqiqiy foyda.
- Qualification shartlari va progress.
- Kutilayotgan, mavjud va band qilingan bonus.
- Amal qilish muddati.
- Aynan tanlangan safarda qancha ishlatish mumkinligi.
- Naqd to‘lanadigan yakuniy summa.
- Bonus nega ishlamaganining tushunarli sababi.

Haydovchi ko‘rsin:

- QR va referral havolasi.
- Mijoz/haydovchi taklif qilish oqimlari.
- Milestone progress.
- Driver Credit va haqiqiy prepaid balance’ning alohida ko‘rinishi.
- Bron bo‘yicha bazaviy komissiya, mijoz chegirmasi kompensatsiyasi, driver credit va yakuniy undirish.
- Mijozdan olinadigan naqd summa.

Taklif qiluvchiga do‘stining aniq marshruti, to‘lovi, telefon raqami yoki boshqa keraksiz shaxsiy ma’lumoti ochilmasin.

Admin kampaniya yaratish, versiyalash, budjet ajratish, pauza qilish, fraud review, audit va reconciliation’ni boshqarsin. Admin sozlamasi arbitrary kod yoki SQL bajarishga imkon bermasin.

Budjetdan tashqari manual grant bo‘lmasin. Operatorga moliyaviy yoki xavfsizlik vakolatlarini avtomatik kengaytirmang.

Amaldagi API uslubiga mos referral summary, attribution, progress, bonus quote, wallet history va admin campaign endpointlarini qo‘shing. Server qoidalari klient validatsiyasiga bog‘liq bo‘lmasin.

## 15. Iqtisodiy simulyatsiya va natija o‘lchovlarini kiriting.

Kampaniya aktivlashtirilishidan oldin oddiy deterministik simulator quyidagilarni ko‘rsatsin:

- Mukofotlarning maksimal umumiy majburiyati.
- 100% redemption holatidagi xarajat.
- Past komissiya va yuqori xarajat holati.
- Mijoz bonusi va driver credit birga ishlatilishi.
- Refund, firibgarlik va kechikkan voqealar ta’siri.
- Budjet tugashi.
- Bonuslarni sarflash uchun taxminan nechta mos bron kerakligi.

Referral CAC hisobida ikki tarafga berilgan rag‘batlar va tegishli jalb qilish xarajatlari hisobga olinsin. Faqat ro‘yxatdan o‘tganlar emas, aniq ta’riflangan haqiqiy aktivlashgan foydalanuvchilar denominator bo‘lsin.

Quyidagi ko‘rsatkichlarni ajrating:

- Referral signup va qualification.
- Birinchi va takror xizmat.
- D30/D60 retention.
- Berilgan bonus, outstanding rezerv va real ishlatilgan chegirma.
- Fraud/reversal ulushi.
- Net contribution va koridor kesimidagi ta’sir.
- Organic va referral foydalanuvchilar natijasi.
- Driver milestone konversiyasi.

Hali 60 kun kuzatilmagan cohort uchun “60 kunlik foyda isbotlandi” demang. Bonus bilan ishlagan har bir xizmatni yangi qo‘shimcha xizmat deb hisoblamang.

## 16. Majburiy QA stsenariylarini bajaring.

Kamida quyidagilar test qilinsin:

1. O‘z referral kodini ishlatish rad etiladi.
2. Attribution takror yuborilsa dublikat paydo bo‘lmaydi.
3. Oddiy ro‘yxatdan o‘tish mukofotni available qilmaydi.
4. Bekor yoki qualification’ga yaroqsiz xizmat mukofot bermaydi.
5. Bir event parallel qayta ishlansa faqat bitta grant yaratiladi.
6. Ikki taraf mukofoti kampaniya budjetida to‘liq hisobga olinadi.
7. Parallel enrollment budjetni oshirib yubormaydi.
8. Budjet tugashi avval berilgan bonusni yo‘q qilmaydi.
9. Ikki bron bir bonusni ikki marta sarflamaydi.
10. Mijoz chegirmasi haydovchining asosiy tushumini kamaytirmaydi.
11. Passenger Bonus va Driver Credit birga marja limitini buzmaydi.
12. Komissiya nol yoki yetarli bo‘lmasa noto‘g‘ri subsidy yaratilmaydi.
13. Stale quote kattaroq naqd summa bilan yashirin qabul qilinmaydi.
14. Bekor qilish bonus va hold’larni to‘g‘ri qaytaradi.
15. Qisman sarflash, expiry va qaytarish summalari mos qoladi.
16. Ishlatilgan mukofot reversal’i haqiqiy balansda avtomatik qarz yaratmaydi.
17. Driver milestone ko‘p bronli bitta trip’ni ko‘p safar deb hisoblamaydi.
18. Bir xil IP’dagi halol foydalanuvchilar avtomatik firibgar bo‘lmaydi.
19. Referral sahifasi begona shaxsning safar ma’lumotini ochmaydi.
20. Worker crash/retry va Redis restart bonus/pulni dublikat qilmaydi.
21. Eski klient noto‘g‘ri naqd summa yoki komissiya ko‘rsatadigan promo bronni boshqarmaydi; capability himoyasi ishlaydi.
22. Campaign tahriri eski berilgan huquqlarni yashirin yomonlashtirmaydi.
23. Bonus o‘chiq bo‘lsa oddiy booking oqimi ishlashda davom etadi.
24. Promo ledger, campaign budget va haqiqiy komissiya reconciliation’i mos keladi.

Tranzaksiya va concurrency testlarini haqiqiy PostgreSQL’da bajaring. UI’da to‘liq oqimlarni tekshiring. Test mavjudligi bilan test o‘tganini ajrating.

## 17. Ishni bosqichma-bosqich yakunlang.

Avval mavjud tizim auditi va moliyaviy kontrakt, keyin budget/promo ledger, attribution, qualification, redemption integratsiyasi, interfeys va admin boshqaruvi, so‘ng QA va iqtisodiy simulyatsiya.

Yangi modulni feature flag ortida tayyorlang. Production uchun haqiqiy budjet, parametrlar va kampaniya shartlari tasdiqlanmagan bo‘lsa, kampaniya o‘chiq qolsin. Sintetik test muhitida esa barcha oqimlar to‘liq ishlasin.

Yakuniy hisobotda:

- Nima implementatsiya qilindi.
- Qaysi kod va migratsiyalar o‘zgardi.
- Qaysi testlar o‘tdi.
- Iqtisodiy simulyatsiya nimani ko‘rsatdi.
- Qaysi parametrlar hali biznes qarorini talab qiladi.
- Qaysi klient yoki muhit cheklovi ochiq qoldi.
- Production’da yoqish uchun aynan nima kerak.

Agent kampaniya foydaliligini dalilsiz kafolatlamasin. Natija — foydalanuvchiga tushunarli manfaat beradigan, haydovchiga mijoz chegirmasini yuklamaydigan, oldindan va’da qilingan bonuslarni hisobga oladigan va platformaning rag‘bat xarajatini qat’iy cheklaydigan ishlaydigan tizim bo‘lsin.

[1]: https://developer.android.com/training/app-links/verify-applinks "Verify App Links | App architecture | Android Developers"
[2]: https://api-security.owasp.org/editions/2023/en/0xa6-unrestricted-access-to-sensitive-business-flows/ "API6:2023 Unrestricted Access to Sensitive Business Flows"
