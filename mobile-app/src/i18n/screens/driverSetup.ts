/** Driver setup screens: profile form, documents, my routes, add route, trip offer create. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const driverSetupMessages = {
  // --- driver-profile-form (Q94: the car is entered once) ---
  "driverProfileForm.title": { uz: "Haydovchi profili", ru: "Профиль водителя" },
  "driverProfileForm.fullName": { uz: "Ism familiya", ru: "Имя и фамилия" },
  "driverProfileForm.vehicleLockedHint": {
    uz: "O'zgartirish uchun operator yoki adminga murojaat qiling",
    ru: "Для изменения обратитесь к оператору или администратору",
  },
  "driverProfileForm.vehicleLockedTitle": { uz: "Avtomobil ma'lumotlari qulflangan", ru: "Данные автомобиля заблокированы" },
  "driverProfileForm.vehicleLockedBody": {
    uz: "Avtomobil ma'lumotlari faqat bir marta kiritiladi. Model, rang yoki davlat raqamini o'zgartirish kerak bo'lsa, operator yoki adminga murojaat qiling.",
    ru: "Данные автомобиля вводятся только один раз. Если нужно изменить модель, цвет или госномер, обратитесь к оператору или администратору.",
  },
  "driverProfileForm.carModel": { uz: "Avtomobil modeli", ru: "Модель автомобиля" },
  "driverProfileForm.carModelPlaceholder": { uz: "Masalan: Cobalt", ru: "Например: Cobalt" },
  "driverProfileForm.carColor": { uz: "Avtomobil rangi", ru: "Цвет автомобиля" },
  "driverProfileForm.carColorPlaceholder": { uz: "Masalan: Oq", ru: "Например: белый" },
  "driverProfileForm.plateNumber": { uz: "Davlat raqami", ru: "Госномер" },
  "driverProfileForm.plateNumberPlaceholder": { uz: "Masalan: 01 A 123 AA", ru: "Например: 01 A 123 AA" },
  "driverProfileForm.passengerSeats": { uz: "Yo'lovchi o'rinlari", ru: "Пассажирские места" },
  "driverProfileForm.cargoKg": { uz: "Yuk uchun joy (kg)", ru: "Место для груза (кг)" },
  "driverProfileForm.cargoLitres": { uz: "Yuk hajmi (litr)", ru: "Объём груза (л)" },
  "driverProfileForm.vehicleStatus": { uz: "Avtomobil holati", ru: "Статус автомобиля" },
  "driverProfileForm.routesAfterReview": {
    uz: "Avtomobil hujjatlari tekshirilgunicha yo'nalish qo'sha olmaysiz.",
    ru: "Пока документы автомобиля не проверены, добавить направление нельзя.",
  },
  "driverProfileForm.saved": { uz: "Profil saqlandi", ru: "Профиль сохранён" },

  // --- driver-documents (§17.1) ---
  "driverDocs.title": { uz: "Hujjatlar", ru: "Документы" },
  "driverDocs.submittedCount": { uz: "{submitted} / {total} hujjat yuborilgan", ru: "Отправлено документов: {submitted} / {total}" },
  "driverDocs.intro": {
    uz: "Har bir bandni alohida yuklang — quyidagi nom qaysi hujjat kerakligini bildiradi.",
    ru: "Загружайте каждый пункт отдельно — название ниже подсказывает, какой документ нужен.",
  },
  "driverDocs.rejectionReason": { uz: "Sabab: {reason}", ru: "Причина: {reason}" },
  "driverDocs.reupload": { uz: "Qayta yuklash", ru: "Загрузить заново" },
  "driverDocs.upload": { uz: "Yuklash", ru: "Загрузить" },
  "driverDocs.uploadedForReview": { uz: "{type} ko'rib chiqishga yuborildi", ru: "{type}: отправлено на проверку" },

  // --- driver-routes / driver-trip-detail ---
  "driverRoutes.title": { uz: "Yo'nalishlarim", ru: "Мои направления" },
  "driverRoutes.tripMeta": { uz: "{date} · {stops} bekat · {seats} o'rin", ru: "{date} · Остановок: {stops} · Мест: {seats}" },
  "driverRoutes.status": { uz: "Status: {status}", ru: "Статус: {status}" },
  "driverRoutes.tripStatusUpdated": { uz: "Safar holati yangilandi", ru: "Статус поездки обновлён" },
  "driverRoutes.boardingWindowHint": {
    uz: "Chiqish oynasi jo'nashdan 60 daqiqa oldin ochiladi.",
    ru: "Посадка открывается за 60 минут до отправления.",
  },
  "driverRoutes.passengerOffer": { uz: "Yo'lovchi e'loni", ru: "Объявление для пассажиров" },
  "driverRoutes.parcelOffer": { uz: "Yuk e'loni", ru: "Объявление для груза" },
  "driverRoutes.perSeatSuffix": { uz: " / o'rin", ru: " / место" },
  "driverRoutes.offerStatusLine": {
    uz: "{status} · boshlang'ich narx, mijoz o'z narxini taklif qiladi",
    ru: "{status} · стартовая цена, клиент предлагает свою",
  },
  "driverRoutes.published": { uz: "E'lon bozorga chiqarildi", ru: "Объявление опубликовано" },
  "driverRoutes.publish": { uz: "Bozorga chiqarish", ru: "Опубликовать" },
  "driverRoutes.viewMatches": { uz: "Mos so'rovlarni ko'rish", ru: "Посмотреть подходящие запросы" },
  "driverRoutes.addAnotherOffer": { uz: "Yana e'lon qo'shish", ru: "Добавить ещё объявление" },
  "driverRoutes.publishWithPrice": { uz: "Narx bilan e'lon qilish", ru: "Опубликовать с ценой" },
  "driverRoutes.empty": { uz: "Hozircha yo'nalish qo'shilmagan", ru: "Направления пока не добавлены" },
  "driverRoutes.addRoute": { uz: "Yo'nalish qo'shish", ru: "Добавить направление" },

  // --- driver-add-route ---
  "addRoute.vehicle": { uz: "Avtomobil", ru: "Автомобиль" },
  "addRoute.vehiclePlaceholder": { uz: "Avtomobilni tanlang", ru: "Выберите автомобиль" },
  "addRoute.noApprovedVehicle": { uz: "Tasdiqlangan avtomobil yo'q", ru: "Нет подтверждённого автомобиля" },
  "addRoute.vehicleOption": { uz: "{model} · {plate} · {seats} o'rin", ru: "{model} · {plate} · Мест: {seats}" },
  "addRoute.vehicleNeedsReview": {
    uz: "Avtomobil hujjatlari tekshirilgandan keyin safar rejalashtirish mumkin bo'ladi.",
    ru: "Планировать поездки можно будет после проверки документов автомобиля.",
  },
  "addRoute.corridor": { uz: "Qayerdan - qayerga", ru: "Откуда - куда" },
  "addRoute.corridorPlaceholder": { uz: "Yo'nalishni tanlang", ru: "Выберите направление" },
  "addRoute.route": { uz: "Marshrut", ru: "Маршрут" },
  "addRoute.routePlaceholder": { uz: "Marshrutni tanlang", ru: "Выберите маршрут" },
  "addRoute.pickCorridorFirst": { uz: "Avval yo'nalishni tanlang", ru: "Сначала выберите направление" },
  "addRoute.routeOption": { uz: "{stops} bekat · {km} km · {hours} soat", ru: "Остановок: {stops} · {km} км · {hours} ч" },
  "addRoute.noApprovedRoute": {
    uz: "Bu yo'nalishda tasdiqlangan marshrut yo'q — operator marshrut qo'shishi kerak.",
    ru: "На этом направлении нет утверждённого маршрута — его должен добавить оператор.",
  },
  "addRoute.departureTime": { uz: "Jo'nash vaqti", ru: "Время отправления" },
  "addRoute.freeSeats": { uz: "Bo'sh o'rinlar", ru: "Свободные места" },
  "addRoute.plannedOnApprovedRoute": {
    uz: "Safar operator tasdiqlagan marshrut bo'yicha rejalashtiriladi. Yuk uchun joy ko'rsatilmasa, posilka takliflari yuborilmaydi.",
    ru: "Поездка планируется по маршруту, утверждённому оператором. Если не указать место для груза, предложения на посылки не поступят.",
  },
  "addRoute.added": { uz: "Yo'nalish qo'shildi", ru: "Направление добавлено" },

  // --- driver-offer-create (Q92, Q90) ---
  "offerCreate.gateTitle": { uz: "Safar e'loni", ru: "Объявление о поездке" },
  "offerCreate.title": { uz: "Safarni e'lon qilish", ru: "Опубликовать поездку" },
  "offerCreate.tripMeta": { uz: "{date} · {seats} o'rin", ru: "{date} · Мест: {seats}" },
  "offerCreate.servicePassenger": { uz: "Yo'lovchi", ru: "Пассажиры" },
  "offerCreate.serviceParcel": { uz: "Yuk", ru: "Груз" },
  "offerCreate.servicePassengerLower": { uz: "yo'lovchi", ru: "пассажиры" },
  "offerCreate.serviceParcelLower": { uz: "yuk", ru: "груз" },
  "offerCreate.and": { uz: " va ", ru: " и " },
  "offerCreate.alreadyOffered": {
    uz: "Bu safar uchun {services} e'loni allaqachon bor — bittasidan ortiq bo'lmaydi.",
    ru: "Для этой поездки уже есть объявление ({services}) — больше одного на услугу быть не может.",
  },
  "offerCreate.from": { uz: "Qayerdan", ru: "Откуда" },
  "offerCreate.to": { uz: "Qayerga", ru: "Куда" },
  "offerCreate.stopPlaceholder": { uz: "Bekatni tanlang", ru: "Выберите остановку" },
  "offerCreate.sameStops": { uz: "Ikki bekat bir xil bo'lishi mumkin emas.", ru: "Остановки не могут совпадать." },
  "offerCreate.departureWindow": { uz: "Chiqish vaqti", ru: "Время посадки" },
  "offerCreate.windowHint": {
    uz: "Safar shu bekatga rejalashtirilgan vaqt atrofida. Mijoz shu oynada taklif yuboradi.",
    ru: "Окно вокруг запланированного времени прибытия на эту остановку. Клиент отправляет предложение в рамках этого окна.",
  },
  "offerCreate.pricePerSeat": { uz: "Bir o'rin narxi (so'm)", ru: "Цена за место (сум)" },
  "offerCreate.priceParcel": { uz: "Yuk uchun narx (so'm)", ru: "Цена за груз (сум)" },
  "offerCreate.pricePlaceholder": { uz: "Masalan: 200000", ru: "Например: 200000" },
  "offerCreate.totalForSeats": { uz: "{seats} o'rin uchun jami: {total}", ru: "Мест: {seats}, итого: {total}" },
  "offerCreate.noCargoRoom": {
    uz: "Bu safarda yuk uchun joy ko'rsatilmagan — yuk e'lonini joylash uchun safarni yuk sig'imi bilan rejalashtiring.",
    ru: "В этой поездке не указано место для груза — чтобы разместить объявление для груза, запланируйте поездку с грузовой вместимостью.",
  },
  "offerCreate.startingPriceNote": {
    uz: "Bu — boshlang'ich narxingiz. Mijoz o'z narxini taklif qiladi, siz qarshi taklif yuborasiz. Bron faqat ikkalangiz kelishgandan keyin yaratiladi; e'lon o'rin yoki balansni band qilmaydi.",
    ru: "Это ваша стартовая цена. Клиент предложит свою, вы отправите встречное предложение. Бронь создаётся только после того, как вы оба договоритесь; объявление не занимает места и не блокирует баланс.",
  },
  "offerCreate.submit": { uz: "E'lon qilish", ru: "Опубликовать" },
} as const satisfies Record<string, Message>;
