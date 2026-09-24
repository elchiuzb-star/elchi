/** Words returned by the pure flow helpers in `app/` (saved request fit, negotiation turn, proof code hints). Merged into `messages` by `../messages.ts`. */
import type { Message } from "../messages";

export const flowHelpersMessages = {
  // --- tripIntent.ts: saved request summary, price line, fit notes ---
  "intentFit.markedPlace": { uz: "Belgilangan joy", ru: "Отмеченное место" },
  "intentFit.today": { uz: "bugun", ru: "сегодня" },
  "intentFit.tomorrow": { uz: "ertaga", ru: "завтра" },
  "intentFit.people": { uz: "{count} kishi", ru: "{count} чел." },
  "intentFit.oneParcel": { uz: "1 jo'natma", ru: "1 посылка" },
  "intentFit.personUnit": { uz: "kishi", ru: "чел." },
  "intentFit.priceLineTotal": { uz: "{total} (jami)", ru: "{total} (всего)" },
  "intentFit.minutes": { uz: "{minutes} daqiqa", ru: "{minutes} мин" },
  "intentFit.hoursMinutes": { uz: "{hours} soat {minutes} daqiqa", ru: "{hours} ч {minutes} мин" },
  "intentFit.hours": { uz: "{hours} soat", ru: "{hours} ч" },
  "intentFit.otherService": { uz: "Bu e'lon boshqa xizmat turi uchun.", ru: "Это объявление для другого вида услуги." },
  "intentFit.expired": {
    uz: "Safar vaqti o'tib ketgan - avval talabni yangilang.",
    ru: "Время поездки уже прошло — сначала обновите запрос.",
  },
  "intentFit.seatsShort": {
    uz: "Haydovchida {available} ta bo'sh o'rin bor, sizga {requested} ta kerak.",
    ru: "Свободных мест у водителя: {available}, а вам нужно: {requested}.",
  },
  "intentFit.parcelNoRoom": { uz: "Haydovchida jo'natmangiz uchun joy yetmaydi.", ru: "У водителя не хватает места для вашей посылки." },
  "intentFit.timeOutside": {
    uz: "Haydovchi vaqti siz tanlagan oraliqdan {difference} farq qiladi.",
    ru: "Время водителя отличается от выбранного вами интервала на {difference}.",
  },
  "intentFit.originSameDistrict": {
    uz: "Olib ketish joyi shu tumanda, lekin boshqa bekatda.",
    ru: "Место посадки в том же районе, но на другой остановке.",
  },
  "intentFit.originDifferent": { uz: "Olib ketish joyi siz tanlagan joydan boshqa.", ru: "Место посадки отличается от выбранного вами." },
  "intentFit.destinationSameDistrict": {
    uz: "Tushirish joyi shu tumanda, lekin boshqa bekatda.",
    ru: "Место высадки в том же районе, но на другой остановке.",
  },
  "intentFit.destinationDifferent": { uz: "Tushirish joyi siz tanlagan joydan boshqa.", ru: "Место высадки отличается от выбранного вами." },
  "intentFit.offersAffectedOne": {
    uz: "Yo'nalish, vaqt yoki odamlar soni o'zgaradi. Shu talab bo'yicha yuborilgan 1 ta ochiq taklif yopiladi.",
    ru: "Изменятся направление, время или число людей. Открытое предложение, отправленное по этому запросу, будет закрыто.",
  },
  "intentFit.offersAffected": {
    uz: "Yo'nalish, vaqt yoki odamlar soni o'zgaradi. Shu talab bo'yicha yuborilgan {count} ta ochiq taklif yopiladi.",
    ru: "Изменятся направление, время или число людей. Открытые предложения по этому запросу будут закрыты: {count}.",
  },

  // --- auction.ts: whose answer a negotiation waits for ---
  "negotiation.closed": { uz: "Bu taklif yopilgan", ru: "Это предложение закрыто" },
  "negotiation.waitingForAnswer": { uz: "Sizning taklifingiz - javob kutilmoqda", ru: "Ваше предложение — ждём ответа" },
  "negotiation.driverCountered": { uz: "Haydovchi qarshi taklif yubordi", ru: "Водитель отправил встречное предложение" },
  "negotiation.clientCountered": { uz: "Mijoz qarshi taklif yubordi", ru: "Клиент отправил встречное предложение" },

  // --- proofCodes.ts: what to do with each proof code ---
  "proofHint.boarding": {
    uz: "Mashinaga o'tirayotganingizda bu kodni haydovchiga ayting.",
    ru: "Назовите этот код водителю, когда садитесь в машину.",
  },
  "proofHint.delivery": { uz: "Bu kodni faqat qabul qiluvchiga bering.", ru: "Сообщите этот код только получателю." },
  "proofHint.return": {
    uz: "Jo'natma sizga qaytarilganda bu kodni haydovchiga ayting.",
    ru: "Назовите этот код водителю, когда посылку вернут вам.",
  },
  "proofHint.pickup": {
    uz: "Bu kodni haydovchiga posilkani topshirayotganda ayting.",
    ru: "Назовите этот код водителю, когда передаёте посылку.",
  },
} as const satisfies Record<string, Message>;
