/** Bonus/referral helper sentences from `app/promo.ts` (money lines, disclosures, states). Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

// A bonus or credit is a discount right, never money; a commission is a charge, never income.
export const promoHelpersMessages = {
  // --- money lines ---
  "promo.line.agreedPrice": { uz: "Kelishilgan narx", ru: "Согласованная цена" },
  "promo.line.offerPrice": { uz: "Taklif narxi", ru: "Цена предложения" },
  "promo.line.bonusDiscount": { uz: "Bonus chegirmasi", ru: "Бонусная скидка" },
  "promo.line.cashToDriver": { uz: "Haydovchiga naqd to'lanadi", ru: "Наличными водителю" },
  "promo.line.cashFromClient": { uz: "Mijozdan naqd olasiz", ru: "Вы получите от клиента наличными" },
  "promo.line.discountCovered": { uz: "Mijoz chegirmasini ELCHI qoplaydi", ru: "Скидку клиента покрывает ELCHI" },
  "promo.line.creditUsed": { uz: "Ishlatilgan kredit", ru: "Использованный кредит" },
  "promo.line.creditToUse": { uz: "Ishlatiladigan kredit", ru: "Будет использован кредит" },
  "promo.line.chargedFromBalance": { uz: "Balansingizdan yechiladi", ru: "Спишется с вашего баланса комиссии" },
  "promo.line.youKeep": { uz: "Sizda qoladi", ru: "Остаётся у вас" },

  // --- why there is no discount ---
  "promo.noDiscount.serviceNotEligible": {
    uz: "Bu xizmatga bonusingiz ishlamaydi (bonus boshqa xizmat turi uchun yoki jo'natmani qabul qiluvchi to'laydi).",
    ru: "Ваш бонус не действует для этой услуги (бонус предназначен для другого вида услуг или посылку оплачивает получатель).",
  },
  "promo.noDiscount.bonusExpired": { uz: "Bonusingizning muddati tugagan.", ru: "Срок действия вашего бонуса истёк." },
  "promo.noDiscount.bonusReserved": {
    uz: "Bonusingiz boshqa bronga band qilingan.",
    ru: "Ваш бонус зарезервирован под другую бронь.",
  },
  "promo.noDiscount.bonusOnHold": {
    uz: "Bonusingiz hozir tekshiruvda — tekshiruv tugaguncha ishlatib bo'lmaydi.",
    ru: "Ваш бонус сейчас на проверке — до её завершения использовать его нельзя.",
  },
  "promo.noDiscount.noCampaign": {
    uz: "Hozir sizda ishlatsa bo'ladigan bonus yoki faol kampaniya yo'q.",
    ru: "Сейчас у вас нет доступного бонуса или активной кампании.",
  },
  "promo.noDiscount.clientUpdateRequired": {
    uz: "Bonusni ishlatish uchun ilovani yangilang.",
    ru: "Чтобы использовать бонус, обновите приложение.",
  },
  "promo.noDiscount.tripTerms": {
    uz: "Bu safar shartlarida bonus chegirmasi qo'llanmaydi.",
    ru: "Условия этой поездки не допускают бонусную скидку.",
  },

  // --- amendment cash notes ---
  "promo.amendment.cashRisesDespiteLowerFare": {
    uz: "Diqqat: narx kamaygan bo'lsa ham, naqd to'lovingiz oshadi — bonus chegirmasi narxga bog'liq bo'lib, u ham kamaydi.",
    ru: "Внимание: хотя цена снизилась, ваша оплата наличными вырастет — бонусная скидка зависит от цены и тоже уменьшилась.",
  },
  "promo.amendment.discountAlsoSmaller": {
    uz: "Narx kamaydi, lekin bonus chegirmasi ham kamaydi — shuning uchun naqd summa narxdan kamroq kamayadi.",
    ru: "Цена снизилась, но бонусная скидка тоже уменьшилась — поэтому сумма наличных снижается меньше, чем цена.",
  },
  "promo.amendment.fareRose": {
    uz: "Narx oshdi. Bonus chegirmasi oshmaydi: o'zgarishda yangi bonus ishlatilmaydi.",
    ru: "Цена выросла. Бонусная скидка не увеличится: при изменении новый бонус не используется.",
  },
  "promo.amendment.cashChanges": {
    uz: "Naqd to'lanadigan summa o'zgaradi — tasdiqlashdan oldin tekshiring.",
    ru: "Сумма к оплате наличными изменится — проверьте перед подтверждением.",
  },

  // --- referral progress ---
  "promo.progress.remaining": { uz: "Qolgan", ru: "Осталось" },
  "promo.progress.doneTrips": { uz: "{done} / {required} safar", ru: "поездки: {done} / {required}" },
  "promo.progress.doneServices": { uz: "{done} / {required} xizmat", ru: "услуги: {done} / {required}" },
  "promo.progress.countTrips": { uz: "{count} safar", ru: "поездки: {count}" },
  "promo.progress.countServices": { uz: "{count} xizmat", ru: "услуги: {count}" },
  "promo.progress.inReviewHint": {
    uz: "Naqd tasdig'i, komissiya yoki 48 soatlik tekshiruv kutilmoqda — hali bajarilgan hisoblanmaydi",
    ru: "Ожидается подтверждение оплаты наличными, комиссия или 48-часовая проверка — пока не засчитано как выполненное",
  },

  // --- durations ---
  "promo.duration.days": { uz: "{count} kun", ru: "{count} дн." },
  "promo.duration.hours": { uz: "{count} soat", ru: "{count} ч." },

  // --- disclosures ---
  "promo.service.passenger": { uz: "yo'lovchi safari", ru: "пассажирских поездок" },
  "promo.service.parcel": { uz: "pochta jo'natmasi", ru: "почтовых отправлений" },
  "promo.disclosure.notCash": {
    uz: "Bonus pul emas: u faqat keyingi xizmatdagi chegirma. Naqdga aylantirilmaydi va boshqaga o'tkazilmaydi.",
    ru: "Бонус — не деньги, а только скидка на следующую услугу. Его нельзя обналичить или передать другому.",
  },
  "promo.disclosure.nextEligibleService": {
    uz: "Mukofot ro'yxatdan o'tganingiz uchun emas — shartlarga mos xizmatdan keyin beriladi.",
    ru: "Вознаграждение дают не за регистрацию, а после услуги, соответствующей условиям.",
  },
  "promo.disclosure.referrerServiceExcluded": {
    uz: "Sizni taklif qilgan haydovchining o'zi bajargan xizmat hisoblanmaydi.",
    ru: "Услуга, выполненная самим пригласившим вас водителем, не засчитывается.",
  },
  "promo.disclosure.anotherDriverQualifies": {
    uz: "Muddat ichida boshqa haydovchi bilan bajarilgan xizmat hisoblanadi.",
    ru: "Засчитывается услуга, выполненная в срок с другим водителем.",
  },
  "promo.disclosure.qualificationDeadline": {
    uz: "Shartni bajarish muddati: {duration}.",
    ru: "Срок выполнения условия: {duration}.",
  },
  "promo.disclosure.milestones": {
    uz: "Bosqichlar: {steps} ta alohida safar.",
    ru: "Этапы: отдельных поездок — {steps}.",
  },
  "promo.disclosure.requiredServices": {
    uz: "Kerakli xizmatlar soni: {count}.",
    ru: "Необходимое количество услуг: {count}.",
  },
  "promo.disclosure.serviceTypeOnly": {
    uz: "Bonus faqat {service} uchun ishlatiladi.",
    ru: "Бонус используется только для {service}.",
  },
  "promo.disclosure.rewardValidity": {
    uz: "Bonusni ishlatish muddati: {duration}.",
    ru: "Срок использования бонуса: {duration}.",
  },
  "promo.disclosure.riskCheck": {
    uz: "Xizmatdan keyin {duration} tekshiruv: bonus shundan keyin ochiladi.",
    ru: "После услуги — проверка ({duration}): бонус станет доступен после неё.",
  },
  "promo.disclosure.enrollmentLimit": {
    uz: "Kampaniyada ishtirokchilar soni cheklangan.",
    ru: "Число участников кампании ограничено.",
  },
  "promo.disclosure.milestoneUnit": {
    uz: "Har bosqich — alohida safar (bir safardagi bir nechta buyurtma bitta bosqich).",
    ru: "Каждый этап — отдельная поездка (несколько заказов в одной поездке — один этап).",
  },
  "promo.parcelPayerRule": {
    uz: "Pochtada bonus faqat jo'natuvchi o'zi to'laydigan jo'natmada ishlatiladi; qabul qiluvchi to'lasa — ishlatilmaydi.",
    ru: "В почте бонус действует только для посылки, которую оплачивает сам отправитель; если платит получатель — не действует.",
  },

  // --- qualification / enrollment / instrument states ---
  "promo.qualification.waiting": {
    uz: "Xizmat bajarildi — tekshiruv kutilmoqda",
    ru: "Услуга выполнена — ожидается проверка",
  },
  "promo.qualification.review": { uz: "Xodim tekshirmoqda", ru: "Проверяет сотрудник" },
  "promo.qualification.qualified": { uz: "Shart bajarildi", ru: "Условие выполнено" },
  "promo.enrollment.promised": { uz: "Shart kutilmoqda", ru: "Ожидается выполнение условия" },
  "promo.enrollment.released": { uz: "Muddat tugadi", ru: "Срок истёк" },
  "promo.instrument.passengerBonus": { uz: "Mijoz bonusi", ru: "Бонус клиента" },
  "promo.instrument.driverCredit": { uz: "Haydovchi krediti", ru: "Кредит водителя" },

  // --- discount-right buckets ---
  "promo.bucket.available": { uz: "Ishlatish mumkin", ru: "Можно использовать" },
  "promo.bucket.reserved": { uz: "Band (bron uchun)", ru: "Зарезервировано (под бронь)" },
  "promo.bucket.reservedHint": {
    uz: "Bron tugaganda sarflanadi yoki qaytadi",
    ru: "По завершении брони будет израсходовано или вернётся",
  },
  "promo.bucket.underReviewHint": {
    uz: "Tekshiruv tugaguncha ishlatib bo'lmaydi",
    ru: "До окончания проверки использовать нельзя",
  },
  "promo.bucket.consumed": { uz: "Sarflangan", ru: "Израсходовано" },
  "promo.bucket.expired": { uz: "Muddati tugagan", ru: "Срок истёк" },
} as const satisfies Record<string, Message>;
