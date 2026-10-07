# Dizayn v3 — backend uchun topshiriq (handoff)

**Kimga:** backend (Temur). **Sana:** 07.10.2026. **Holat:** Android, iOS va `/admin` Claude Design v3 bo'yicha
qurilmoqda; quyidagi bandlar backendda maydon yoki endpoint yo'qligi sababli **ekranda yashirilgan** (BLOCKED).
Maydon paydo bo'lgach ilova uni ko'rsatadi — hammasi **additiv** bo'lishi kifoya, mavjud javoblar o'zgarmaydi.
Batafsil manba: `elchi-dev/DESIGN-V3-*-DIFF.md`, `DESIGN08/09/10-DIFF.md` (har band raqami qavsda).

Qoida: bu ro'yxat qaror emas, so'rov. AGENTS.md ga zid band (masalan, Q150 bo'yicha yo'nalishga jo'nash vaqti,
Q160 bo'yicha «Yaqin» moslik turi) bu yerga kiritilmagan — ilova u yerlarda qoidaga amal qiladi.

## Haydovchi: bosh sahifa, yo'nalishlar, safar (Royxat v3, Safar v3)
1. **Matn qidiruvi** — `q` parametri: `GET /driver-directions/{id}/requests` va `GET /feed` (Safar 1.4). Hozir klient
   o'zi filtrlaydi.
2. **Kam balans chegarasi** — `WalletDTO` da minimal balans / «to'ldirish kerak» belgisi (Royxat 1.5, Safar 1.9).
3. **Haydovchi shahri** — profil DTO da hudud/shahar (Royxat 1.3, Safar 1.3).
4. **Yo'nalish uchlarini tahrirlash** — `DriverDirectionPatch` ga `origin`/`destination` (Safar 2.4). Hozir faqat
   arxivlab yangisini qo'shish mumkin.
5. **Safar sarlavhasi** — `TripDTO.direction_id` yoki `origin_name`/`destination_name` (Safar 4.1). Hozir yo'nalishsiz
   safar vaqt bilan ataladi.
6. **Bo'laklar yorlig'i** — `ManifestPlaceDTO.position_m` yoki `StretchAvailabilityDTO` da joy nomlari (Safar 4.5);
   500 m dan qisqa bo'lak «0–0 km» bo'lib chiqadi.
7. **Taklif soni lentada** — `DirectionRequestItemDTO.offer_count` (Safar 5.8).
8. **Haydovchi uchun narx bandi** — haydovchi o'qiy oladigan band endpointi (Safar 6.4, 7.9).
9. **Yo'nalishga yangi so'rov xabari** — `SAVED_SEARCH_MATCHED` dan tashqari yo'nalish eventi (Safar 5.9).

## Haydovchi: bron ijrosi (BOSQICH 08)
10. **O'qilmagan xabarlar soni** — `/me/bookings` qatorida `unread_count` (08: 1.8).
11. **Ochiq bron kodi** — `BookingDTO.public_code` (08: 2.2), mijoz va haydovchi bir xil kodni aytishi uchun.
12. **Chat tizim qatorlari** — `ChatMessageDTO.kind=system` + event kodi (08: 9.5). Typing indikatori — keyinroq (9.4).
13. **Manzilgacha masofa** — `BookingTrackingDTO.remaining_distance_m` (08: 11.5).

## Haydovchi: hamyon (BOSQICH 09)
14. **Bank rekvizitlari** — konfiguratsiya yoki endpoint (09).
15. **Top-up min/max** — `TopupCreate.amount_minor` chegaralari serverda (hozir faqat `gt=0`).
16. **Kvitansiya yuklash** — `evidence_file_id` uchun upload turi (09).
17. **Rad etish sababi** — `TopupDTO.rejection_reason` (09).
18. **Kutilayotgan so'rovni bekor qilish** — endpoint + holat (09, finance qarori kerak).

## Mijoz: profil va arxiv (Profil v3, BOSQICH 10)
19. **Murojaatni mijoz yopishi** — mijoz uchun support thread close (Profil 6.7).
20. **O'chirishdan oldingi tekshiruv** — akkaunt o'chirish to'siqlarini oldindan aytadigan endpoint (Profil 9.1).
21. **v1 baho** — `GET /api/v1/client/orders/{id}` da `my_rating` (BOSQICH 10, 2.8). v1 xulq o'zgarishi — AGENTS §2
    bo'yicha alohida tasdiq bilan.

## Admin (`/admin` v3)
22. **Moliya roli uchun kunlik summa va holatlar** — v2 dan 7 kunlik bron summalari/holat sonlari (Admin 2.8).
23. **30 daqiqalik GPS iz** — xodim safar joylashuvi endpointida `points[]` (Admin 4.7, auditli).
24. **Haydovchi + avtomobilni birga tasdiqlash** — bitta endpoint (Admin 15.4); hozir ikki tugma.
25. **Hujjat hajmi va turi** — `AdminDriverDocument.size_bytes`/`mime` (Admin 15.7).
26. **KPI kunlik qatori** — `/admin/metrics/kpi` da kunlik seriya (Admin 19.1).

Har band tayyor bo'lgach `mobile-app/src/api/generated` ni yangilang; native tomonda `scripts/gen_native_api.py`
ni biz ishga tushiramiz va ekranni yoqamiz.
