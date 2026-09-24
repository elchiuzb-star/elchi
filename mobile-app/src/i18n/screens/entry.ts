/** Entry and client-home screens: splash, onboarding, role, phone/OTP sign-in, support, settings, home, driver offers, offer bid, direction pickers. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const entryMessages = {
  // --- splash / onboarding / role ---
  "onboarding.tagline": { uz: "Shaharlararo posilka va yo'lovchi xizmati", ru: "Междугородние посылки и пассажирские поездки" },
  "onboarding.start": { uz: "Boshlash", ru: "Начать" },
  "onboarding.next": { uz: "Keyingisi", ru: "Далее" },
  "onboarding.skip": { uz: "O'tkazib yuborish", ru: "Пропустить" },
  "onboarding.step1Title": { uz: "Posilkangizni shahardan shaharga yuboring", ru: "Отправляйте посылки из города в город" },
  "onboarding.step1Text": {
    uz: "Yo'nalishni tanlang, manzillarni kiriting va haydovchilardan taklif oling.",
    ru: "Выберите направление, укажите адреса и получите предложения от водителей.",
  },
  "onboarding.step2Title": { uz: "Haydovchilar narx taklif qiladi", ru: "Водители предлагают цену" },
  "onboarding.step2Text": { uz: "Sizga mos narx va haydovchini o'zingiz tanlaysiz.", ru: "Подходящую цену и водителя вы выбираете сами." },
  "onboarding.step3Title": { uz: "Yetkazildi - tasdiqlang va baholang", ru: "Доставлено - подтвердите и оцените" },
  "onboarding.step3Text": {
    uz: "Posilka yetib borgach, buyurtmani tasdiqlang va haydovchiga baho bering.",
    ru: "Когда посылка доставлена, подтвердите заказ и оцените водителя.",
  },
  "onboarding.roleClient": { uz: "Men mijozman", ru: "Я клиент" },
  "onboarding.roleClientHint": { uz: "Posilka yuborish yoki yo'lovchi sifatida borish", ru: "Отправить посылку или поехать пассажиром" },
  "onboarding.roleDriver": { uz: "Men haydovchiman", ru: "Я водитель" },
  "onboarding.roleDriverHint": { uz: "Yo'nalishingizga yuk va yo'lovchi olish", ru: "Брать грузы и пассажиров по своему маршруту" },
  "onboarding.roleTitle": { uz: "Qanday davom etamiz?", ru: "Как продолжим?" },
  "onboarding.roleSubtitle": { uz: "Rolingizni tanlang - keyin ham almashtira olasiz.", ru: "Выберите роль - её можно сменить позже." },

  // --- phone / OTP ---
  "auth.codeSent": { uz: "Kod yuborildi", ru: "Код отправлен" },
  // Follows the bold role name ("Haydovchi sifatida" / "Водитель — вход").
  "auth.roleSuffix": { uz: "sifatida", ru: "— вход" },
  "auth.phoneTitle": { uz: "Telefon raqamingiz", ru: "Ваш номер телефона" },
  "auth.phoneSubtitle": { uz: "Tasdiqlash kodi SMS orqali yuboriladi.", ru: "Код подтверждения придёт по SMS." },
  "auth.getCode": { uz: "Kod olish", ru: "Получить код" },
  "auth.otpTitle": { uz: "Kodni kiriting", ru: "Введите код" },
  "auth.otpSentTo": { uz: "Kod shu raqamga yuborildi", ru: "Код отправлен на номер" },
  // The length comes from OTP_LENGTH; the source never spells a digit count (contract test).
  "auth.otpLabel": { uz: "{length} xonali kod", ru: "Код из {length} цифр" },
  "auth.devCode": { uz: "Mahalliy test kodi: {code}", ru: "Локальный тестовый код: {code}" },
  "auth.resendIn": { uz: "Qayta yuborish 0:{seconds}", ru: "Повторная отправка 0:{seconds}" },
  "auth.codeResent": { uz: "Kod qayta yuborildi", ru: "Код отправлен повторно" },
  "auth.resendCode": { uz: "Kodni qayta yuborish", ru: "Отправить код ещё раз" },

  // --- support ---
  "support.title": { uz: "Yordam", ru: "Помощь" },
  "support.cardTitle": { uz: "Qo'llab-quvvatlash", ru: "Поддержка" },
  "support.noPhoneLine": {
    uz: "Hozircha telefon liniyasi yo'q. Murojaatingizni shu yerdan yozib qoldiring - operator ilova ichida javob beradi.",
    ru: "Телефонной линии пока нет. Оставьте обращение здесь - оператор ответит в приложении.",
  },
  "support.newTicket": { uz: "Murojaat yuborish", ru: "Отправить обращение" },
  "support.messagePlaceholder": {
    uz: "Nima bo'ldi? Bron raqamini ham yozsangiz tezroq topamiz.",
    ru: "Что случилось? Укажите номер брони - так мы найдём её быстрее.",
  },
  "support.ticketSent": { uz: "Murojaat yuborildi", ru: "Обращение отправлено" },
  "support.myTickets": { uz: "Murojaatlarim", ru: "Мои обращения" },
  "support.faqTitle": { uz: "Savollar", ru: "Вопросы" },
  "support.faq1Question": { uz: "Buyurtma qanday yarataman?", ru: "Как создать заказ?" },
  "support.faq1Answer": {
    uz: "Olib ketish va yetkazish joyini xaritada belgilang, keyin o'z narxingiz bilan e'lon bering yoki haydovchilarning e'lonlariga narx taklif qiling.",
    ru: "Отметьте на карте место отправки и доставки, затем разместите объявление со своей ценой или предложите цену на объявления водителей.",
  },
  "support.faq2Question": { uz: "Narx qanday belgilanadi?", ru: "Как определяется цена?" },
  "support.faq2Answer": {
    uz: "Narxni siz va haydovchi kelishasiz. Siz narx taklif qilasiz, haydovchi qarshi taklif berishi mumkin; qabul qilingan oxirgi taklif bron narxi bo'ladi. ELCHI narxni o'zi belgilamaydi.",
    ru: "Цену согласуете вы и водитель. Вы предлагаете цену, водитель может сделать встречное предложение; последнее принятое предложение становится ценой брони. ELCHI сам цену не устанавливает.",
  },
  "support.faq3Question": { uz: "Buyurtmani bekor qilsam bo'ladimi?", ru: "Можно ли отменить заказ?" },
  "support.faq3Answer": {
    uz: "Ha. Taklif qabul qilinmaguncha e'lonni istalgan vaqtda yopishingiz mumkin. Bron tuzilgandan keyin bekor qilish shartlari bron sahifasida ko'rsatiladi.",
    ru: "Да. Пока предложение не принято, объявление можно закрыть в любой момент. После создания брони условия отмены указаны на странице брони.",
  },
  "support.faq4Question": { uz: "Haydovchining telefoni qachon ochiladi?", ru: "Когда станет виден телефон водителя?" },
  "support.faq4Answer": {
    uz: "Xizmat boshlanganda: yo'lovchi uchun siz mashinaga chiqqanda, pochta uchun yuk olib ketilganda. Undan oldin aloqa ilova ichidagi chat orqali bo'ladi.",
    ru: "Когда начнётся услуга: для пассажира - когда вы сядете в машину, для посылки - когда груз заберут. До этого связь идёт через чат в приложении.",
  },

  // --- settings ---
  "settingsScreen.title": { uz: "Sozlamalar", ru: "Настройки" },
  "settingsScreen.appearance": { uz: "Ko'rinish", ru: "Оформление" },
  "settingsScreen.account": { uz: "Akkaunt", ru: "Аккаунт" },
  "settingsScreen.privacy": { uz: "Maxfiylik siyosati", ru: "Политика конфиденциальности" },
  "settingsScreen.logout": { uz: "Chiqish", ru: "Выйти" },

  // --- client home ---
  "home.currentLocation": { uz: "Joriy joylashuv", ru: "Текущее местоположение" },
  "home.referralCodeSaved": {
    uz: "Taklif kodi saqlandi: {code} — tasdiqlash uchun bosing",
    ru: "Код приглашения сохранён: {code} — нажмите, чтобы подтвердить",
  },
  "home.modeTaxi": { uz: "Taksi", ru: "Такси" },
  "home.modeParcel": { uz: "Pochta", ru: "Посылки" },
  "home.checkingRoute": { uz: "Yo'nalish tekshirilmoqda...", ru: "Проверяем направление..." },
  "home.movePointHint": {
    uz: "Nuqtalardan birini ELCHI yo'nalishiga yaqinroq joyga ko'chiring.",
    ru: "Перенесите одну из точек ближе к направлению ELCHI.",
  },
  "home.estimatedTime": { uz: "Taxminiy yo'l vaqti · {corridor}", ru: "Примерное время в пути · {corridor}" },
  "home.routeDistricts": { uz: "Yo'nalishdagi tumanlar", ru: "Районы по направлению" },
  "home.routeLoading": { uz: "Yo'nalish yuklanmoqda...", ru: "Загружаем направление..." },
  "home.districtDriversNote": {
    uz: "Shu tumanlardagi haydovchilar ham e'loningizni ko'radi.",
    ru: "Водители из этих районов тоже увидят ваше объявление.",
  },
  "home.viewRoute": { uz: "Yo'nalishni ko'rish", ru: "Посмотреть направление" },
  "home.passengerClosed": { uz: "Yo'lovchi xizmati bu hududda hali ochilmagan.", ru: "Пассажирские перевозки в этом регионе пока не открыты." },
  "home.parcelClosed": { uz: "Pochta xizmati bu hududda hali ochilmagan.", ru: "Доставка посылок в этом регионе пока не открыта." },
  "home.sameStop": {
    uz: "Olib ketish va yetkazish bekati bir xil bo'lishi mumkin emas.",
    ru: "Остановки отправления и доставки не могут совпадать.",
  },
  "home.noConfirmedRoute": { uz: "Bu ikki bekat orasida tasdiqlangan yo'nalish yo'q.", ru: "Между этими остановками нет утверждённого направления." },

  // --- driver offers (client side) ---
  "offers.title": { uz: "Haydovchi e'lonlari", ru: "Объявления водителей" },
  "offers.makeOffer": { uz: "Narxingizni taklif qiling", ru: "Предложите свою цену" },
  "offers.driverPriceRated": {
    uz: "Haydovchi narxi · {count} ta bajarilgan safar · {rating}",
    ru: "Цена водителя · Выполнено поездок: {count} · {rating}",
  },
  "offers.driverPriceUnrated": {
    uz: "Haydovchi narxi · {count} ta bajarilgan safar · hali baholanmagan",
    ru: "Цена водителя · Выполнено поездок: {count} · оценок пока нет",
  },
  "offers.introPassenger": {
    uz: "Shu yo'nalishda safar e'lon qilgan haydovchilar. Narxi to'g'ri kelmasa, o'z narxingizni taklif qiling.",
    ru: "Водители, объявившие поездку по этому направлению. Если цена не подходит, предложите свою.",
  },
  "offers.introParcel": {
    uz: "Shu yo'nalishda yuk oladigan haydovchilar. Narxi to'g'ri kelmasa, o'z narxingizni taklif qiling.",
    ru: "Водители, которые берут груз по этому направлению. Если цена не подходит, предложите свою.",
  },
  "offers.emptyTitle": { uz: "Bu yo'nalishda e'lon yo'q", ru: "По этому направлению объявлений нет" },
  "offers.emptySubtitle": {
    uz: "O'zingiz e'lon bering - haydovchilar sizga narx taklif qiladi.",
    ru: "Разместите своё объявление - водители предложат вам цену.",
  },
  "offers.emptyAction": { uz: "O'zim e'lon beraman", ru: "Разместить объявление" },

  // --- offer bid ---
  "offerBid.yourRequest": { uz: "Talabingiz", ru: "Ваш запрос" },
  "offerBid.newIntent": { uz: "Yangi safar/jo'natma", ru: "Новая поездка/посылка" },
  "offerBid.intentExpired": {
    uz: "Talabingizdagi vaqt o'tib ketgan. Sana avtomatik o'zgartirilmaydi - avval vaqtni yangilang.",
    ru: "Время в вашем запросе уже прошло. Дата не меняется автоматически - сначала обновите время.",
  },
  "offerBid.driverPrice": { uz: "Haydovchi narxi: {price}", ru: "Цена водителя: {price}" },
  "offerBid.departure": { uz: "Chiqish: {from} - {to}", ru: "Отправление: {from} - {to}" },
  "offerBid.peopleLabel": { uz: "Odamlar soni:", ru: "Количество человек:" },
  "offerBid.peopleCount": { uz: "{count} kishi", ru: "{count} чел." },
  "offerBid.peopleFromIntent": {
    uz: "(talabingizdan; o'zgartirish uchun \"Tahrirlash\")",
    ru: "(из вашего запроса; чтобы изменить, нажмите «Изменить»)",
  },
  "offerBid.seatsLabel": { uz: "Nechta o'rin", ru: "Сколько мест" },
  "offerBid.pricePerSeatLabel": { uz: "Bir o'rin uchun narxingiz (so'm)", ru: "Ваша цена за место (сум)" },
  "offerBid.priceLabel": { uz: "Narxingiz (so'm)", ru: "Ваша цена (сум)" },
  "offerBid.pricePlaceholder": { uz: "Masalan: 180000", ru: "Например: 180000" },
  "offerBid.yourOffer": { uz: "Sizning taklifingiz: {price}", ru: "Ваше предложение: {price}" },
  "offerBid.totalForSeats": { uz: "{seats} o'rin uchun jami: {total}", ru: "Мест: {seats}, итого: {total}" },
  "offerBid.requestPriceOtherBasis": {
    uz: "Talabingizdagi narx ({price}) boshqa birlikda, shuning uchun maydon haydovchi narxidan boshlandi.",
    ru: "Цена в вашем запросе ({price}) указана в другой единице, поэтому поле заполнено ценой водителя.",
  },
  "offerBid.priceOnlyForDriver": {
    uz: "Bu narx faqat shu haydovchiga yuboriladi; saqlangan talabingiz o'zgarmaydi.",
    ru: "Эта цена отправляется только этому водителю; сохранённый запрос не меняется.",
  },
  "offerBid.weightKg": { uz: "Og'irlik (kg)", ru: "Вес (кг)" },
  "offerBid.lengthCm": { uz: "Uzunlik (sm)", ru: "Длина (см)" },
  "offerBid.widthCm": { uz: "Eni (sm)", ru: "Ширина (см)" },
  "offerBid.heightCm": { uz: "Balandligi (sm)", ru: "Высота (см)" },
  "offerBid.receiverName": { uz: "Qabul qiluvchi ismi", ru: "Имя получателя" },
  "offerBid.receiverPhone": { uz: "Qabul qiluvchi telefoni", ru: "Телефон получателя" },
  "offerBid.reservesNothing": {
    uz: "Taklif o'rin band qilmaydi - haydovchi qabul qilganda yoki siz uning qarshi taklifini qabul qilganingizda bron yaratiladi.",
    ru: "Предложение не бронирует место - бронь создаётся, когда водитель его примет или вы примете его встречное предложение.",
  },
  "offerBid.sent": { uz: "Taklifingiz yuborildi", ru: "Ваше предложение отправлено" },
  "offerBid.submit": { uz: "Taklif yuborish", ru: "Отправить предложение" },
  "offerBid.parcelRequestTitle": { uz: "Jo'natma talabi", ru: "Запрос на посылку" },
  "offerBid.tripRequestTitle": { uz: "Safar talabi", ru: "Запрос на поездку" },
  "offerBid.noSavedRequest": { uz: "Saqlangan talab yo'q", ru: "Сохранённого запроса нет" },

  // --- direction pickers ---
  "direction.from": { uz: "Qayerdan?", ru: "Откуда?" },
  "direction.to": { uz: "Qayerga?", ru: "Куда?" },
} as const satisfies Record<string, Message>;
