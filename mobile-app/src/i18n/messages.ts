/**
 * The words this product says, in both languages.
 *
 * One entry per key, both languages side by side, so a translation can never drift into a separate file that
 * nobody updates. `messages.test.ts` enforces that every entry really has both.
 *
 * Wording rules that outrank literal translation (spec §9.2, §21.2):
 *   - a refusal says what happened and what can be done about it, never "try again" for a business rule;
 *   - nothing promises what the platform has not checked (a route, an arrival, an operator on the phone);
 *   - money words stay exact: "komissiya balansi" / "баланс комиссии" is not "earnings", and a fare paid in
 *     cash is never described as something ELCHI received.
 */

import { appCoreMessages } from "./screens/appCore";
import { entryMessages } from "./screens/entry";
import { orderFlowMessages } from "./screens/orderFlow";
import { bookingOpsMessages } from "./screens/bookingOps";
import { bookingViewMessages } from "./screens/bookingView";
import { driverSetupMessages } from "./screens/driverSetup";
import { driverWorkMessages } from "./screens/driverWork";
import { panelsAMessages } from "./screens/panelsA";
import { panelsBMessages } from "./screens/panelsB";
import { componentsMessages } from "./screens/components";
import { promoHelpersMessages } from "./screens/promoHelpers";
import { flowHelpersMessages } from "./screens/flowHelpers";
import { adr0026Messages } from "./screens/adr0026";
import { liveTrackingMessages } from "./screens/liveTracking";

export interface Message {
  uz: string;
  ru: string;
}

