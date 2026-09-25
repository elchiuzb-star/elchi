/** ADR-0026 screens: the operator chat ("Shikoyat qilish"), parcel size categories, the codeless parcel on the way. */
import type { Message } from "../messages";

export const adr0026Messages = {
  // --- operator chat (Q141) ---
  // Q146: the main entry is help and complaints together; the safety report is a separate, secondary action
  "support.complain": { uz: "Yordam / shikoyat", ru: "Помощь / жалоба" },
  "safety.menuTitle": { uz: "Xavfsizlik haqida xabar berish", ru: "Сообщить о проблеме безопасности" },
  "safety.reportTitle": { uz: "Xavfsizlik haqida xabar", ru: "Сообщение о безопасности" },
  "support.threadTitle": { uz: "Operator bilan yozishma", ru: "Переписка с оператором" },
  "support.statusLabel": { uz: "Holat", ru: "Статус" },
  "support.status.waiting": {
    uz: "Navbatda - operator hali ko'rmadi",
    ru: "В очереди - оператор ещё не видел",
  },
  "support.status.assigned": { uz: "Operator ko'rib chiqmoqda", ru: "Оператор рассматривает" },
  "support.status.answered": { uz: "Operator javob berdi", ru: "Оператор ответил" },
  "support.status.closed": { uz: "Yopilgan", ru: "Закрыто" },
  "support.noPromise": {
    uz: "Javob vaqti va'da qilinmaydi. Bu yozishma pul qaytarmaydi va hech kimni ayblamaydi.",
    ru: "Время ответа не обещается. Эта переписка не возвращает деньги и никого не обвиняет.",
  },
  "support.emptyThread": {
    uz: "Muammoni o'z so'zingiz bilan yozing - bron raqami va yo'nalish operatorga avtomatik ko'rinadi.",
    ru: "Опишите проблему своими словами - номер брони и маршрут оператор видит автоматически.",
  },
  "support.operator": { uz: "Operator", ru: "Оператор" },
  "support.refresh": { uz: "Yangilash", ru: "Обновить" },
  "support.draftLabel": { uz: "Xabar", ru: "Сообщение" },
  "support.send": { uz: "Yuborish", ru: "Отправить" },
  "support.masked": {
    uz: "Xabardagi aloqa ma'lumotlari yashirildi.",
    ru: "Контактные данные в сообщении скрыты.",
  },
  "support.closedNote": {
    uz: "Bu yozishma yopilgan. Yangi murojaat uchun bron sahifasidagi «Yordam / shikoyat» tugmasini bosing.",
    ru: "Эта переписка закрыта. Для нового обращения нажмите «Помощь / жалоба» на странице брони.",
  },
  "support.myThreads": { uz: "Murojaatlarim", ru: "Мои обращения" },
  "support.myThreadsHint": { uz: "Operator bilan yozishmalar", ru: "Переписка с оператором" },
  "support.threadMeta": { uz: "{count} ta xabar · {date}", ru: "Сообщений: {count} · {date}" },
  "support.noThreadsTitle": { uz: "Murojaat yo'q", ru: "Обращений нет" },
  "support.noThreadsHint": {
    uz: "Bron sahifasidagi «Yordam / shikoyat» tugmasi shu bron bo'yicha operator bilan yozishmani ochadi.",
    ru: "Кнопка «Помощь / жалоба» на странице брони открывает переписку с оператором по этой брони.",
  },

  // --- codeless parcel (Q139) and the passenger ladder that keeps its code ---
  "parcel.operatorRecordsOutcome": {
    uz: "Haydovchi yo'lga chiqdi. Jo'natma yetkazilgani yoki qaytarilishini operator qayd etadi - kod va tasdiq kerak emas.",
    ru: "Водитель выехал. Доставку или возврат посылки фиксирует оператор - код и подтверждение не нужны.",
  },
  "driverBooking.action.board": { uz: "Yo'lovchini chiqardim", ru: "Пассажир сел" },
  "driverBooking.action.dropOff": { uz: "Yo'lovchini tushirdim", ru: "Пассажир высажен" },
  "driverBooking.receiver": { uz: "Qabul qiluvchi", ru: "Получатель" },
  "driverBooking.receiverHidden": {
    uz: "Safar jo'naganda ochiladi (jo'natuvchi telefoni ko'rsatilmaydi)",
    ru: "Откроется, когда поездка начнётся (телефон отправителя не показывается)",
  },
  "driverBooking.boardingCode": { uz: "Yo'lovchining chiqish kodi", ru: "Код посадки пассажира" },
  "driverBooking.codeFromPassenger": {
    uz: "Kodni yo'lovchidan so'rang - u ilovasida ko'radi.",
    ru: "Спросите код у пассажира - он видит его в приложении.",
  },

  // --- honest parcel progress (Q142): the system knows the trip departed, not that the parcel was handed over ---
  "parcel.status.driverDeparted": { uz: "Haydovchi yo'lga chiqdi", ru: "Водитель выехал" },
  "parcel.progress.tripPreparing": { uz: "Safarga tayyorlanmoqda", ru: "Поездка готовится" },
  "parcel.progress.deliveredByOperator": { uz: "Operator yetkazilganini qayd etdi", ru: "Оператор отметил доставку" },

  // --- quantity before and after a booking (Q145) ---
  "listingEdit.seats": { uz: "Odamlar soni", ru: "Количество человек" },
  "listingEdit.seatsHint": {
    uz: "Bron bo'lguncha o'zgartirish mumkin. O'zgartirsangiz, ochiq takliflar yopiladi va haydovchilar yangi son uchun qayta taklif beradi.",
    ru: "Можно менять до брони. После изменения открытые предложения закрываются, и водители предлагают заново для нового числа.",
  },
  "listingOwner.invalid.seats": { uz: "Odamlar soni 1 dan 8 gacha bo'lishi kerak.", ru: "Количество человек - от 1 до 8." },
  "listingOwner.invalid.seats_children": {
    uz: "Odamlar soni bolalar sonidan ko'p bo'lishi kerak (kamida bitta kattalar).",
    ru: "Количество человек должно быть больше числа детей (хотя бы один взрослый).",
  },
  "amendment.seatsFixed": {
    uz: "Odamlar soni kelishilgan: {count}. Bron qilingandan keyin uni o'zgartirib bo'lmaydi - faqat narxni kelishib o'zgartirish mumkin.",
    ru: "Количество человек согласовано: {count}. После брони его изменить нельзя - можно только договориться о цене.",
  },
  "amendment.parcelQuantityFixed": {
    uz: "Pochta bitta jo'natma sifatida kelishilgan - faqat narxni kelishib o'zgartirish mumkin.",
    ru: "Посылка согласована как одно отправление - можно только договориться о цене.",
  },
  "listingBids.noRatingsYet": { uz: "Hali baholanmagan", ru: "Ещё без оценок" },

  // --- parcel size categories (Q140) ---
  "parcelCategory.label": { uz: "Jo'natma o'lchami", ru: "Размер посылки" },
  "parcelCategory.hint": {
    uz: "Jo'natmangiz tanlangan toifa chegarasidan oshmasligi kerak.",
    ru: "Посылка не должна превышать пределы выбранной категории.",
  },
  "parcelCategory.limits": {
    uz: "{length}×{width}×{height} sm gacha · {weight} kg gacha",
    ru: "до {length}×{width}×{height} см · до {weight} кг",
  },
  "parcelCategory.synthetic": {
    uz: "Sinov katalogi - haqiqiy tarif emas.",
    ru: "Тестовый каталог - не реальный тариф.",
  },
  "parcelCategory.unconfirmed": {
    uz: "Jo'natma o'lchamlari katalogi hali tasdiqlanmagan - pochta e'lonini hozir berib bo'lmaydi.",
    ru: "Каталог размеров посылок ещё не утверждён - объявление о посылке сейчас подать нельзя.",
  },
  "parcelCategory.loading": { uz: "O'lchamlar yuklanmoqda...", ru: "Загружаем размеры..." },
  "parcelCategory.loadFailed": { uz: "O'lchamlar yuklanmadi", ru: "Не удалось загрузить размеры" },
  "parcelCategory.choose": { uz: "O'lchamni tanlang", ru: "Выберите размер" },
  "parcelCategory.agreed": { uz: "Kelishilgan o'lcham", ru: "Согласованный размер" },
  "parcelCategory.amountDue": { uz: "To'lanadigan summa (naqd)", ru: "Сумма к оплате (наличными)" },
} as const satisfies Record<string, Message>;
