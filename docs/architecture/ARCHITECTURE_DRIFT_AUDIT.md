# Arxitektura drift auditi — ELCHI marketplace modeli

**Sana:** 18.09.2026 • **Doira:** `app/` (v2 modullar, kontraktlar), `mobile-app/src/`, `alembic/`, `tests/`, `docs/architecture/`
**Mezon:** `ELCHI_PRODUCTION_ARCHITECTURE.md` §5 (e'lonlar va **ikki tomonlama narx kelishuvi**), §6 (moslik), §8 (ranking)
+ foydalanuvchi qarorlari Q88–Q93.
**Usul:** kod o'qish + `py -m pytest tests/modules tests/contracts -q` (ishga tushirildi). PG testlari **ishga tushirilmadi**
— Docker daemon ochiq emas (`docker ps` → `cannot find the file specified`). PG bo'yicha da'volar kod o'qishga asoslangan
va shunday belgilangan.

> **Qoida:** hech narsa refaktor qilinmadi (§15). Bu hujjat — tasnif, tuzatish emas.

---

## 1. ELCHI'ning asl invariantlari (mezon)

Spetsifikatsiyaning o'zi (o'zgartirilmaydigan manba) quyidagini aytadi:

| # | Invariant | Spec manzili |
|---|---|---|
| I1 | `listing` — hali kelishilmagan e'lon; `proposal_thread` — muzokara; `proposal_version` — o'zgarmas versiya; `booking` — ikki tomon qabul qilgan snapshot; `trip` — real jismoniy safar | §3 lug'at, §5 |
| I2 | «`bids` faqat haydovchidan buyurtmaga» modeli **ataylab rad etilgan**: kerak bo'lgani — ikki tomonlama kelishuv va o'zgarmas taklif versiyalari | 45-qator |
| I3 | Taklif yuborish o'rin yoki balansni **band qilmaydi**; band qilish faqat accept paytida atomar | 123-qator |
| I4 | Narx — kelishuv natijasi. «Masofaga mutanosib hisob **yakuniy kelishuv o'rnini bosmaydi**» | 188-qator |
| I5 | `L/U` narx diapazoni — **faqat ranking `P` komponenti**; ishonchli diapazon bo'lmasa `P=0.5` | 240-qator |
| I6 | Bitta `trip` bir nechta e'lon va bir nechta bronni ko'tara oladi; sig'im **segment** bo'yicha | 97, 200–210-qatorlar |
| I7 | Mijoz haydovchini reyting, sharh va avtomobilga qarab **o'zi tanlaydi** (inDrive tamoyili) | 62, 960-qatorlar |

**Muhim xulosa:** spetsifikatsiyada **qattiq narx bandi (hard price band) hech qachon bo'lmagan.** U wave 1.6 da
ADR-0019 orqali kiritilgan («7-band "ogohlantirish" varianti rad etildi»). Ya'ni **Q90 — spetsifikatsiyadan
chekinish emas, aksincha, unga qaytish.** Chekingan hujjat — ADR-0019.

---

## 2. Topilgan drift