/** Shared vocabulary, codes and statuses: words more than one screen says. */
const baseMessages = {
  // --- shared vocabulary ----------------------------------------------------------------------------------
  "common.back": { uz: "Orqaga", ru: "Назад" },
  "common.cancel": { uz: "Bekor qilish", ru: "Отмена" },
  "common.confirm": { uz: "Tasdiqlash", ru: "Подтвердить" },
  "common.continue": { uz: "Davom etish", ru: "Продолжить" },
  "common.save": { uz: "Saqlash", ru: "Сохранить" },
  "common.send": { uz: "Yuborish", ru: "Отправить" },
  "common.close": { uz: "Yopish", ru: "Закрыть" },
  "common.delete": { uz: "O'chirish", ru: "Удалить" },
  "common.retry": { uz: "Qayta urinish", ru: "Повторить" },
  "common.loading": { uz: "Yuklanmoqda...", ru: "Загрузка..." },
  "common.sending": { uz: "Yuborilmoqda...", ru: "Отправляется..." },
  "common.checking": { uz: "Tekshirilmoqda...", ru: "Проверяется..." },
  "common.none": { uz: "Yo'q", ru: "Нет" },
  "common.dash": { uz: "-", ru: "-" },
  "common.reason": { uz: "Sabab", ru: "Причина" },
  "common.price": { uz: "Narx", ru: "Цена" },
  "common.total": { uz: "Jami", ru: "Итого" },
  "common.seat": { uz: "o'rin", ru: "место" },
  "common.perSeat": { uz: "bir o'rin uchun", ru: "за место" },
  "common.soum": { uz: "so'm", ru: "сум" },

  // --- error codes ----------------------------------------------------------------------------------------
  // Shared by the v1 and v2 maps: the same code means the same thing to a person on either engine.
  "error.fallback": { uz: "Xatolik yuz berdi", ru: "Произошла ошибка" },
  "error.offline": { uz: "Internet aloqasi yo'q", ru: "Нет соединения с интернетом" },
  "error.VALIDATION_ERROR": { uz: "Ma'lumotlarni tekshiring", ru: "Проверьте введённые данные" },
  "error.UNAUTHORIZED": { uz: "Avval tizimga kiring", ru: "Сначала войдите в систему" },
  "error.FORBIDDEN": { uz: "Ruxsat yo'q", ru: "Нет доступа" },
  "error.NOT_FOUND": { uz: "Topilmadi", ru: "Не найдено" },
  "error.CAPABILITY_REQUIRED": { uz: "Bu amal uchun ruxsatingiz yo'q", ru: "У вас нет прав на это действие" },
  "error.RATE_LIMITED": { uz: "Juda tez-tez urinyapsiz, biroz kuting", ru: "Слишком часто — подождите немного" },
  "error.SERVICE_UNAVAILABLE": { uz: "Xizmat vaqtincha ishlamayapti", ru: "Сервис временно недоступен" },
  "error.SERVER_ERROR": { uz: "Xatolik yuz berdi", ru: "Произошла ошибка" },
  "error.VERSION_CONFLICT": {
    uz: "Ma'lumot yangilangan — ekranni yangilang va qayta urinib ko'ring",
    ru: "Данные обновились — обновите экран и повторите",
  },
  "error.FEATURE_DISABLED": { uz: "Bu xizmat shu yo'nalishda hali ochilmagan", ru: "Эта услуга на данном направлении пока не открыта" },
  "error.CLIENT_UPGRADE_REQUIRED": { uz: "Ilovani yangilang", ru: "Обновите приложение" },
  "error.PROMO_QUOTE_STALE": {
    uz: "Bonus summasi o'zgardi — yangi hisobni ko'rib, qayta tasdiqlang",
    ru: "Сумма бонуса изменилась — посмотрите новый расчёт и подтвердите снова",
  },
  "error.PROMO_CONSENT_REQUIRED": {
    uz: "Yangi naqd summani tasdiqlashingiz kerak",
    ru: "Нужно подтвердить новую сумму наличных",
  },
  "promoNotice.driverAckRequired": {
    uz: "O'zgarishdan keyingi hisobingizni ko'rib, tasdiqlang",
    ru: "Посмотрите свой расчёт после изменения и подтвердите",
  },
  "promoNotice.counterpartyStale": {
    uz: "Qarshi tomon bonus shartlarini o'z ilovasidan qayta tasdiqlashi kerak. Taklifning o'zi o'zgarmadi.",
    ru: "Другая сторона должна заново подтвердить условия бонуса в своём приложении. Само предложение не изменилось.",
  },
  "error.PROMO_PARAMETERS_UNSET": { uz: "Kampaniya shartlari hali to'liq belgilanmagan", ru: "Условия кампании ещё не заданы полностью" },
  "error.PROMO_BUDGET_EXHAUSTED": { uz: "Kampaniya byudjeti tugagan", ru: "Бюджет кампании исчерпан" },
  "error.TRIP_INTENT_BOOKED": {
    uz: "Bu safar talabi bo'yicha bron allaqachon tanlangan - boshqa takliflar yopilgan",
    ru: "По этому запросу бронь уже выбрана - остальные предложения закрыты",
  },
  "error.TRIP_INTENT_CHANGED": {
    uz: "Siz talabni o'zgartirgansiz - eski taklif qabul qilinmaydi, yangisini yuboring",
    ru: "Вы изменили запрос - старое предложение не принимается, отправьте новое",
  },
  "error.TRIP_INTENT_OFFERS_AFFECTED": {
    uz: "Bu o'zgarish ochiq takliflarni yopadi - tasdiqlang",
    ru: "Это изменение закроет открытые предложения - подтвердите",
  },
  "error.TRIP_INTENT_EXPIRED": {
    uz: "Safar vaqti o'tib ketgan - sanani yangilang",
    ru: "Время поездки прошло - обновите дату",
  },
  "error.PROMO_BUDGET_BELOW_COMMITMENT": {
    uz: "Byudjetni sarflangan summa va majburiyatlardan pastga kamaytirib bo'lmaydi",
    ru: "Бюджет нельзя уменьшить ниже потраченного и обязательств",
  },
  "error.REFERRAL_CODE_INVALID": { uz: "Bunday taklif kodi topilmadi", ru: "Такой код приглашения не найден" },
  "error.REFERRAL_SELF_REFERRAL": { uz: "O'zingizning kodingizni kiritib bo'lmaydi", ru: "Нельзя ввести собственный код" },
  "error.REFERRAL_ALREADY_ATTRIBUTED": {
    uz: "Sizda allaqachon taklif kodi bor — u almashtirilmaydi",
    ru: "У вас уже есть код приглашения — он не заменяется",
  },
  "error.REFERRAL_WINDOW_CLOSED": {
    uz: "Taklif kodini kiritish muddati o'tgan",
    ru: "Срок для ввода кода приглашения истёк",
  },
  "error.REFERRAL_NOT_ELIGIBLE": { uz: "Bu taklif sizga to'g'ri kelmaydi", ru: "Это предложение вам не подходит" },
  "error.IDEMPOTENCY_KEY_REUSED": { uz: "Bu amal boshqa ma'lumot bilan yuborilgan", ru: "Это действие уже отправлено с другими данными" },
  "error.IDEMPOTENCY_IN_PROGRESS": { uz: "Oldingi so'rov hali bajarilmoqda — biroz kuting", ru: "Предыдущий запрос ещё выполняется — подождите" },
  "error.INVALID_STATE_TRANSITION": { uz: "Bu amalni hozirgi holatda bajarib bo'lmaydi", ru: "В текущем состоянии это действие недоступно" },
  "error.INVALID_CURSOR": { uz: "Ro'yxatni boshidan yuklang", ru: "Загрузите список сначала" },

  "error.ROLE_MISMATCH": { uz: "Bu telefon raqam boshqa rolda ro'yxatdan o'tgan", ru: "Этот номер зарегистрирован в другой роли" },
  "error.OTP_INVALID": { uz: "Kod noto'g'ri", ru: "Неверный код" },
  "error.OTP_EXPIRED": { uz: "Kod muddati tugagan", ru: "Срок действия кода истёк" },
  "error.OTP_USED": { uz: "Kod allaqachon ishlatilgan", ru: "Код уже использован" },
  "error.OTP_RESEND_TOO_SOON": { uz: "Kodni qayta yuborishdan oldin biroz kuting", ru: "Подождите перед повторной отправкой кода" },
  "error.OTP_TOO_MANY_ATTEMPTS": { uz: "Juda ko'p urinish bo'ldi", ru: "Слишком много попыток" },
  "error.OTP_SEND_LIMIT_EXCEEDED": {
    uz: "Kod olish urinishlari ko'payib ketdi. Keyinroq urinib ko'ring",
    ru: "Превышено число запросов кода. Попробуйте позже",
  },
  "error.INVALID_PHONE": { uz: "Telefon raqam noto'g'ri", ru: "Неверный номер телефона" },
  "error.USER_BLOCKED": { uz: "Foydalanuvchi bloklangan", ru: "Пользователь заблокирован" },
  "error.USER_INACTIVE": { uz: "Foydalanuvchi faol emas", ru: "Пользователь неактивен" },

  "error.DRIVER_NOT_APPROVED": { uz: "Profil tasdiqlanmagan", ru: "Профиль не подтверждён" },
  "error.DRIVER_NOT_AVAILABLE": { uz: "Faol holatni yoqing", ru: "Включите статус «на линии»" },
  "error.DRIVER_DOCUMENTS_INCOMPLETE": { uz: "Barcha kerakli hujjatlarni yuklang", ru: "Загрузите все необходимые документы" },
  "error.DRIVER_DOCUMENT_INVALID_TYPE": { uz: "Hujjat turi noto'g'ri", ru: "Неверный тип документа" },
  "error.DRIVER_DOCUMENT_TOO_LARGE": { uz: "Hujjat hajmi juda katta", ru: "Файл документа слишком большой" },
  "error.DRIVER_NOT_ELIGIBLE": {
    uz: "Hisobingiz yangi ish qabul qila olmaydi — profil va hujjatlarni tekshiring",
    ru: "Аккаунт не может брать новые заказы — проверьте профиль и документы",
  },
  "error.VEHICLE_NOT_ELIGIBLE": { uz: "Avtomobil tasdiqlanmagan yoki sig'imi yetmaydi", ru: "Автомобиль не подтверждён или не хватает вместимости" },
  // Q94: the car is entered once. Both refusals mean the same thing to a driver, so both name the way out.
  "error.DRIVER_VEHICLE_LOCKED": {
    uz: "Avtomobil ma'lumotlari bir marta kiritiladi — o'zgartirish uchun operator yoki adminga murojaat qiling",
    ru: "Данные автомобиля вводятся один раз — для изменения обратитесь к оператору или администратору",
  },

  "error.CITY_INACTIVE": { uz: "Tanlangan shahar faol emas", ru: "Выбранный город неактивен" },
  "error.DISTRICT_REQUIRED": { uz: "Tumanni tanlang", ru: "Выберите район" },
  "error.DISTRICT_CITY_MISMATCH": { uz: "Tuman tanlangan shaharga tegishli emas", ru: "Район не относится к выбранному городу" },
  "error.DISTRICT_INACTIVE": { uz: "Tanlangan tuman faol emas", ru: "Выбранный район неактивен" },
  "error.ROUTE_TARIFF_NOT_FOUND": { uz: "Bu yo'nalish uchun narx topilmadi", ru: "Для этого направления цена не найдена" },
  "error.ROUTE_NOT_MATCHED": { uz: "Bu buyurtma sizning yo'nalishingizga mos emas", ru: "Этот заказ не подходит вашему маршруту" },

  "error.LISTING_NOT_OPEN": { uz: "E'lon endi ochiq emas", ru: "Объявление больше не открыто" },
  "error.LISTING_EXPIRED": { uz: "E'lon muddati tugagan", ru: "Срок объявления истёк" },
  "error.LISTING_INCOMPLETE": { uz: "E'lon to'liq emas — barcha maydonlarni to'ldiring", ru: "Объявление неполное — заполните все поля" },
  "error.DUPLICATE_LISTING": { uz: "Bunday e'lon allaqachon bor", ru: "Такое объявление уже есть" },
  "error.SELF_DEALING_FORBIDDEN": { uz: "O'z e'loningizga taklif yubora olmaysiz", ru: "Нельзя отправить предложение на собственное объявление" },
  "error.NOT_PROPOSAL_RECIPIENT": { uz: "O'z taklifingizni o'zingiz qabul qila olmaysiz", ru: "Нельзя принять собственное предложение" },
  "error.PROPOSAL_CHANGED": { uz: "Taklif o'zgargan — yangi shartlarni ko'ring", ru: "Предложение изменилось — посмотрите новые условия" },
  "error.PROPOSAL_EXPIRED": { uz: "Taklif muddati tugagan", ru: "Срок предложения истёк" },
  "error.NEGOTIATION_LIMIT_REACHED": { uz: "Narxni o'zgartirish imkoni tugadi", ru: "Лимит изменения цены исчерпан" },
  "error.PRICE_BASIS_NOT_ALLOWED": { uz: "Bu xizmat uchun narx turi mos emas", ru: "Для этой услуги такой тип цены не подходит" },
  "error.QUANTITY_MISMATCH": { uz: "Miqdor mos kelmadi", ru: "Количество не совпадает" },
  // Q90: only an `enforced` reference refuses a price, and that is an admin-imposed safety limit.
  "error.PRICE_OUT_OF_BAND": {
    uz: "Bu narx administrator belgilagan qat'iy chegaradan tashqarida",
    ru: "Эта цена вне жёсткого предела, заданного администратором",
  },

  "error.CAPACITY_UNAVAILABLE": { uz: "Bo'sh o'rin qolmadi", ru: "Свободных мест не осталось" },
  "error.CARGO_LIMIT_EXCEEDED": { uz: "Safarda yuk uchun joy yetmaydi", ru: "В поездке не хватает места для груза" },
  "error.TIME_WINDOW_CONFLICT": { uz: "Safar vaqti mijoz so'ragan oynaga to'g'ri kelmaydi", ru: "Время поездки не совпадает с запрошенным окном" },
  "error.BOOKING_CUTOFF_PASSED": { uz: "Bron muddati o'tgan", ru: "Время бронирования прошло" },
  "error.ROUTE_MISMATCH": { uz: "Bu joy safar marshrutiga mos kelmadi", ru: "Это место не совпадает с маршрутом поездки" },
  "error.ROUTING_UNAVAILABLE": {
    uz: "Marshrut hisoblanmadi — faqat tasdiqlangan bekatlar ko'rsatilmoqda",
    ru: "Маршрут не рассчитан — показаны только подтверждённые остановки",
  },
  "error.CORRIDOR_NOT_ACTIVE": { uz: "Bu yo'nalish hozir faol emas", ru: "Это направление сейчас неактивно" },
  "error.TRIP_NOT_STARTED": { uz: "Avval safarni boshlang", ru: "Сначала начните поездку" },
  "error.TRIP_STOPS_LOCKED": { uz: "Bronlar bor — bekatlarni o'zgartirib bo'lmaydi", ru: "Есть брони — остановки изменить нельзя" },
  "error.AMENDMENT_CONFLICT": { uz: "O'zgartirish so'rovi allaqachon bor", ru: "Запрос на изменение уже есть" },

  "error.PROOF_INVALID": { uz: "Kod noto'g'ri", ru: "Неверный код" },
  "error.PROOF_ATTEMPTS_EXCEEDED": { uz: "Kod urinishlari tugadi — operatorga murojaat qiling", ru: "Попытки исчерпаны — обратитесь к оператору" },
  "error.PROOF_REISSUE_LIMITED": { uz: "Kodni qayta yuborish chegarasiga yetdingiz", ru: "Достигнут предел повторной отправки кода" },
  "error.NO_SHOW_REVIEW_PENDING": { uz: "Operator ko'rib chiqmoqda", ru: "Оператор рассматривает" },

  "error.INSUFFICIENT_COMMISSION_BALANCE": {
    uz: "Komissiya balansi yetarli emas — balansni to'ldiring",
    ru: "Недостаточно баланса комиссии — пополните баланс",
  },
  "error.TOPUP_REFERENCE_DUPLICATE": { uz: "Bu to'lov ma'lumoti allaqachon kiritilgan", ru: "Эти платёжные данные уже внесены" },
  "error.PARCEL_POLICY_UNCONFIRMED": {
    uz: "Pochta qoidalari tasdiqlanmagan — hozircha yangi bron ochib bo'lmaydi",
    ru: "Правила перевозки не подтверждены — новую бронь пока открыть нельзя",
  },

  "error.TRACKING_WINDOW_NOT_OPEN": { uz: "Jonli joylashuv hozir ko'rinmaydi", ru: "Геопозиция сейчас недоступна" },
  "error.TRACKING_SESSION_CLOSED": { uz: "Kuzatuv sessiyasi yopilgan", ru: "Сессия отслеживания закрыта" },

  "error.DISPUTE_ALREADY_OPEN": { uz: "Bu buyurtma bo'yicha nizo allaqachon ochiq", ru: "По этому заказу спор уже открыт" },
  "error.RATING_NOT_ALLOWED": { uz: "Hozir baho berib bo'lmaydi", ru: "Сейчас оценку поставить нельзя" },
  "error.RATING_ALREADY_EXISTS": { uz: "Siz allaqachon baho bergansiz", ru: "Вы уже поставили оценку" },
  "error.SAVED_SEARCH_LIMIT_REACHED": { uz: "Saqlangan yo'nalishlar soni chegarasiga yetdingiz", ru: "Достигнут предел сохранённых направлений" },
  "error.CHAT_CLOSED": { uz: "Yozishma yopilgan", ru: "Переписка закрыта" },
  "error.PRODUCTION_INVARIANTS_FAILED": { uz: "Xizmat vaqtincha mavjud emas", ru: "Сервис временно недоступен" },

  // --- warnings (a successful action with something worth saying) ------------------------------------------
  "warning.CONTACT_INFO_MASKED": {
    uz: "Aloqa ma'lumotlari yashirildi — kelishuv ilova ichida bo'ladi",
    ru: "Контакты скрыты — договорённость проходит внутри приложения",
  },
  "warning.PROOF_CODE_MASKED": { uz: "Kod chatda yashirildi — uni faqat yuzma-yuz ayting", ru: "Код скрыт в чате — называйте его только лично" },
  "warning.ROUTING_UNAVAILABLE": { uz: "Marshrut o'lchanmadi — faqat tasdiqlangan bekatlar", ru: "Маршрут не измерен — только подтверждённые остановки" },
  "warning.PRICE_OUTSIDE_REFERENCE": {
    uz: "Bu narx yo'nalish uchun odatdagi oraliqdan tashqarida — taklif yuborildi, lekin bir ko'rib chiqing",
    ru: "Цена вне обычного диапазона для направления — предложение отправлено, но стоит перепроверить",
  },
  "warning.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY": {
    uz: "Yetkazish kodini faqat qabul qiluvchiga bering",
    ru: "Код вручения сообщайте только получателю",
  },

  // --- booking, order and listing statuses -----------------------------------------------------------------
  "status.draft": { uz: "Qoralama", ru: "Черновик" },
  "status.published": { uz: "E'lon qilingan", ru: "Опубликовано" },
  "status.bidding": { uz: "Takliflar bor", ru: "Есть предложения" },
  "status.accepted": { uz: "Haydovchi tanlangan", ru: "Водитель выбран" },
  "status.picked_up": { uz: "Olib ketildi", ru: "Забрано" },
  "status.in_transit": { uz: "Yo'lda", ru: "В пути" },
  "status.delivered": { uz: "Yetkazildi", ru: "Доставлено" },
  "status.confirmed": { uz: "Tasdiqlandi", ru: "Подтверждено" },
  "status.cancelled": { uz: "Bekor qilingan", ru: "Отменено" },
  "status.disputed": { uz: "Nizo ochilgan", ru: "Открыт спор" },
  "status.paused": { uz: "To'xtatilgan", ru: "Приостановлено" },
  "status.pending": { uz: "Kutilmoqda", ru: "Ожидает" },
  "status.approved": { uz: "Tasdiqlangan", ru: "Подтверждено" },
  "status.rejected": { uz: "Rad etilgan", ru: "Отклонено" },
  "status.proposed": { uz: "Javob kutilmoqda", ru: "Ожидает ответа" },
  "status.withdrawn": { uz: "Qaytarib olingan", ru: "Отозвано" },
  "status.fulfilled": { uz: "Bajarilgan", ru: "Выполнено" },
  "status.expired": { uz: "Muddati tugagan", ru: "Срок истёк" },
  "status.completed": { uz: "Yakunlangan", ru: "Завершено" },
  "status.awaiting_pickup": { uz: "Olib ketish kutilmoqda", ru: "Ожидает подачи" },
  "status.boarding": { uz: "Chiqish boshlandi", ru: "Посадка началась" },
  "status.in_progress": { uz: "Yo'lda", ru: "В пути" },
  "status.interrupted": { uz: "To'xtatilgan", ru: "Прервано" },
  "status.no_show": { uz: "Kelmadi", ru: "Не явился" },

  // --- match types (§8.2) ----------------------------------------------------------------------------------
  "match.exact": { uz: "Bekat mos", ru: "Остановка совпадает" },
  // Not "on the way": the place projects onto the road the driver already drives. What happens at the pickup
  // is still what the two of them agree - the app must not promise a detour it has not measured (Q46).
  "match.on_route": { uz: "Yo'l yo'nalishida", ru: "По направлению маршрута" },
  "match.detour": { uz: "Chetga chiqish", ru: "С заездом" },
  "match.alternative": { uz: "Muqobil", ru: "Альтернатива" },
  // The alternative group gets its own heading and its own sentence: "Muqobil" alone does not tell a driver
  // whether to look at the clock or at the map (§6.4).
  "match.alternativesTitle": { uz: "Tavsiya etilgan e'lonlar", ru: "Рекомендованные объявления" },
  "match.alternativesNote": {
    uz: "Bular aniq so'rovingizga to'liq mos emas, lekin yaqin. Taklif yuborishdan oldin vaqt va joyni tekshiring.",
    ru: "Это не полное совпадение с вашим запросом, но близкие варианты. Проверьте время и место перед предложением.",
  },
  "match.reason.time_differs": { uz: "Vaqti boshqa", ru: "Другое время" },
  "match.reason.nearby_stop": { uz: "Yaqin bekat", ru: "Ближайшая остановка" },
  "match.confirmedStopsNote": {
    uz:
      "Mosliklar tasdiqlangan bekatlar bo'yicha hisoblangan. Haydovchining yo'ldan chetga chiqishi hisoblanmagan — " +
      "aniq uchrashuv joyini taklif yozishmasida kelishasiz.",
    ru:
      "Совпадения рассчитаны по подтверждённым остановкам. Заезд водителя в сторону не рассчитывался — " +
      "точное место встречи вы согласуете в переписке по предложению.",
  },

  // --- vehicles, proofs, trips -----------------------------------------------------------------------------
  "vehicleStatus.pending": { uz: "Tekshiruvda", ru: "На проверке" },
  "vehicleStatus.approved": { uz: "Tasdiqlangan", ru: "Подтверждён" },
  "vehicleStatus.rejected": { uz: "Rad etilgan", ru: "Отклонён" },
  "vehicleStatus.expired": { uz: "Muddati tugagan", ru: "Срок истёк" },

  "proofCode.boarding_code": { uz: "Chiqish kodi", ru: "Код посадки" },
  "proofCode.pickup_code": { uz: "Topshirish kodi", ru: "Код передачи" },
  "proofCode.delivery_code": { uz: "Yetkazish kodi", ru: "Код вручения" },
  "proofCode.return_code": { uz: "Qaytarish kodi", ru: "Код возврата" },

  "tripStatus.planned": { uz: "Rejalashtirilgan", ru: "Запланирована" },
  "tripStatus.boarding": { uz: "Chiqish boshlandi", ru: "Посадка началась" },
  "tripStatus.in_progress": { uz: "Yo'lda", ru: "В пути" },
  "tripStatus.completed": { uz: "Yakunlangan", ru: "Завершена" },
  "tripStatus.cancelled": { uz: "Bekor qilingan", ru: "Отменена" },
  "tripStatus.interrupted": { uz: "To'xtatilgan", ru: "Прервана" },

  "tripAction.start_boarding": { uz: "Chiqishni boshlash", ru: "Начать посадку" },
  "tripAction.depart": { uz: "Yo'lga chiqdim", ru: "Выехал" },
  "tripAction.complete": { uz: "Safarni yakunlash", ru: "Завершить поездку" },

  // --- tracking --------------------------------------------------------------------------------------------
  "trackingWindow.not_yet_open": { uz: "Jonli joylashuv xizmat boshlanganda ochiladi.", ru: "Геопозиция откроется с началом услуги." },
  "trackingWindow.parcel_not_picked_up": {
    uz: "Jonli joylashuv posilka olib ketilgandan keyin ko'rinadi.",
    ru: "Геопозиция появится после того, как посылку заберут.",
  },
  "trackingWindow.booking_finished": { uz: "Buyurtma yakunlangan — jonli joylashuv yopildi.", ru: "Заказ завершён — геопозиция закрыта." },
  "trackingWindow.trip_finished": { uz: "Safar yakunlangan — jonli joylashuv yopildi.", ru: "Поездка завершена — геопозиция закрыта." },
  "trackingWindow.open": { uz: "Hozircha nuqta kelmadi.", ru: "Точка пока не поступила." },

  "trackingFreshness.fresh": { uz: "hozirgi", ru: "актуально" },
  "trackingFreshness.delayed": { uz: "kechikmoqda", ru: "с задержкой" },
  "trackingFreshness.lost": { uz: "aloqa uzilgan", ru: "связь потеряна" },
  "trackingFreshness.no_data": { uz: "ma'lumot yo'q", ru: "данных нет" },

  // --- proposals and disputes -------------------------------------------------------------------------------
  "proposalStatus.superseded": { uz: "yangilangan", ru: "заменено" },
  "proposalStatus.accepted": { uz: "qabul qilingan", ru: "принято" },
  "proposalStatus.rejected": { uz: "rad etilgan", ru: "отклонено" },
  "proposalStatus.withdrawn": { uz: "qaytarib olingan", ru: "отозвано" },
  "proposalStatus.expired": { uz: "muddati tugagan", ru: "срок истёк" },

  "disputeType.service": { uz: "Xizmat sifati", ru: "Качество услуги" },
  "disputeType.no_show": { uz: "Kelmadi", ru: "Не явился" },
  "disputeType.payment": { uz: "To'lov bo'yicha kelishmovchilik", ru: "Разногласие по оплате" },
  "disputeType.delivery": { uz: "Yetkazishda muammo", ru: "Проблема с доставкой" },
  "disputeType.safety": { uz: "Xavfsizlik", ru: "Безопасность" },
  "disputeType.other": { uz: "Boshqa muammo", ru: "Другая проблема" },

  "disputeStatus.open": { uz: "ochiq", ru: "открыт" },
  "disputeStatus.under_review": { uz: "ko'rib chiqilmoqda", ru: "на рассмотрении" },
  "disputeStatus.resolved": { uz: "hal qilindi", ru: "решён" },
  "disputeStatus.rejected": { uz: "rad etildi", ru: "отклонён" },

  "disputeResolution.service_confirmed": { uz: "Xizmat ko'rsatilgani tasdiqlandi", ru: "Подтверждено, что услуга оказана" },
  "disputeResolution.service_not_provided": { uz: "Xizmat ko'rsatilmagani tasdiqlandi", ru: "Подтверждено, что услуга не оказана" },
  "disputeResolution.paid_confirmed": { uz: "To'lov qilingani tasdiqlandi", ru: "Подтверждено, что оплата произведена" },
  "disputeResolution.unpaid_confirmed": { uz: "To'lov qilinmagani tasdiqlandi", ru: "Подтверждено, что оплата не произведена" },
  "disputeResolution.commission_adjusted": { uz: "Komissiya tuzatildi", ru: "Комиссия скорректирована" },
  "disputeResolution.no_action": { uz: "O'zgarish talab qilinmadi", ru: "Изменения не потребовались" },
  "disputeResolution.other": { uz: "Boshqa qaror", ru: "Иное решение" },

  // --- listing statuses (a listing is "on the market", which is not the same as an order being "published") -
  "listingStatus.draft": { uz: "Qoralama", ru: "Черновик" },
  "listingStatus.published": { uz: "Bozorda", ru: "На рынке" },
  "listingStatus.paused": { uz: "To'xtatilgan", ru: "Приостановлено" },
  "listingStatus.fulfilled": { uz: "Yakunlangan", ru: "Завершено" },
  "listingStatus.expired": { uz: "Muddati tugagan", ru: "Срок истёк" },
  "listingStatus.cancelled": { uz: "Bekor qilingan", ru: "Отменено" },

  // Q98: a count of people, so zero is a real and useful answer - "nobody has looked yet" tells the owner the
  // route or the window is wrong, where a low number with proposals would mean the price is.
  "listing.viewsSuffix": { uz: "ta ko'rish", ru: "просмотров" },
  "listing.viewsNone": { uz: "Hali hech kim ko'rmagan", ru: "Пока никто не смотрел" },

  // --- chat (§16, ADR-0020) ----------------------------------------------------------------------------------
  // A quick reply is a sentence, not a command: it never changes what was agreed (§16). `price_agreed` is
  // deliberately absent from the booking chat - by then the price is settled, and offering it back would
  // invite exactly the haggling the negotiation flow exists to keep out of here.
  "quickReply.clarify_stop": { uz: "Bekatni aniqlashtiraylik", ru: "Уточним место" },
  "quickReply.arriving_in_5_min": { uz: "5 daqiqada yetaman", ru: "Буду через 5 минут" },
  "quickReply.at_stop": { uz: "Bekatdaman", ru: "Я на месте" },
  "quickReply.price_agreed": { uz: "Narxga roziman", ru: "Согласен с ценой" },

  "chat.closedTitle": { uz: "Suhbat yopildi", ru: "Чат закрыт" },
  "chat.closedBody": {
    uz: "Safar yakunlangani uchun yangi xabar yuborib bo'lmaydi. Yozishmalar o'qish uchun ochiq qoladi.",
    ru: "Поездка завершена, новые сообщения отправить нельзя. Переписка остаётся доступной для чтения.",
  },
  "chat.closesSoon": { uz: "Suhbat shu vaqtgacha ochiq:", ru: "Чат открыт до:" },

  // --- driver documents (§17.1) ------------------------------------------------------------------------------
  "docType.passport": { uz: "Pasport", ru: "Паспорт" },
  "docType.selfie": { uz: "Selfi", ru: "Селфи" },
  "docType.license": { uz: "Haydovchilik guvohnomasi", ru: "Водительское удостоверение" },
  "docType.car_document": { uz: "Avtomobil hujjati", ru: "Документ на автомобиль" },
  "docType.car_photo": { uz: "Avtomobil rasmi", ru: "Фото автомобиля" },

  // What exactly has to be in the frame, so the slot name is not the only thing a driver has to go on.
  "docHint.passport": { uz: "Pasport yoki ID karta ma'lumot sahifasi", ru: "Страница с данными паспорта или ID-карты" },
  "docHint.selfie": { uz: "Pasportingizni ushlab turgan selfi", ru: "Селфи с паспортом в руке" },
  "docHint.license": { uz: "Haydovchilik guvohnomasining old tomoni", ru: "Лицевая сторона водительского удостоверения" },
  "docHint.car_document": { uz: "Texnik pasport (avtomobil guvohnomasi)", ru: "Техпаспорт (свидетельство о регистрации)" },
  "docHint.car_photo": { uz: "Avtomobil davlat raqami ko'rinadigan rasm", ru: "Фото автомобиля, где виден госномер" },

  // Per-slot upload state, so the driver can see which item is still missing (§17.1).
  "docState.missing": { uz: "Yuklanmagan", ru: "Не загружено" },
  "docState.pending": { uz: "Tekshiruvda", ru: "На проверке" },
  "docState.approved": { uz: "Tasdiqlangan", ru: "Подтверждено" },
  "docState.rejected": { uz: "Rad etilgan", ru: "Отклонено" },

  // --- U6: the trust group on a competing offer; never a number, always read with the count ------------------
  "ratingBucket.new_verified": { uz: "Yangi haydovchi", ru: "Новый водитель" },
  "ratingBucket.good": { uz: "Yaxshi baholangan", ru: "Хорошие оценки" },
  "ratingBucket.mixed": { uz: "Aralash baholar", ru: "Смешанные оценки" },
  "ratingBucket.low": { uz: "Past baholar", ru: "Низкие оценки" },

  "vehicleClass.car": { uz: "Yengil avtomobil", ru: "Легковой автомобиль" },
  "vehicleClass.minivan": { uz: "Miniven", ru: "Минивэн" },
  "vehicleClass.minibus": { uz: "Mikroavtobus", ru: "Микроавтобус" },

  // --- booking cancel (B3): the pilot has no penalty (Q45); a pending no-show review blocks it (Q7/Q19) -------
  "bookingCancel.button": { uz: "Bronni bekor qilish", ru: "Отменить бронь" },
  "bookingCancel.title": { uz: "Bronni bekor qilasizmi?", ru: "Отменить бронь?" },
  "bookingCancel.body": {
    uz: "Bron yopiladi va o'rin bo'shatiladi. Pilot davrida jarima yo'q. Ikkinchi tomonga xabar boradi.",
    ru: "Бронь закроется, место освободится. В пилотный период штрафа нет. Другая сторона получит уведомление.",
  },
  "bookingCancel.reasonLabel": { uz: "Sabab", ru: "Причина" },
  "bookingCancel.commentLabel": { uz: "Izoh (ixtiyoriy)", ru: "Комментарий (необязательно)" },
  "bookingCancel.confirm": { uz: "Ha, bekor qilish", ru: "Да, отменить" },
  "bookingCancel.keep": { uz: "Bronni saqlash", ru: "Оставить бронь" },
  "bookingCancel.done": { uz: "Bron bekor qilindi", ru: "Бронь отменена" },
  "bookingCancel.reviewPending": {
    uz: "Operator «kelmadi» xabarini ko'rib chiqmoqda — shu vaqtda bronni faqat operator bekor qila oladi.",
    ru: "Оператор рассматривает сообщение о неявке — в это время отменить бронь может только оператор.",
  },
  "bookingCancel.cancelledBy": { uz: "Bekor qilindi", ru: "Отменено" },
  "bookingCancel.searchAgainHint": {
    uz: "Bu bron saqlangan talabingizdan edi. Eski takliflar yopiq qoladi — qayta qidirishni o'zingiz boshlaysiz.",
    ru: "Эта бронь была из вашего сохранённого запроса. Старые предложения остаются закрытыми — поиск запускаете вы сами.",
  },
  "bookingCancel.searchAgain": { uz: "Qayta qidirish", ru: "Искать снова" },
  "bookingCancel.reason.plans_changed": { uz: "Rejalarim o'zgardi", ru: "Изменились планы" },
  "bookingCancel.reason.found_other_option": { uz: "Boshqa yo'l topdim", ru: "Нашёл другой вариант" },
  "bookingCancel.reason.driver_unreachable": { uz: "Haydovchi javob bermayapti", ru: "Водитель не отвечает" },
  "bookingCancel.reason.trip_changed": { uz: "Safar rejasi o'zgardi", ru: "Изменился план поездки" },
  "bookingCancel.reason.vehicle_problem": { uz: "Mashinada nosozlik", ru: "Неисправность машины" },
  "bookingCancel.reason.client_unreachable": { uz: "Mijoz javob bermayapti", ru: "Клиент не отвечает" },
  "bookingCancel.reason.other": { uz: "Boshqa sabab", ru: "Другая причина" },
  "bookingCancel.refused.noShowPending": {
    uz: "Bekor qilib bo'lmadi: operator «kelmadi» xabarini ko'rib chiqmoqda. Qaror chiqquncha bronni faqat operator bekor qiladi.",
    ru: "Отменить нельзя: оператор рассматривает сообщение о неявке. До решения бронь отменяет только оператор.",
  },
  "bookingCancel.refused.custody": {
    uz: "Yuk allaqachon haydovchida — bekor qilish o'rniga qaytarish jarayoni kerak. Qo'llab-quvvatlashga yozing.",
    ru: "Груз уже у водителя — вместо отмены нужен возврат. Напишите в поддержку.",
  },
  "bookingCancel.refused.tooLate": {
    uz: "Xizmat boshlangan — endi bronni bekor qilib bo'lmaydi. Muammo bo'lsa, nizo oching.",
    ru: "Услуга уже началась — отменить бронь нельзя. Если есть проблема, откройте спор.",
  },
  "bookingCancel.refused.changed": {
    uz: "Bron shu orada o'zgargan. Yangi holatini ko'rib, qayta urinib ko'ring.",
    ru: "Бронь тем временем изменилась. Посмотрите новое состояние и попробуйте снова.",
  },

  // --- proof code reissue (B5a, Q75: 2 minutes apart, 3 per 24 hours) ----------------------------------------
  "reissue.button": { uz: "Yangi kod olish", ru: "Получить новый код" },
  "reissue.hint": {
    uz: "Eski kod darhol ishlamay qoladi. Kunda 3 martagacha, har safar orasida 2 daqiqa.",
    ru: "Старый код сразу перестанет работать. До 3 раз в сутки, с интервалом 2 минуты.",
  },
  "reissue.done": { uz: "Yangi kod tayyor — eski kod endi ishlamaydi", ru: "Новый код готов — старый больше не действует" },
  "reissue.waitMinutes": {
    uz: "Yangi kodni {minutes} daqiqa {seconds} soniyadan keyin olish mumkin.",
    ru: "Новый код можно получить через {minutes} мин {seconds} сек.",
  },
  "reissue.waitHours": {
    uz: "Bugungi chegara tugadi. Yangi kodni {hours} soat {minutes} daqiqadan keyin olish mumkin.",
    ru: "Дневной лимит исчерпан. Новый код можно получить через {hours} ч {minutes} мин.",
  },
  "reissue.left": { uz: "Qolgan urinishlar: {count}", ru: "Осталось попыток: {count}" },

  // --- rating / dispute from either side (S1, S3) ------------------------------------------------------------
  "rating.titleDriver": { uz: "Haydovchini baholang", ru: "Оцените водителя" },
  "rating.titleClient": { uz: "Mijozni baholang", ru: "Оцените клиента" },
  "rating.rateDriver": { uz: "Haydovchini baholash", ru: "Оценить водителя" },
  "rating.rateClient": { uz: "Mijozni baholash", ru: "Оценить клиента" },
  "disputeType.commission": { uz: "Komissiya", ru: "Комиссия" },
  "dispute.detailTitle": { uz: "Nizo", ru: "Спор" },
  "dispute.openedBy": { uz: "Kim ochdi", ru: "Кто открыл" },
  "dispute.side.client": { uz: "Mijoz", ru: "Клиент" },
  "dispute.side.driver": { uz: "Haydovchi", ru: "Водитель" },
  "dispute.side.operator": { uz: "Operator", ru: "Оператор" },
  "dispute.escalated": { uz: "Katta xodimga yuborilgan", ru: "Передан старшему сотруднику" },
  "dispute.details": { uz: "Batafsil", ru: "Подробнее" },
  "dispute.refresh": { uz: "Yangilash", ru: "Обновить" },

  // --- listing owner controls (L3/L5/L6, Q20) ----------------------------------------------------------------
  "listingOwner.pause": { uz: "Vaqtincha to'xtatish", ru: "Приостановить" },
  "listingOwner.pauseHint": {
    uz: "E'lon lentadan yashiriladi; ochiq takliflar o'z holicha qoladi.",
    ru: "Объявление скроется из ленты; открытые предложения останутся как есть.",
  },
  "listingOwner.resume": { uz: "Qayta ochish", ru: "Возобновить" },
  "listingOwner.paused": { uz: "E'lon to'xtatildi", ru: "Объявление приостановлено" },
  "listingOwner.resumed": { uz: "E'lon qayta ochildi", ru: "Объявление снова открыто" },
  "listingOwner.edit": { uz: "Tahrirlash", ru: "Изменить" },
  "listingOwner.editTitle": { uz: "E'lonni tahrirlash", ru: "Изменение объявления" },
  "listingOwner.priceLabel": { uz: "Narx (so'm)", ru: "Цена (сум)" },
  "listingOwner.commentLabel": { uz: "Izoh", ru: "Комментарий" },
  "listingOwner.windowStart": { uz: "Jo'nash oynasi boshlanishi", ru: "Начало окна отправления" },
  "listingOwner.windowEnd": { uz: "Jo'nash oynasi tugashi", ru: "Конец окна отправления" },
  "listingOwner.windowFromTrip": {
    uz: "Vaqt safaringiz jadvalidan olinadi — uni safarda o'zgartirasiz.",
    ru: "Время берётся из расписания поездки — меняется в самой поездке.",
  },
  "listingOwner.nonMaterialNote": {
    uz: "Narx va izohni o'zgartirish ochiq takliflarni yopmaydi.",
    ru: "Изменение цены и комментария не закрывает открытые предложения.",
  },
  "listingOwner.materialWarning": {
    uz: "Vaqt oynasi yoki odamlar sonini o'zgartirsangiz, bu e'londagi barcha ochiq takliflar yopiladi (muddati tugaydi). Haydovchilar yangi shartlarga qaytadan taklif yuboradi.",
    ru: "Если изменить окно времени или число людей, все открытые предложения по объявлению закроются (истекут). Водители отправят новые предложения на новые условия.",
  },
  "listingOwner.openOffers": { uz: "Ochiq takliflar: {count} ta.", ru: "Открытых предложений: {count}." },
  "listingOwner.materialConfirm": { uz: "Tushundim, saqlash", ru: "Понятно, сохранить" },
  "listingOwner.saved": { uz: "E'lon yangilandi", ru: "Объявление обновлено" },
  "listingOwner.invalid.price": { uz: "Narxni kiriting.", ru: "Укажите цену." },
  "listingOwner.invalid.window_incomplete": {
    uz: "Vaqt oynasini to'liq kiriting (kun, oy, yil va vaqt).",
    ru: "Укажите окно полностью (день, месяц, год и время).",
  },
  "listingOwner.invalid.window_order": {
    uz: "Tugash vaqti boshlanishdan keyin bo'lishi kerak.",
    ru: "Время окончания должно быть позже начала.",
  },
  "listingOwner.invalid.window_past": {
    uz: "Vaqt oynasi o'tib ketgan — kelajakdagi vaqtni tanlang.",
    ru: "Окно уже прошло — выберите время в будущем.",
  },

  // --- driver commission estimate (W11): driver only (Q16), an estimate, not money (§9) -----------------------
  "commissionPreview.title": { uz: "Taxminiy komissiya", ru: "Ориентировочная комиссия" },
  "commissionPreview.line": {
    uz: "{amount} ({percent}%) — jami {total} bo'yicha",
    ru: "{amount} ({percent}%) — от суммы {total}",
  },
  "commissionPreview.note": {
    uz: "Bu hisob-kitob, to'langan pul emas. Mijoz qabul qilganda shu summa komissiya balansingizda band qilinadi; yo'lkirani mijoz sizga naqd beradi.",
    ru: "Это расчёт, а не полученные деньги. Когда клиент примет предложение, эта сумма будет удержана на балансе комиссии; плату за проезд клиент отдаёт вам наличными.",
  },
  "commissionPreview.unavailable": {
    uz: "Komissiyani hozir hisoblab bo'lmadi — taklif yuborishga bu to'sqinlik qilmaydi.",
    ru: "Сейчас не удалось рассчитать комиссию — это не мешает отправить предложение.",
  },

  // --- proposal reject / refresh (P7) -----------------------------------------------------------------------
  "proposal.reject": { uz: "Rad etish", ru: "Отклонить" },
  "proposal.rejected": { uz: "Taklif rad etildi", ru: "Предложение отклонено" },
  "proposal.refresh": { uz: "Yangilash", ru: "Обновить" },

  // --- v2 inbox (N4): the server sends keys, the words are chosen here ---------------------------------------
  "notification.fallback.title": { uz: "Yangi bildirishnoma", ru: "Новое уведомление" },
  "notification.listing.published.title": { uz: "E'lon bozorga chiqdi", ru: "Объявление опубликовано" },
  "notification.listing.expired.title": { uz: "E'lon muddati tugadi", ru: "Срок объявления истёк" },
  "notification.listing.cancelled.title": { uz: "E'lon bekor qilindi", ru: "Объявление отменено" },
  "notification.proposal.created.title": { uz: "Yangi taklif", ru: "Новое предложение" },
  "notification.proposal.superseded.title": { uz: "Qarshi taklif keldi", ru: "Пришло встречное предложение" },
  "notification.proposal.withdrawn.title": { uz: "Taklif qaytarib olindi", ru: "Предложение отозвано" },
  "notification.proposal.rejected.title": { uz: "Taklif rad etildi", ru: "Предложение отклонено" },
  "notification.proposal.expired.title": { uz: "Taklif muddati tugadi", ru: "Срок предложения истёк" },
  "notification.booking.accepted.title": { uz: "Kelishuv tuzildi", ru: "Сделка заключена" },
  "notification.booking.accepted.body": {
    uz: "Bron yaratildi — tafsilotlar va suhbat bron sahifasida.",
    ru: "Бронь создана — детали и чат на странице брони.",
  },
  "notification.booking.cancelled.title": { uz: "Bron bekor qilindi", ru: "Бронь отменена" },
  "notification.booking.started.title": { uz: "Xizmat boshlandi", ru: "Услуга началась" },
  "notification.booking.status_changed.title": { uz: "Bron holati o'zgardi", ru: "Статус брони изменился" },
  "notification.booking.completed.title": { uz: "Bron yakunlandi", ru: "Бронь завершена" },
  "notification.booking.no_show_reported.title": { uz: "«Kelmadi» xabari yuborildi", ru: "Сообщение о неявке отправлено" },
  "notification.booking.custody_case_opened.title": { uz: "Yuk bo'yicha holat ochildi", ru: "Открыт случай по грузу" },
  "notification.booking.proof_code.reissued.title": { uz: "Kod yangilandi", ru: "Код обновлён" },
  "notification.booking.driver_arrived.title": { uz: "Haydovchi yetib keldi", ru: "Водитель на месте" },
  "notification.booking.amendment_requested.title": { uz: "Shartlarni o'zgartirish so'raldi", ru: "Запрошено изменение условий" },
  "notification.booking.amendment_decided.title": { uz: "O'zgartirish bo'yicha javob", ru: "Ответ по изменению условий" },
  "notification.booking.confirmation_overdue.title": { uz: "Yetkazilganini tasdiqlang", ru: "Подтвердите доставку" },
  "notification.trip.status_changed.title": { uz: "Safar holati o'zgardi", ru: "Статус поездки изменился" },
  "notification.chat.message.created.title": { uz: "Yangi xabar", ru: "Новое сообщение" },
  "notification.tracking.window_opened.title": { uz: "Kuzatuv ochildi", ru: "Отслеживание доступно" },
  "notification.tracking.stale.title": { uz: "Joylashuv yangilanmayapti", ru: "Местоположение не обновляется" },
  "notification.saved_search.matched.title": { uz: "Saqlangan qidiruvga mos e'lon", ru: "Подходящее объявление по поиску" },
  "notification.dispute.opened.title": { uz: "Nizo ochildi", ru: "Открыт спор" },
  "notification.dispute.resolved.title": { uz: "Nizo bo'yicha qaror", ru: "Решение по спору" },
  "notification.rating.published.title": { uz: "Baho e'lon qilindi", ru: "Оценка опубликована" },
  "notification.support.ticket.status_changed.title": { uz: "Murojaatingiz holati o'zgardi", ru: "Статус обращения изменился" },
  "notification.trust.warning_issued.title": { uz: "Ogohlantirish", ru: "Предупреждение" },
  "notification.wallet.topup.approved.title": { uz: "To'ldirish tasdiqlandi", ru: "Пополнение подтверждено" },
  "notification.wallet.hold.created.title": { uz: "Komissiya band qilindi", ru: "Комиссия удержана" },
  "notification.wallet.hold.released.title": { uz: "Band qilingan komissiya bo'shatildi", ru: "Удержание комиссии снято" },
  "notification.commission.captured.title": { uz: "Komissiya yechildi", ru: "Комиссия списана" },
  "notification.commission.reversed.title": { uz: "Komissiya qaytarildi", ru: "Комиссия возвращена" },
  "notification.promo.reward_granted.title": { uz: "Bonus berildi", ru: "Бонус начислен" },

  // --- safety, sharing and reputation mounts ----------------------------------------------------------------
  "safety.section": { uz: "Xavfsizlik", ru: "Безопасность" },
  "safety.sectionHint": {
    uz: "Xavfli xatti-harakat, firibgarlik shubhasi yoki ilovadan tashqari aloqaga undash haqida xabar bering yoki bu odamni bloklang. Oddiy muammo uchun yuqoridagi «Yordam / shikoyat» chatidan foydalaning. Bron majburiyatlari davom etadi.",
    ru: "Сообщите об опасном поведении, подозрении на мошенничество или попытке связаться вне приложения либо заблокируйте этого человека. С обычной проблемой пишите в чат «Помощь / жалоба» выше. Обязательства по брони сохраняются.",
  },
  "safety.counterpartyMissing": {
    uz: "Bronda ikkinchi tomon ko'rsatilmagan, shuning uchun bu yerda bloklab bo'lmaydi.",
    ru: "В брони не указана вторая сторона, поэтому заблокировать здесь нельзя.",
  },
  "safety.centerTitle": { uz: "Bloklanganlar va shikoyatlarim", ru: "Блокировки и мои жалобы" },
  "safety.centerDescription": {
    uz: "Bloklagan odamlaringiz va yuborgan shikoyatlaringiz holati",
    ru: "Кого вы заблокировали и статус ваших жалоб",
  },
  "safety.driverTitle": { uz: "Haydovchi", ru: "Водитель" },
  "safety.clientTitle": { uz: "Mijoz", ru: "Клиент" },
  "tracking.shareTitle": { uz: "Yaqinlaringiz bilan kuzatuv", ru: "Отслеживание для близких" },
  "listingShare.title": { uz: "E'lonni ulashish", ru: "Поделиться объявлением" },
  "trip.detailsTitle": { uz: "Safar tafsilotlari", ru: "Детали поездки" },
  "tripPlan.stopSearchLabel": { uz: "Bekat nomi bo'yicha marshrut topish", ru: "Найти маршрут по названию остановки" },
  "tripPlan.stopFilter": { uz: "{name} orqali o'tadigan marshrutlar", ru: "Маршруты через {name}" },
  "tripPlan.stopFilterClear": { uz: "Filtrni olib tashlash", ru: "Сбросить фильтр" },
  "tripPlan.stopFilterNone": {
    uz: "Bu yo'nalishning tasdiqlangan marshrutlari {name} orqali o'tmaydi.",
    ru: "Утверждённые маршруты этого направления не проходят через {name}.",
  },

  // --- the language switch itself ---------------------------------------------------------------------------
  "settings.language": { uz: "Til", ru: "Язык" },
  "settings.languageHint": { uz: "Ilova tilini tanlang", ru: "Выберите язык приложения" },
} as const satisfies Record<string, Message>;

