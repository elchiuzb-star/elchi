# Haydovchi GPS’i: avtomatik sinov va real telefondagi dala sinovi (Q148, Q149)

**Kim uchun:** haydovchi telefonidan joylashuv yuborish (`mobile-app`, foreground) va mijoz xaritasidagi jonli kuzatuvni
chiqarishdan oldin tekshiradigan dasturchi yoki QA.

**Muhim chegara:** quyidagi 1-bo‘lim kompyuterda avtomatik bajariladi. 2-bo‘lim — **real Android telefonda qo‘lda**:
ekran qulfi, batareya tejash rejimi, haqiqiy GPS va mobil internet emulyatsiya qilinmaydi. 2-bo‘lim bajarilmaguncha
hech bir hisobot «real qurilmada o‘tdi» deb yozmaydi (AGENTS §7).

## 1. Avtomatik tekshiruvlar (kompyuterda)

| Nima | Buyruq | Kutilgan |
|---|---|---|
| Nuqta qoidalari, soxta signallar | `py -m pytest tests/modules/tracking -q` | hammasi o‘tadi |
| Tracking PostgreSQL (K1–K9, Q149) | `ELCHI_TEST_PG_REQUIRED=1 py -m pytest -m pg tests/pg/tracking` | hammasi o‘tadi |
| Klient (navbat, tracker, panel, WebSocket) | `cd mobile-app && npx vitest run` | hammasi o‘tadi |
| API e2e: HTTPS + WSS proksi orqali | `node scripts/tracking_e2e_api.mjs` | `8/8 checks passed` |
| Haqiqiy Chrome (CDP): HTTPS, ruxsat, GPS emulyatsiyasi, teleport | `node scripts/tracking_e2e_browser.mjs` | `7/7 browser checks passed` |

E2E uchun muhit (sintetik baza, [SYNTHETIC_UI_DB.md](SYNTHETIC_UI_DB.md) tartibida, baza nomi `elchi_ui_tracking`):

```bash
docker exec elchi-test-postgis-1 psql -U elchi_test -d postgres -c "CREATE DATABASE elchi_ui_tracking"
export ELCHI_DATABASE_URL="postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_ui_tracking" \
       ELCHI_ENVIRONMENT=development ELCHI_SECRET_KEY="<shu baza uchun tasodifiy qiymat>"
py -m alembic upgrade head
py scripts/seed_adr26_ui_world.py --out "$OUT"          # adr26_world.json: sintetik tokenlar
py -m uvicorn app.main:app --host 127.0.0.1 --port 8010
# tracking_enabled - faqat admin API orqali (Q72): PUT /api/v2/admin/feature-flags/tracking_enabled/scopes/country/UZ
# (super_admin tokeni adr26_world.json da), body {"enabled": true, "reason": "..."}

# Git Bash'da MSYS_NO_PATHCONV=1 SHART: aks holda "/api/v1" "C:/Program Files/Git/api/v1" ga aylanadi
cd mobile-app
MSYS_NO_PATHCONV=1 ELCHI_DEV_API_PROXY=http://127.0.0.1:8010 VITE_API_BASE_URL=/api/v1 \
  ELCHI_DEV_HTTPS_CERT=cert.pem ELCHI_DEV_HTTPS_KEY=key.pem npx vite --host 127.0.0.1 --port 5175
# brauzer sinovining 1-qadami uchun: xuddi shu, lekin sertifikatsiz, LAN IP'da (http://<LAN-IP>:5176)

ELCHI_E2E_OUT="$OUT" ELCHI_E2E_INSECURE_BASE=http://<LAN-IP>:5176 node scripts/tracking_e2e_browser.mjs
```

Avtomatik sinov nimani **isbotlamaydi**: brauzer fonga o‘tganda yoki ekran qulflanganda Android Chrome haqiqatan
nima qilishi, batareya tejash rejimi, haqiqiy GPS shovqini, mobil tarmoq uzilishi. Bular — 2-bo‘lim.

## 2. Real telefondagi dala sinovi (qo‘lda)

**Tayyorgarlik.** Telefon va kompyuter bitta Wi-Fi’da. Telefon ishonadigan sertifikat kerak:
`mkcert -install` + `mkcert <LAN-IP>` (mkcert ildiz sertifikatini telefonga ham o‘rnating), yoki vaqtinchalik HTTPS
tunnel. Vite’ni `--host 0.0.0.0` bilan ishga tushiring, telefonda `https://<LAN-IP>:5173` ni oching. Ikkinchi qurilma
(yoki kompyuter brauzeri) mijoz sifatida bron kuzatuv ekranini ochadi.

Har qadamda natija, vaqt, telefon modeli, Android va Chrome versiyasini yozing. «Kutilgan» bajarilmasa — xato.

