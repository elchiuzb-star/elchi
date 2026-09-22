# ADR-0018: Hosila kalitlar, proof kodlar va sir token’lar

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §10.6 (≥128 bit token, hash), §11 (kod hash, urinish limiti), §17.6 • **BR:** D11, D18
**Kontrakt:** `app/contracts/crypto.py`, `tests/contracts/test_tracking_crypto_policy.py`

## Kontekst
Bitta `ELCHI_SECRET_KEY` JWT imzolaydi (`app/core/config.py`). H0 fayl URL imzosi uchun undan alohida kalit derivatsiya qiladi: `HMAC-SHA256(secret_key, b"elchi:file-url-signing-key:v1")` (`app/utils/file_access.py`, ishchi daraxt). Stage-2 cursor, proof kod va share token’lari ham sir talab qiladi. Raw `secret_key`ni bir nechta maqsadda ishlatish kalit ajralishini buzadi (BR D11). `uuid4` identifikator, sir emas (BR D18).

## Qaror
1. **Derivatsiya:** `crypto.derive_subkey(master, purpose, version=1) = HMAC-SHA256(master, b"elchi:<purpose>:v<version>")` — H0 formati bilan bir xil. Purpose’lar: `booking-proof-code-key`, `cursor-signing-key`, `file-url-signing-key` (H0). Yangi maqsad — yangi purpose; rotatsiya — `version`.
2. **Proof kodlar:** `derive_proof_code(proof_key, booking_public_id, proof_kind, rotation)` — 6 raqamli HMAC truncation; plaintext saqlanmaydi. DB’da `proof_code_hash` (keyed HMAC, qisqa kod uchun unkeyed hash yetarli emas), `failed_attempts ≤ 5`, `code_rotation`. Limitdan keyin operator rotatsiya qiladi (eski kod yaroqsiz).
3. **Kod ko‘rsatish:** faqat kod egasiga (`GET /bookings/{id}/codes`), qayta hisoblash yo‘li bilan; haydovchi javobida yo‘q.
4. **Sir token’lar** (tracking grant, share link): `crypto.new_secret_token()` — `secrets.token_bytes(32)` base64url (minimum 16 bayt = 128 bit); DB’da `secret_token_hash` (SHA-256). URL faqat yaratilganda bir marta qaytadi.
5. `public_id` (UUIDv4) hech qachon ruxsat beruvchi sir sifatida ishlatilmaydi.
6. Alohida env kalitlari (`ELCHI_PROOF_CODE_KEY` va h.k.) keyin qo‘shilishi mumkin; bo‘lmasa derivatsiya fallback’i (H0 naqshi).
7. **Rotatsiya oynasi (BR N5):** proof kod tekshiruvi `crypto.build_keyring(purpose, current_master, previous_masters, version, previous_versions)` + `verify_proof_code` orqali. Yangi kodlar doim `current` subkey bilan; oldingi `secret_key` (yoki oldingi subkey `version`) `KEY_ROTATION_VERIFICATION_WINDOW` (48 soat) davomida faqat **tekshiruv** uchun qabul qilinadi, keyin konfiguratsiyadan olib tashlanadi. Barcha kalitlar ketma-ket tekshiriladi (qaysi kalit mos kelgani vaqt bo‘yicha sizmaydi). `booking_proofs` joriy `PROOF_CODE_KEY_VERSION`ni qayd etadi.
8. Oldingi master kalitlar konfiguratsiyasi (masalan `ELCHI_PREVIOUS_SECRET_KEYS`) va rotatsiya runbook’i — A10a; tekshiruvni ulash — A4. `KeyRing` naqshi cursor imzosi uchun ham ishlatilishi mumkin (eski cursor rotatsiyadan keyin `INVALID_CURSOR` bo‘lishi ham qabul qilinadi).

## Muqobillar
- **HKDF (`cryptography`)** — `contracts` dependency-free qoidasi; HMAC label ajratish shu maqsad uchun yetarli va H0 bilan mos.
- **Kodni shifrlab saqlash** — kalit boshqaruvi og‘irroq, spec hash’ni talab qiladi.

## Implementatsiya holati (wave 1.5 integratsiyasi)
- **Kodda bor:** `app/core/config.py` — `previous_secret_keys` (`ELCHI_PREVIOUS_SECRET_KEYS`, vergul bilan, yangisi birinchi), `proof_code_key` (`ELCHI_PROOF_CODE_KEY`), `cursor_signing_key` (`ELCHI_CURSOR_SIGNING_KEY`), ixtiyoriy, ≥ 32 belgi, bo‘sh → derivatsiya. Helper’lar: `proof_code_keyring()` = `build_keyring(PURPOSE_BOOKING_PROOF_CODE, proof_code_key or secret_key, previous_masters=previous_secret_keys)` (A4 proof kodlarida ishlatadi); `cursor_signing_secret()` = `derive_subkey(cursor_signing_key or secret_key, PURPOSE_CURSOR_SIGNING)` — `app/api/v2/web.py` ulangan; eski kalit bilan cursor qabul qilinmaydi (klient paginatsiyani qaytadan boshlaydi).
- **Keyingi ish:** `app/modules/wallet/api.py` cursor’i hali `derive_subkey(settings.secret_key, …)` — A3 `cursor_signing_secret()`ga o‘tkazadi.
- **Ochiq band (Proposed emas, ish bandi):** JWT keyring — `kid` header, joriy kalit bilan imzo, `ELCHI_PREVIOUS_SECRET_KEYS`dagi kalitlar `refresh_token_expire_days` davomida qabul; hozir JWT raw `secret_key` bilan (`app/core/security.py`, v1) va master rotatsiyasi barcha sessiyalarni chiqaradi. `otp_hash` ham previous master’larni sinamaydi. v1 xulqi o‘zgarishi sababli alohida karta/qaror bilan (egasi: A1 + A10a runbook).

## Wave 2.1 qo‘shimchasi (15.09.2026, BR blocker 3, Q65)
- **Proof kodni qayta chiqarish** (2-banddagi “limitdan keyin operator rotatsiya qiladi”ni aniqlashtiradi): `booking_proofs.code_rotation + 1` — eski kod endi tekshiruvdan o‘tmaydi, `failed_attempts` 0 dan boshlanadi. Kanallar: (a) kod egasi o‘zi (passenger — boarding; jo‘natuvchi — pickup/delivery/return; **driver hech qachon**), `app.contracts.proofs.reissue_decision` limiti bilan (2 daqiqa oraliq, 24 soatda 3 marta; oshsa `429 PROOF_REISSUE_LIMITED`); (b) operator `OperatorBookingCommand.REISSUE_PROOF_CODE` (`ops.booking_command`, sabab majburiy, limitsiz). Har biri audit qatori va `booking.proof_code.reissued` event’i (kodsiz). Qabul qilingan proof qayta chiqarilmaydi.
- **Q65:** delivery kodi pilotda jo‘natuvchiga B5 orqali `WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY` ogohlantirishi bilan ko‘rsatiladi; chatda 6 xonali kodga o‘xshash raqamlar maskalanadi (`contact_filter.scan(..., mask_proof_codes=True)`, kategoriya `proof_code`). Keyin kod qabul qiluvchiga havola/SMS orqali (A13/A7).

## Oqibatlar
- `secret_key` rotatsiyasi barcha subkey’larni (JWT, fayl URL, cursor, proof kod) birga almashtiradi — runbook’da (A10a) ko‘rsatiladi; proof kodlar uchun ikki kalitli tekshiruv oynasi (N5) foydalanuvchiga ko‘rsatilgan kodlarni buzmaydi.
