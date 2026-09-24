/** Client order flow: route summary, order form steps, review, success, orders list/detail, booking detail, proposals. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const orderFlowMessages = {
  // --- client-route-summary ---
  "routeSummary.direction": { uz: "Yo'nalish", ru: "Направление" },
  "routeSummary.pickup": { uz: "Olib ketish", ru: "Откуда" },
  "routeSummary.dropoff": { uz: "Yetkazish", ru: "Куда" },
  "routeSummary.estimatedRoute": { uz: "Taxminiy yo'l", ru: "Примерный путь" },
  "routeSummary.driverProposesTimeLine1": { uz: "Haydovchi jo'nash", ru: "Время отправления" },
  "routeSummary.driverProposesTimeLine2": { uz: "vaqtini o'zi taklif qiladi", ru: "предложит водитель" },
  "routeSummary.mapNote": { uz: "Tasdiqlangan yo'nalish va uning bekatlari.", ru: "Подтверждённое направление и его остановки." },
  "routeSummary.districtsTitle": { uz: "Yo'nalishdagi tumanlar", ru: "Районы по пути" },
  "routeSummary.districtsHint": {
    uz: "Shu tumanlardagi haydovchilar ham e'loningizni tavsiya sifatida ko'radi.",
    ru: "Водители из этих районов тоже увидят ваше объявление в рекомендациях.",
  },
  "routeSummary.windowHint": {
    uz: "Haydovchilar shu oraliqda jo'nashni taklif qiladi.",
    ru: "Водители предложат время отправления в этом промежутке.",
  },
  "routeSummary.pricePerPerson": { uz: "Bir kishi uchun narx (so'm)", ru: "Цена за одного человека (сум)" },
  "routeSummary.driversSendOffers": { uz: "Haydovchilar o'z taklifini yuboradi.", ru: "Водители пришлют свои предложения." },
  "routeSummary.updateRequest": { uz: "Talabni yangilash", ru: "Обновить запрос" },
  "routeSummary.seeDriverOffers": { uz: "Haydovchi e'lonlarini ko'rish", ru: "Смотреть объявления водителей" },

  // --- client-order-address / parcel / photo ---
  "orderForm.contactTitle": { uz: "Aloqa ma'lumotlari", ru: "Контактные данные" },
  "orderForm.senderName": { uz: "Yuboruvchi ismi", ru: "Имя отправителя" },
  "orderForm.senderPhone": { uz: "Yuboruvchi telefon raqami", ru: "Телефон отправителя" },
  "orderForm.receiverName": { uz: "Qabul qiluvchi ismi", ru: "Имя получателя" },
  "orderForm.receiverPhone": { uz: "Qabul qiluvchi telefon raqami", ru: "Телефон получателя" },
  "orderForm.phonesHidden": {
    uz: "Telefon raqamlar taklif qabul qilinmaguncha haydovchiga ko'rsatilmaydi.",
    ru: "Водитель не увидит номера телефонов, пока предложение не принято.",
  },
  "orderForm.parcelTitle": { uz: "Posilka ma'lumotlari", ru: "Данные посылки" },
  "orderForm.parcelType": { uz: "Posilka turi", ru: "Тип посылки" },
  "orderForm.weight": { uz: "Og'irligi (kg)", ru: "Вес (кг)" },
  "orderForm.length": { uz: "Uzunligi (sm)", ru: "Длина (см)" },
  "orderForm.width": { uz: "Eni (sm)", ru: "Ширина (см)" },
  "orderForm.height": { uz: "Balandligi (sm)", ru: "Высота (см)" },
  "orderForm.sizeHint": {
    uz: "O'lcham va og'irlik haydovchi mashinasiga sig'ishini tekshirish uchun kerak.",
    ru: "Размеры и вес нужны, чтобы проверить, поместится ли посылка в машину водителя.",
  },
  "orderForm.photoTitle": { uz: "Posilka rasmi", ru: "Фото посылки" },
  "orderForm.uploadPhoto": { uz: "Rasm yuklash", ru: "Загрузить фото" },
  "orderForm.uploadPhotoHint": {
    uz: "Posilkani haydovchi ko'rishi uchun bitta rasm yuklang",
    ru: "Загрузите одно фото, чтобы водитель увидел посылку",
  },
  "orderForm.photoUploaded": { uz: "Rasm yuklandi", ru: "Фото загружено" },
  "orderForm.photoAlt": { uz: "Yuklangan posilka rasmi", ru: "Загруженное фото посылки" },
  "orderForm.photoReady": { uz: "Rasm tayyor", ru: "Фото готово" },
  "orderForm.photoRequired": { uz: "Posilka rasmini yuklang", ru: "Загрузите фото посылки" },
  "orderForm.reviewOrder": { uz: "Buyurtmani ko'rib chiqish", ru: "Проверить заказ" },

  // --- client-order-review ---
  "orderForm.review.title": { uz: "Buyurtmani tekshiring", ru: "Проверьте заказ" },
  "orderForm.review.verifiedStop": { uz: "Tasdiqlangan bekat · {where}", ru: "Подтверждённая остановка · {where}" },
  "orderForm.review.pickupPlace": { uz: "Olib ketish joyi", ru: "Место отправления" },
  "orderForm.review.dropoffPlace": { uz: "Yetkazish joyi", ru: "Место назначения" },
  "orderForm.review.districtsDetail": {
    uz: "Shu tumanlardagi haydovchilar ham ko'radi",
    ru: "Водители из этих районов тоже увидят",
  },
  "orderForm.review.window": { uz: "Jo'nash oynasi", ru: "Окно отправления" },
  "orderForm.review.perPersonDetail": { uz: "{count} × {price} (bir kishi uchun)", ru: "{count} × {price} (за одного человека)" },
  "orderForm.review.driversSendOffers": { uz: "Haydovchilar o'z taklifini yuboradi", ru: "Водители пришлют свои предложения" },
  "orderForm.review.passengers": { uz: "Yo'lovchilar", ru: "Пассажиры" },
  "orderForm.review.peopleCount": { uz: "{count} kishi", ru: "{count} чел." },
  "orderForm.review.seatNegotiated": { uz: "O'rin haydovchi bilan kelishiladi", ru: "Место согласуется с водителем" },
  "orderForm.review.parcel": { uz: "Posilka", ru: "Посылка" },
  "orderForm.review.parcelWeight": { uz: "{type}, {weight} kg", ru: "{type}, {weight} кг" },
  "orderForm.review.parcelSize": { uz: "{length} x {width} x {height} sm", ru: "{length} x {width} x {height} см" },
  "orderForm.review.sender": { uz: "Yuboruvchi", ru: "Отправитель" },
  "orderForm.review.receiver": { uz: "Qabul qiluvchi", ru: "Получатель" },
  "orderForm.review.noPhone": { uz: "Telefon kiritilmagan", ru: "Телефон не указан" },
  "orderForm.review.uploaded": { uz: "Yuklangan", ru: "Загружено" },
  "orderForm.review.incompletePassenger": {
    uz: "E'lon qilish uchun yo'nalish, vaqt va narx to'liq bo'lishi kerak.",
    ru: "Чтобы опубликовать, укажите направление, время и цену.",
  },
  "orderForm.review.incompleteParcel": {
    uz: "E'lon qilish uchun yo'nalish, telefonlar va posilka rasmi to'liq bo'lishi kerak.",
    ru: "Чтобы опубликовать, укажите направление, телефоны и добавьте фото посылки.",
  },
  "orderForm.review.publish": { uz: "Buyurtmani e'lon qilish", ru: "Опубликовать заказ" },

  // --- client-success ---
  "orderForm.success.title": { uz: "Buyurtma e'lon qilindi", ru: "Заказ опубликован" },
  "orderForm.success.waiting": { uz: "Haydovchilardan takliflar kutilmoqda", ru: "Ждём предложений от водителей" },
  "orderForm.success.notify": { uz: "Taklif kelganda sizga xabar beramiz", ru: "Мы сообщим вам, когда придёт предложение" },
  "orderForm.success.contactsHidden": {
    uz: "Izohdagi aloqa ma'lumotlari yashirildi",
    ru: "Контактные данные в комментарии скрыты",
  },
  "orderForm.success.toOrders": { uz: "Buyurtmalarimga o'tish", ru: "Перейти к моим заказам" },

  // --- client-orders / client-order-detail ---
  "orders.title": { uz: "Buyurtmalar", ru: "Заказы" },
  "orders.empty": { uz: "Hozircha buyurtmalar yo'q", ru: "Заказов пока нет" },
  "orders.legacy": { uz: "Eski buyurtmalar", ru: "Старые заказы" },
  "orders.detailTitle": { uz: "Buyurtma tafsilotlari", ru: "Детали заказа" },
  "orders.mapPoints": { uz: "Xarita nuqtalari", ru: "Точки на карте" },
  "orders.pickupMarked": { uz: "Olib ketish joyi belgilangan", ru: "Место отправления отмечено" },
  "orders.pickupNotMarked": { uz: "Olib ketish joyi belgilanmagan", ru: "Место отправления не отмечено" },
  "orders.dropoffMarked": { uz: "Yetkazish joyi belgilangan", ru: "Место назначения отмечено" },
  "orders.dropoffNotMarked": { uz: "Yetkazish joyi belgilanmagan", ru: "Место назначения не отмечено" },
  "orders.viewOnMap": { uz: "Xaritada ko'rish", ru: "Показать на карте" },
  "orders.noBids": { uz: "Hozircha takliflar yo'q", ru: "Предложений пока нет" },
  "orders.noBidsHint": {
    uz: "Haydovchilar taklif yuborishi bilan shu yerda ko'rasiz",
    ru: "Предложения водителей появятся здесь, как только они их отправят",
  },
  "orders.confirmDelivered": { uz: "Yetkazilganini tasdiqlash", ru: "Подтвердить доставку" },
  "orders.viewBids": { uz: "Takliflarni ko'rish", ru: "Посмотреть предложения" },
  "orders.cancel": { uz: "Buyurtmani bekor qilish", ru: "Отменить заказ" },
  "orders.reportProblem": { uz: "Muammo haqida xabar berish", ru: "Сообщить о проблеме" },

  // --- client-booking-detail ---
  "bookingDetail.fare": { uz: "Yo'lkira", ru: "Плата за проезд" },
  "bookingDetail.fareCash": { uz: "{amount} — haydovchiga naqd to'lanadi", ru: "{amount} — оплачивается водителю наличными" },
  "bookingDetail.fareNote": {
    uz: "To'lov ilova orqali o'tmaydi; ELCHI bu summani qabul qilmaydi.",
    ru: "Оплата не проходит через приложение; ELCHI эту сумму не получает.",
  },
  "bookingDetail.cashRecorded": { uz: "Qayd saqlandi", ru: "Отметка сохранена" },
  "bookingDetail.answerSaved": { uz: "Javob saqlandi", ru: "Ответ сохранён" },
  "bookingDetail.messages": { uz: "Xabarlar", ru: "Сообщения" },
  "bookingDetail.tracking": { uz: "Kuzatuv", ru: "Отслеживание" },
  "bookingDetail.changeTerms": { uz: "Shartlarni o'zgartirish", ru: "Изменить условия" },
  "bookingDetail.completed": { uz: "Buyurtma yakunlandi", ru: "Заказ завершён" },

  // --- driver-proposals / client-proposals ---
  "proposals.title": { uz: "Takliflarim", ru: "Мои предложения" },
  "proposals.closed": { uz: "Yopilgan ({status}) — javob berib bo'lmaydi.", ru: "Закрыто ({status}) — ответить нельзя." },
  "proposals.newPrice": { uz: "Yangi narx (so'm)", ru: "Новая цена (сум)" },
  "proposals.counterSent": { uz: "Qarshi taklif yuborildi", ru: "Встречное предложение отправлено" },
  "proposals.ifYouAccept": { uz: "Qabul qilsangiz", ru: "Если вы примете" },
  "proposals.acceptDriverPrice": { uz: "Haydovchi narxini qabul qilish", ru: "Принять цену водителя" },
  "proposals.acceptClientPrice": { uz: "Mijoz narxini qabul qilish", ru: "Принять цену клиента" },
  "proposals.counterAnother": {
    uz: "Boshqa narx taklif qilish ({count} marta qoldi)",
    ru: "Предложить другую цену (осталось попыток: {count})",
  },
  "proposals.noRevisionsLeft": { uz: "Narxni o'zgartirish imkoni tugadi.", ru: "Возможность изменить цену исчерпана." },
  "proposals.withdraw": { uz: "Taklifni qaytarib olish", ru: "Отозвать предложение" },
  "proposals.empty": { uz: "Taklif yubormagansiz", ru: "Вы ещё не отправляли предложений" },
  "proposals.emptyClient": {
    uz: "Haydovchi e'lonlaridan birini tanlab o'z narxingizni taklif qiling.",
    ru: "Выберите одно из объявлений водителей и предложите свою цену.",
  },
  "proposals.emptyDriver": {
    uz: "«Moslar» bo'limidan mijoz so'roviga narx taklif qiling.",
    ru: "Предложите цену на запрос клиента в разделе «Подходящие».",
  },
} as const satisfies Record<string, Message>;
