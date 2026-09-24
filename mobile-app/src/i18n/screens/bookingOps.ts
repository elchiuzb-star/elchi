/** Booking follow-up screens: rating, opening a dispute, amendments, saved directions, my disputes, listing edit, matches. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const bookingOpsMessages = {
  // --- booking-rating ---
  "bookingRating.bookingNotFound": { uz: "Bron topilmadi", ru: "Бронь не найдена" },
  "bookingRating.prompt": { uz: "1 dan 5 gacha baho bering", ru: "Поставьте оценку от 1 до 5" },
  "bookingRating.starsAria": { uz: "{value} yulduz", ru: "Звёзд: {value}" },
  "bookingRating.commentLabel": { uz: "Izoh qoldiring", ru: "Оставьте комментарий" },
  "bookingRating.moderationNote": {
    uz: "Izoh nashr etilishidan oldin tekshiriladi; aloqa ma'lumotlari yashiriladi.",
    ru: "Комментарий проверяется перед публикацией; контактные данные скрываются.",
  },
  "bookingRating.sent": { uz: "Baho yuborildi", ru: "Оценка отправлена" },
  "bookingRating.submit": { uz: "Bahoni yuborish", ru: "Отправить оценку" },
  "bookingRating.later": { uz: "Keyinroq", ru: "Позже" },

  // --- booking-dispute ---
  "bookingDispute.title": { uz: "Muammo haqida xabar berish", ru: "Сообщить о проблеме" },
  "bookingDispute.typeLabel": { uz: "Muammo turi", ru: "Тип проблемы" },
  "bookingDispute.typePlaceholder": { uz: "Turini tanlang", ru: "Выберите тип" },
  "bookingDispute.gpsEvidenceNote": {
    uz: "Nizo ochilganda safar GPS nuqtalari dalil sifatida saqlanadi (Q77).",
    ru: "При открытии спора GPS-точки поездки сохраняются как доказательство (Q77).",
  },
  "bookingDispute.opened": {
    uz: "Nizo ochildi. Operatorlar muammoni ko'rib chiqadi",
    ru: "Спор открыт. Операторы рассмотрят проблему",
  },

  // --- booking-amendment ---
  "amendment.title": { uz: "Shartlarni o'zgartirish", ru: "Изменение условий" },
  "amendment.currentTerms": { uz: "Hozirgi kelishuv", ru: "Текущая договорённость" },
  "amendment.takesEffectNote": {
    uz: "O'zgartirish ikkinchi tomon qabul qilgandan keyingina kuchga kiradi. Qabul qilinmaguncha bron shu shartlarda qoladi.",
    ru: "Изменение вступает в силу только после того, как его примет другая сторона. До этого бронь остаётся на прежних условиях.",
  },
  "amendment.proposeTitle": { uz: "Yangi shart taklif qilish", ru: "Предложить новые условия" },
  "amendment.seatsLabel": { uz: "O'rinlar soni", ru: "Количество мест" },
  "amendment.quantityLabel": { uz: "Miqdor", ru: "Количество" },
  "amendment.seatPriceLabel": { uz: "Bir o'rin narxi (so'm)", ru: "Цена за место (сум)" },
  "amendment.priceLabel": { uz: "Narx (so'm)", ru: "Цена (сум)" },
  "amendment.reasonPlaceholder": { uz: "Nega o'zgartirmoqchisiz?", ru: "Почему вы хотите изменить условия?" },
  "amendment.reasonHint": { uz: "Ikkinchi tomon shu izohni ko'radi.", ru: "Другая сторона увидит этот комментарий." },
  "amendment.newTotal": { uz: "Yangi jami: {total}", ru: "Новый итог: {total}" },
  "amendment.consentAsk": {
    uz: "Yangi hisob: bonus chegirmasi {discount}, haydovchiga naqd {cash}. Rozi bo'lsangiz, qayta yuboring.",
    ru: "Новый расчёт: бонусная скидка {discount}, наличными водителю {cash}. Если вы согласны, отправьте ещё раз.",
  },
  "amendment.driverAckAsk": {
    uz: "O'zgarishdan keyin: mijozdan naqd {cash}, balansingizdan yechiladi {commission}. Rozi bo'lsangiz, qayta yuboring.",
    ru: "После изменения: наличными с клиента {cash}, с вашего баланса будет списано {commission}. Если вы согласны, отправьте ещё раз.",
  },
  "amendment.sent": { uz: "Taklif yuborildi", ru: "Предложение отправлено" },
  "amendment.submitConsent": { uz: "Yangi naqd summaga roziman — yuborish", ru: "Согласен с новой суммой наличными — отправить" },
  "amendment.submitDriverAck": { uz: "Shu hisobga roziman — yuborish", ru: "Согласен с этим расчётом — отправить" },
  "amendment.submit": { uz: "Taklif yuborish", ru: "Отправить предложение" },
  "amendment.empty": { uz: "Hozircha o'zgartirish takliflari yo'q.", ru: "Предложений об изменении пока нет." },
  "amendment.mine": { uz: "Sizning taklifingiz", ru: "Ваше предложение" },
  "amendment.theirs": { uz: "Ikkinchi tomon taklifi", ru: "Предложение другой стороны" },
  "amendment.afterChangeTitle": { uz: "O'zgarishdan keyingi hisob", ru: "Расчёт после изменения" },
  "amendment.accepted": { uz: "Yangi shartlar kuchga kirdi", ru: "Новые условия вступили в силу" },
  "amendment.accept": { uz: "Qabul qilish", ru: "Принять" },
  "amendment.rejected": { uz: "Rad etildi", ru: "Отклонено" },
  "amendment.promoReconfirmed": { uz: "Bonus shartlari qayta tasdiqlandi", ru: "Условия бонуса подтверждены повторно" },
  "amendment.promoReconfirm": { uz: "Bonus shartlarini qayta tasdiqlash", ru: "Повторно подтвердить условия бонуса" },
  "amendment.withdrawn": { uz: "Taklif qaytarib olindi", ru: "Предложение отозвано" },
  "amendment.withdraw": { uz: "Taklifni qaytarib olish", ru: "Отозвать предложение" },

  // --- driver-saved-searches ---
  "savedSearches.title": { uz: "Saqlangan yo'nalishlar", ru: "Сохранённые направления" },
  "savedSearches.intro": {
    uz: "Yo'nalishni saqlasangiz, shu yo'nalishda yangi mijoz so'rovi chiqqanda bildirishnoma olasiz. Bildirishnomalar ilova ichida ko'rinadi.",
    ru: "Сохраните направление — и вы получите уведомление, когда на нём появится новый запрос клиента. Уведомления отображаются внутри приложения.",
  },
  "savedSearches.currentDirection": { uz: "Hozirgi yo'nalish", ru: "Текущее направление" },
  "savedSearches.saved": { uz: "Yo'nalish saqlandi", ru: "Направление сохранено" },
  "savedSearches.save": { uz: "Shu yo'nalishni saqlash", ru: "Сохранить это направление" },
  "savedSearches.pickEndsFirst": {
    uz: "Avval «Moslar» sahifasida ikkala uchni tanlang.",
    ru: "Сначала выберите обе точки на странице «Подходящие».",
  },
  "savedSearches.notifyOn": { uz: "bildirishnoma yoqilgan", ru: "уведомления включены" },
  "savedSearches.notifyOff": { uz: "bildirishnoma o'chirilgan", ru: "уведомления выключены" },
  "savedSearches.deleted": { uz: "O'chirildi", ru: "Удалено" },
  "savedSearches.emptyTitle": { uz: "Saqlangan yo'nalish yo'q", ru: "Нет сохранённых направлений" },
  "savedSearches.emptySubtitle": {
    uz: "Tez-tez yuradigan yo'nalishingizni saqlab qo'ying — yangi so'rovlardan xabar topasiz.",
    ru: "Сохраните направление, по которому часто ездите, — и вы узнаете о новых запросах.",
  },

  // --- my-disputes / dispute-detail ---
  "disputes.title": { uz: "Nizolarim", ru: "Мои споры" },
  "disputes.evidence": { uz: "Dalillar", ru: "Доказательства" },
  "disputes.fileAttached": { uz: "Fayl biriktirildi", ru: "Файл прикреплён" },
  "disputes.filesAttached": { uz: "{count} ta fayl biriktirildi", ru: "Прикреплено файлов: {count}" },
  "disputes.decisionPrefix": { uz: "Qaror:", ru: "Решение:" },
  "disputes.addEvidence": { uz: "Dalil qo'shish", ru: "Добавить доказательство" },
  "disputes.extraNoteLabel": { uz: "Qo'shimcha izoh", ru: "Дополнительный комментарий" },
  "disputes.contactsHiddenHint": {
    uz: "Telefon raqam va havolalar avtomatik yashiriladi.",
    ru: "Номера телефонов и ссылки скрываются автоматически.",
  },
  "disputes.evidenceAdded": { uz: "Dalil qo'shildi", ru: "Доказательство добавлено" },
  "disputes.emptyTitle": { uz: "Nizo yo'q", ru: "Споров нет" },
  "disputes.emptySubtitle": {
    uz: "Buyurtmada muammo bo'lsa, bron ekranidan «Muammo haqida xabar berish» tugmasi orqali ochasiz.",
    ru: "Если с заказом возникла проблема, откройте спор на экране брони кнопкой «Сообщить о проблеме».",
  },

  // --- listing-edit ---
  "listingEdit.perSeatSuffix": { uz: " / o'rin", ru: " / место" },

  // --- listing-matches ---
  "matches.completedCount": { uz: "{count} ta bajarilgan buyurtma", ru: "Выполненных заказов: {count}" },
  "matches.rating": { uz: "reyting {rating}", ru: "рейтинг {rating}" },
  "matches.notRated": { uz: "hali baholanmagan", ru: "ещё без оценок" },
  "matches.makeOffer": { uz: "Narx taklif qilish", ru: "Предложить цену" },
  "matches.titleTrips": { uz: "Mos safarlar", ru: "Подходящие поездки" },
  "matches.titleRequests": { uz: "Mos so'rovlar", ru: "Подходящие запросы" },
  "matches.introTrips": {
    uz: "E'loningizdagi yo'nalish, vaqt va miqdor bo'yicha mos safarlar. Tartib — tavsiya, tanlov sizniki.",
    ru: "Поездки, подходящие по направлению, времени и количеству из вашего объявления. Порядок — рекомендация, выбор за вами.",
  },
  "matches.introRequests": {
    uz: "Safaringizga mos mijoz so'rovlari. Tartib — tavsiya, tanlov sizniki.",
    ru: "Запросы клиентов, подходящие к вашей поездке. Порядок — рекомендация, выбор за вами.",
  },
  "matches.emptyTrips": { uz: "Hozircha mos safar yo'q", ru: "Подходящих поездок пока нет" },
  "matches.emptyRequests": { uz: "Hozircha mos so'rov yo'q", ru: "Подходящих запросов пока нет" },
  "matches.emptyTripsSubtitle": {
    uz: "Haydovchilar safar e'lon qilgach shu yerda ko'rinadi. E'loningiz o'z holicha ham haydovchilarga ko'rinib turadi.",
    ru: "Поездки появятся здесь, когда водители их опубликуют. Ваше объявление и так остаётся видимым для водителей.",
  },
  "matches.emptyRequestsSubtitle": {
    uz: "Mijozlar so'rov qo'ygach shu yerda ko'rinadi.",
    ru: "Запросы появятся здесь, когда клиенты их разместят.",
  },
} as const satisfies Record<string, Message>;
