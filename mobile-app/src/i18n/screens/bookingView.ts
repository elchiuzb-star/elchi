/** Booking chat and tracking, the client's listing detail and offers, legacy v1 order screens, inbox, client profile and driver home. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const bookingViewMessages = {
  // --- booking-chat ---
  "bookingChat.title": { uz: "Xabarlar", ru: "Сообщения" },
  "bookingChat.olderMessages": { uz: "Oldingi xabarlar", ru: "Предыдущие сообщения" },
  "bookingChat.emptyTitle": { uz: "Xabar yo'q", ru: "Сообщений нет" },
  "bookingChat.emptySubtitle": {
    uz: "Xizmat boshlangunicha aloqa faqat shu chat orqali bo'ladi.",
    ru: "До начала поездки связь возможна только через этот чат.",
  },
  "bookingChat.hiddenByStaff": { uz: "Xabar operator tomonidan yashirildi", ru: "Сообщение скрыто оператором" },
  "bookingChat.contactsHidden": { uz: "Aloqa ma'lumotlari yashirildi: {codes}", ru: "Контактные данные скрыты: {codes}" },
  "bookingChat.notSent": { uz: "Yuborilmadi: {text}", ru: "Не отправлено: {text}" },
  "bookingChat.placeholder": { uz: "Xabar yozing", ru: "Напишите сообщение" },
  "bookingChat.autoMaskNote": {
    uz: "Telefon raqam va havolalar avtomatik yashiriladi.",
    ru: "Номера телефонов и ссылки скрываются автоматически.",
  },

  // --- booking-tracking ---
  "bookingTracking.title": { uz: "Kuzatuv", ru: "Отслеживание" },
  "bookingTracking.progressTitle": { uz: "Holat kuzatuvi", ru: "Ход выполнения" },
  "bookingTracking.progressHint": {
    uz: "Buyurtma bosqichlari — haydovchi belgilagan holatlar bo'yicha.",
    ru: "Этапы заказа — по статусам, которые отметил водитель.",
  },
  "bookingTracking.liveTitle": { uz: "Jonli joylashuv", ru: "Местоположение в реальном времени" },
  "bookingTracking.liveDisabled": {
    uz: "Bu yo'nalishda jonli kuzatuv hali yoqilmagan.",
    ru: "На этом направлении отслеживание в реальном времени пока не включено.",
  },
  "bookingTracking.lastPoint": { uz: "Oxirgi nuqta: {time}", ru: "Последняя точка: {time}" },
  "bookingTracking.lowAccuracy": { uz: "aniqligi past", ru: "низкая точность" },
  "bookingTracking.sourceLine": {
    uz: "Manba: haydovchining telefoni. Yangilanish: {freshness}.",
    ru: "Источник: телефон водителя. Обновление: {freshness}.",
  },
  "bookingTracking.etaTitle": { uz: "Taxminiy yetib kelish", ru: "Ориентировочное прибытие" },
  "bookingTracking.etaDisclaimer": { uz: "Bu taxmin, kafolat emas.", ru: "Это оценка, а не гарантия." },

  // --- client-listing-detail ---
  "listingDetail.title": { uz: "Buyurtma tafsilotlari", ru: "Детали заказа" },
  "listingDetail.pickupStop": { uz: "Olib ketish bekati", ru: "Остановка отправления" },
  "listingDetail.pickupPoint": { uz: "Olib ketish joyi", ru: "Место отправления" },
  "listingDetail.dropoffStop": { uz: "Yetkazish bekati", ru: "Остановка доставки" },
  "listingDetail.dropoffPoint": { uz: "Yetkazish joyi", ru: "Место доставки" },
  "listingDetail.departureWindow": { uz: "Jo'nash oynasi", ru: "Время отправления" },
  "listingDetail.parcel": { uz: "Posilka", ru: "Посылка" },
  "listingDetail.parcelValue": { uz: "{type}, {weight} kg", ru: "{type}, {weight} кг" },
  "listingDetail.parcelPhoto": { uz: "Posilka rasmi", ru: "Фото посылки" },
  "listingDetail.viewOffers": { uz: "Takliflarni ko'rish", ru: "Посмотреть предложения" },
  "listingDetail.viewMatches": { uz: "Mos safarlarni ko'rish", ru: "Посмотреть подходящие поездки" },
  "listingDetail.cancelled": { uz: "Buyurtma bekor qilindi", ru: "Заказ отменён" },
  "listingDetail.cancel": { uz: "Buyurtmani bekor qilish", ru: "Отменить заказ" },

  // --- client-listing-bids / client-bids ---
  "listingBids.title": { uz: "Haydovchi takliflari", ru: "Предложения водителей" },
  "listingBids.emptyTitle": { uz: "Hozircha takliflar yo'q", ru: "Предложений пока нет" },
  "listingBids.emptySubtitle": {
    uz: "Haydovchilar taklif yuborishi bilan shu yerda ko'rasiz",
    ru: "Как только водители отправят предложения, вы увидите их здесь",
  },
  "listingBids.yourPrice": { uz: "Sizning narxingiz (so'm)", ru: "Ваша цена (сум)" },
  "listingBids.counterSent": { uz: "Qarshi taklif yuborildi", ru: "Встречное предложение отправлено" },
  "listingBids.counterButton": {
    uz: "Boshqa narx taklif qilish ({count} marta qoldi)",
    ru: "Предложить другую цену (осталось попыток: {count})",
  },
  "listingBids.noRevisionsLeft": {
    uz: "Narxni o'zgartirish imkoni tugadi — taklifni qabul qiling yoki rad eting.",
    ru: "Изменить цену больше нельзя — примите или отклоните предложение.",
  },
  "listingBids.awaitingDriver": {
    uz: "Sizning qarshi taklifingiz yuborildi — haydovchining javobi kutilmoqda.",
    ru: "Ваше встречное предложение отправлено — ждём ответа водителя.",
  },
  "listingBids.driverChosen": { uz: "Haydovchi tanlandi", ru: "Водитель выбран" },
  "listingBids.chooseDriver": { uz: "Shu haydovchini tanlash", ru: "Выбрать этого водителя" },
  "listingBids.closed": {
    uz: "Bu taklif yopilgan ({status}) — javob berib bo'lmaydi.",
    ru: "Это предложение закрыто ({status}) — ответить на него нельзя.",
  },
  "listingBids.identityHidden": {
    uz: "Haydovchining ismi, telefoni va davlat raqami taklif qabul qilinmaguncha ko'rsatilmaydi.",
    ru: "Имя, телефон и госномер водителя не показываются, пока предложение не принято.",
  },

  // --- legacy v1 order: client-bids, client-confirm, client-rating, client-dispute ---
  "legacyOrder.rating": { uz: "Reyting: {rating}", ru: "Рейтинг: {rating}" },
  "legacyOrder.confirmTitle": { uz: "Buyurtmani tasdiqlang", ru: "Подтвердите заказ" },
  "legacyOrder.confirmBody": {
    uz: "Posilka yetib kelgan bo'lsa, buyurtmani tasdiqlang.",
    ru: "Если посылка доставлена, подтвердите заказ.",
  },
  "legacyOrder.confirmed": { uz: "Buyurtma tasdiqlandi", ru: "Заказ подтверждён" },
  "legacyOrder.ratingHint": { uz: "1 dan 5 gacha baho bering", ru: "Поставьте оценку от 1 до 5" },
  "legacyOrder.stars": { uz: "{value} yulduz", ru: "Звёзд: {value}" },
  "legacyOrder.ratingComment": { uz: "Izoh qoldiring", ru: "Оставьте комментарий" },
  "legacyOrder.ratingSent": { uz: "Baho yuborildi", ru: "Оценка отправлена" },
  "legacyOrder.ratingSubmit": { uz: "Bahoni yuborish", ru: "Отправить оценку" },
  "legacyOrder.later": { uz: "Keyinroq", ru: "Позже" },
  "legacyOrder.dispute.title": { uz: "Muammo haqida xabar berish", ru: "Сообщить о проблеме" },
  "legacyOrder.dispute.typeLabel": { uz: "Muammo turi", ru: "Тип проблемы" },
  "legacyOrder.dispute.driverNoShow": { uz: "Haydovchi kelmadi", ru: "Водитель не приехал" },
  "legacyOrder.dispute.parcelLate": { uz: "Posilka kechikdi", ru: "Посылка задержалась" },
  "legacyOrder.dispute.priceDisagreement": { uz: "Narx bo'yicha kelishmovchilik", ru: "Разногласие по цене" },
  "legacyOrder.dispute.opened": {
    uz: "Nizo ochildi. Operatorlar muammoni ko'rib chiqadi",
    ru: "Спор открыт. Операторы рассмотрят проблему",
  },

  // --- notifications ---
  "notifications.title": { uz: "Bildirishnomalar", ru: "Уведомления" },
  "notifications.empty": { uz: "Hozircha bildirishnomalar yo'q", ru: "Уведомлений пока нет" },

  // --- client-profile ---
  "clientProfile.title": { uz: "Profil", ru: "Профиль" },
  "clientProfile.accountBadge": { uz: "Mijoz akkaunti", ru: "Аккаунт клиента" },
  "clientProfile.statActive": { uz: "Faol", ru: "Активные" },
  "clientProfile.statBids": { uz: "Taklif", ru: "Предложения" },
  "clientProfile.ordersTitle": { uz: "Buyurtmalar holati", ru: "Статус заказов" },
  "clientProfile.latestOrder": { uz: "So'nggi buyurtma", ru: "Последний заказ" },
  "clientProfile.personalTitle": { uz: "Shaxsiy ma'lumotlar", ru: "Личные данные" },
  "clientProfile.fullName": { uz: "Ism familiya", ru: "Имя и фамилия" },
  "clientProfile.fullNamePlaceholder": { uz: "Masalan: Ali Valiyev", ru: "Например: Али Валиев" },
  "clientProfile.updated": { uz: "Profil yangilandi", ru: "Профиль обновлён" },
  "clientProfile.quickActions": { uz: "Tezkor amallar", ru: "Быстрые действия" },
  "clientProfile.myOrders": { uz: "Buyurtmalarim", ru: "Мои заказы" },
  "clientProfile.myOrdersHint": { uz: "Yaratilgan buyurtmalar va holatlarni ko'rish", ru: "Созданные заказы и их статусы" },
  "clientProfile.myProposals": { uz: "Takliflarim", ru: "Мои предложения" },
  "clientProfile.myProposalsHint": {
    uz: "Haydovchi e'lonlariga yuborgan narx takliflaringiz",
    ru: "Ценовые предложения, которые вы отправили на объявления водителей",
  },
  "clientProfile.bonus": { uz: "Bonuslar va taklif kodi", ru: "Бонусы и код приглашения" },
  "clientProfile.bonusHint": {
    uz: "Chegirma huquqlari, taklif kodingiz va kampaniyalar",
    ru: "Права на скидку, ваш код приглашения и кампании",
  },
  "clientProfile.notificationsHint": { uz: "Takliflar va buyurtma yangiliklari", ru: "Предложения и новости по заказам" },
  "clientProfile.myDisputes": { uz: "Nizolarim", ru: "Мои споры" },
  "clientProfile.myDisputesHint": {
    uz: "Ochilgan nizolar, ularning holati va dalillar",
    ru: "Открытые споры, их статус и доказательства",
  },
  "clientProfile.help": { uz: "Yordam", ru: "Помощь" },
  "clientProfile.helpHint": { uz: "Savollar va operatorga murojaat", ru: "Вопросы и обращение к оператору" },
  "clientProfile.settings": { uz: "Sozlamalar", ru: "Настройки" },
  "clientProfile.settingsHint": { uz: "Ko'rinish, maxfiylik va akkaunt", ru: "Оформление, конфиденциальность и аккаунт" },
  "clientProfile.home": { uz: "Bosh sahifa", ru: "Главная" },
  "clientProfile.homeHint": { uz: "Yangi buyurtma yaratish oynasiga qaytish", ru: "Вернуться к созданию нового заказа" },
  "clientProfile.logout": { uz: "Chiqish", ru: "Выйти" },
  "clientProfile.logoutHint": { uz: "Akkauntdan xavfsiz chiqish", ru: "Безопасный выход из аккаунта" },

  // --- driver-home ---
  "driverHome.pendingReferral": {
    uz: "Taklif kodi saqlandi: {code} — tasdiqlash uchun bosing",
    ru: "Код приглашения сохранён: {code} — нажмите, чтобы подтвердить",
  },
  "driverHome.completeProfileTitle": { uz: "Profilni to'ldiring", ru: "Заполните профиль" },
  "driverHome.notificationsUnread": {
    uz: "Bildirishnomalar, {count} ta o'qilmagan",
    ru: "Уведомления, непрочитанных: {count}",
  },
  "driverHome.commissionBalance": { uz: "Komissiya balansi", ru: "Баланс комиссии" },
  "driverHome.verificationStatus": { uz: "Tasdiqlash holati: {status}", ru: "Статус проверки: {status}" },
  "driverHome.approvedHint": {
    uz: "Faol bo'lsangiz, yo'nalishingizga mos buyurtmalar ko'rinadi",
    ru: "Когда вы на линии, вам видны заказы по вашему направлению",
  },
  "driverHome.onboardingHint": {
    uz: "Buyurtmalarni ko'rish uchun avval profil va hujjatlaringizni yuboring.",
    ru: "Чтобы видеть заказы, сначала отправьте профиль и документы.",
  },
  "driverHome.availabilityTitle": { uz: "Faollik holati", ru: "Статус активности" },
  "driverHome.available": { uz: "Faolman", ru: "На линии" },
  "driverHome.availabilityLocked": {
    uz: "Tasdiqlanmaguncha faol bo'la olmaysiz",
    ru: "До подтверждения выйти на линию нельзя",
  },
  "driverHome.availabilityUpdated": { uz: "Faollik yangilandi", ru: "Статус активности обновлён" },
  "driverHome.completeProfile": { uz: "Profilni to'ldirish", ru: "Заполнить профиль" },
  "driverHome.uploadDocuments": { uz: "Hujjatlarni yuklash", ru: "Загрузить документы" },
  "driverHome.viewMatchingOrders": { uz: "Mos buyurtmalarni ko'rish", ru: "Посмотреть подходящие заказы" },
} as const satisfies Record<string, Message>;