| # | Qadam | Kutilgan |
|---|---|---|
| F1 | Sahifani **HTTP** manzilda oching, safarni boshlang | Panel: «Sahifa xavfsiz (HTTPS) manzilda ochilmagan…»; sessiya ochilmaydi |
| F2 | HTTPS’da birinchi marta «Yoqish» | Chrome ruxsat so‘raydi; panelda «Ruxsat berish»ni tanlash maslahati |
| F3 | Ruxsatni **rad eting** | «Joylashuvga ruxsat berilmagan» + Chrome sozlamasiga yo‘l; server sessiya ochmaydi |
| F4 | Sayt sozlamasida ruxsatni yoqing (sahifani yangilamasdan) | Yuborish o‘zi tiklanadi, «Joylashuv yuborilmoqda» |
| F5 | Telefon sozlamasida **GPS’ni o‘chiring** 2 daqiqaga | ~1 daqiqadan keyin «GPS yoqilganini va batareya tejash…» maslahati; GPS qaytgach — «telefon joylashuv bermadi» oralig‘i ko‘rsatiladi |
| F6 | 10 daqiqa haydang, ekran yoniq | Mijoz xaritasida nuqta ~10–15 s kechikish bilan yuradi, «Jonli joylashuv» |
| F7 | **Ekranni qulflang** 3 daqiqaga | Mijozda 30 s’dan keyin «kechikmoqda», 2 daqiqadan keyin «aloqa uzilgan», marker kulrang. Qulf ochilgach: yuborish davom etadi, panelda «ekran qulflangan yoki ilova fonda edi» oralig‘i |
| F8 | Boshqa ilovaga o‘ting 3 daqiqaga | F7 bilan bir xil («fonda») |
| F9 | **Batareya tejash rejimini** yoqing, 5 daqiqa haydang | Panel batareya foizini va ogohlantirishni ko‘rsatadi (≤ 20 %, quvvatlagichsiz); nuqtalar siyraklashishi mumkin — mijoz buni kechikish sifatida ko‘radi, soxta «jonli» emas |
| F10 | Parvoz rejimi 2 daqiqa, keyin o‘chiring | «Internet yo‘q: N ta nuqta telefonda kutmoqda»; aloqa qaytgach hammasi yuboriladi, trekda teshik yo‘q |
| F11 | Sahifani yangilang (yoki brauzerni yopib oching) safar davomida | Yangi sessiya ochiladi (§10.4), eski navbatdagi nuqtalar yo‘qolmaydi |
| F12 | Ikkinchi qurilmada shu haydovchi bilan yuborishni yoqing | Birinchi qurilma: «boshqa qurilma yoki oynadan yuborilmoqda», «Shu telefondan yuborish» tugmasi |
| F13 | Android’da **soxta GPS ilovasi** (Developer options → mock location app) bilan 100 km «sakrang» | Mijoz markeri sakramaydi; operator navbatida (Admin → Ishonch → Firibgarlik signallari) `suspicious_location` signali (skaner ishlaganda) |
| F14 | Soxta GPS bilan **silliq marshrut** simulyatsiyasi | Brauzer mock bayrog‘ini o‘qiy olmaydi: agar tezlik/aniqlik tabiiy bo‘lsa, aniqlanmasligi mumkin — natijani yozing (ma’lum cheklov) |
| F15 | Safarni «Yakunlash» | Oxirgi nuqtalar yuboriladi, sessiya yopiladi, panel yo‘qoladi; mijozda kuzatuv oynasi yopiladi |

## 3. Soxta joylashuvni aniqlash — nimani qila oladi, nimani qila olmaydi (Q149)

Server har nuqtani tekshiradi va belgilaydi; hech bir belgi haydovchini bloklamaydi, jarimalamaydi yoki strike
bermaydi (§10.4, §17.3). Bir sessiyada 24 soat ichida ≥ 3 ta shubhali nuqta — operator navbatiga bitta
`suspicious_location` signali (faqat hisoblar va public id, koordinata yo‘q).

| Belgi | Qachon | Marker’ni siljitadimi |
|---|---|---|
| `mock_location` | klient `is_mock=true` yuborgan (native ilova) | yo‘q |
| `implausible_speed` | oxirgi ishonchli nuqtadan > 70 m/s (252 km/soat) | yo‘q (ketma-ket ikkinchi izchil nuqta tiklaydi) |
| `zero_accuracy` | aniqlik aynan 0 m | yo‘q |
| `speed_mismatch` | qurilma tezligi 5–30 s ichidagi haqiqiy siljishdan ≥ 54 km/soat farq qiladi (aniqlik hisobga olinadi) | ha (faqat signal) |

Brauzer Android’ning «mock provider» bayrog‘ini o‘qiy olmaydi, klient aytgan narsani esa soxtalashtirish mumkin. Shuning
uchun web’da aniqlash **xulq-atvorga** asoslangan: sakrash, imkonsiz tezlik, tabiiy bo‘lmagan aniqlik va tezlik
ziddiyati. Tabiiy tezlikdagi silliq soxta marshrutni ishonchli aniqlash uchun qurilma attestatsiyasi (native ilova,
Play Integrity) kerak — bu ochiq cheklov.
