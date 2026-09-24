# Taklif: operator orqali attribution tuzatish (yoqilmagan)

**Holat:** taklif — **yoqilmagan**, qaror kutilmoqda • **Sana:** 23.09.2026 • **Bog‘liq:** ADR-0023, Q106, Q117, 3-bosqich

3-bosqichda attribution’ni operator orqali almashtirish **qo‘shilmadi**. `referral_attributions` qatoridagi taklif qiluvchi, kod va oyna DB trigger’i bilan o‘zgarmas; hech bir servis funksiyasi uni tahrirlamaydi. Operator faqat risk signalini ko‘rib chiqadi va eligibility qarorini dalil asosida beradi (`promo_reviews`) — bu attribution egasini almashtirish vakolati emas.

## Qachon kerak bo‘lishi mumkin
1. Ilova xatosi: foydalanuvchi to‘g‘ri kodni kiritdi, lekin klient boshqa kodni yubordi (server log/audit bilan isbotlanadi).
2. Taklif qiluvchi akkaunti firibgarlik sababli rad etilgan va halol yangi foydalanuvchi boshqa haqiqiy taklif qiluvchini ko‘rsatadi.
3. Kod egasi o‘z akkauntini o‘chirgan, attribution esa hali va’dasiz.

## Xavf va moliyaviy oqibat
- Almashtirish ikkinchi acquisition mukofotini ochish yo‘li bo‘lib qolmasligi kerak: `(referee, family)` bo‘yicha bitta attribution va identity bo‘yicha bitta tirik enrollment saqlanadi.
- Agar eski attribution bo‘yicha enrollment va budjet va’dasi bo‘lsa, eski taklif qiluvchining majburiyati **release** qilinadi (budjetga qaytadi), yangisi uchun **yangi va’da** budjet lock’i ostida rezerv qilinadi — budjet yetmasa tuzatish rad etiladi. Berilgan (granted) yoki sarflangan mukofot bo‘lsa tuzatish taqiqlanadi.
- Eski taklif qiluvchiga oldindan xabar va shikoyat yo‘li kerak (u halol bo‘lishi mumkin).

## Taklif etilgan qoidalar (tasdiq uchun)
- Faqat admin+ (`promo.fraud_decide`), ikki turli xodim (so‘rovchi ≠ tasdiqlovchi), sabab va dalil havolasi majburiy.
- Faqat attribution `attributed`/`qualifying` va hech qanday obligation `granted` bo‘lmaganda.
- Amalga oshirish: eski qator o‘zgartirilmaydi; `superseded_by` havolali yangi attribution yoziladi (append-only), eski enrollment release, yangi enrollment odatdagi qoidalar bilan.
- Audit va outbox (`promo.attribution_corrected`, faqat staff).

Qaror qabul qilinmaguncha bu imkoniyat kodga qo‘shilmaydi.
