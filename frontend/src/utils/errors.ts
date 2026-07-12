import { ApiError } from "../types/api";

const uzbekErrorMessages: Record<string, string> = {
  ROLE_MISMATCH: "Bu telefon raqam boshqa rolda ro'yxatdan o'tgan",
  OTP_INVALID: "Kod noto'g'ri",
  OTP_EXPIRED: "Kod muddati tugagan",
  OTP_USED: "Kod allaqachon ishlatilgan",
  OTP_RESEND_TOO_SOON: "Kodni qayta yuborishdan oldin biroz kuting",
  OTP_TOO_MANY_ATTEMPTS: "Juda ko'p urinish bo'ldi",
  OTP_SEND_LIMIT_EXCEEDED: "Kod olish urinishlari ko'payib ketdi. Keyinroq urinib ko'ring",
  INVALID_PHONE: "Telefon raqam noto'g'ri",
  DRIVER_NOT_APPROVED: "Profil tasdiqlanmagan",
  DRIVER_NOT_AVAILABLE: "Faol holatni yoqing",
  DRIVER_DOCUMENTS_INCOMPLETE: "Barcha kerakli hujjatlarni yuklang",
  DRIVER_DOCUMENT_INVALID_TYPE: "Hujjat turi noto'g'ri",
  DRIVER_DOCUMENT_TOO_LARGE: "Hujjat hajmi juda katta",
  CITY_INACTIVE: "Tanlangan shahar faol emas",
  DISTRICT_REQUIRED: "Tumanni tanlang",
  DISTRICT_CITY_MISMATCH: "Tuman tanlangan shaharga tegishli emas",
  DISTRICT_INACTIVE: "Tanlangan tuman faol emas",
  ROUTE_TARIFF_NOT_FOUND: "Bu yo'nalish uchun narx topilmadi",
  ROUTE_NOT_MATCHED: "Bu buyurtma sizning yo'nalishingizga mos emas",
  BID_UPDATE_LIMIT_REACHED: "Taklif narxini 3 martadan ko'p o'zgartirib bo'lmaydi",
  ALREADY_EXISTS: "Siz bu buyurtmaga allaqachon taklif bergansiz",
  UNAUTHORIZED: "Avval tizimga kiring",
  FORBIDDEN: "Ruxsat yo'q",
  USER_BLOCKED: "Foydalanuvchi bloklangan",
  USER_INACTIVE: "Foydalanuvchi faol emas",
  VALIDATION_ERROR: "Ma'lumotlarni tekshiring",
  NOT_FOUND: "Ma'lumot topilmadi",
};

export function getUzbekErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return uzbekErrorMessages[error.code] ?? "Xatolik yuz berdi";
  }
  if (error instanceof Error && error.message) {
    return "Xatolik yuz berdi";
  }
  return "Internet aloqasi yo'q";
}
