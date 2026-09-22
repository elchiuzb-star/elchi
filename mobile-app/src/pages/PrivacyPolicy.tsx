/**
 * Maxfiylik siyosati — Uzbek-language privacy policy.
 *
 * The contents describe what the Elchi backend ACTUALLY stores (see app/models):
 * users, client_profiles, driver_profiles, driver_documents, orders, otp_codes,
 * refresh_sessions, ratings, disputes, notifications, audit_logs — plus the two
 * third parties that receive data (Eskiz.uz for SMS, Yandex for geocoding).
 *
 * ⚠️ Placeholders marked [...] MUST be filled with the real legal entity details
 * before this is published, and the whole text should be reviewed by a lawyer
 * familiar with O'zR ZRU-547 "Shaxsiy ma'lumotlar to'g'risida".
 */

const UPDATED_AT = "2026-yil 5-avgust";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-lg font-bold text-foreground">{title}</h2>
      <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  );
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-background py-10" >
      <div className="mx-auto max-w-3xl px-5">
        <div className="rounded-2xl border border-border bg-card p-7 shadow-sm sm:p-10">
          <p className="text-xs font-semibold uppercase tracking-wide text-primary">Elchi</p>
          <h1 className="mt-1.5 text-2xl font-bold text-foreground">Maxfiylik siyosati</h1>
          <p className="mt-2 text-xs text-muted-foreground">Oxirgi yangilanish: {UPDATED_AT}</p>

          <Section title="1. Umumiy qoidalar">
            <p>
              Ushbu Maxfiylik siyosati [YURIDIK SHAXS NOMI] (keyingi o'rinlarda — «Biz»,
              «Elchi») tomonidan Elchi mobil ilovasi va veb-saytidan (keyingi o'rinlarda —
              «Platforma») foydalanuvchilarning shaxsiy ma'lumotlarini yig'ish, saqlash,
              qayta ishlash va himoya qilish tartibini belgilaydi.
            </p>
            <p>
              Platforma shaharlararo yuk va pochta jo'natmalarini yetkazib berish xizmati
              bo'lib, mijozlar va haydovchilarni bog'laydi. Platformadan foydalanish orqali
              siz ushbu siyosat shartlariga rozilik bildirasiz.
            </p>
            <p>
              Ma'lumotlar O'zbekiston Respublikasining «Shaxsiy ma'lumotlar to'g'risida»gi
              ZRU-547-sonli Qonuni talablariga muvofiq qayta ishlanadi.
            </p>
          </Section>

          <Section title="2. Biz qanday ma'lumotlarni yig'amiz">
            <p className="font-medium text-secondary-foreground">Barcha foydalanuvchilar uchun:</p>
            <List
              items={[
                "Telefon raqami — ro'yxatdan o'tish va tizimga kirish uchun;",
                "Ism-familiya — profilda ko'rsatilgan holda;",
                "Tasdiqlash kodi (OTP) va so'rov yuborilgan IP-manzil — xavfsizlik va suiiste'molning oldini olish uchun;",
                "Seans ma'lumotlari — tizimga kirish vaqti va faol qurilmalar;",
                "Bildirishnomalar va ilova sozlamalari.",
              ]}
            />

            <p className="pt-2 font-medium text-secondary-foreground">Mijozlardan qo'shimcha ravishda:</p>
            <List
              items={[
                "Jo'natish va yetkazib berish manzillari hamda ularning koordinatalari (kenglik/uzunlik);",
                "Jo'natuvchi va qabul qiluvchining telefon raqamlari;",
                "Yuk turi, izohlar va yuk fotosurati;",
                "Buyurtma narxi, to'lov usuli va buyurtma tarixi;",
                "Haydovchilarga qoldirilgan reyting va sharhlar.",
              ]}
            />

            <p className="pt-2 font-medium text-secondary-foreground">Haydovchilardan qo'shimcha ravishda:</p>
            <List
              items={[
                "Avtomobil modeli, rangi va davlat raqami;",
                "Shaxsni tasdiqlovchi hujjatlar nusxalari (pasport, haydovchilik guvohnomasi, texnik pasport) — faqat tekshiruvdan o'tkazish maqsadida;",
                "Tekshiruv holati, faollik statusi, reyting va bajarilgan buyurtmalar statistikasi;",
                "Tanlangan yo'nalishlar (qaysi shaharlar orasida ishlash).",
              ]}
            />

            <p className="pt-2">
              Biz bank kartalari ma'lumotlarini yig'maymiz va saqlamaymiz. Hozirgi vaqtda
              to'lov faqat naqd pul orqali amalga oshiriladi.
            </p>
          </Section>

          <Section title="3. Ma'lumotlardan foydalanish maqsadlari">
            <List
              items={[
                "Foydalanuvchini identifikatsiya qilish va hisobga kirishini ta'minlash;",
                "Buyurtmalarni yaratish, haydovchilar bilan bog'lash va yetkazib berishni kuzatish;",
                "Mijoz va haydovchi o'rtasida aloqani ta'minlash;",
                "Haydovchilarni tekshirish va platforma xavfsizligini saqlash;",
                "Nizolarni ko'rib chiqish va qo'llab-quvvatlash xizmatini ko'rsatish;",
                "Xizmat sifatini yaxshilash va statistik tahlil;",
                "Qonun hujjatlarida nazarda tutilgan majburiyatlarni bajarish.",
              ]}
            />
          </Section>

          <Section title="4. Ma'lumotlarni uchinchi shaxslarga berish">
            <p>
              Biz shaxsiy ma'lumotlaringizni sotmaymiz. Ma'lumotlar faqat quyidagi hollarda
              va faqat zarur hajmda uzatiladi:
            </p>
            <List
              items={[
                "Buyurtma ishtirokchilariga — yetkazib berish uchun zarur bo'lgan manzil va telefon raqami tayinlangan haydovchiga, haydovchining ismi va avtomobil ma'lumotlari esa mijozga ko'rsatiladi;",
                "Eskiz.uz — tasdiqlash kodlarini SMS orqali yuborish uchun telefon raqami uzatiladi;",
                "Yandex Maps — manzilni koordinataga aylantirish (geokodlash) va xaritani ko'rsatish uchun;",
                "Vakolatli davlat organlariga — qonun hujjatlarida belgilangan tartibda rasmiy so'rov asosida.",
              ]}
            />
          </Section>

          <Section title="5. Ma'lumotlarni saqlash">
            <p>
              Shaxsiy ma'lumotlar O'zbekiston Respublikasi hududida joylashgan serverlarda
              saqlanadi.
            </p>
            <List
              items={[
                "Hisob ma'lumotlari — hisob faol bo'lgan davrda va o'chirilgandan keyin qonunda belgilangan muddat davomida;",
                "Buyurtmalar tarixi va moliyaviy yozuvlar — hisobot majburiyatlari talab qilgan muddatda;",
                "Tasdiqlash kodlari — bir necha daqiqa ichida amal qilish muddati tugaydi;",
                "Haydovchi hujjatlari — hamkorlik davomida va u tugagach qonunda belgilangan muddatda.",
              ]}
            />
          </Section>

          <Section title="6. Xavfsizlik">
            <p>
              Ma'lumotlarni himoya qilish uchun quyidagi choralar qo'llaniladi: barcha
              ma'lumotlar shifrlangan HTTPS ulanishi orqali uzatiladi; parollar va
              tasdiqlash kodlari faqat qaytarilmas kriptografik shaklda (xesh) saqlanadi;
              ma'lumotlar bazasiga tashqi tarmoqdan to'g'ridan-to'g'ri kirish yopilgan;
              ma'muriy amallar audit jurnalida qayd etiladi.
            </p>
            <p>
              Shunga qaramay, internet orqali ma'lumot uzatishning 100% xavfsizligini
              kafolatlash mumkin emas. Hisobingiz xavfsizligi buzilganiga shubha qilsangiz,
              darhol biz bilan bog'laning.
            </p>
          </Section>

          <Section title="7. Sizning huquqlaringiz">
            <List
              items={[
                "O'zingiz haqingizdagi ma'lumotlarni olish va ular bilan tanishish;",
                "Noto'g'ri yoki to'liq bo'lmagan ma'lumotlarni tuzatishni talab qilish;",
                "Ma'lumotlaringizni o'chirishni yoki qayta ishlashni to'xtatishni talab qilish;",
                "Berilgan rozilikni qaytarib olish;",
                "Huquqlaringiz buzilgan deb hisoblasangiz, vakolatli organga murojaat qilish.",
              ]}
            />
            <p>
              So'rovlar quyidagi bo'limda ko'rsatilgan aloqa vositalari orqali qabul
              qilinadi. Ba'zi ma'lumotlar (masalan, yakunlangan buyurtmalar bo'yicha
              yozuvlar) qonuniy majburiyatlar sababli saqlanib qolishi mumkin.
            </p>
          </Section>

          <Section title="8. Voyaga yetmaganlar">
            <p>
              Platforma 18 yoshga to'lmagan shaxslar uchun mo'ljallanmagan. Agar voyaga
              yetmagan shaxsning ma'lumotlari yig'ilgani aniqlansa, ular o'chiriladi.
            </p>
          </Section>

          <Section title="9. Siyosatga o'zgartirishlar">
            <p>
              Ushbu siyosatga o'zgartirishlar kiritilishi mumkin. Yangi tahrir ushbu
              sahifada e'lon qilingan paytdan boshlab kuchga kiradi. Muhim o'zgarishlar
              haqida ilova orqali xabar beriladi.
            </p>
          </Section>

          <Section title="10. Biz bilan bog'lanish">
            <p>Ma'lumotlaringiz bo'yicha savollar va so'rovlar uchun:</p>
            <List
              items={[
                "Tashkilot: [YURIDIK SHAXS NOMI]",
                "STIR (INN): [STIR RAQAMI]",
                "Manzil: [YURIDIK MANZIL]",
                "Elektron pochta: [EMAIL]",
                "Telefon: [TELEFON RAQAMI]",
              ]}
            />
          </Section>

          <p className="mt-10 border-t border-border pt-5 text-xs text-muted-foreground">
            © Elchi · Shaharlararo yuk va pochta yetkazib berish xizmati
          </p>
        </div>
      </div>
    </div>
  );
}
