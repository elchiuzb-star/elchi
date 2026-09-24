/** Driver work screens (feed, orders, bid, booking, commission balance, profile) and the shell's map sheet and confirm dialogs. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const driverWorkMessages = {
  // --- driver-feed ---
  "driverFeed.title": { uz: "Mos buyurtmalar", ru: "Подходящие заказы" },
  "driverFeed.sendOffer": { uz: "Taklif yuborish", ru: "Отправить предложение" },
  "driverFeed.modeTaxi": { uz: "Taksi", ru: "Такси" },
  "driverFeed.modeParcel": { uz: "Pochta", ru: "Посылки" },
  "driverFeed.from": { uz: "Qayerdan?", ru: "Откуда?" },
  "driverFeed.to": { uz: "Qayerga?", ru: "Куда?" },
  "driverFeed.districtHint": {
    uz: "Tuman tanlansa, shu tumandagi barcha tasdiqlangan bekatlarning e'lonlari ko'rinadi.",
    ru: "Если выбрать район, будут видны объявления со всех подтверждённых остановок этого района.",
  },
  "driverFeed.savedSearches": { uz: "Saqlangan yo'nalishlar", ru: "Сохранённые направления" },
  "driverFeed.emptyTitle": { uz: "Hozircha mos buyurtmalar yo'q", ru: "Подходящих заказов пока нет" },
  "driverFeed.emptyTryOther": {
    uz: "Boshqa yo'nalish yoki sanani tanlab ko'ring",
    ru: "Попробуйте выбрать другое направление или дату",
  },
  "driverFeed.emptyPickFirst": {
    uz: "Avval qayerdan va qayerga ekanini tanlang",
    ru: "Сначала выберите, откуда и куда",
  },

  // --- driver-orders ---
  "driverOrders.title": { uz: "Buyurtmalar tarixi", ru: "История заказов" },
  "driverOrders.empty": { uz: "Buyurtmalar tarixi bo'sh", ru: "История заказов пуста" },

  // --- driver-bid ---
  "driverBid.title": { uz: "Narx taklif qiling", ru: "Предложите цену" },
  "driverBid.clientPrice": { uz: "Mijoz narxi: {price}", ru: "Цена клиента: {price}" },
  "driverBid.departure": { uz: "Jo'nash: {start} - {end}", ru: "Отправление: {start} - {end}" },
  "driverBid.trip": { uz: "Safar", ru: "Поездка" },
  "driverBid.tripPlaceholder": { uz: "Safarni tanlang", ru: "Выберите поездку" },
  "driverBid.noPlannedTrips": { uz: "Rejalashtirilgan safar yo'q", ru: "Нет запланированных поездок" },
  "driverBid.planTripFirst": {
    uz: "Taklif yuborish uchun avval \"Yo'nalishlar\" bo'limida safar rejalashtiring.",
    ru: "Чтобы отправить предложение, сначала запланируйте поездку в разделе «Направления».",
  },
  "driverBid.tripWindowMismatch": {
    uz: "Bu safar mijoz so'ragan vaqtga to'g'ri kelmaydi — boshqa safarni tanlang yoki yangi safar rejalashtiring.",
    ru: "Эта поездка не совпадает со временем, которое указал клиент, — выберите другую поездку или запланируйте новую.",
  },
  "driverBid.pickupWindow": { uz: "Olib ketish vaqti", ru: "Время посадки" },
  "driverBid.priceLabel": { uz: "Taklif narxi", ru: "Цена предложения" },
  "driverBid.pricePlaceholder": { uz: "Masalan: 200000", ru: "Например: 200000" },
  "driverBid.noHoldNote": {
    uz: "Taklif o'rin yoki balansni band qilmaydi — mijoz qabul qilganda bron yaratiladi.",
    ru: "Предложение не занимает места и не блокирует баланс — бронь создаётся, когда клиент его примет.",
  },
  "driverBid.sent": { uz: "Taklif yuborildi", ru: "Предложение отправлено" },
  "driverBid.send": { uz: "Taklif yuborish", ru: "Отправить предложение" },

  // --- driver-order-detail ---
  "driverBooking.title": { uz: "Buyurtma tafsilotlari", ru: "Детали заказа" },
  "driverBooking.action.arrive": { uz: "Yetib keldim deb belgilash", ru: "Отметить: я на месте" },
  "driverBooking.action.pickUp": { uz: "Olib ketildi deb belgilash", ru: "Отметить: забрал" },
  "driverBooking.action.startTransit": { uz: "Yo'lga chiqdi deb belgilash", ru: "Отметить: в пути" },
  "driverBooking.action.deliver": { uz: "Yetkazildi deb belgilash", ru: "Отметить: доставлено" },
  "driverBooking.pickupStop": { uz: "Olib ketish bekati", ru: "Остановка посадки" },
  "driverBooking.pickupPoint": { uz: "Olib ketish joyi", ru: "Место посадки" },
  "driverBooking.dropoffStop": { uz: "Yetkazish bekati", ru: "Остановка высадки" },
  "driverBooking.dropoffPoint": { uz: "Yetkazish joyi", ru: "Место высадки" },
  "driverBooking.clientHidden": { uz: "Tanlangandan keyin ko'rinadi", ru: "Будет видно после выбора" },
  "driverBooking.phone": { uz: "Telefon", ru: "Телефон" },
  "driverBooking.phoneHidden": { uz: "Xizmat boshlanganda ochiladi", ru: "Откроется, когда начнётся поездка" },
  "driverBooking.fare": { uz: "Yo'lkira", ru: "Плата за проезд" },
  "driverBooking.fareCash": {
    uz: "{amount} — mijozdan naqd olinadi",
    ru: "{amount} — клиент платит вам наличными",
  },
  "driverBooking.parcelPhoto": { uz: "Posilka rasmi", ru: "Фото посылки" },
  "driverBooking.handoverCode": { uz: "Topshirish kodi", ru: "Код передачи" },
  "driverBooking.deliveryCode": { uz: "Yetkazish kodi", ru: "Код доставки" },
  "driverBooking.codePlaceholder": { uz: "6 xonali kod", ru: "6-значный код" },
  "driverBooking.codeFromSender": { uz: "Kodni jo'natuvchidan oling.", ru: "Получите код у отправителя." },
  "driverBooking.codeFromRecipient": {
    uz: "Kodni faqat qabul qiluvchidan oling — jo'natuvchidan emas.",
    ru: "Получите код только у получателя — не у отправителя.",
  },
  "driverBooking.cashRecorded": { uz: "Qayd saqlandi", ru: "Отметка сохранена" },
  "driverBooking.cashAnswered": { uz: "Javob saqlandi", ru: "Ответ сохранён" },
  "driverBooking.messages": { uz: "Xabarlar", ru: "Сообщения" },
  "driverBooking.tracking": { uz: "Kuzatuv", ru: "Отслеживание" },
  "driverBooking.amend": { uz: "Shartlarni o'zgartirish", ru: "Изменить условия" },
  "driverBooking.reportProblem": { uz: "Muammo haqida xabar berish", ru: "Сообщить о проблеме" },
  "driverBooking.statusUpdated": { uz: "Status yangilandi", ru: "Статус обновлён" },

  // --- driver-income (commission balance, not earnings) ---
  "income.title": { uz: "Komissiya balansi", ru: "Баланс комиссии" },
  "income.available": { uz: "Ishlatish mumkin", ru: "Доступно" },
  "income.balanceNote": {
    uz: "ELCHI komissiyalarini to'lash uchun balans. Yo'lkira bu yerda hisoblanmaydi — uni mijoz haydovchiga naqd to'laydi.",
    ru: "Баланс для оплаты комиссий ELCHI. Плата за проезд здесь не учитывается — клиент платит её водителю наличными.",
  },
  "income.held": { uz: "Ushlab qolingan komissiya", ru: "Заблокированная комиссия" },
  "income.reversed": { uz: "Qaytarilgan komissiya", ru: "Возвращённая комиссия" },
  "income.topups": { uz: "To'ldirishlar", ru: "Пополнения" },
  "income.pendingTopups": { uz: "Tasdiqlanmagan so'rov", ru: "Неподтверждённые заявки" },
  "income.capturedTitle": { uz: "Ushlangan komissiya", ru: "Списанная комиссия" },
  "income.period.daily": { uz: "7 kun", ru: "7 дней" },
  "income.period.monthly": { uz: "6 oy", ru: "6 месяцев" },
  "income.chartEmpty": { uz: "Hali komissiya ushlanmagan", ru: "Комиссия ещё не списывалась" },
  "income.chartNote": {
    uz: "Bu ELCHI olgan komissiya. Yo'lkira mijozdan sizga naqd o'tadi va bu yerda ko'rinmaydi.",
    ru: "Это комиссия, которую получил ELCHI. Плата за проезд переходит от клиента к вам наличными и здесь не отображается.",
  },
  "income.topupTitle": { uz: "Balansni to'ldirish", ru: "Пополнение баланса" },
  "income.topupNote": {
    uz: "So'rov moliya xodimi tasdiqlagandan keyin balansga qo'shiladi.",
    ru: "Сумма будет зачислена на баланс после подтверждения заявки финансовым сотрудником.",
  },
  "income.amountLabel": { uz: "Summa (so'm)", ru: "Сумма (сум)" },
  "income.topupSent": { uz: "To'ldirish so'rovi yuborildi", ru: "Заявка на пополнение отправлена" },
  "income.topupSend": { uz: "So'rov yuborish", ru: "Отправить заявку" },
  "income.requestsTitle": { uz: "To'ldirish so'rovlari", ru: "Заявки на пополнение" },
  "income.requestsEmpty": { uz: "So'rov yo'q", ru: "Заявок нет" },
  "income.requestsEmptyHint": {
    uz: "Balansni to'ldirish so'rovlari shu yerda ko'rinadi.",
    ru: "Здесь будут отображаться заявки на пополнение баланса.",
  },

  // --- driver-profile ---
  "driverProfile.title": { uz: "Profil", ru: "Профиль" },
  "driverProfile.noVehicle": { uz: "Avtomobil ma'lumoti kiritilmagan", ru: "Данные автомобиля не указаны" },
  "driverProfile.statusNew": { uz: "Yangi", ru: "Новый" },
  "driverProfile.active": { uz: "Faol", ru: "Активен" },
  "driverProfile.inactive": { uz: "Faol emas", ru: "Неактивен" },
  "driverProfile.rating": { uz: "Reyting", ru: "Рейтинг" },
  "driverProfile.completed": { uz: "Bajarilgan", ru: "Выполнено" },
  "driverProfile.availabilityTitle": { uz: "Faollik holati", ru: "Статус активности" },
  "driverProfile.availabilityOn": { uz: "Buyurtma qabul qilishga tayyor", ru: "Готов принимать заказы" },
  "driverProfile.availabilityOff": { uz: "Vaqtincha faol emas", ru: "Временно неактивен" },
  "driverProfile.availabilityNeedsApproval": { uz: "Avval admin tasdiqlashi kerak", ru: "Сначала нужно подтверждение администратора" },
  "driverProfile.availabilityUpdated": { uz: "Faollik yangilandi", ru: "Статус активности обновлён" },
  "driverProfile.vehicle": { uz: "Avtomobil", ru: "Автомобиль" },
  "driverProfile.status": { uz: "Holat", ru: "Статус" },
  "driverProfile.routes": { uz: "Yo'nalish", ru: "Направления" },
  "driverProfile.quickActions": { uz: "Tezkor amallar", ru: "Быстрые действия" },
  "driverProfile.action.edit": { uz: "Profilni tahrirlash", ru: "Редактировать профиль" },
  "driverProfile.action.editHint": {
    uz: "Ism, avtomobil va davlat raqamini yangilash",
    ru: "Обновить имя, автомобиль и госномер",
  },
  "driverProfile.action.documents": { uz: "Hujjatlar", ru: "Документы" },
  "driverProfile.action.documentsHint": {
    uz: "Pasport, guvohnoma va avtomobil hujjatlari",
    ru: "Паспорт, водительское удостоверение и документы на автомобиль",
  },
  "driverProfile.action.routes": { uz: "Yo'nalishlarim", ru: "Мои направления" },
  "driverProfile.action.routesHint": {
    uz: "Qaysi yo'nalishlarda ishlashingizni boshqarish",
    ru: "Управление направлениями, на которых вы работаете",
  },
  "driverProfile.action.proposals": { uz: "Takliflarim", ru: "Мои предложения" },
  "driverProfile.action.proposalsHint": {
    uz: "Yuborilgan takliflar va mijozning javoblari",
    ru: "Отправленные предложения и ответы клиентов",
  },
  "driverProfile.action.bonus": { uz: "Kredit va taklif kodi", ru: "Кредит и код приглашения" },
  "driverProfile.action.bonusHint": {
    uz: "Komissiya krediti, taklif kodingiz va kampaniyalar",
    ru: "Кредит на комиссию, ваш код приглашения и кампании",
  },
  "driverProfile.action.orders": { uz: "Buyurtmalarim", ru: "Мои заказы" },
  "driverProfile.action.ordersHint": { uz: "Qabul qilingan buyurtmalar tarixi", ru: "История принятых заказов" },
  "driverProfile.action.disputes": { uz: "Nizolarim", ru: "Мои споры" },
  "driverProfile.action.disputesHint": {
    uz: "Ochilgan nizolar, ularning holati va dalillar",
    ru: "Открытые споры, их статус и доказательства",
  },
  "driverProfile.action.support": { uz: "Yordam", ru: "Помощь" },
  "driverProfile.action.supportHint": { uz: "Savollar va operatorga murojaat", ru: "Вопросы и обращение к оператору" },
  "driverProfile.action.settings": { uz: "Sozlamalar", ru: "Настройки" },
  "driverProfile.action.settingsHint": { uz: "Ko'rinish, maxfiylik va akkaunt", ru: "Оформление, конфиденциальность и аккаунт" },
  "driverProfile.action.home": { uz: "Bosh sahifa", ru: "Главная" },
  "driverProfile.action.homeHint": {
    uz: "Balans va mos buyurtmalar oynasiga qaytish",
    ru: "Вернуться к балансу и подходящим заказам",
  },
  "driverProfile.action.logout": { uz: "Chiqish", ru: "Выйти" },
  "driverProfile.action.logoutHint": { uz: "Akkauntdan xavfsiz chiqish", ru: "Безопасный выход из аккаунта" },
  "driverProfile.notFound": { uz: "Ma'lumot topilmadi", ru: "Данные не найдены" },

  // --- shell: read-only map sheet ---
  "mapSheet.title": { uz: "Xarita nuqtalari", ru: "Точки на карте" },
  "mapSheet.openPickup": { uz: "Olib ketish joyini Yandex Xaritada ochish", ru: "Открыть место посадки в Яндекс Картах" },
  "mapSheet.open": { uz: "Yandex Xaritada ochish", ru: "Открыть в Яндекс Картах" },

  // --- shell: confirm dialogs ---
  "confirmDialog.back": { uz: "Ortga", ru: "Назад" },
  "confirmDialog.intentEdit.title": { uz: "Ochiq takliflar yopiladi", ru: "Открытые предложения будут закрыты" },
  "confirmDialog.intentEdit.saved": { uz: "Talab yangilandi", ru: "Запрос обновлён" },
  "confirmDialog.selectDriver.title": { uz: "Haydovchini tanlaysizmi?", ru: "Выбрать этого водителя?" },
  "confirmDialog.selectDriver.text": {
    uz: "Tanlaganingizdan keyin boshqa takliflar yopiladi.",
    ru: "После выбора остальные предложения будут закрыты.",
  },
  "confirmDialog.selectDriver.confirm": { uz: "Tanlash", ru: "Выбрать" },
  "confirmDialog.confirmDelivery.title": { uz: "Posilka yetib keldimi?", ru: "Посылка доставлена?" },
  "confirmDialog.confirmDelivery.text": {
    uz: "Tasdiqlaganingizdan keyin buyurtma yakunlanadi.",
    ru: "После подтверждения заказ будет завершён.",
  },
  "confirmDialog.cancelOrder.title": { uz: "Buyurtmani bekor qilasizmi?", ru: "Отменить заказ?" },
  "confirmDialog.cancelOrder.acceptedText": {
    uz: "Haydovchi tanlangan. Buyurtmani bekor qilmoqchimisiz?",
    ru: "Водитель уже выбран. Вы хотите отменить заказ?",
  },
  "confirmDialog.cancelOrder.text": { uz: "Bu amalni ortga qaytarib bo'lmaydi.", ru: "Это действие нельзя отменить." },
  "confirmDialog.cancelOrder.done": { uz: "Buyurtma bekor qilindi", ru: "Заказ отменён" },
} as const satisfies Record<string, Message>;