/**
 * Screen text, one file per area of the app (`./screens/`), so a screen's words sit together and can be reviewed
 * against that screen. Keys never repeat across sources - `messages.test.ts` checks it, because a spread would let
 * a later file silently overwrite an earlier sentence.
 */
export const messageSources = {
  base: baseMessages,
  appCore: appCoreMessages,
  entry: entryMessages,
  orderFlow: orderFlowMessages,
  bookingOps: bookingOpsMessages,
  bookingView: bookingViewMessages,
  driverSetup: driverSetupMessages,
  driverWork: driverWorkMessages,
  panelsA: panelsAMessages,
  panelsB: panelsBMessages,
  components: componentsMessages,
  promoHelpers: promoHelpersMessages,
  flowHelpers: flowHelpersMessages,
  adr0026: adr0026Messages,
  liveTracking: liveTrackingMessages,
} as const;

export const messages = {
  ...baseMessages,
  ...appCoreMessages,
  ...entryMessages,
  ...orderFlowMessages,
  ...bookingOpsMessages,
  ...bookingViewMessages,
  ...driverSetupMessages,
  ...driverWorkMessages,
  ...panelsAMessages,
  ...panelsBMessages,
  ...componentsMessages,
  ...promoHelpersMessages,
  ...flowHelpersMessages,
  ...adr0026Messages,
  ...liveTrackingMessages,
} as const satisfies Record<string, Message>;

export type MessageKey = keyof typeof messages;
