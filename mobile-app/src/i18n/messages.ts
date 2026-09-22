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

export interface Message {
  uz: string;
  ru: string;
}

export const messages = {
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

  // --- the language switch itself ---------------------------------------------------------------------------
  "settings.language": { uz: "Til", ru: "Язык" },
  "settings.languageHint": { uz: "Ilova tilini tanlang", ru: "Выберите язык приложения" },
} as const satisfies Record<string, Message>;

export type MessageKey = keyof typeof messages;