| # | Drift | Jiddiylik | Holat | Tasnif |
|---|---|---|---|---|
| D-01 | Narx bandi taklif/qarshi taklifni **bloklaydi** (`400 PRICE_OUT_OF_BAND`) | P0 | Kodda **tuzatilgan** (wave 15), lekin ish **yarim** | FIX (davomi) |
| D-02 | Kontrakt hujjatlari hamon «band → 400» deydi — kod bilan zid, §1 manba tartibida hujjat kod ustida | P0 | Ochiq | FIX |
| D-03 | 5 ta test fayli hamon hard reject kutadi; 1 tasi **isbotlangan yiqilish** | P0 | Ochiq | FIX |
| D-04 | `enforced` (Q90 ning yagona qattiq chegarasi) admin API'da **yo'q** — o'qib ham, yozib ham bo'lmaydi | P1 | Ochiq | FIX |
| D-05 | `counter_proposal` nuqtali (Q88) e'londa **KeyError → 500** — qarshi taklif ishlamaydi | P0 | Ochiq | FIX |
| D-06 | `list_listing_offers` (P9, Q40) nuqtali e'londa **404** | P1 | Ochiq | FIX |
| D-07 | `listing_matches` (M2) nuqtali e'lonni **jimgina yo'qotadi** (ikkala yo'nalishda) | P1 | Ochiq | FIX |
| D-08 | Saqlangan qidiruv (`_search_matches`) nuqtali e'lonni **hech qachon topmaydi** | P2 | Ochiq | FIX |
| D-09 | `PRICE_OUT_OF_BAND` ogohlantirishi `WarningCode` reyestrida yo'q → mijozga **kod ko'rsatiladi**, jumla emas | P2 | Ochiq | FIX |
| D-10 | ADR-0019 «ogohlantirish varianti rad etildi» deb qolgan | P2 | Ochiq | FIX (supersede) |

### Drift **topilmagan** joylar (tekshirildi, toza — KEEP)

* Hisoblangan/fixed fare v2 da **yo'q**: `grep tariff|fare|calculated_price|suggested_price|auto_accept|auto_award`
  → faqat izohlar. Accept `version.unit_price_minor` / `version.total_minor` ni **o'zgarishsiz** ko'chiradi
  (`bookings/service.py:798`).
* Accept'siz booking yaratadigan oqim **yo'q**: `Booking(` yagona joyda — `bookings/service.py:760`, `accept_proposal` ichida.
* Publish seat/wallet hold **yaratmaydi**: `_publish_like` faqat status/version o'zgartiradi (`marketplace/service.py:1145`).
  `hold_fee` faqat accept'da.
* Passenger request modeli **olib tashlanmagan** — Q91 bo'yicha tiklangan; xato qo'riqchi test almashtirilgan
  (`tests/contracts/test_passenger_model_is_flag_gated.py`).
* Corridor **user-facing booking primitivi emas**: mijoz UI'da koridor tanlash ekrani yo'q; koridor faqat flag doirasi
  va validatsiya uchun ishlatiladi (`ConnectedApp.tsx:1525`, `1579`).
* Trip va trip_offer **aralashmagan**: `trips` jadvali alohida, `listings.trip_id` orqali bog'lanadi; bitta trip bir nechta
  e'lon ko'taradi (`has_published_trip_offer`, `listings_for_trip`).

---

## 3. Saqlanadigan to'g'ri komponentlar (KEEP)

**Kontrakt qatlami**
* `ListingKind {request, trip_offer}` × `ServiceType {passenger, parcel}` = to'rt tur, `ALLOWED_PRICE_BASIS` bilan
  kontraktda muhrlangan (`app/contracts/enums.py`).
* `ProposalStatus {active, superseded, accepted, rejected, withdrawn, expired}` — versiyalash to'g'ri.
* `app/contracts/money.py` — komissiya yagona manbada; float yo'q.

**Domen**
* `submit_proposal` ikki tomonlama: `proposer_side(kind)` — `request` → haydovchi taklif qiladi, `trip_offer` → mijoz
  (`marketplace/service.py:2131`). `SELF_DEALING_FORBIDDEN` bilan himoyalangan.
* `counter_proposal` har tahrirda yangi `ProposalVersion`, eskisi `superseded`, `price_revisions_left` cheklovi bilan.
* `accept` — yagona atomar nuqta: trip, sig'im, jadval, faol versiya, komissiya, wallet, listing holati qayta tekshiriladi.
* **Q88 geo ishi butunlay saqlanadi:** `_resolve_point_direction`, `_place_on_route`, `project_point_on_route`,
  `EndPlacement`, segment bo'yicha `pickup_occurrence_seq`, `ROUTE_MISMATCH`, koridor bo'yicha sozlanadigan radius
  (0077), `origin_point`/`destination_point` GiST indekslari, DB CHECK «stop **yoki** point, ikkalasi ham emas».
* `_point_listing_match` — nuqtali e'lon hech qachon `exact` bo'lmaydi, eng yaxshisi `on_route` (Q88 4-band).
* `evaluate_price_band` / `assert_price_within_band` — Q90 semantikasi to'g'ri yozilgan (`geo/pricing.py`).
* Ranking'da band faqat `P`/`Y` komponenti (`_client_components`, `_driver_components`) — I5 ga mos.

**Klient (`mobile-app`)**
* Ikkala kirish nuqtasi ham bor: mijoz «Yo'nalishni ko'rish» (o'z so'rovini narxi bilan e'lon qiladi) va
  «Haydovchi e'lonlarini ko'rish» (`side=offers`) — `ConnectedApp.tsx:2297–2313`.
* Haydovchi «Safarni e'lon qilish» (`driver-offer-create`, 4211) — o'z boshlang'ich narxi bilan; ekran matni
  aynan auksion semantikasini aytadi: «Bu — boshlang'ich narxingiz… e'lon o'rin yoki balansni band qilmaydi».
* Haydovchi lentasi (`driver-feed`, 4345) — mijoz so'rovlari, ikkala xizmat turi uchun.
* Qarshi taklif **ikkala tomonda** ishlaydi (`counterFor`, 3139–3168); avtomatik g'olib yo'q: mijoz «Shu haydovchini
  tanlash» tugmasi bilan o'zi tanlaydi (3611).
* Passenger rejimi `flags?.passenger_enabled` ortida — Q91 ga mos (2206, 4237, 4350).

---

## 4. Tuzatilishi kerak bo'lgan o'zgarishlar (FIX / REVERT)

### D-01/D-03 — wave 15 ishi yarim qolgan (P0)

`geo/pricing.py` va `marketplace/service.py::_check_price_band` Q90 ga ko'chirilgan, lekin **eski testlar
yangilanmagan**. Isbot (ishga tushirildi):

```
py -m pytest tests/modules tests/contracts -q
FAILED tests/modules/geo/test_geo_pricing.py::test_assert_price_within_band_raises_contract_error
        Failed: DID NOT RAISE <class 'app.contracts.errors.DomainError'>
```
Qolgan hammasi o'tdi (`tests/contracts` to'liq yashil).

Hamon hard reject kutayotgan fayllar (PG — ishga tushirilmadi, kod o'qish):
* `tests/pg/marketplace/test_marketplace_r2_band_pg.py:125,137,154` — `_band(...)` helper'i `enforced` yozmaydi
  → endi `submit_proposal` **rad etmaydi** → `pytest.raises` yiqiladi.
* `tests/pg/marketplace/test_marketplace_wave17_pg.py:165`, `test_marketplace_wave21_pg.py:115` — xuddi shunday.
* `tests/modules/geo/test_geo_pricing.py:89` — **isbotlangan yiqilish**.

**Tuzatish yo'nalishi:** bu testlar o'chirilmaydi — ular **`enforced=true`** stsenariysiga ko'chiriladi
(qattiq chegara hamon ishlashi kerak), va har biriga `enforced=false` da **ogohlantirish qaytishini** tekshiradigan
juftlik qo'shiladi. `test_price_is_negotiated_pg.py` allaqachon shu namunani beradi.

### D-02/D-10 — hujjatlar kodga zid (P0)

§1 manba tartibida kontrakt hujjati koddan yuqori turadi, shuning uchun bu shunchaki «eskirgan matn» emas —
ziddiyat. Yangilanishi shart:

| Fayl | Qator | Hozir | Bo'lishi kerak |
|---|---|---|---|
| `API_V2_CONTRACT.md` | 68 | «`PRICE_OUT_OF_BAND` details yagona manbada» | + «faqat `enforced` band rad etadi; aks holda `ApiWarning`» |
| `API_V2_CONTRACT.md` | 73 | `PriceBandUpsert {...}` / `PriceBandDTO {...}` | + `enforced` maydoni |
| `API_V2_CONTRACT.md` | 196 | P1 xatolari ro'yxatida `PRICE_OUT_OF_BAND` (Q42) | «(Q90: faqat `enforced`)» |
| `API_V2_CONTRACT.md` | 212 | «band'dan tashqarida bo'lsa `400`» | Q90 semantikasi |
| `STATE_MACHINES.md` | 207 | counter → `400 PRICE_OUT_OF_BAND` | ogohlantirish / `enforced` |
| `DATA_MODEL.md` | 264 | `corridor_price_bands` ustunlari | + `enforced` (0078) |
| `adr/0019-open-offer-visibility.md` | 3 | «7-band "ogohlantirish" varianti **rad etildi**» | Q90 bilan **superseded** deb belgilanadi (yangi ADR-0022, yoki 0019 sarlavhasiga «Superseded by Q90») |

### D-04 — `enforced` operatsion emas (P1)

`corridor_price_bands.enforced` ustuni bor (0078) va `PriceBand` dataclass'ida o'qiladi
(`geo/service.py:1888`), lekin:
* `set_price_band(...)` (`geo/service.py:1898`) parametrni **qabul qilmaydi**;
* `PriceBandDTO` (`geo/schemas.py:259`) maydonni **ko'rsatmaydi**;
* `PriceBandUpsert` da yo'q.

Natija: Q90 ning yagona qattiq chegarasi — abuse/safety limiti — **amalda yoqib bo'lmaydi**, va operator band
maslahatmi yoki majburiymi, buni ko'rmaydi. Xavfsiz tomonga qiyshaygan (hech qachon bloklamaydi), lekin chala.
`test_price_is_negotiated_pg.py` ning `configure_band()` funksiyasi `enforced` ni **to'g'ridan-to'g'ri SQL bilan**
yozishga majbur — bu ham shu bo'shliqning dalili.

### D-05 — qarshi taklif nuqtali e'londa yiqiladi (**P0**)

`marketplace/service.py:2353`:
```python
stops = get_ports().geo.stops_by_ids(session, [current.pickup_stop_id, current.dropoff_stop_id])
pickup, dropoff = stops[current.pickup_stop_id], stops[current.dropoff_stop_id]
```
Nuqtali (Q88) e'londa `submit_proposal` `pickup_stop_id=None` yozadi (points tarmog'ida `pickup = dropoff = None`,
`_insert_version`). `get_stops(session, [None, None])` → `{}` → `stops[None]` → **`KeyError` → 500**.

**Ta'siri:** Wave 13 klienti mijozga aynan **nuqtali** e'lon yaratadi (xaritadan joy). Ya'ni bugungi asosiy mijoz
oqimida: e'lon chiqadi ✅, haydovchi taklif yuboradi ✅, mijoz **qarshi taklif yubora olmaydi** ❌ — ikki tomonlama
auksionning yarmi o'lik. `submit_proposal` nuqtali tarmoqni to'g'ri ishlaydi (`_place_listing_ends_on_trip`),
`counter_proposal` esa shu tarmoqqa **umuman ega emas**.

**Test qopqog'i yo'q:** `tests/pg/marketplace/test_point_endpoints_pg.py` submit va accept'ni qamraydi, `counter`ni
**hech qayerda chaqirmaydi**.

### D-06 — Q40 raqobat ro'yxati nuqtali e'londa 404 (P1)

`marketplace/service.py:2841`:
```python
stops = get_ports().geo.stops_by_ids(session, [listing.origin_stop_id, listing.destination_stop_id])
_open_corridor(session, stops[listing.origin_stop_id], stops[listing.destination_stop_id])
except (DomainError, KeyError):
    raise DomainError(ErrorCode.NOT_FOUND)
```
`KeyError` allaqachon ushlanadi, shuning uchun 500 emas — lekin natija **404**: nuqtali e'londa P9
`GET /listings/{id}/offers` ishlamaydi. Q40 (anonim raqobatchi takliflar) shunday e'lonlarda mavjud emas.

### D-07 — M2 nuqtali e'lonni jimgina yo'qotadi (P1)

`feed/service.py:1075` va `1117`:
```python
origin_ids=(listing.origin_stop_id,)          # nuqtali e'londa -> (None,)
destination_ids=(listing.destination_stop_id,)
```
`best_trip_match` → `MatchRequest(pickup_stop_id=None, dropoff_stop_id=None)` →
`matching.py:169`: `if request.pickup_stop_id == request.dropoff_stop_id: return failure(ROUTE_MISMATCH, SAME_STOP)`
→ **bo'sh natija, xatosiz**.

Ya'ni `GET /listings/{id}/matches`:
* mijoz nuqtali so'rovi uchun — hech qanday trip offer topilmaydi;
* haydovchi trip_offer'i uchun — nuqtali mijoz so'rovlari nomzodlar ichidan tushib qoladi
  (`_evaluate_request_for_trip:808`).

**Diqqat:** asosiy `/feed` **to'g'ri** — u `_evaluate_request_by_stops` orqali `_point_listing_match` ni chaqiradi
(`feed/service.py:748`). Shuning uchun klient bugun buni sezmaydi (klient M2 ni chaqirmaydi), lekin kontrakt buzuq.

### D-08 — saqlangan qidiruv nuqtali e'lonni topmaydi (P2)

`feed/service.py:1297`: `rules.stop_segment_match(..., listing.origin_stop_id, listing.destination_stop_id)`
— nuqtali e'londa `(None, None)` → hech qachon mos kelmaydi. Klient saqlangan qidiruvni ko'rsatadi
(`client-extras.api.ts:28`), shuning uchun bu ko'rinadigan bo'shliq.

### D-09 — ogohlantirishning matni yo'q (P2)

`marketplace/service.py:1951` warnings'ga `ErrorCode.PRICE_OUT_OF_BAND.value` ni qo'yadi, lekin
`WarningCode` (`contracts/errors.py:226`) da bunday a'zo yo'q. `api/v2/web.py:133` da:
```python
try: message = WARNING_CATALOGUE[WarningCode(code)]
except ValueError: message = code
```
→ foydalanuvchi `message` sifatida **`"PRICE_OUT_OF_BAND"`** satrini oladi. Klient tomonida ham
`mobile-app/src/utils/v2Errors.ts:69` xaritasida bu kod yo'q → xom kod ko'rsatiladi.

---

## 5. Passenger auksion oqimi

```
Mijoz: Qayerdan (xarita nuqtasi) → Qayerga (xarita nuqtasi) → sana/vaqt → o'rinlar soni
     → O'Z NARXI (per_seat) → listing {kind: request, service_type: passenger} → publish
Haydovchi: driver-feed (side=requests, passenger) → «Taklif yuborish» + trip_id + o'z narxi → proposal v1
Mijoz:     qarshi taklif (v2) ──┐
Haydovchi: qarshi taklif (v3)   │  har biri yangi immutable versiya, eskisi superseded
Mijoz:     ACCEPT v3 → booking.total_minor = v3.total_minor
```
**Holat:** backend to'liq; klient to'liq; `passenger_enabled` flagi ortida (Q91 — to'g'ri).
**Buzuq bo'g'in:** «Mijoz: qarshi taklif» — nuqtali e'londa **D-05** (500).

## 6. Driver auksion oqimi

```
Haydovchi: vehicle → trip (route_version + stops + seats/cargo) → trip_offer listing + O'Z BOSHLANG'ICH NARXI → publish
Mijoz:     client-offers (side=offers) → «Narx taklif qilish» → proposal v1 (mijoz muallif)
Haydovchi: qarshi taklif → Mijoz: qarshi taklif → ACCEPT
```
**Holat:** to'liq ishlaydi. Trip stop'larga bog'langani uchun `trip_offer` uchlari doim stop — D-05/D-06/D-07 bu
oqimga **tegmaydi**. Bitta trip bir vaqtda passenger va parcel trip_offer ko'tara oladi (§97; `has_published_trip_offer`
bitta `(trip, service_type)` bo'yicha unique).

## 7. Parcel auksion oqimi

Passenger bilan bir xil semantika, farqlari: `price_basis=total`, `ParcelType`/`Amenity` enum'lari, qabul qiluvchi
majburiy (Q79), `parcel_policy` tasdiqlangan bo'lishi shart (publish'da fail-closed), cargo sig'imi segment bo'yicha.
**Holat:** ishlaydi; D-05/D-06/D-07 bu yerda ham amal qiladi (mijoz nuqtali parcel so'rovi — bugungi asosiy oqim).

## 8. Listing / proposal / booking / trip chegaralari

| Obyekt | Egasi | Nima | Buzilmagan chegarasi |
|---|---|---|---|
| `listings` | marketplace (A1) | Kelishilmagan e'lon | Sig'im/pul band qilmaydi; `terms_version` Q54 bo'yicha alohida |
| `proposal_threads` + `proposal_versions` | A1 | Muzokara va o'zgarmas versiyalar | Bir threadda bitta `active` versiya (partial unique index) |
| `bookings` | A4 orkestrator | Qabul qilingan versiya snapshot'i | Faqat `accept_proposal` yaratadi; Q60 trigger snapshot ustunlarini muzlatadi |
| `trips` + `trip_occurrences` | trips | Jismoniy safar | `booking_allocations` segment bo'yicha; release faqat `active` true→false o'tishida |

Chegaralar **to'g'ri saqlangan**. `bookings/bridges.py` (Q59 vaqtinchalik ko'prik) hamon mavjud — wave 2.1 dan beri
ochiq qarz; bu auditning doirasidan tashqarida, lekin eslatib qo'yiladi.

## 9. Point-to-point integratsiyasi

**To'g'ri:** e'lon nuqtasi tasdiqlangan marshrutga proyeksiya qilinadi, koridor o'z radiusini beradi, tartib
(`origin.fraction < destination.fraction`) majburlanadi, segment `pickup_occurrence_seq` beradi, DB CHECK
«stop yoki point» ni ushlaydi, nuqta hech qachon `exact` bo'lmaydi.

**Buzuq:** nuqtali e'lon `stop_id` kutayotgan **to'rtta** joyda yo'qoladi yoki yiqiladi — D-05, D-06, D-07, D-08.
Bularning hammasi bitta naqshning takrori: `listing.origin_stop_id` / `version.pickup_stop_id` **`None` bo'lishi
mumkinligi** hisobga olinmagan. Umumiy yechim — `_point_listing_match` / `_place_listing_ends_on_trip` kabi
mavjud nuqta-ongli yordamchilarni shu to'rt chaqiruv joyiga ham ulash (yangi mexanizm kerak emas).

## 10. Narx muzokarasi semantikasi (yakuniy holat)

| Qoida | Holat |
|---|---|
| Band submit/counter'da **ogohlantiradi**, bloklamaydi | ✅ kodda (`evaluate_price_band`) |
| Faqat `enforced` band rad etadi | ⚠️ kodda bor, **API'da yoqib bo'lmaydi** (D-04) |
| Accept'da band **qayta baholanmaydi** | ✅ `_check_price_band` faqat 2225/2387 da |
| Booking jami = qabul qilingan versiya jami | ✅ `bookings/service.py:798`, testi bor |
| Qattiq rad faqat: `unit_price ≤ 0`, overflow, valyuta, `price_basis` ziddiyati | ✅ `ALLOWED_PRICE_BASIS`, `_positive_int` |
| Ogohlantirish `ApiWarning` sifatida o'qiladigan matn bilan | ❌ D-09 |

## 11. Feed / matching

* `/feed?side=requests` (haydovchi) — nuqta-ongli ✅
* `/feed?side=offers` (mijoz) — so'rov uchlari stop/district bo'yicha; klient nuqtaning **tumanini** yuboradi ✅
* `/listings/{id}/matches` (M2) — ❌ D-07
* Saqlangan qidiruv — ❌ D-08
* Narx **hard filter emas**: `max_total_minor` faqat foydalanuvchi o'zi qo'ygan ixtiyoriy filtr; band esa
  faqat `P`/`Y` skori ✅
* Avtomatik g'olib yo'q: `auto_accept`/`auto_award` kodda mavjud emas ✅

## 12. Q7 / Q91 — feature flag munosabati

To'g'ri bajarilgan: model, API, domen invariantlari joyida; faqat UI navigatsiyasi `passenger_enabled` ga qaraydi;
navigatsiya **screen state**, URL orqali aylanib o'tib bo'lmaydi (`main.tsx` faqat `/admin` va `/e/` ni yo'naltiradi);
`effectiveFlags(corridorId)` serverdan koridor doirasida so'raladi. Kontrakt testi buni muhrlaydi.
Production'da `passenger_enabled=false` qoladi (K7 huquqiy tekshiruvigacha).

## 13. Kerakli DB/API o'zgarishlari

| # | O'zgarish | Turi | Egasi |
|---|---|---|---|
| 1 | `PriceBandUpsert.enforced` + `PriceBandDTO.enforced` + `set_price_band(..., enforced=...)` | API (ustun 0078 da bor) | A2 |
| 2 | `WarningCode.PRICE_OUT_OF_BAND` + `WARNING_CATALOGUE` matni | Kontrakt | A0a |
| 3 | `counter_proposal` nuqtali tarmog'i (`_place_listing_ends_on_trip` bilan) | Domen | A1 |
| 4 | `list_listing_offers` koridorni `listing.corridor_id` dan oladi, stop'dan emas | Domen | A1 |
| 5 | `listing_matches` ikkala tarmog'ida nuqta-ongli uchlar | Feed | A5 |
| 6 | `_search_matches` nuqta-ongli | Feed | A5 |

**Migratsiya kerak emas** — barcha ustunlar (0076/0077/0078) allaqachon joyida.

## 14. Kerakli frontend o'zgarishlari

| # | O'zgarish | Sabab |
|---|---|---|
| 1 | `v2Errors.ts` ogohlantirish xaritasiga `PRICE_OUT_OF_BAND` matni | D-09 |
| 2 | Taklif/qarshi taklif ekranlarida server ogohlantirishini ko'rsatish (hozir faqat listing yaratish va chatda ko'rsatiladi) | Q90 — narx bandi endi maslahat, foydalanuvchi uni ko'rishi kerak |
| 3 | Admin panelida narx bandi `enforced` ustuni (D-04 bajarilgandan keyin) | Operator maslahat/majburiy farqini ko'rishi shart |

**Klientda boshqa o'zgarish talab qilinmaydi** — auksion UX to'liq va to'g'ri.

## 15. Testlar

**Ishga tushirildi:**
```
py -m pytest tests/modules tests/contracts -q
→ 1 failed: tests/modules/geo/test_geo_pricing.py::test_assert_price_within_band_raises_contract_error
→ qolgan barchasi passed (tests/contracts to'liq yashil)
```

**Ishga tushirilmadi (Docker yopiq):** `tests/pg/**`. Docker Desktop ochilgandan keyin birinchi navbatda:
`test_price_is_negotiated_pg.py`, `test_marketplace_r2_band_pg.py`, `test_marketplace_wave17_pg.py`,
`test_marketplace_wave21_pg.py`, `test_point_endpoints_pg.py`, `tests/pg/geo/test_geo_price_bands*_pg.py`.

**Yozilishi kerak bo'lgan yangi testlar:**
1. `test_point_endpoints_pg.py` ga: nuqtali e'londa **qarshi taklif** → accept (D-05 qopqog'i).
2. Nuqtali e'londa `GET /listings/{id}/offers` 200 qaytaradi (D-06).
3. Nuqtali e'londa `GET /listings/{id}/matches` bo'sh emas, ikkala yo'nalishda (D-07).
4. Nuqtali e'lon saqlangan qidiruvni uyg'otadi (D-08).
5. `enforced` ni **API orqali** qo'yish va shundan keyingina rad etish (D-04).
6. Ogohlantirish `message` maydoni kod emas, jumla (D-09).

## 16. Qolgan bloklovchilar

| # | Bloklovchi | Kim hal qiladi |
|---|---|---|
| B-1 | **D-05** — nuqtali e'londa qarshi taklif 500 beradi; bugungi asosiy mijoz oqimini yarmida uzadi. Boshqa hech narsadan oldin tuzatilishi kerak | A1 |
| B-2 | **D-02/D-03** — hujjat va testlar kod bilan zid; shu holatda wave yopilmaydi (§8 DoD) | A0a |
| B-3 | Docker ochilmaguncha PG invariantlari isbotlanmaydi (§7: «test mavjud» ≠ «test o'tdi») | foydalanuvchi |
| B-4 | `enforced` yo'lisiz Q90 ning abuse/safety chegarasi yo'q — pilot uchun qabul qilinadi, lekin launch checklistiga kiradi | A2 |
| B-5 | Avvalgi qarzlar: `bookings/bridges.py` (Q59), U6 `rating_bucket` chegaralari, ADR-0021 staff MFA (Proposed) | avvalgi wave'lardan |

---

### Xulosa

Asosiy arxitektura — ikki tomonlama auksion — **buzilmagan**: to'rtala e'lon turi, ikki tomonlama muzokara,
immutable versiyalar, accept'da atomar band qilish, inson tanlovi, snapshot narx — hammasi joyida, va Wave 15
tuzatishi (Q90/Q91/Q92/Q93) to'g'ri yo'nalishda boshlangan.

Qolgan drift ikki toifaga tushadi: (a) **Wave 15 ning yarim qolgan ishi** — testlar, hujjatlar va `enforced`
yo'li; (b) **Q88 nuqta modeli `stop_id` kutayotgan eski chaqiruv joylariga to'liq ulanmagan** — to'rt joy, ulardan
biri (qarshi taklif) P0.
