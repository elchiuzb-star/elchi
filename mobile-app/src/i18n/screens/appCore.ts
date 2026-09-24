/** Shared pieces of ConnectedApp: labels, cash record, driver gate, rival board, bottom nav, location and toasts. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const appCoreMessages = {
  // --- driver verification status ---
  "app.driverVerification.new": { uz: "Yangi", ru: "Новый" },
  "app.driverVerification.pending": { uz: "Ko'rib chiqilmoqda", ru: "На проверке" },
  "app.driverVerification.blocked": { uz: "Bloklangan", ru: "Заблокирован" },

  // --- parcel types (Q68) ---
  "app.parcelType.documents": { uz: "Hujjat", ru: "Документы" },
  "app.parcelType.box": { uz: "Quti", ru: "Коробка" },
  "app.parcelType.bag": { uz: "Sumka", ru: "Сумка" },
  "app.parcelType.electronics": { uz: "Elektronika", ru: "Электроника" },
  "app.parcelType.clothing": { uz: "Kiyim", ru: "Одежда" },
  "app.parcelType.other": { uz: "Boshqa", ru: "Другое" },

  // --- booking progress ladder ---
  "app.progress.driverAtStop": { uz: "Haydovchi bekatda", ru: "Водитель на остановке" },
  "app.progress.parcelPickedUp": { uz: "Yuk olindi", ru: "Груз забран" },
  "app.progress.completed": { uz: "Yakunlandi", ru: "Завершено" },

  // --- distance and duration ---
  "app.distance.km": { uz: "{value} km", ru: "{value} км" },
  "app.distance.m": { uz: "{value} m", ru: "{value} м" },
  "app.duration.hoursMinutes": { uz: "{hours} soat {minutes} daqiqa", ru: "{hours} ч {minutes} мин" },
  "app.duration.hours": { uz: "{hours} soat", ru: "{hours} ч" },
  "app.duration.minutes": { uz: "{minutes} daqiqa", ru: "{minutes} мин" },

  // --- v1 order status timeline ---
  "app.orderStatus.title": { uz: "Buyurtma holati", ru: "Статус заказа" },
  "app.orderStatus.published": { uz: "E'lon qilindi", ru: "Опубликовано" },
  "app.orderStatus.accepted": { uz: "Haydovchi tanlandi", ru: "Водитель выбран" },

  // --- shared rows and cards ---
  "app.citySelect.placeholder": { uz: "Shaharni tanlang", ru: "Выберите город" },
  "app.route.noAddress": { uz: "Manzil kiritilmagan", ru: "Адрес не указан" },
  "app.route.change": { uz: "O'zgartirish", ru: "Изменить" },
  "app.orderCard.bids": { uz: "{count} ta taklif", ru: "Предложений: {count}" },
  "app.savedEnd.district": { uz: "Tuman", ru: "Район" },
  "app.savedEnd.stop": { uz: "Tanlangan bekat", ru: "Выбранная остановка" },
  "app.endLabel.mapPlace": { uz: "Xaritadagi joy", ru: "Место на карте" },

  // --- parcel photo ---
  "app.photo.none": { uz: "Rasm yuklanmagan", ru: "Фото не загружено" },
  "app.photo.zoom": { uz: "Posilka rasmini kattalashtirish", ru: "Увеличить фото посылки" },
  "app.photo.loading": { uz: "Rasm yuklanmoqda...", ru: "Фото загружается..." },
  "app.photo.failed": { uz: "Rasmni ko'rsatib bo'lmadi", ru: "Не удалось показать фото" },
  "app.photo.alt": { uz: "Posilka rasmi", ru: "Фото посылки" },
  "app.photo.reload": { uz: "Qayta yuklash", ru: "Загрузить снова" },

  // --- cash record (§9) ---
  "app.cash.title": { uz: "Naqd to'lov qaydi", ru: "Отметка об оплате наличными" },
  "app.cash.explainer": {
    uz: "Yo'lkira haydovchiga naqd beriladi. Bu yerda faqat qayd qoladi — ELCHI bu pulni qabul qilmaydi.",
    ru: "Плата за проезд передаётся водителю наличными. Здесь остаётся только отметка — ELCHI эти деньги не принимает.",
  },
  "app.cash.dueLabel": { uz: "Naqd to'lanadigan summa", ru: "Сумма к оплате наличными" },
  "app.cash.agreedLabel": { uz: "Kelishilgan summa", ru: "Согласованная сумма" },
  "app.cash.receivedField": { uz: "Olingan summa (so'm)", ru: "Полученная сумма (сум)" },
  "app.cash.givenField": { uz: "Berilgan summa (so'm)", ru: "Переданная сумма (сум)" },
  "app.cash.markReceived": { uz: "Naqd olindi deb qayd qilish", ru: "Отметить, что наличные получены" },
  "app.cash.markGiven": { uz: "Naqd berildi deb qayd qilish", ru: "Отметить, что наличные переданы" },
  "app.cash.reportedByMe": { uz: "Siz qayd qildingiz: {amount} · {date}", ru: "Вы отметили: {amount} · {date}" },
  "app.cash.reportedByOther": {
    uz: "Ikkinchi tomon qayd qildi: {amount} · {date}",
    ru: "Другая сторона отметила: {amount} · {date}",
  },
  "app.cash.awaitingOther": {
    uz: "Ikkinchi tomonning tasdig'i kutilmoqda.",
    ru: "Ожидается подтверждение другой стороны.",
  },
  "app.cash.acknowledge": { uz: "Tasdiqlayman", ru: "Подтверждаю" },
  "app.cash.contest": { uz: "Rozi emasman", ru: "Не согласен" },
  "app.cash.bothConfirmed": { uz: "Ikkala tomon tasdiqladi.", ru: "Обе стороны подтвердили." },
  "app.cash.contested": {
    uz: "Kelishmovchilik qayd etildi — operator ko'rib chiqadi.",
    ru: "Разногласие зафиксировано — его рассмотрит оператор.",
  },

  // --- driver verification gate (D16) ---
  "app.driverGate.title": {
    uz: "Tasdiqlanmaguncha buyurtma qabul qila olmaysiz",
    ru: "Пока профиль не подтверждён, вы не можете принимать заказы",
  },
  "app.driverGate.status": { uz: "Holat: {status}", ru: "Статус: {status}" },
  "app.driverGate.decided": {
    uz: "Hisobingiz bo'yicha qaror qabul qilingan. Sababi va keyingi qadamlar uchun qo'llab-quvvatlash xizmatiga yozing.",
    ru: "По вашему аккаунту принято решение. Чтобы узнать причину и дальнейшие шаги, напишите в поддержку.",
  },
  "app.driverGate.pending": {
    uz: "Profilni to'ldiring va barcha hujjatlarni yuklang — operator tekshirgandan so'ng taklif yubora olasiz.",
    ru: "Заполните профиль и загрузите все документы — после проверки оператором вы сможете отправлять предложения.",
  },
  "app.driverGate.support": { uz: "Qo'llab-quvvatlashga yozish", ru: "Написать в поддержку" },
  "app.driverGate.documents": { uz: "Hujjatlarni yuklash", ru: "Загрузить документы" },
  "app.driverGate.profile": { uz: "Profilni to'ldirish", ru: "Заполнить профиль" },

  // --- rival offer board (Q40) ---
  "app.rivalBoard.title": { uz: "Boshqa haydovchilar takliflari", ru: "Предложения других водителей" },
  "app.rivalBoard.count": { uz: "{count} ta", ru: "Всего: {count}" },
  "app.rivalBoard.empty": {
    uz: "Hozircha boshqa taklif yo'q — birinchi bo'lib narx taklif qilishingiz mumkin.",
    ru: "Других предложений пока нет — вы можете первым предложить цену.",
  },
  "app.rivalBoard.cheapest": { uz: "Eng arzon taklif:", ru: "Самое дешёвое предложение:" },
  "app.rivalBoard.vehicleSeats": { uz: "{vehicle} · {seats} o'rin", ru: "{vehicle} · мест: {seats}" },
  "app.rivalBoard.ratings": { uz: "{bucket} · {count} ta baho", ru: "{bucket} · оценок: {count}" },
  "app.rivalBoard.countered": { uz: "Mijoz qarshi taklif yubordi", ru: "Клиент отправил встречное предложение" },
  "app.rivalBoard.mine": { uz: "Sizning joriy taklifingiz: {price}", ru: "Ваше текущее предложение: {price}" },

  // --- bottom navigation ---
  "app.nav.home": { uz: "Bosh sahifa", ru: "Главная" },
  "app.nav.orders": { uz: "Buyurtmalar", ru: "Заказы" },
  "app.nav.messages": { uz: "Xabarlar", ru: "Сообщения" },
  "app.nav.profile": { uz: "Profil", ru: "Профиль" },
  "app.nav.routes": { uz: "Yo'nalishlar", ru: "Направления" },
  "app.nav.matches": { uz: "Moslar", ru: "Подходящие" },

  // --- current location and direction preview ---
  "app.location.unsupported": {
    uz: "Bu brauzer joylashuvni aniqlay olmaydi - joyni xaritadan belgilang.",
    ru: "Этот браузер не может определить местоположение — отметьте место на карте.",
  },
  "app.location.noDistrict": {
    uz: "Joylashuvingizga mos tuman katalogda topilmadi - joyni xaritadan belgilang.",
    ru: "Район для вашего местоположения не найден в каталоге — отметьте место на карте.",
  },
  "app.location.found": {
    uz: "Joylashuvingiz aniqlandi: {district}, {region}",
    ru: "Ваше местоположение определено: {district}, {region}",
  },
  "app.location.denied": {
    uz: "Joylashuvga ruxsat berilmadi - brauzer sozlamasidan ruxsat bering yoki joyni xaritadan belgilang.",
    ru: "Доступ к местоположению не разрешён — разрешите его в настройках браузера или отметьте место на карте.",
  },
  "app.location.failed": {
    uz: "Joylashuvni aniqlab bo'lmadi - joyni xaritadan belgilang.",
    ru: "Не удалось определить местоположение — отметьте место на карте.",
  },
  "app.location.offRoute": {
    uz: "Belgilangan joy yo'ldan {km} km chetda - bu masofa yuqoridagi vaqtga kirmagan.",
    ru: "Отмеченное место находится в {km} км от дороги — это расстояние не входит в указанное выше время.",
  },
  "app.location.previewMismatch": {
    uz: "Bu ikki nuqta hozircha ELCHI yo'nalishiga mos kelmaydi.",
    ru: "Эти две точки пока не подходят ни под одно направление ELCHI.",
  },

  // --- listing form checks ---
  "app.validation.bothPoints": {
    uz: "Ikkala nuqtani belgilang va yo'nalish tekshirilishini kuting.",
    ru: "Отметьте обе точки и дождитесь проверки направления.",
  },
  "app.validation.windowStart": {
    uz: "Jo'nash oynasi boshlanishini to'liq kiriting (kun, oy, yil va vaqt).",
    ru: "Полностью укажите начало окна отправления (день, месяц, год и время).",
  },
  "app.validation.windowEnd": {
    uz: "Jo'nash oynasi tugashini to'liq kiriting (kun, oy, yil va vaqt).",
    ru: "Полностью укажите конец окна отправления (день, месяц, год и время).",
  },
  "app.validation.endAfterStart": {
    uz: "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak.",
    ru: "Время окончания должно быть позже времени начала.",
  },
  "app.validation.windowPast": {
    uz: "Jo'nash oynasi o'tib ketgan - kelajakdagi vaqtni tanlang.",
    ru: "Окно отправления уже прошло — выберите время в будущем.",
  },

  // --- toasts ---
  "app.toast.roleUnsupported": {
    uz: "Bu rol mobile ilova uchun mavjud emas",
    ru: "Эта роль недоступна в мобильном приложении",
  },
  "app.toast.searchRestarted": { uz: "Qidiruv qayta boshlandi", ru: "Поиск возобновлён" },
  "app.toast.intentUpdated": { uz: "Talab yangilandi", ru: "Запрос обновлён" },
  "app.toast.intentClosed": { uz: "Talab yopildi", ru: "Запрос закрыт" },

  // --- booking cancel form ---
  "app.bookingCancel.commentHint": {
    uz: "Telefon raqam va havolalar avtomatik yashiriladi.",
    ru: "Номера телефонов и ссылки скрываются автоматически.",
  },
} as const satisfies Record<string, Message>;
