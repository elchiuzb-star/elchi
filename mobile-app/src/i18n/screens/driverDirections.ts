/**
 * ADR-0027 (Q150-Q155): the driver's direction - "where from -> where to" - and everything the system does with it.
 * Same wording rules as messages.ts: say what happens, never promise what the server does not do.
 */
import type { Message } from "../messages";

export const driverDirectionsMessages = {
  // --- "Yo'nalishlarim" and the add form ---
  "dir.region": { uz: "Viloyat", ru: "Область" },
  "dir.district": { uz: "Tuman", ru: "Район" },
  "dir.regionPlaceholder": { uz: "Viloyatni tanlang", ru: "Выберите область" },
  "dir.districtPlaceholder": { uz: "Tumanni tanlang", ru: "Выберите район" },
  "dir.wholeCity": { uz: "Butun shahar", ru: "Весь город" },
  "dir.formHint": {
    uz: "Faqat yo'nalishni kiriting. Safar va jo'nash vaqtini tizim mijozlar so'roviga qarab o'zi tuzadi.", ru: "Укажите только направление. Поездку и время выезда система составит сама по заявкам клиентов.",
  },
  "dir.save": { uz: "Yo'nalishni saqlash", ru: "Сохранить направление" },
  "dir.added": { uz: "Yo'nalish qo'shildi", ru: "Направление добавлено" },
  "dir.noRoad": {
    uz: "Bu yo'nalishda hali ELCHI yo'li yo'q. Boshqa tumanni tanlab ko'ring.",
    ru: "На этом направлении пока нет маршрута ELCHI. Попробуйте другой район.",
  },
  "dir.exists": { uz: "Bu yo'nalish allaqachon qo'shilgan", ru: "Это направление уже добавлено" },
  "dir.via": { uz: "{names} orqali", ru: "через {names}" },
  "dir.capacity": { uz: "{seats} o'rin · {kg} kg yuk", ru: "Мест: {seats} · груз до {kg} кг" },
  "dir.statusActive": { uz: "Faol", ru: "Активно" },
  "dir.statusPaused": { uz: "To'xtatilgan", ru: "Приостановлено" },
  "dir.pause": { uz: "To'xtatish", ru: "Приостановить" },
  "dir.resume": { uz: "Faollashtirish", ru: "Возобновить" },
  "dir.archive": { uz: "O'chirish", ru: "Удалить" },
  "dir.archived": { uz: "Yo'nalish o'chirildi", ru: "Направление удалено" },
  "dir.updated": { uz: "Yo'nalish yangilandi", ru: "Направление обновлено" },
  "dir.trip": { uz: "Safar: {date} · {status} · {seats} o'rin band", ru: "Поездка: {date} · {status} · занято мест: {seats}" },
  "dir.noTrip": {
    uz: "Safar hali yo'q — birinchi taklifingiz safarni rejalashtiradi",
    ru: "Поездки пока нет — ваше первое предложение запланирует её",
  },
  "dir.openRequests": { uz: "Mos buyurtmalar", ru: "Подходящие заказы" },
  "dir.empty": { uz: "Hali yo'nalish yo'q", ru: "Направлений пока нет" },
  "dir.emptyHint": {
    uz: "Masalan: Toshkent → Qarshi. Yo'l bo'yidagi buyurtmalar ham ko'rinadi.",
    ru: "Например: Ташкент → Карши. Заказы по пути тоже будут видны.",
  },
  "dir.tripsTitle": { uz: "Safarlarim", ru: "Мои поездки" },
  "dir.tripsHint": {
    uz: "Safarlarni tizim takliflaringizdan tuzadi. Bort, jo'nash va yakunlash shu yerda.",
    ru: "Поездки система составляет из ваших предложений. Посадка, выезд и завершение — здесь.",
  },

  // --- the direction feed ---
  "dir.feedPick": { uz: "Yo'nalish", ru: "Направление" },
  "dir.day.today": { uz: "Bugun", ru: "Сегодня" },
  "dir.day.tomorrow": { uz: "Ertaga", ru: "Завтра" },
  "dir.day.week": { uz: "7 kun", ru: "7 дней" },
  "dir.group.fits": { uz: "Safaringizga mos", ru: "Подходит к вашей поездке" },
  "dir.group.fitsNote": { uz: "Mashina mijozga u so'ragan vaqtda yetadi.", ru: "Машина будет у клиента в запрошенное время." },
  "dir.group.new": { uz: "Yangi safar uchun", ru: "Для новой поездки" },
  "dir.group.newNote": {
    uz: "Birinchi taklif safarni shu mijoz vaqtiga rejalashtiradi.",
    ru: "Первое предложение запланирует поездку под время этого клиента.",
  },
  "dir.group.time": { uz: "Vaqti boshqa", ru: "Другое время" },
  "dir.group.timeNote": {
    uz: "Mijoz boshqa vaqt so'ragan. Taklifingiz vaqt taklifi bo'ladi — mijoz rozi bo'lsagina bron qilinadi.",
    ru: "Клиент просил другое время. Ваше предложение будет предложением времени — бронь только с согласия клиента.",
  },
  "dir.card.eta": { uz: "Mashina yetadi: {time}", ru: "Машина будет: {time}" },
  "dir.card.departure": { uz: "Jo'nash: {time}", ru: "Выезд: {time}" },
  "dir.card.asked": { uz: "Mijoz so'ragan: {start} – {end}", ru: "Клиент просил: {start} – {end}" },
  "dir.card.myOffer": { uz: "Taklifingiz yuborilgan", ru: "Ваше предложение отправлено" },
  "dir.noDirections": { uz: "Avval yo'nalish qo'shing", ru: "Сначала добавьте направление" },
  "dir.noDirectionsHint": {
    uz: "Yo'nalish qo'shsangiz, yo'l bo'yidagi buyurtmalar shu yerda chiqadi va safarni tizim o'zi tuzadi.",
    ru: "Добавьте направление — заказы по пути появятся здесь, а поездку система составит сама.",
  },
  "dir.paused": { uz: "Bu yo'nalish to'xtatilgan — buyurtmalar ko'rsatilmaydi.", ru: "Направление приостановлено — заказы не показываются." },
  "dir.feedEmpty": { uz: "Bu kunlarda mos buyurtma yo'q", ru: "На эти дни подходящих заказов нет" },
  "dir.districtSearch": { uz: "Tuman bo'yicha qidirish", ru: "Поиск по районам" },

  // --- the offer from a direction ---
  "dir.bid.timeProposal": {
    uz: "Mashina {time} da yetadi. Mijoz {start} – {end} so'ragan — bu vaqt taklifi bo'ladi.",
    ru: "Машина будет в {time}. Клиент просил {start} – {end} — это будет предложение времени.",
  },
  "dir.bid.proposeTime": { uz: "{time} ni taklif qilish", ru: "Предложить {time}" },
  "dir.bid.tripCreated": {
    uz: "Taklif yuborildi. Safar {time} da jo'nashga rejalashtirildi.",
    ru: "Предложение отправлено. Выезд запланирован на {time}.",
  },
  "dir.bid.tripRetimed": {
    uz: "Taklif yuborildi. Safar vaqti {time} ga o'zgartirildi.",
    ru: "Предложение отправлено. Время поездки изменено на {time}.",
  },
  "dir.bid.planned": { uz: "Tizim safarni {time} da jo'nashga rejalashtiradi.", ru: "Система запланирует выезд на {time}." },
  "dir.bid.tooFar": {
    uz: "Mashina bu mijozga u so'ragan vaqtdan juda uzoqda yetadi. Vaqt taklifi ko'pi bilan {early} soat oldin yoki {late} soat keyin bo'lishi mumkin.",
    ru: "Машина будет у клиента слишком далеко от запрошенного времени. Предложить время можно не более чем на {early} ч раньше или {late} ч позже.",
  },
  "dir.passed": { uz: "Bu joydan o'tib ketdingiz", ru: "Вы уже проехали это место" },

  // --- Q158: a trip read by districts, not by internal route nodes ---

  // --- the client's view of a driver's time proposal (Q153) ---
  "offer.timeProposal": {
    uz: "Haydovchi {time} da olishni taklif qilmoqda (siz {start} – {end} so'ragansiz)",
    ru: "Водитель предлагает забрать в {time} (вы просили {start} – {end})",
  },

  // --- error the dictionary did not have ---
  "error.ROUTE_CHANGED": {
    uz: "Safar marshruti yoki vaqti o'zgardi. Taklifni yangilang.",
    ru: "Маршрут или время поездки изменились. Обновите предложение.",
  },

  // --- admin: what drivers said they drive ---
  "admin.dir.title": { uz: "Haydovchi yo'nalishlari", ru: "Направления водителей" },
  "admin.nav.driverDirections": { uz: "Yo'nalishlar", ru: "Направления" },
  "admin.dir.refresh": { uz: "Yangilash", ru: "Обновить" },
  "admin.dir.hint": {
    uz: "Haydovchilar kiritgan yo'nalishlar. Safarni tizim mijozlarga berilgan takliflardan tuzadi (ADR-0027).",
    ru: "Направления, указанные водителями. Поездки система составляет из предложений клиентам (ADR-0027).",
  },
  "admin.dir.empty": { uz: "Yo'nalish yo'q", ru: "Направлений нет" },
  "admin.dir.driver": { uz: "Haydovchi", ru: "Водитель" },
  "admin.dir.ends": { uz: "Yo'nalish", ru: "Направление" },
  "admin.dir.trip": { uz: "Joriy safar", ru: "Текущая поездка" },
  "admin.dir.status": { uz: "Holat", ru: "Статус" },
  "dir.seatsBooked": { uz: "{seats} o'rin band", ru: "занято мест: {seats}" },
  "admin.dir.archivedStatus": { uz: "O'chirilgan", ru: "Удалено" },
} satisfies Record<string, Message>;
