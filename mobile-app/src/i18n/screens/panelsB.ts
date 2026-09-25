/** Public share/tracking pages, reputation card, route map, stop search, share links and the saved trip request. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const panelsBMessages = {
  // --- public listing page (shared link) ---
  "publicShare.linkStale": {
    uz: "Havola eskirgan bo'lishi mumkin. E'lon egasidan yangi havola so'rang.",
    ru: "Возможно, ссылка устарела. Попросите у автора объявления новую ссылку.",
  },
  "publicShare.open": { uz: "Ochiq", ru: "Открыто" },
  "publicShare.closed": { uz: "Yopiq", ru: "Закрыто" },
  "publicShare.service": { uz: "Xizmat", ru: "Услуга" },
  "publicShare.passenger": { uz: "Yo'lovchi", ru: "Пассажир" },
  "publicShare.parcel": { uz: "Pochta", ru: "Посылка" },
  "publicShare.date": { uz: "Sana", ru: "Дата" },
  "publicShare.window": { uz: "Vaqt oynasi", ru: "Временное окно" },
  "publicShare.priceBasis": { uz: "Narx birligi", ru: "Единица цены" },
  "publicShare.openHint": {
    uz: "Taklif berish uchun ilovaga kiring: telefon raqamingiz SMS kod bilan tasdiqlanadi. Bron ilova ichida saqlanadi.",
    ru: "Чтобы сделать предложение, войдите в приложение: номер телефона подтверждается кодом из SMS. Бронь хранится в приложении.",
  },
  "publicShare.closedHint": {
    uz: "Bu e'lon hozir yangi taklif qabul qilmayapti.",
    ru: "Это объявление сейчас не принимает новые предложения.",
  },
  "publicShare.openApp": { uz: "Ilovani ochish", ru: "Открыть приложение" },
  "publicShare.privacy": {
    uz: "Bu sahifada e'lon egasining ismi va telefoni ko'rsatilmaydi.",
    ru: "Имя и телефон автора объявления на этой странице не показываются.",
  },

  // --- public tracking page ---
  "publicTracking.status.passengerConfirmed": { uz: "Bron tasdiqlangan", ru: "Бронь подтверждена" },
  "publicTracking.status.passengerAwaitingPickup": {
    uz: "Yo'lovchi olib ketilishini kutmoqda",
    ru: "Пассажир ожидает посадки",
  },
  "publicTracking.status.passengerOnboard": { uz: "Yo'lovchi yo'lda", ru: "Пассажир в пути" },
  "publicTracking.status.passengerArrived": { uz: "Yo'lovchi yetib keldi", ru: "Пассажир прибыл" },
  "publicTracking.status.passengerCompleted": { uz: "Safar yakunlandi", ru: "Поездка завершена" },
  "publicTracking.status.parcelConfirmed": { uz: "Jo'natma bron qilingan", ru: "Посылка забронирована" },
  "publicTracking.status.parcelAwaitingPickup": {
    uz: "Jo'natma olinishini kutmoqda",
    ru: "Посылка ожидает, когда её заберут",
  },
  "publicTracking.status.parcelPickedUp": { uz: "Jo'natma haydovchida", ru: "Посылка у водителя" },
  // Q142: the trip departed; that is not proof the parcel was handed over or loaded
  "publicTracking.status.parcelInTransit": { uz: "Haydovchi yo'lga chiqdi", ru: "Водитель выехал" },
  "publicTracking.status.parcelDeliveryFailed": { uz: "Yetkazib bo'lmadi", ru: "Доставить не удалось" },
  "publicTracking.status.parcelDelivered": { uz: "Jo'natma topshirildi", ru: "Посылка передана" },
  "publicTracking.status.parcelReturnRequired": {
    uz: "Jo'natma qaytarilishi kerak",
    ru: "Посылку нужно вернуть",
  },
  "publicTracking.status.parcelReturned": { uz: "Jo'natma qaytarildi", ru: "Посылка возвращена" },
  "publicTracking.status.parcelCompleted": { uz: "Yakunlandi", ru: "Завершено" },
  "publicTracking.status.active": { uz: "Bron faol", ru: "Бронь активна" },
  "publicTracking.fresh": { uz: "Jonli", ru: "В реальном времени" },
  "publicTracking.delayed": { uz: "Kechikmoqda", ru: "С задержкой" },
  "publicTracking.lost": { uz: "Aloqa uzilgan", ru: "Связь потеряна" },
  "publicTracking.noData": { uz: "Joylashuv yo'q", ru: "Нет местоположения" },
  "publicTracking.unavailableTitle": { uz: "Kuzatuv mavjud emas", ru: "Отслеживание недоступно" },
  "publicTracking.unavailableBody": {
    uz: "Havola muddati tugagan, bekor qilingan yoki safar hali boshlanmagan bo'lishi mumkin. Jo'natuvchidan yangi havola so'rang.",
    ru: "Возможно, срок ссылки истёк, она отозвана или поездка ещё не началась. Попросите у отправителя новую ссылку.",
  },
  "publicTracking.vehicleTitle": {
    uz: "Bronungizni olib ketayotgan avtomobil",
    ru: "Автомобиль, который везёт вашу бронь",
  },
  "publicTracking.lastPosition": { uz: "Oxirgi joylashuv", ru: "Последнее местоположение" },
  "publicTracking.howLongAgo": { uz: "Qancha oldin", ru: "Как давно" },
  "publicTracking.lessThanMinute": { uz: "1 daqiqadan kam", ru: "Меньше минуты назад" },
  "publicTracking.minutesAgo": { uz: "{minutes} daqiqa oldin", ru: "{minutes} мин. назад" },
  "publicTracking.coordinates": { uz: "Koordinatalar", ru: "Координаты" },
  "publicTracking.accuracy": { uz: "Aniqlik", ru: "Точность" },
  "publicTracking.lowAccuracy": { uz: "Bu nuqtaning aniqligi past.", ru: "У этой точки низкая точность." },
  "publicTracking.delayedHint": {
    uz: "Joylashuv kechikib kelmoqda - avtomobil hozir boshqa joyda bo'lishi mumkin.",
    ru: "Местоположение приходит с задержкой - автомобиль может быть уже в другом месте.",
  },
  "publicTracking.lostHint": {
    uz: "Haydovchi telefonidan yangi joylashuv kelmayapti. Ko'rsatilgan nuqta eskirgan.",
    ru: "С телефона водителя не приходит новое местоположение. Показанная точка устарела.",
  },
  "publicTracking.noPointHint": {
    uz: "Hozircha joylashuv ma'lumoti yo'q. Haydovchi telefoni joylashuv yubora boshlaganda shu yerda ko'rinadi.",
    ru: "Данных о местоположении пока нет. Они появятся здесь, когда телефон водителя начнёт их передавать.",
  },
  "publicTracking.sourceNote": {
    uz: "Manba: haydovchining telefoni. Sahifa har 30 soniyada yangilanadi. Bu yerda ism, telefon va manzil ko'rsatilmaydi.",
    ru: "Источник: телефон водителя. Страница обновляется каждые 30 секунд. Имя, телефон и адрес здесь не показываются.",
  },

  // --- reputation card ---
  "reputation.title": { uz: "Reyting", ru: "Рейтинг" },
  "reputation.new": { uz: "Yangi", ru: "Новый" },
  "reputation.ratingCount": { uz: "Baholar soni", ru: "Количество оценок" },
  "reputation.count": { uz: "{count} ta", ru: "{count}" },
  "reputation.notRated": { uz: "Hali baholanmagan", ru: "Оценок пока нет" },
  "reputation.completedBookings": { uz: "Bajarilgan bronlar", ru: "Выполненные брони" },
  "reputation.completedTrips": { uz: "Yakunlangan safarlar", ru: "Завершённые поездки" },

  // --- route map ---
  "routeMap.loading": { uz: "Xarita yuklanmoqda...", ru: "Карта загружается..." },
  "routeMap.missingKey": {
    uz: "Xarita kaliti kiritilmagan — yo'nalish bekatlar ro'yxati bilan ko'rsatilmoqda.",
    ru: "Ключ карты не указан — направление показано списком остановок.",
  },
  "routeMap.failedList": {
    uz: "Xarita yuklanmadi — yo'nalish bekatlar ro'yxati bilan ko'rsatilmoqda.",
    ru: "Карта не загрузилась — направление показано списком остановок.",
  },
  "routeMap.failed": { uz: "Xarita yuklanmadi.", ru: "Карта не загрузилась." },

  // --- stop search and referral code check ---
  "stopSearch.label": { uz: "Bekat qidirish", ru: "Поиск остановки" },
  "stopSearch.placeholder": { uz: "Masalan: Qarshi avtovokzal", ru: "Например: Карши автовокзал" },
  "stopSearch.minChars": { uz: "Kamida 2 ta harf kiriting.", ru: "Введите не менее 2 букв." },
  "stopSearch.searching": { uz: "Qidirilmoqda...", ru: "Идёт поиск..." },
  "stopSearch.empty": {
    uz: "Tasdiqlangan bekat topilmadi. Boshqa nom bilan qidiring.",
    ru: "Подтверждённая остановка не найдена. Попробуйте другое название.",
  },
  "stopSearch.inactive": { uz: "faol emas", ru: "неактивна" },
  "stopSearch.referralLabel": { uz: "Taklif kodi", ru: "Код приглашения" },
  "stopSearch.referralPlaceholder": { uz: "Kodni kiriting", ru: "Введите код" },
  "stopSearch.referralCheck": { uz: "Tekshirish", ru: "Проверить" },
  "stopSearch.referralValid": { uz: "Kod amal qiladi.", ru: "Код действителен." },
  "stopSearch.referralInvalid": { uz: "Bu kod amal qilmaydi.", ru: "Этот код недействителен." },

  // --- tracking and listing share links ---
  "trackingShare.ttlMinutes": { uz: "{count} daqiqa", ru: "{count} мин." },
  "trackingShare.ttlHours": { uz: "{count} soat", ru: "{count} ч." },
  "trackingShare.ttlDays": { uz: "{count} kun", ru: "{count} дн." },
  "trackingShare.copied": { uz: "Nusxa olindi", ru: "Скопировано" },
  "trackingShare.copy": { uz: "Havoladan nusxa olish", ru: "Скопировать ссылку" },
  "trackingShare.copyFailed": {
    uz: "Nusxa olib bo'lmadi - havolani belgilab, qo'lda nusxalang.",
    ru: "Не удалось скопировать - выделите ссылку и скопируйте вручную.",
  },
  "trackingShare.trackingTitle": { uz: "Kuzatuv havolasi", ru: "Ссылка для отслеживания" },
  "trackingShare.trackingHint": {
    uz: "Havolani olgan odam faqat avtomobil holatini va oxirgi joylashuvini ko'radi - ism, telefon va manzilsiz. Joylashuv faqat safar davomida ko'rinadi. Havola faqat hozir bir marta ko'rsatiladi.",
    ru: "Получатель ссылки видит только статус автомобиля и его последнее местоположение - без имени, телефона и адреса. Местоположение видно только во время поездки. Ссылка показывается только сейчас, один раз.",
  },
  "trackingShare.ttlLabel": { uz: "Amal qilish muddati", ru: "Срок действия" },
  "trackingShare.create": { uz: "Havola yaratish", ru: "Создать ссылку" },
  "trackingShare.revoked": { uz: "Havola bekor qilindi.", ru: "Ссылка отозвана." },
  "trackingShare.expiredAt": { uz: "Muddati tugagan: {time}", ru: "Срок истёк: {time}" },
  "trackingShare.validUntil": { uz: "Amal qiladi: {time} gacha", ru: "Действует до: {time}" },
  "trackingShare.urlOnce": {
    uz: "Havola matni faqat birinchi javobda keladi. Kerak bo'lsa, bu havolani bekor qilib, yangisini yarating.",
    ru: "Текст ссылки приходит только в первом ответе. При необходимости отзовите эту ссылку и создайте новую.",
  },
  "trackingShare.shareTitle": { uz: "E'lonni ulashish", ru: "Поделиться объявлением" },
  "trackingShare.shareHint": {
    uz: "Havola ochgan odam yo'nalish, vaqt va narxni ko'radi; ismingiz va telefoningiz ko'rsatilmaydi. Hech narsa siz uchun avtomatik joylanmaydi.",
    ru: "Открывший ссылку увидит направление, время и цену; ваше имя и телефон не показываются. Ничего не публикуется от вашего имени автоматически.",
  },
  "trackingShare.channelLabel": { uz: "Matn qaysi joy uchun", ru: "Для чего текст" },
  "trackingShare.channelGeneric": { uz: "Umumiy", ru: "Общий" },

  // --- saved trip/parcel request ---
  "tripIntent.parcelType.documents": { uz: "Hujjat", ru: "Документы" },
  "tripIntent.parcelType.box": { uz: "Quti", ru: "Коробка" },
  "tripIntent.parcelType.bag": { uz: "Sumka", ru: "Сумка" },
  "tripIntent.parcelType.electronics": { uz: "Elektronika", ru: "Электроника" },
  "tripIntent.parcelType.clothing": { uz: "Kiyim", ru: "Одежда" },
  "tripIntent.parcelType.other": { uz: "Boshqa", ru: "Другое" },
  "tripIntent.loadFailed": {
    uz: "Saqlangan talabni yuklab bo'lmadi: {error}",
    ru: "Не удалось загрузить сохранённый запрос: {error}",
  },
  "tripIntent.emptyTitle": { uz: "Saqlangan talab yo'q", ru: "Сохранённого запроса нет" },
  "tripIntent.emptyHint": {
    uz: "Yo'nalish, vaqt va odamlar sonini bir marta kiriting - har bir haydovchiga taklif shu ma'lumot bilan to'ldiriladi. Talab boshqalarga ko'rinmaydi va o'zi hech kimga yuborilmaydi.",
    ru: "Укажите направление, время и число людей один раз - предложение каждому водителю будет заполняться этими данными. Запрос не виден другим и сам никому не отправляется.",
  },
  "tripIntent.new": { uz: "Yangi safar/jo'natma", ru: "Новая поездка/посылка" },
  "tripIntent.passengerTitle": { uz: "Safar talabingiz", ru: "Ваш запрос на поездку" },
  "tripIntent.parcelTitle": { uz: "Jo'natma talabingiz", ru: "Ваш запрос на посылку" },
  "tripIntent.yourPrice": { uz: "Siz o'ylagan narx: {price}", ru: "Ваша желаемая цена: {price}" },
  "tripIntent.openOffers": { uz: "Ochiq takliflaringiz: {count} ta", ru: "Ваших открытых предложений: {count}" },
  "tripIntent.expiredHint": {
    uz: "Vaqt o'tib ketgan. Sana avtomatik o'zgartirilmaydi - yangi vaqtni tanlang.",
    ru: "Время прошло. Дата не меняется автоматически - выберите новое время.",
  },
  "tripIntent.bookingCancelledHint": {
    uz: "Shu talabdan qilingan bron bekor qilindi. Eski takliflar qayta ochilmaydi - xohlasangiz qidiruvni qaytadan boshlang.",
    ru: "Бронь по этому запросу отменена. Старые предложения заново не открываются - при желании начните поиск снова.",
  },
  "tripIntent.bookedHint": {
    uz: "Shu talab bo'yicha bron qilindi. Boshqa haydovchilarga yuborilgan takliflar yopildi.",
    ru: "По этому запросу оформлена бронь. Предложения, отправленные другим водителям, закрыты.",
  },
  "tripIntent.updateTime": { uz: "Vaqtni yangilash", ru: "Обновить время" },
  "tripIntent.others": { uz: "Boshqa talablaringiz", ru: "Другие ваши запросы" },
  "tripIntent.fits": {
    uz: "Talabingiz shu e'longa mos: vaqt, joy va o'rinlar to'g'ri keladi.",
    ru: "Ваш запрос подходит к этому объявлению: время, место и число мест совпадают.",
  },
  "tripIntent.problem.windowIncomplete": {
    uz: "Vaqt oralig'ini to'liq kiriting.",
    ru: "Укажите временной интервал полностью.",
  },
  "tripIntent.problem.endBeforeStart": {
    uz: "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak.",
    ru: "Время окончания должно быть позже времени начала.",
  },
  "tripIntent.problem.past": {
    uz: "Vaqt o'tib ketgan - kelajakdagi vaqtni tanlang.",
    ru: "Время уже прошло - выберите время в будущем.",
  },
  "tripIntent.route": { uz: "Yo'nalish", ru: "Направление" },
  "tripIntent.changeRoute": { uz: "Yo'nalishni o'zgartirish", ru: "Изменить направление" },
  "tripIntent.windowStart": { uz: "Jo'nash oynasi boshlanishi", ru: "Начало окна отправления" },
  "tripIntent.windowEnd": { uz: "Jo'nash oynasi tugashi", ru: "Конец окна отправления" },
  "tripIntent.people": { uz: "Necha kishi", ru: "Сколько человек" },
  "tripIntent.pricePerPerson": {
    uz: "Bir kishi uchun narx (so'm, ixtiyoriy)",
    ru: "Цена за человека (сум, необязательно)",
  },
  "tripIntent.priceTotal": { uz: "Narx (so'm, ixtiyoriy)", ru: "Цена (сум, необязательно)" },
  "tripIntent.parcelTypeLabel": { uz: "Jo'natma turi", ru: "Тип посылки" },
  "tripIntent.weight": { uz: "Og'irlik (kg)", ru: "Вес (кг)" },
  "tripIntent.length": { uz: "Uzunlik (sm)", ru: "Длина (см)" },
  "tripIntent.width": { uz: "Eni (sm)", ru: "Ширина (см)" },
  "tripIntent.height": { uz: "Balandligi (sm)", ru: "Высота (см)" },
  "tripIntent.receiverName": { uz: "Qabul qiluvchi ismi", ru: "Имя получателя" },
  "tripIntent.receiverPhone": { uz: "Qabul qiluvchi telefoni", ru: "Телефон получателя" },
  "tripIntent.receiverHint": {
    uz: "Qabul qiluvchi ma'lumoti faqat sizga ko'rinadi; haydovchi uni jo'natmani olgandan keyin ko'radi.",
    ru: "Данные получателя видны только вам; водитель увидит их после того, как заберёт посылку.",
  },
  "tripIntent.openOffersWarning": {
    uz: "Sizda {count} ta ochiq taklif bor. Yo'nalish, vaqt, odamlar soni yoki jo'natma o'zgarsa, ular yopiladi - saqlashdan oldin so'raymiz. Faqat narxni o'zgartirish ularga tegmaydi.",
    ru: "Открытых предложений: {count}. Если изменится направление, время, число людей или посылка, они будут закрыты - мы спросим перед сохранением. Изменение только цены их не затрагивает.",
  },
  "tripIntent.close": { uz: "Talabni yopish", ru: "Закрыть запрос" },
} as const satisfies Record<string, Message>;
