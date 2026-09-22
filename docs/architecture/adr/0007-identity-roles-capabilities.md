# ADR-0007: Identity — `user_roles` + capability, `users.role` va JWT backward compatible

**Holat:** Accepted (Q3, Q8, Q15, Q17, Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §2, §8.1, §9.2, §10, §12, §13, §15, §16, §17.5 • **AC:** AC05, AC41 • **BR:** D16
**Kontrakt:** `Capability`, `STAFF_ROLE_CAPABILITIES`, `NEW_BUSINESS_CAPABILITIES`, `OBLIGATION_CAPABILITIES`, `role_combination_allowed` (`app/contracts/enums.py`)

## Kontekst
`users.phone` unique (`app/models/user.py:13`), bitta `users.role` (`:23`), OTP rolga bog‘langan (`app/services/auth_service.py:219-235,393-398`), JWT `role` (`:503`), v1 ruxsat DB `users.role` bo‘yicha (`app/api/deps.py:46-55`). v1 `block_driver` `verification_status` va `users.status`ni `blocked` qiladi (`app/services/admin_driver_service.py:397-416`, HEAD).

## Qaror
1. **Jadval:** `user_roles(user_id, role, status, granted_by, created_at)`, `UNIQUE(user_id, role)`; backfill `users.role`dan (idempotent).
2. **`users.role` = legacy primary role**, v1 va JWT uchun o‘zgarmaydi; telefon unique saqlanadi.
3. **Q3 — akkauntlar alohida:** staff (`operator/admin/super_admin/finance`) va marketplace (`client/driver`) rollari bitta akkauntda birlashmaydi (`409 ROLE_COMBINATION_FORBIDDEN`; DB’da trigger). Client+driver bitta akkauntda mumkin.
4. **Q8 — OTP:** 4 xona saqlanadi, v1 xulqi o‘zgarmaydi; 6 xona Android v2 klienti bilan. Review/store akkauntlari real foydalanuvchi va pulga yetmaydi — H1. Staff MFA rejasi — A12 (wave 3). v2 login endpointi yo‘q; mobile-app v1 OTP’dan foydalanadi.
5. **Capability serverda, har so‘rovda** (blok darhol, AC41):
   - `client` roli (akkaunt faol) → `listing.create_request`, `proposal.submit_as_client`.
   - `driver` roli: **eligible** (`verification_status='approved'`, akkaunt faol, eligibility bloki yo‘q, hujjatlar amal qiladi) → `NEW_BUSINESS_CAPABILITIES` (`listing.create_trip_offer`, `proposal.submit_as_driver`, `trip.create`) + `OBLIGATION_CAPABILITIES`; **eligible emas, lekin tayinlangan non-terminal trip/bron bor** → faqat `OBLIGATION_CAPABILITIES` (`trip.operate`, `tracking.publish`, `wallet.view_own`, `wallet.topup_request`) va o‘z bronlaridagi proof/cash/dispute amallari.
   - Staff: `STAFF_ROLE_CAPABILITIES` — operator: `ops.view`, `ops.booking_command`, `ops.dispute_resolve`, `finance.commission_policy_view`; admin: + `ops.dispute_decide` (wave 3.1: v2 nizosini yopish — v1 Q13/Q38 pariteti; operator faqat ko‘rib chiqadi va izoh yozadi), `ops.booking_cancel`, `ops.corridor_manage`, `ops.feature_flag_manage`, `ops.driver_eligibility_manage`, `finance.reports`; **finance (Q17):** `ops.view`, `finance.topup_approve`, `finance.adjustment`, `finance.adjustment_approve`, `finance.fee_finalize`, `finance.reports`, `finance.commission_policy_view`; super_admin: admin + finance capability’lari (rol ulanguncha finance vazifasini bajaradi) + `finance.commission_policy_manage` (Q2), `staff.manage`. Katta tuzatish/top-up: ikkinchi tasdiq boshqa xodimdan (`finance.adjustment_approve`, servis tekshiradi).
6. **D16 — bloklash semantikasi:** driver eligibility bloki (v2 `POST /api/v2/admin/drivers/{id}/eligibility`), rad etish yoki hujjat muddati tugashi faqat yangi bron, listing va trip’ni to‘xtatadi; faol trip’larda tracking, proof, cash, support davom etadi (§9.2, §10). Eligibility bloki `users.status`ni o‘zgartirmaydi.
   **Account suspension** (`users.status != 'active'`) — alohida xavfsizlik amali: v1 kabi barcha API’ni yopadi; operator avval faol trip/bronlarni hal qiladi.
7. **Self-dealing:** o‘z listing’iga taklif va o‘z versiyasini qabul qilish — `403 SELF_DEALING_FORBIDDEN` (AC05).
8. **Eligibility lock:** `identity.lock_user_eligibility(user_ids)` — lock tartibining birinchi guruhi (ADR-0017); admin eligibility bloki shu lock’ni oladi. v1 `block_driver` ↔ `select_driver_for_order` race — H1.
9. **JWT** o‘zgarmaydi.

## Hal qilingan bandlar
- **Q22:** faol (`users.status='active'`) driver akkaunti tasdiqlashdan oldin yoki eligibility blokida ham `wallet.view_own` va `wallet.topup_request`ga ega — bu yangi biznes emas (`OBLIGATION_CAPABILITIES`dagi wallet capability’lari faol trip talab qilmaydi).
- **Q21:** mijoz taklifi eligible bo‘lmagan (bloklangan, tasdiqlanmagan, hujjati o‘tgan) haydovchining trip_offer’iga rad — `403 DRIVER_NOT_ELIGIBLE`; A5 lentasi bunday listing’larni ko‘rsatmaydi.
- **Q23:** boshqaning listing’ini bekor qilish — `ops.booking_command` + audit qatori; operator `draft`ni bekor qila olmaydi.
- **Q17:** top-up tasdiqlash va `finalize_fee` — `finance` roli; rol ulanguncha super_admin. `user_roles` CHECK’iga `finance` qo‘shiladi (A1), capability tekshiruvi — A3.
- **Q15:** v1 `block_driver` faol v2 trip’li haydovchi uchun faqat yangi biznesni bloklaydi (v2 eligibility bloki sifatida ishlaydi); faol trip, GPS va support davom etadi. To‘liq favqulodda blok (`users.status=blocked`) — faqat super_admin. Egasi: A4/A12, v2 trip’lar mavjud bo‘lgach (wave 2/3 kartasi).

## Muqobillar
- `users.role`ni ko‘p qiymatli qilish — v1 buziladi. Rol bo‘yicha alohida telefon — §16 ga zid. Capability JWT’da — blok kechikadi.

## Oqibatlar
- Har v2 so‘rovda eligibility query (cache yo‘q).
