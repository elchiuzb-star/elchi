/** Block/report, the driver's trip detail, the parcel policy notice and the bonus/referral screens. Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const panelsAMessages = {
  // --- block and report (BlockAndReportPanel) ---
  "blockReport.reason.off_platform_contact": { uz: "Ilovadan tashqari aloqaga undash", ru: "Склоняет к общению вне приложения" },
  "blockReport.reason.fraud_suspicion": { uz: "Firibgarlik shubhasi", ru: "Подозрение на мошенничество" },
  "blockReport.reason.unsafe_behaviour": { uz: "Xavfli xatti-harakat", ru: "Опасное поведение" },
  "blockReport.reason.no_show": { uz: "Kelmadi", ru: "Не явился" },
  "blockReport.reason.price_pressure": { uz: "Narx bo'yicha bosim", ru: "Давление по цене" },
  "blockReport.reason.prohibited_item": { uz: "Taqiqlangan jo'natma", ru: "Запрещённая посылка" },
  "blockReport.reason.harassment": { uz: "Haqorat yoki bezovta qilish", ru: "Оскорбления или преследование" },
  "blockReport.reason.other": { uz: "Boshqa", ru: "Другое" },
  "blockReport.subject.user": { uz: "Foydalanuvchi", ru: "Пользователь" },
  "blockReport.subject.listing": { uz: "E'lon", ru: "Объявление" },
  "blockReport.subject.booking": { uz: "Bron", ru: "Бронь" },
  "blockReport.subject.chat_message": { uz: "Chat xabari", ru: "Сообщение в чате" },
  "blockReport.status.open": { uz: "Yuborildi", ru: "Отправлена" },
  "blockReport.status.under_review": { uz: "Ko'rib chiqilmoqda", ru: "На рассмотрении" },
  "blockReport.status.dismissed": { uz: "Yopildi", ru: "Закрыта" },
  "blockReport.status.actioned": { uz: "Chora ko'rildi", ru: "Приняты меры" },
  "blockReport.blockTitle": { uz: "Bloklash", ru: "Блокировка" },
  "blockReport.blockNote": {
    uz:
      "Bloklangan odamga xabar berilmaydi. Siz uning e'lon va takliflarini ko'rmaysiz, u sizga yangi taklif yubora " +
      "olmaydi. Mavjud bron majburiyatlari va qo'llab-quvvatlash davom etadi.",
    ru:
      "Заблокированный человек не получит уведомления. Вы не будете видеть его объявления и предложения, а он не " +
      "сможет отправлять вам новые предложения. Обязательства по существующим броням и поддержка сохраняются.",
  },
  "blockReport.unblock": { uz: "Blokdan chiqarish", ru: "Разблокировать" },
  "blockReport.block": { uz: "Bloklash", ru: "Заблокировать" },
  "blockReport.blocksEmpty": { uz: "Siz hech kimni bloklamagansiz.", ru: "Вы никого не заблокировали." },
  "blockReport.unblockShort": { uz: "Chiqarish", ru: "Разблокировать" },
  "blockReport.sentTitle": { uz: "Shikoyat yuborildi", ru: "Жалоба отправлена" },
  "blockReport.savedText": { uz: "Saqlangan matn: {details}", ru: "Сохранённый текст: {details}" },
  "blockReport.sentNote": {
    uz:
      "Operator ko'rib chiqadi. Shikoyatning o'zi hech kimni avtomatik jazolamaydi. Holatini \"Mening " +
      "shikoyatlarim\" ro'yxatida ko'rasiz.",
    ru:
      "Жалобу рассмотрит оператор. Сама по себе жалоба никого автоматически не наказывает. Её статус вы увидите " +
      "в списке «Мои жалобы».",
  },
  "blockReport.reportAgain": { uz: "Yana shikoyat yozish", ru: "Написать ещё одну жалобу" },
  "blockReport.formTitle": { uz: "Shikoyat: {subject}", ru: "Жалоба: {subject}" },
  "blockReport.chooseReason": { uz: "Sababni tanlang", ru: "Выберите причину" },
  "blockReport.detailsLabel": { uz: "Izoh (ixtiyoriy)", ru: "Комментарий (необязательно)" },
  "blockReport.detailsHint": {
    uz: "Telefon raqami, havola yoki boshqa aloqa ma'lumoti avtomatik yashiriladi.",
    ru: "Номер телефона, ссылки и другие контактные данные скрываются автоматически.",
  },
  "blockReport.myReportsTitle": { uz: "Mening shikoyatlarim", ru: "Мои жалобы" },
  "blockReport.myReportsEmpty": { uz: "Siz hali shikoyat yubormagansiz.", ru: "Вы ещё не отправляли жалоб." },
  "blockReport.loadMore": { uz: "Yana yuklash", ru: "Загрузить ещё" },

  // --- driver trip detail (DriverTripDetail) ---
  "tripDetail.status.boarding": { uz: "Yo'lovchilar chiqmoqda", ru: "Идёт посадка" },
  "tripDetail.service.awaiting_pickup": { uz: "Olib ketishni kutmoqda", ru: "Ожидает подачи" },
  "tripDetail.service.onboard": { uz: "Mashinada", ru: "В машине" },
  "tripDetail.service.arrived": { uz: "Yetib keldi", ru: "Прибыл" },
  "tripDetail.service.picked_up": { uz: "Olindi", ru: "Забрано" },
  "tripDetail.service.delivered": { uz: "Topshirildi", ru: "Вручено" },
  "tripDetail.service.delivery_failed": { uz: "Topshirib bo'lmadi", ru: "Не удалось вручить" },
  "tripDetail.service.return_required": { uz: "Qaytarish kerak", ru: "Требуется возврат" },
  "tripDetail.service.returned": { uz: "Qaytarildi", ru: "Возвращено" },
  "tripDetail.kg": { uz: "{value} kg", ru: "{value} кг" },
  "tripDetail.litres": { uz: "{value} l", ru: "{value} л" },
  "tripDetail.parcel": { uz: "Jo'natma", ru: "Посылка" },
  "tripDetail.seats": { uz: "{count} o'rin", ru: "Мест: {count}" },
  "tripDetail.phoneAfterPickup": {
    uz: "Telefon jo'natma olingandan keyin ko'rinadi. Hozircha ilova chatidan foydalaning.",
    ru: "Телефон появится после того, как посылку заберут. Пока пользуйтесь чатом в приложении.",
  },
  "tripDetail.phoneAfterStart": {
    uz: "Telefon safar boshlanganda ko'rinadi. Hozircha ilova chatidan foydalaning.",
    ru: "Телефон появится, когда начнётся поездка. Пока пользуйтесь чатом в приложении.",
  },
  "tripDetail.departure": { uz: "Jo'nash", ru: "Отправление" },
  "tripDetail.arrival": { uz: "Yetib borish", ru: "Прибытие" },
  "tripDetail.vehicle": { uz: "Avtomobil", ru: "Автомобиль" },
  "tripDetail.seatsLabel": { uz: "O'rinlar", ru: "Места" },
  "tripDetail.seatsValue": { uz: "{count} ta", ru: "{count}" },
  "tripDetail.cutoffLabel": { uz: "Bron qabul qilish", ru: "Приём броней" },
  "tripDetail.cutoffValue": { uz: "{time} gacha", ru: "до {time}" },
  "tripDetail.availabilityTitle": { uz: "Bo'sh joy (bo'laklar bo'yicha)", ru: "Свободные места (по участкам)" },
  "tripDetail.availabilityEmpty": { uz: "Bo'laklar hali hisoblanmagan.", ru: "Участки ещё не рассчитаны." },
  "tripDetail.stopSeq": { uz: "{seq}-bekat", ru: "Остановка {seq}" },
  "tripDetail.segmentLine": {
    uz: "{seats} o'rin · yuk {weight} / {volume} · bagaj {baggage}",
    ru: "Мест: {seats} · груз {weight} / {volume} · багаж {baggage}",
  },
  "tripDetail.computedNote": {
    uz: "Hisoblangan qoldiq, band qilish emas. Yangilangan: {time}",
    ru: "Расчётный остаток, а не бронирование. Обновлено: {time}",
  },
  "tripDetail.manifestTitle": { uz: "Yo'lovchi va jo'natmalar ro'yxati", ru: "Список пассажиров и посылок" },
  "tripDetail.manifestEmpty": { uz: "Bu safarda hali bron yo'q.", ru: "В этой поездке пока нет броней." },
  "tripDetail.agreedPoint": { uz: "Kelishilgan nuqta", ru: "Согласованная точка" },
  "tripDetail.pickups": { uz: "Olib ketish", ru: "Забрать" },
  "tripDetail.dropoffs": { uz: "Tushirish", ru: "Высадить" },
  "tripDetail.refresh": { uz: "Yangilash", ru: "Обновить" },

  // --- parcel policy notice (ParcelPolicyNotice) ---
  "parcelPolicy.category.prohibited": { uz: "Taqiqlangan", ru: "Запрещено" },
  "parcelPolicy.category.restricted": { uz: "Cheklangan", ru: "Ограничено" },
  "parcelPolicy.category.business_declined": { uz: "Elchi qabul qilmaydi", ru: "Elchi не принимает" },
  "parcelPolicy.appliesTo.parcel": { uz: "Pochta", ru: "Посылки" },
  "parcelPolicy.appliesTo.passenger_baggage": { uz: "Yo'lovchi yuki", ru: "Багаж пассажира" },
  "parcelPolicy.appliesTo.all": { uz: "Pochta va yo'lovchi yuki", ru: "Посылки и багаж пассажира" },
  "parcelPolicy.source": { uz: "Manba: {source}", ru: "Источник: {source}" },
  "parcelPolicy.sourceChecked": {
    uz: "Manba: {source} (tekshirilgan: {date})",
    ru: "Источник: {source} (проверено: {date})",
  },
  "parcelPolicy.title": { uz: "Taqiqlangan jo'natmalar", ru: "Запрещённые отправления" },
  "parcelPolicy.unconfirmed": {
    uz:
      "Ro'yxat hali tasdiqlanmagan. Bu hamma narsani yuborish mumkin degani emas: qonun bilan taqiqlangan narsalar " +
      "baribir yuborilmaydi.",
    ru: "Список ещё не утверждён. Это не значит, что можно отправлять всё: запрещённое законом всё равно отправить нельзя.",
  },
  "parcelPolicy.effectiveFrom": { uz: "{date} dan", ru: "с {date}" },
  "parcelPolicy.empty": {
    uz: "Tasdiqlangan ro'yxatda band ko'rsatilmagan. Qonun bilan taqiqlangan narsalar baribir yuborilmaydi.",
    ru: "В утверждённом списке нет пунктов. Запрещённое законом всё равно отправить нельзя.",
  },
  "parcelPolicy.loadFailed": {
    uz: "Taqiqlangan jo'natmalar ro'yxatini yuklab bo'lmadi. Yuborishdan oldin uni albatta tekshiring.",
    ru: "Не удалось загрузить список запрещённых отправлений. Обязательно проверьте его перед отправкой.",
  },

  // --- bonus and referral screens (PromoScreens) ---
  "promoScreen.moneyTitle": { uz: "Bonus bilan hisob", ru: "Расчёт с бонусом" },
  "promoScreen.clientCovers": {
    uz: "Chegirmani ELCHI qoplaydi. Haydovchiga faqat pastdagi naqd summani berasiz.",
    ru: "Скидку покрывает ELCHI. Водителю вы отдаёте только сумму наличными, указанную ниже.",
  },
  "promoScreen.driverCovers": {
    uz: "Mijoz chegirmasi sizning daromadingizdan olinmaydi: uni ELCHI komissiyasidan qoplaydi.",
    ru: "Скидка клиента не вычитается из вашего заработка: ELCHI покрывает её из своей комиссии.",
  },
  "promoScreen.quoteFailed": { uz: "Bonus hisobini olib bo'lmadi: {error}", ru: "Не удалось получить расчёт бонуса: {error}" },
  "promoScreen.useBonusLine": {
    uz: "{bonus} bonusni ishlataman — haydovchiga {cash} naqd beraman",
    ru: "Использую бонус {bonus} — отдам водителю {cash} наличными",
  },
  "promoScreen.consentNote": {
    uz: "Belgilamasangiz bonus ishlatilmaydi. Haydovchi qabul qilganda summa o'zgarsa, sizdan qayta so'raladi.",
    ru: "Без отметки бонус не используется. Если при принятии водителем сумма изменится, вас спросят снова.",
  },
  "promoScreen.useBonusShort": { uz: "Bonusni ishlataman ({amount})", ru: "Использую бонус ({amount})" },
  "promoScreen.whyNoDiscount": { uz: "Nega chegirma yo'q?", ru: "Почему нет скидки?" },
  "promoScreen.staleTitle": { uz: "Bonus shartlarini qayta tasdiqlang", ru: "Подтвердите условия бонуса снова" },
  "promoScreen.staleNote": {
    uz: "Avvalgi tasdig'ingiz boshqa kirish yoki ilova holatida berilgan edi. Taklifning o'zi o'zgarmaydi.",
    ru: "Прежнее подтверждение было дано при другом входе или в другом состоянии приложения. Само предложение не меняется.",
  },
  "promoScreen.staleNoBonus": {
    uz: "Bonus bu narxda endi qo'llanmaydi: kelishuv bonusiz bo'lishi uchun bonussiz qarshi taklif yuboring.",
    ru: "При этой цене бонус больше не применяется: чтобы договориться без бонуса, отправьте встречное предложение без бонуса.",
  },
  "promoScreen.agreeQuote": { uz: "Shu hisobga roziman", ru: "Согласен с этим расчётом" },
  "promoScreen.qrAria": { uz: "Taklif havolasining QR kodi", ru: "QR-код пригласительной ссылки" },
  "promoScreen.milestone": { uz: "{count} safar", ru: "Поездок: {count}" },
  "promoScreen.milestoneReached": { uz: "{count} safar — bajarildi", ru: "Поездок: {count} — выполнено" },
  "promoScreen.joinOffer": { uz: "Shartlarga roziman — qatnashaman", ru: "Согласен с условиями — участвую" },
  "promoScreen.programOff": { uz: "Taklif dasturi hozircha ishlamayapti.", ru: "Программа приглашений пока не работает." },
  "promoScreen.codeAccepted": {
    uz: "Kod qabul qilindi. Endi shartlarni ko'rib, kampaniyaga qo'shilishingiz mumkin.",
    ru: "Код принят. Теперь можно ознакомиться с условиями и присоединиться к кампании.",
  },
  "promoScreen.titleClient": { uz: "Bonuslar va taklif kodi", ru: "Бонусы и код приглашения" },
  "promoScreen.titleDriver": { uz: "Kredit va taklif kodi", ru: "Кредит и код приглашения" },
  "promoScreen.bonusNotMoney": {
    uz: "Bonus — keyingi mos xizmatdagi chegirma huquqi. U pul emas: naqd qilib olinmaydi va boshqaga o'tkazilmaydi.",
    ru: "Бонус — право на скидку при следующей подходящей услуге. Это не деньги: его нельзя обналичить или передать другому.",
  },
  "promoScreen.creditNotMoney": {
    uz: "Kredit faqat komissiyangizni kamaytiradi. U pul emas: to'ldirilgan balansga qo'shilmaydi va yechib olinmaydi.",
    ru: "Кредит только уменьшает вашу комиссию. Это не деньги: он не добавляется к пополненному балансу и не выводится.",
  },
  "promoScreen.myBonuses": { uz: "Mening bonuslarim", ru: "Мои бонусы" },
  "promoScreen.myCredit": { uz: "Mening kreditim", ru: "Мой кредит" },
  "promoScreen.noBonusTitle": { uz: "Hozircha bonus yo'q", ru: "Бонусов пока нет" },
  "promoScreen.noBonusSubtitle": {
    uz: "Bonus faqat kampaniya shartlari bajarilgandan keyin paydo bo'ladi.",
    ru: "Бонус появляется только после выполнения условий кампании.",
  },
  "promoScreen.service.parcel": { uz: "pochta", ru: "посылки" },
  "promoScreen.service.passenger": { uz: "yo'lovchi", ru: "пассажиры" },
  "promoScreen.nextExpiry": { uz: "Eng yaqin muddat: {date}", ru: "Ближайший срок: {date}" },
  "promoScreen.myCode": { uz: "Taklif kodim", ru: "Мой код приглашения" },
  "promoScreen.qrNote": {
    uz: "QR shu havolaning o'zi. Skaner ishlamasa, kodni aytib bering — u ilovada qo'lda kiritiladi.",
    ru: "QR — это та же ссылка. Если сканер не работает, продиктуйте код — его вводят в приложении вручную.",
  },
  "promoScreen.linkNotReady": {
    uz: "Havola hali tayyor emas. Do'stingiz ilovada kodni qo'lda kiritadi.",
    ru: "Ссылка ещё не готова. Друг введёт код в приложении вручную.",
  },
  "promoScreen.copied": { uz: "Nusxa olindi", ru: "Скопировано" },
  "promoScreen.copy": { uz: "Nusxa olish", ru: "Копировать" },
  "promoScreen.rewardNote": {
    uz:
      "Kod orqali qo'shilgan odam uchun mukofot faqat u shartni bajargandan keyin beriladi — ro'yxatdan o'tishning " +
      "o'zi mukofot emas.",
    ru: "Награда за человека, присоединившегося по коду, даётся только после выполнения им условия — сама регистрация наградой не является.",
  },
  "promoScreen.showCode": { uz: "Kodimni ko'rsatish", ru: "Показать мой код" },
  "promoScreen.enterCode": { uz: "Taklif kodi kiritish", ru: "Ввод кода приглашения" },
  "promoScreen.friendCode": { uz: "Do'stingiz bergan kod", ru: "Код от друга" },
  "promoScreen.codeExample": { uz: "Masalan: AB2CD3EF", ru: "Например: AB2CD3EF" },
  "promoScreen.codeFormat": { uz: "Kod 8 ta harf va raqamdan iborat", ru: "Код состоит из 8 букв и цифр" },
  "promoScreen.confirmCode": { uz: "Kodni tasdiqlash", ru: "Подтвердить код" },
  "promoScreen.codeOnce": {
    uz: "Kod faqat bir marta qabul qilinadi va keyin almashtirilmaydi.",
    ru: "Код принимается только один раз, заменить его потом нельзя.",
  },
  "promoScreen.availableCampaigns": { uz: "Qo'shilish mumkin bo'lgan kampaniyalar", ru: "Кампании, к которым можно присоединиться" },
  "promoScreen.programOffWithBalance": {
    uz: "Taklif dasturi hozircha ishlamayapti. Mavjud bonuslaringiz yuqorida ko'rsatilgan.",
    ru: "Программа приглашений пока не работает. Ваши текущие бонусы показаны выше.",
  },
  "promoScreen.myCampaigns": { uz: "Kampaniyalarim", ru: "Мои кампании" },
  "promoScreen.noCampaigns": {
    uz: "Siz hali hech qaysi kampaniyada qatnashmayapsiz.",
    ru: "Вы пока не участвуете ни в одной кампании.",
  },
  "promoScreen.youAreInvited": { uz: "Siz taklif qilingansiz", ru: "Вас пригласили" },
  "promoScreen.youInvited": { uz: "Siz taklif qilgansiz", ru: "Вы пригласили" },
  "promoScreen.deadline": { uz: "Shart muddati: {date}", ru: "Срок выполнения условия: {date}" },
  "promoScreen.invitedCount": { uz: "Kodim orqali qo'shilganlar: {count} ta", ru: "Присоединились по моему коду: {count}" },
} as const satisfies Record<string, Message>;
