# Sintetik UI bazasi (`elchi_ui_adr26`)

**Nima uchun:** ADR-0026 ekranlarini (mijoz, haydovchi, operator) haqiqiy backend va PostgreSQL bilan tekshirish va
360/390/1280 kenglikda skrinshot olish. Unda faqat **sintetik** odamlar, telefonlar, narxlar va belgilangan sintetik
o'lcham katalogi bor. Hech qanday haqiqiy foydalanuvchi, pul yoki production ma'lumoti yo'q.

**Qayerda:** lokal test stack (`docker-compose.test.yml`, PostGIS `127.0.0.1:45432`), baza nomi `elchi_ui_adr26`.
PG test to'plami o'z bazalarini alohida yaratadi. Bu bazaga tegmaydi, lekin test yurishi bilan bir vaqtda ishlatmang
(qarang: PG testlarini bir-biriga ustma-ust yurgizmaslik qoidasi).

**Saqlanishi:** test stack PostGIS ma'lumotni tmpfs'da saqlaydi — konteyner yoki Docker qayta ishga tushsa, baza
yo'qoladi va quyidagi tartib bilan qayta yaratiladi (25.09.2026 da Docker qayta ishga tushirilgandan keyin shunday
qayta yaratildi).

**Ichida nima bor** (`scripts/seed_adr26_ui_world.py`):
- sintetik katalog (`synthetic=true`): konvert, kichik quti, o'rta quti;
- mijozning e'lon qilingan pochta so'rovi (haydovchi lentasida toifa bilan ko'rinadi);
- ikkinchi haydovchi bilan pochta broni: trip jo'nagan (`in_transit`), kelishilgan narx 72 000 so'm;
- shu bron bo'yicha ikkita «Yordam / shikoyat» chati: mijozniki (navbatda) va haydovchiniki (operator javob bergan);
- `client_new` — hech narsasi yo'q (bo'sh holatlar).

**Qayta yaratish** (`.env` o'zgartirilmaydi — qiymatlar faqat shu shell uchun):
```bash
docker exec elchi-test-postgis-1 psql -U elchi_test -d postgres -c "DROP DATABASE IF EXISTS elchi_ui_adr26" -c "CREATE DATABASE elchi_ui_adr26"
export ELCHI_DATABASE_URL="postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_ui_adr26" \
       ELCHI_ENVIRONMENT=development ELCHI_SECRET_KEY="<faqat shu sintetik baza uchun tasodifiy qiymat>"
py -m alembic upgrade head
py scripts/seed_adr26_ui_world.py --out <papka>   # adr26_world.json: sintetik id va dev token'lar
py -m uvicorn app.main:app --host 127.0.0.1 --port 8010
# mobile-app: VITE_API_BASE_URL=http://127.0.0.1:8010/api/v1 npx vite --host=127.0.0.1 --port 5174
```
Skript faqat nomi `elchi_ui_` bilan boshlanadigan bazaga yozadi va production muhitida ishlamaydi.

**Vaqt bo'yicha eslatma:** sintetik safar kelajakdagi sanada. Telefon ochilishini (Q142) ko'rsatish uchun
`in_transit` bronning `service_started_at` qiymati shu bazada qo'lda «hozir − 10 daqiqa»ga suriladi. Bu faqat
sintetik bazadagi ko'rinish uchun; kod yoki test bunga tayanmaydi.

**Qachon o'chiriladi:** ADR-0026 ekran tekshiruvi yopilgach yoki foydalanuvchi aytganda
(`DROP DATABASE elchi_ui_adr26`). Bu baza zaxira qilinmaydi va hech qayerga ko'chirilmaydi.
