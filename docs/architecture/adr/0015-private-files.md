# ADR-0015: Private fayllar (H0 bajarmoqda)

**Holat:** Accepted (K2, Q6, 13.09.2026) — **implementatsiya H0 agentida** • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §17.4, §17.8, §19.1 • **AC:** AC40 (attachment tiklash)

## Kontekst
HEAD’da upload papkasi autentifikatsiyasiz `StaticFiles` (`app/main.py:59-63`, `app/core/config.py:58,61`), volume `docker-compose.prod.yml:38`. H0 tuzatmoqda (ishchi daraxtda `app/main.py`, `app/utils/file_storage.py`, `app/utils/file_access.py`, `app/api/v1/files.py` va testlar). A0a bu kodni o‘zgartirmaydi.

## Qaror (talablar; BR H0 natijasini shularga qarab tekshiradi)
1. Hujjat va dalil fayllari public static URL ostida emas; yuklab olish autentifikatsiyali yoki qisqa muddatli imzolangan havola orqali. Imzo kaliti `secret_key`dan domen-ajratilgan derivatsiya (`elchi:file-url-signing-key:v1`, ADR-0018).
2. **Ruxsat scope’i:**
   - Haydovchi hujjatlari (pasport, selfie, guvohnoma, avtomobil hujjatlari) — hujjat egasi va vakolatli staff.
   - **Cargo rasmi (Q6)** — faqat buyurtma egasi va shu buyurtmaga **tayinlangan** haydovchi; staff — admin endpointlari orqali. Taklif bergan, lekin tayinlanmagan haydovchi va boshqa foydalanuvchilar ko‘rmaydi. v2’da ekvivalent: parcel bron egasi (sender) va bronning haydovchisi.
   - Proof/nizo dalillari — bron ishtirokchilari va operator (A4/A12).
3. **v1 moslik:** muzlatilgan klientlar kutadigan maydonlar (`file_url`, `cargo_photo_url`) mavjud qoladi; qiymat shakli H0 hisobotiga ko‘ra.
4. v2’da fayl havolasi `file_id` (opaque); URL faqat so‘rov paytida.
5. Saqlash O‘zbekistonda (ADR-0011); backup/restore fayllarni ham qamraydi (AC40).
6. Akkaunt o‘chirilganda retention qoidasi (§17.8; A12).

## Oqibatlar
- v2 modullari H0 fayl kirish servisini qayta ishlatadi. H0 yakunlagach ADR uning haqiqiy qarorlari bilan yangilanadi.
