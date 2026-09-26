/**
 * Q148: the driver's GPS publisher bar and the live map viewers see.
 *
 * Wording rules (§9, §10.4-§10.5): "sending" only while the phone really gave a position; no "GPS faol"; the web
 * client is said to work only while the app is open; the dot is "the vehicle carrying your booking", never the parcel.
 */
import type { Message } from "../messages";

export const liveTrackingMessages = {
  // --- driver: the publisher bar ---
  "driverTracking.idle": { uz: "Joylashuv yuborilmayapti", ru: "Местоположение не передаётся" },
  "driverTracking.idleHint": {
    uz: "Safar boshlandi. Mijozlar avtomobilni xaritada ko'rishi uchun joylashuvni yuborishni yoqing.",
    ru: "Поездка началась. Включите передачу местоположения, чтобы клиенты видели автомобиль на карте.",
  },
  "driverTracking.start": { uz: "Yoqish", ru: "Включить" },
  "driverTracking.stop": { uz: "To'xtatish", ru: "Остановить" },
  "driverTracking.retry": { uz: "Qayta urinish", ru: "Повторить" },
  "driverTracking.takeOver": { uz: "Shu telefondan yuborish", ru: "Передавать с этого телефона" },
  "driverTracking.starting": { uz: "Kuzatuv sessiyasi ochilmoqda...", ru: "Открываем сессию отслеживания..." },
  "driverTracking.sending": { uz: "Joylashuv yuborilmoqda", ru: "Местоположение передаётся" },
  "driverTracking.waitingFirstFix": {
    uz: "Telefon joylashuvi kutilmoqda",
    ru: "Ожидаем местоположение телефона",
  },
  "driverTracking.waitingFix": {
    uz: "Yangi joylashuv yo'q - oxirgisi {time} da",
    ru: "Нового местоположения нет - последнее в {time}",
  },
  "driverTracking.lastSent": { uz: "Serverga oxirgi yuborilgan: {time}", ru: "Последняя отправка на сервер: {time}" },
  "driverTracking.lowAccuracy": {
    uz: "Aniqlik past (±{meters} m) - ochiq joyda yaxshilanadi",
    ru: "Низкая точность (±{meters} м) - на открытом месте станет лучше",
  },
  "driverTracking.queuedOffline": {
    uz: "Internet yo'q: {count} ta nuqta telefonda kutmoqda, aloqa tiklanganda yuboriladi",
    ru: "Нет интернета: {count} точек ждут на телефоне и уйдут, когда связь вернётся",
  },
  "driverTracking.hidden": {
    uz: "Ilova fonda: brauzer joylashuvni to'xtatishi mumkin. Ilovani ochiq qoldiring.",
    ru: "Приложение в фоне: браузер может остановить геолокацию. Оставьте приложение открытым.",
  },
  "driverTracking.foregroundOnly": {
    uz: "Joylashuv faqat ilova ochiq va ekran yoniq turganda yuboriladi.",
    ru: "Местоположение передаётся, только пока приложение открыто и экран включён.",
  },
  "driverTracking.dropped": {
    uz: "{count} ta nuqta serverga yetib bormadi - bu oraliqda yo'l izi yo'q",
    ru: "{count} точек не дошли до сервера - в этом промежутке трека нет",
  },
  "driverTracking.permissionDenied": { uz: "Joylashuvga ruxsat berilmagan", ru: "Нет доступа к местоположению" },
  "driverTracking.permissionHint": {
    uz: "Chrome: manzil satridagi qulf belgisi → Ruxsatlar → Joylashuv → Ruxsat berish. Telefon sozlamalarida GPS ham yoqilgan bo'lsin. Ruxsat berilishi bilan yuborish o'zi davom etadi.",
    ru: "Chrome: значок замка в адресной строке → Разрешения → Местоположение → Разрешить. GPS в настройках телефона тоже должен быть включён. Как только доступ появится, передача продолжится сама.",
  },
  "driverTracking.permissionPrompt": {
    uz: "Brauzer joylashuvga ruxsat so'raydi - «Ruxsat berish»ni tanlang.",
    ru: "Браузер спросит доступ к местоположению - выберите «Разрешить».",
  },
  "driverTracking.unavailable": {
    uz: "Bu brauzer joylashuvni bera olmaydi",
    ru: "Этот браузер не умеет передавать местоположение",
  },
  "driverTracking.insecure": {
    uz: "Sahifa xavfsiz (HTTPS) manzilda ochilmagan - brauzer joylashuvni bermaydi",
    ru: "Страница открыта не по защищённому адресу (HTTPS) - браузер не даёт местоположение",
  },
  "driverTracking.stalled": {
    uz: "Telefon 1 daqiqadan beri joylashuv bermayapti: GPS yoqilganini va batareya tejash rejimi o'chiqligini tekshiring.",
    ru: "Телефон больше минуты не даёт местоположение: проверьте, что GPS включён, а режим энергосбережения выключен.",
  },
  "driverTracking.gapBackground": {
    uz: "{from}-{to}: ekran qulflangan yoki ilova fonda edi - bu oraliqda joylashuv yozilmadi",
    ru: "{from}-{to}: экран был заблокирован или приложение в фоне - в этот промежуток местоположение не записано",
  },
  "driverTracking.gapNoFix": {
    uz: "{from}-{to}: telefon joylashuv bermadi (GPS o'chiq yoki batareya tejash rejimi) - bu oraliqda yo'l izi yo'q",
    ru: "{from}-{to}: телефон не давал местоположение (GPS выключен или энергосбережение) - трека в этот промежуток нет",
  },
  "driverTracking.lowBattery": {
    uz: "Batareya {pct}%: tejash rejimi yoqilsa joylashuv sekinlashadi yoki to'xtaydi. Telefonni quvvatga ulang.",
    ru: "Батарея {pct}%: в режиме энергосбережения местоположение замедлится или остановится. Подключите зарядку.",
  },
  "driverTracking.noWakeLock": {
    uz: "Ekran o'zi o'chib qolishi mumkin - telefon sozlamalarida ekran o'chish vaqtini uzaytiring.",
    ru: "Экран может погаснуть сам - увеличьте время отключения экрана в настройках телефона.",
  },
  "driverTracking.error.disabled": {
    uz: "Bu yo'nalishda jonli kuzatuv hali yoqilmagan",
    ru: "На этом направлении отслеживание пока не включено",
  },
  "driverTracking.error.notRunning": {
    uz: "Safar hali boshlanmagan yoki tugagan",
    ru: "Поездка ещё не началась или уже завершена",
  },
  "driverTracking.error.network": {
    uz: "Serverga ulanib bo'lmadi. Internetni tekshiring.",
    ru: "Не удалось связаться с сервером. Проверьте интернет.",
  },
  "driverTracking.error.generic": {
    uz: "Kuzatuv sessiyasini ochib bo'lmadi",
    ru: "Не удалось открыть сессию отслеживания",
  },
  "driverTracking.superseded": {
    uz: "Joylashuv boshqa qurilma yoki oynadan yuborilmoqda",
    ru: "Местоположение передаётся с другого устройства или вкладки",
  },
  "driverTracking.closed": { uz: "Kuzatuv sessiyasi yopildi", ru: "Сессия отслеживания закрыта" },
  "driverTracking.unauthorized": {
    uz: "Tizimdan chiqilgan - joylashuv yuborilmayapti",
    ru: "Вы вышли из системы - местоположение не передаётся",
  },
  "driverTracking.stopped": { uz: "Joylashuv yuborish to'xtatildi", ru: "Передача местоположения остановлена" },

  // --- viewers: the live map ---
  "liveTracking.freshness.fresh": { uz: "Jonli joylashuv", ru: "Местоположение в реальном времени" },
  "liveTracking.freshness.delayed": { uz: "Joylashuv kechikmoqda", ru: "Местоположение с задержкой" },
  "liveTracking.freshness.lost": { uz: "Haydovchi telefoni bilan aloqa uzilgan", ru: "Связь с телефоном водителя потеряна" },
  "liveTracking.freshness.no_data": { uz: "Joylashuv hali kelmagan", ru: "Местоположение ещё не поступало" },
  "liveTracking.vehicle": { uz: "Buyurtmangizni olib ketayotgan avtomobil", ru: "Автомобиль с вашим заказом" },
  "liveTracking.lastPoint": { uz: "Oxirgi nuqta: {time}", ru: "Последняя точка: {time}" },
  "liveTracking.lowAccuracy": { uz: "aniqligi past", ru: "низкая точность" },
  "liveTracking.delayedHint": {
    uz: "Nuqta 30 soniyadan eski - avtomobil hozir boshqa joyda bo'lishi mumkin.",
    ru: "Точке больше 30 секунд - автомобиль сейчас может быть в другом месте.",
  },
  "liveTracking.lostHint": {
    uz: "2 daqiqadan beri yangi nuqta yo'q. Xaritada oxirgi ma'lum joy ko'rsatilgan.",
    ru: "Новых точек нет больше 2 минут. На карте - последнее известное место.",
  },
  "liveTracking.noPoint": {
    uz: "Haydovchi telefonidan hali joylashuv kelmadi. Kelishi bilan xaritada paydo bo'ladi.",
    ru: "С телефона водителя ещё не пришло местоположение. Оно появится на карте, как только придёт.",
  },
  "liveTracking.source": {
    uz: "Manba: haydovchining telefoni.",
    ru: "Источник: телефон водителя.",
  },
  "liveTracking.polling": {
    uz: "Har 15 soniyada yangilanadi.",
    ru: "Обновляется каждые 15 секунд.",
  },
  "liveTracking.gone": {
    uz: "Bu bron uchun jonli joylashuv endi mavjud emas.",
    ru: "Для этой брони местоположение больше недоступно.",
  },
} as const satisfies Record<string, Message>;
