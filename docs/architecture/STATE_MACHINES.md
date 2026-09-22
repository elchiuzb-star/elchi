# STATE_MACHINES — 2-bosqich holat mashinalari

**Muallif:** A0a • **Sana:** 13.09.2026 (wave 0.5 tuzatishlari bilan) • **Holat:** Accepted (Q1, Q7, Q16, Q17, Q19; BR N3)
**Spec:** §5.3–5.4, §7, §9.2–9.5, §10.4, §10.6, §11, §15, §22
**Kod kontrakti:** [`app/contracts/state_machines.py`](../../app/contracts/state_machines.py) (`(from, to, command)` juftliklari, `booking_blocks_trip_completion`), [`money.py`](../../app/contracts/money.py) (fee semantikasi), [`tracking.py`](../../app/contracts/tracking.py); testlar `tests/contracts/`. Bu hujjat guard, actor, lock, side effect va xato kodlarini beradi.

## 0. Umumiy qoidalar

### 0.1 Buyruq qolipi
capability → **lock (0.2 tartibi)** → `expected_version` → `assert_transition(from, to, command)` → guard’lar → yozuv → `version+1` → tarix (`booking_status_history` va h.k.) → outbox (allowlist payload) → idempotent javob (ADR-0005: domen 4xx savepoint naqshi).
- Ruxsat etilmagan o‘tish: `409 INVALID_STATE_TRANSITION`.
- Har mashina mustaqil ustunda (§11). **Nizo xizmat/moliya holatini yozmaydi va tiklamaydi.** **Trip yakuni booking holatini o‘zgartirmaydi** (AC42).
- Actor: C — mijoz (listing/booking egasi yoki payer), D — tayinlangan haydovchi, O — operator capability’si (`OPERATOR_COMMAND_CAPABILITY` bo‘yicha: `cancel` — admin+, `finalize_fee` — finance roli, ulanguncha super_admin — Q17), S — system/worker. Pul ta’sir qiladigan har buyruq production invariantlari buzilganda `503 PRODUCTION_INVARIANTS_FAILED` (N1). Komissiya holati va fee maydonlari mijozga API/event’da ko‘rsatilmaydi (Q16, N2).

### 0.2 Global lock tartibi (D7, ADR-0017)
`users → trips → listings → proposal_threads → bookings → booking bolalari (amendments, no_show_reviews, custody_cases, cash_receipts, disputes_v2) → wallet_accounts → wallet_holds / topup_requests`. Guruh ichida `id ASC`. Buyruq keraksiz guruhni o‘tkazib yuborishi mumkin, lekin tartibni teskari qila olmaydi. Bola id bilan kelgan so‘rov (masalan `/amendments/{id}/accept`) avval lock’siz o‘qib `booking_id/trip_id`ni topadi, tartib bo‘yicha lock oladi, bolani `FOR UPDATE` bilan qayta o‘qib ota id’lari o‘zgarmaganini tekshiradi. Deadlock/serialization — shu idempotency kaliti bilan ≤3 marta ichki retry.

| Buyruq | users | trips | listings | threads | bookings | bolalar | wallets |
|---|---|---|---|---|---|---|---|
| `accept` (A4) | client + driver | trip | request + supply | thread | (insert) | — | driver wallet → hold (insert) |
| `submit`/`counter`/`reject`/`withdraw` | — | — | listing | thread | — | — | — |
| listing `PATCH`/`cancel`/`system_expire` | — | — | listing | listing’ning ochiq thread’lari | — | — | — |
| booking `cancel` | — | trip | booking listing’lari (reopen) | — | booking | pending no_show_review (tekshiruv) | wallet → hold |
| trip `cancel` | — | trip | trip listing’lari | ochiq thread’lar | trip bronlari | bolalar | wallet → hold’lar |
| trip `complete` | — | trip | — | — | trip bronlari | custody_cases, no_show_reviews (o‘qish) | — |
| `amendment` create | — | — | — | — | booking | amendment (insert) | — |
| `amendment` accept (D10) | — | trip | — | — | booking | amendment | wallet → hold (update) |
| `board`/`pick_up`/`start_transit`/`deliver`/`drop_off` | — | — | — | — | booking | booking_proofs, review/custody (yopish) | — |
| `report_no_show` | — | — | — | — | booking | no_show_review (insert) | — |
| `confirm_no_show` | — | trip (allocation release) | — | — | booking | no_show_review | wallet → hold (release) |
| `reject_no_show` (trip ishlayapti) | — | — | — | — | booking | no_show_review | — |
| `reject_no_show` (trip terminal, N3) | — | trip (allocation release) | booking listing’lari (reopen) | — | booking | no_show_review | wallet → hold (release) |
| `report_delivery_failed`/`require_return` | — | — | — | — | booking | custody_case (insert) | — |
| `complete` → capture/release | — | — | — | — | booking | — | wallet → hold |
| admin eligibility block (D16) | driver user | — | — | — | — | — | — |
| `open_dispute` | — | — | — | — | booking | dispute (insert) | — |
| `resolve` dispute (+moliyaviy buyruq) | — | — | — | — | booking | dispute, cash_receipt | wallet → hold |
| cash `report`/`acknowledge`/`contest` | — | — | — | — | booking | cash_receipt (+dispute insert) | — |
| top-up approve/reject, ledger adjustment | — | — | — | — | — | — | wallet → topup_request |
| tracking session create | — | trip (`FOR SHARE`) | — | — | — | — | — (sessions — mustaqil guruh, trip’dan keyin) |

Asoslash: users birinchi, chunki admin block va accept eligibility bo‘yicha serializatsiya qilinishi kerak (AC41) va block faqat user’ni lock qiladi. Trip — jismoniy sig‘im manbai, har bron/sig‘im buyrug‘i undan boshlanadi. Listing va thread trip’dan keyin, chunki accept avval sig‘imni, keyin kelishuvni tekshiradi. Wallet oxirida, chunki pul har doim yakuniy qadam va hech bir buyruq wallet’ni bron/bolasidan oldin lock qilmaydi. Commission policy yaratish row lock olmaydi (exclusion constraint).

**Wave 1 implementatsiya farqi (A1, integratsiya qaydi):** `publish` va `resume` listing egasining `users` qatorini `FOR NO KEY UPDATE` (wave 1 da `FOR UPDATE` edi — wave 1.5 lock rejimi qoidasi bilan almashtiriladi), `submit` va `counter` esa taklif beruvchining `users` qatorini `FOR SHARE` bilan lock qiladi (eligibility admin bloki bilan serializatsiya uchun). Bu jadvaldan qat’iyroq, lekin tartibga zid emas: `users` birinchi guruh (§15, ADR-0017) va keyingi guruhlar ham o‘sish tartibida olinadi. Qarama-qarshilik topilmadi; `FOR SHARE` bir vaqtdagi `FOR UPDATE` (admin block) bilan kutadi — AC41 ruhiga mos.

**Wave 1.5 qoidalari (ADR-0017 §10–11):** `users` qatorlari faqat `FOR NO KEY UPDATE` (`with_for_update(key_share=True)`) yoki `FOR SHARE` — oddiy `FOR UPDATE` taqiq (FK key-share lock’lari bilan deadlock). Har v2 buyrug‘i `run_with_db_retry` ichida. Ro‘yxatdagi wallet guruhiga `ledger_adjustment_requests` kiradi. **Release kontrakti:** A4 `booking_allocations.active`ni trip lock ostida `true → false` o‘tkazadi va `trips.release`ni faqat shu o‘tishda chaqiradi (cancel, `confirm_no_show`, trip-terminal `reject_no_show`, amendment).

### 0.3 Eligibility va bloklash (D16)
Driver eligibility yo‘qolishi (admin eligibility block, `verification_status` o‘zgarishi, hujjat muddati) faqat `NEW_BUSINESS_CAPABILITIES`ni oladi: yangi listing, trip, proposal va accept → `403 DRIVER_NOT_ELIGIBLE`. Tayinlangan non-terminal trip/bronlarda `OBLIGATION_CAPABILITIES` saqlanadi: trip action, tracking, proof, cash, dispute/support. Balans yetishmasligi ham faqat yangi bronni to‘xtatadi (§9.2). Account suspension (`users.status != active`) — alohida favqulodda xavfsizlik amali, faqat super_admin (Q15); v1 kabi to‘liq kirishni yopadi, faol trip’larni operator hal qiladi. v1 `block_driver` faol v2 trip’li haydovchi uchun faqat eligibility bloki sifatida ishlaydi (Q15, A4/A12, ADR-0007).

---

## 1. Listing
Boshlang‘ich `draft`; terminal `expired`, `cancelled`.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| draft → published | `publish` | Egasi (C request, D trip_offer) | NEW_BUSINESS capability; flag `<service>_enabled` (+`driver_listing_enabled` trip_offer’da); koridor/bekat faol; to‘liqlik (§5.2); `departure_window_end > now`; `expires_at ≤ departure_window_end`; trip_offer: trip `planned`, egasiniki, resurs > 0; dublikat (§5.4); rate-limit | `published_at`; outbox `listing.published` | `LISTING_INCOMPLETE`, `FEATURE_DISABLED`, `CORRIDOR_NOT_ACTIVE`, `LISTING_EXPIRED`, `DUPLICATE_LISTING`, `DRIVER_NOT_ELIGIBLE`, `RATE_LIMITED`, `VERSION_CONFLICT` | AC01 |
| draft → cancelled | `cancel` | Egasi | — | — | `VERSION_CONFLICT` | — |
| published → paused / paused → published | `pause` / `resume` | Egasi | resume: publish guard’lari | Pauzada accept rad | publish xatolari | — |
| published → fulfilled | `system_fulfil` | S (accept tx) | request: non-cancelled booking bor; trip_offer: hech bir segmentda resurs qolmadi | Qolgan faol versiyalar → `expired` (`demand_fulfilled`/`capacity_gone`) | — | AC06 |
| fulfilled → published | `system_reopen` | S (cancel tx) | request: bronni **D yoki O** bekor qilgan va `expires_at > now` hamda `departure_window_end > now` (Q19); trip_offer: resurs qaytdi | outbox `listing.published` (dedup); request egasiga (mijozga) xabar (Q19) | — | AC21 |
| published/paused/fulfilled → expired | `system_expire` | S | `now ≥ expires_at` yoki `departure_window_end` | Faol versiyalar `expired`; bronlarga ta’sir yo‘q | — | — |
| published/paused/fulfilled → cancelled | `cancel` | Egasi, O (`ops.booking_command`, Q23) | O uchun sabab + audit qatori; operator `draft`ni bekor qila olmaydi (Q23) | Faol versiyalar `expired` (`listing_closed`); **bronlar bekor qilinmaydi** | `VERSION_CONFLICT` | — |

`PATCH`: yo‘nalish, oyna, miqdor, `price_basis` yoki narx o‘zgarsa `version+1` va mos kelmaydigan faol versiyalar `expired` (`listing_changed`). **Q20 (wave 1.5, wave 1 dagi A1 farqi o‘rniga):** ochiq takliflar faqat **yo‘nalish (bekatlar), oyna, miqdor/`seat_count` yoki `price_basis`** o‘zgarganda `expired` (`listing_changed`). Birlik narxi, izoh, `expires_at`, qulayliklar, maxsus yordam tahriri `version+1` qiladi, lekin takliflarni expire qilmaydi (accept `expected_listing_version`ni baribir tekshiradi — mijoz yangi versiyani ko‘radi). Mijoz bekor qilgan request bron → listing `cancelled`.

## 2. Proposal (thread + o‘zgarmas versiyalar)
Thread `open|accepted|closed`; versiya kontenti immutable; boshlang‘ich `active`.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| ∅ → active | `submit` | request’ga D (trip bilan), trip_offer’ga C | Listing `published`; o‘z listing’i emas; NEW_BUSINESS capability; flag; bir tomon/trip kontekstida bitta ochiq thread; **miqdor (D9):** passenger request’da `quantity == seat_count`, parcel’da `quantity == 1`, trip_offer’da `quantity ≤` segmentning qolgan o‘rni; D: trip `planned`, egasiniki, sig‘im **tekshiriladi, rezerv qilinmaydi**; C trip_offer’ga: trip egasi haydovchi eligible bo‘lishi shart (Q21, aks holda `403 DRIVER_NOT_ELIGIBLE`); segment marshrutda; `price_basis` ruxsat; `expires_at = min(now + (2 soat agar departure − now > 2 soat, aks holda 10 daq), booking_cutoff_at)`; fee quote snapshot (policy, bps, commission) | outbox `proposal.created`; o‘rin/balans band emas | `LISTING_NOT_OPEN`, `SELF_DEALING_FORBIDDEN`, `CAPABILITY_REQUIRED`, `DRIVER_NOT_ELIGIBLE`, `QUANTITY_MISMATCH`, `CAPACITY_UNAVAILABLE`, `ROUTE_MISMATCH`, `PRICE_BASIS_NOT_ALLOWED`, `BOOKING_CUTOFF_PASSED`, `FEATURE_DISABLED`, `RATE_LIMITED` | AC02, AC03, AC05 |
| active → superseded | `counter` | Joriy versiya **qabul qiluvchisi** | `expected_revision`; tomon narx tuzatishi ≤ 3; submit guard’lari (D9 ham) | Yangi `active` versiya (muallif = chaqiruvchi), yangi TTL va **yangi fee quote**; outbox | `PROPOSAL_CHANGED`, `NEGOTIATION_LIMIT_REACHED`, `NOT_PROPOSAL_RECIPIENT`, `QUANTITY_MISMATCH` | AC04, AC43 |
| active → accepted | `accept` (A4) | Qabul qiluvchi | §15: idempotency; lock 0.2; `proposal_version_id` joriy + `expected_listing_version`; TTL (fee quote shu TTL bilan birga tugaydi — alohida quote xatosi yo‘q); eligibility; flag; trip `planned`, cutoff; route version; barcha oynalar; har segment sig‘im/bagaj/yuk; kumulyativ detour (soniyada; `DetourQuote` snapshot’i route/trip versiyasiga mos va muddati o‘tmagan; bir leg’da ikki detour rad — Q25); D9 miqdor qayta; fee: snapshot bps → `initial_commission_status`; bps > 0 va `balance_check_required` → `available ≥ commission` | Booking `confirmed` + allocations + hold yoki `exempt`; thread `accepted`; demand’ning boshqa faol versiyalari `expired`; listing fulfil/availability; outbox `booking.accepted`, `wallet.hold.created` | `PROPOSAL_CHANGED`, `PROPOSAL_EXPIRED`, `NOT_PROPOSAL_RECIPIENT`, `SELF_DEALING_FORBIDDEN`, `QUANTITY_MISMATCH`, `CAPACITY_UNAVAILABLE`, `CARGO_LIMIT_EXCEEDED`, `ROUTE_CHANGED`, `DETOUR_LIMIT_EXCEEDED`, `TIME_WINDOW_CONFLICT`, `INSUFFICIENT_COMMISSION_BALANCE`, `DRIVER_NOT_ELIGIBLE`, `FEATURE_DISABLED`, `BOOKING_CUTOFF_PASSED`, `IDEMPOTENCY_KEY_REUSED` | AC02–AC09, AC12, AC17, AC19, AC41, AC43 |
| active → rejected | `reject` | Qabul qiluvchi | — | thread `closed` | `NOT_PROPOSAL_RECIPIENT` | — |
| active → withdrawn | `withdraw` | Muallif | — | thread `closed` | `INVALID_STATE_TRANSITION` | — |
| active → expired | `system_expire` | S | TTL; listing o‘zgardi/yopildi; demand bajarildi; sig‘im tugadi | thread `closed` | — | — |

## 3. Trip
Boshlang‘ich `planned`; terminal `completed`, `cancelled`. Bronlarga tegadigan trip buyruqlari — A4.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| ∅ → planned | `create` (A1) | D (`trip.create`) | Eligibility; vehicle `approved`; `seat_capacity ≤` vehicle; route version tasdiqlangan; driver va vehicle `blocked_period` overlap yo‘q (exclusion) | Segment resurslari | `SCHEDULE_CONFLICT`, `VEHICLE_NOT_ELIGIBLE`, `DRIVER_NOT_ELIGIBLE` | AC13 |
| planned → boarding | `start_boarding` | D (`trip.operate`) | `now ≥ planned_start_at − boarding_lead` (60 daq, konfiguratsiya — Q19) | `confirmed` bronlar → `awaiting_pickup` | `INVALID_STATE_TRANSITION` | AC44 |
| planned → cancelled | `cancel` | D, O | Sabab; har faol bron `cancel` (initiator/fault), allocation + hold release shu tx | Request listing’lar `system_reopen` | `VERSION_CONFLICT` | AC21 |
| boarding → in_progress | `depart` | D | Hech bir bron `confirmed` emas | Yangi bron qabul yopiladi | — | — |
| boarding → cancelled | `cancel` | D, O | Hech bir bron `onboard`/custody’da emas | yuqoridagidek | `TRIP_HAS_UNRESOLVED_BOOKINGS` | AC22 |
| boarding/in_progress → interrupted | `interrupt` | D, O | Sabab | Bronlar o‘zgarmaydi; operator navbati | — | §11 |
| in_progress/interrupted → completed | `complete` | D (in_progress), O (interrupted, sabab bilan) | Har bron uchun `booking_blocks_trip_completion(...) == False` (§3.1) | **Booking statuslari o‘zgarmaydi**; tracking sessiyalari va grant’lar yopiladi; trip overlap constraint’dan chiqadi | `TRIP_HAS_UNRESOLVED_BOOKINGS` | AC42 |
| interrupted → in_progress | `resume` | D, O | Sabab | — | — | — |
| interrupted → cancelled | `cancel` | O | Custody’da parcel yoki onboard yo‘lovchi yo‘q | — | `TRIP_HAS_UNRESOLVED_BOOKINGS` | — |

### 3.1 Trip yakunini bloklamaydigan bron holatlari (D1)
| Xizmat | Hal qilingan | Ochiq qoladi, lekin bloklamaydi | Bloklaydi |
|---|---|---|---|
| Passenger | `arrived`, `completed`, `cancelled`, `no_show` | `awaiting_pickup` + pending no-show review | `confirmed`, `onboard`, review’siz `awaiting_pickup` |
| Parcel | `delivered`, `completed`, `cancelled`, `returned` | `delivery_failed`/`return_required` + **ochiq custody case** | `confirmed`, `awaiting_pickup`, `picked_up`, `in_transit`, case’siz `delivery_failed`/`return_required` |

Ochiq qolgan bronlar trip `completed` bo‘lgach operator case orqali yakunlanadi; yuk haydovchi custody’sida qoladi (dalil va aloqa saqlanadi).

## 4. Passenger booking
Boshlang‘ich `confirmed`; terminal `completed`, `cancelled`, `no_show`.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| confirmed → awaiting_pickup | `mark_awaiting_pickup` | S (trip `boarding` yoki pickup − 30 daq), D | Trip `planned/boarding` | Tracking grant oynasi ochiladi | — | AC44 |
| confirmed/awaiting_pickup → cancelled | `cancel` | C, D, O(admin) | Sabab + initiator; jarima 0; **pending no-show review bo‘lsa faqat O** | Bitta tx: allocation’lar `active=false`, resurslar kamayadi, hold `released` (yoki exempt qoladi), listing `system_reopen` (D/O), grant revoke; outbox | `INVALID_STATE_TRANSITION`, `NO_SHOW_REVIEW_PENDING`, `VERSION_CONFLICT` | AC21 |
| awaiting_pickup → onboard | `board` | D | Boarding code mos (keyed hash, ≤5 urinish; kod ADR-0018 subkey’dan); D kodni ko‘rmaydi | proof; `booking.started`; pending review bo‘lsa → `rejected` (`system_close_boarded`) | `PROOF_INVALID`, `PROOF_ATTEMPTS_EXCEEDED` | §11 |
| *(status o‘zgarmaydi)* | `report_no_show` | D | `arrive_at_pickup` qayd etilgan va kelishilgan pickup oynasi ichida (D kechikmagan); kutish ≥ e’londagi (default 10 daq); ≥1 aloqa urinishi; pending review yo‘q | `no_show_reviews(pending)` + dalil; operator navbati; outbox `booking.no_show_reported` | `NO_SHOW_NOT_ALLOWED`, `NO_SHOW_REVIEW_PENDING` | Q7 |
| awaiting_pickup → no_show | `confirm_no_show` | **faqat O** (`ops.booking_command`) | Pending review mavjud; dalil ko‘rib chiqilgan; sabab | Review `confirmed`; allocation release; hold `released` (pilot jarima yo‘q); grant revoke; mijozga nizo imkoni | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT` | Q7, D2 |
| *(status o‘zgarmaydi)* | `reject_no_show` (trip `planned/boarding/in_progress/interrupted`) | O | Pending review; `reject_no_show_outcome(trip.status).booking_status == awaiting_pickup` | Review `rejected`; bron `awaiting_pickup`da qoladi → keyin `board` yoki O `cancel` (initiator va fault operator qarori bilan) | — | D2 |
| awaiting_pickup → cancelled | `reject_no_show` (trip `completed/cancelled`) | O | Pending review; trip terminal — endi hech kim bora olmaydi | **Bitta buyruqda:** review `rejected`; bron `cancelled`, `cancelled_by_side=operator`, **`fault_side=driver`** (`FaultSide.DRIVER`, `reject_no_show_outcome`); allocation release, hold `released`, grant revoke, request listing `system_reopen` guard’i bo‘yicha; outbox `booking.cancelled` | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT` | N3 |
| onboard → arrived | `drop_off` | D (yoki O sabab bilan) | Dropoff occurrence yoki operator sababi | Grant yopilishi rejalashtiriladi | — | — |
| arrived → completed | `complete` | C (tasdiq), O (`complete_with_evidence`) | 24 soatlik tasdiqlash oynasi, keyin O navbati; avtomatik debit yo‘q | Xizmat `completed`; jiddiy ochiq nizo (`service`/`commission`/`payment`) **yo‘q** bo‘lsa shu tx’da capture, bor bo‘lsa commission `held` qoladi | `INVALID_STATE_TRANSITION`, `VERSION_CONFLICT` | AC20, AC26 |

## 5. Parcel booking
Boshlang‘ich `confirmed`; terminal `completed`, `cancelled`, `returned`.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| confirmed → awaiting_pickup | `mark_awaiting_pickup` | S, D | — | — | — | — |
| confirmed/awaiting_pickup → cancelled | `cancel` | C (sender), D, O(admin) | Yuk olinmagan | Allocation + hold release bitta tx | `VERSION_CONFLICT` | AC21 |
| awaiting_pickup → picked_up | `pick_up` | D | Pickup code (delivery kodi rad) | proof; custody; grant | `PROOF_INVALID`, `PROOF_ATTEMPTS_EXCEEDED` | §11 |
| picked_up → in_transit | `start_transit` | D, S | — | — | — | — |
| picked_up/in_transit → cancelled | **mavjud emas** | — | — | — | `CUSTODY_REQUIRES_RETURN_FLOW` | **AC22** |
| in_transit → delivered | `deliver` | D | Delivery code | proof; ochiq custody case bo‘lsa S `resolve_custody_case`; grant yopiladi | `PROOF_INVALID`, `PROOF_ATTEMPTS_EXCEEDED` | §9.5 |
| in_transit → delivery_failed | `report_delivery_failed` | D | Sabab, dalil | **Shu tx’da custody case `open`** (S); operator navbati | — | AC22, D1 |
| delivery_failed → in_transit | `retry_delivery` | D, O | Yangi kelishilgan vaqt | Case ochiq qoladi | — | — |
| picked_up/in_transit/delivery_failed → return_required | `require_return` | O (yoki C+D kelishuvi) | Sabab; qaytarish narxi amendment orqali | Case yo‘q bo‘lsa ochiladi | — | AC22 |
| return_required → returned | `return_to_sender` | D, O | Return code yoki operator dalili | Case `resolved` (S); fee avtomatik emas → O `finalize_fee` | `PROOF_INVALID` | AC22 |
| delivered → completed | `complete` | S (kod bilan tasdiqlangan delivery — shu tx), C, O (`complete_with_evidence`) | Delivery proof bor | Jiddiy ochiq nizo yo‘q → capture, bor → `held` | `INVALID_STATE_TRANSITION` | AC20, AC42 |

**Custody case** (`open → resolved`, buyruq `resolve_custody_case`): S (`delivered`/`returned`ga yetganda) yoki O (sabab + dalil; bron `delivered`, `completed`, `returned` yoki operator buyrug‘i bilan shu holatga o‘tkazilgan bo‘lishi shart).

## 6. Cash collection (`bookings.cash_status`)
Boshlang‘ich `unpaid`; terminal `acknowledged`. Xizmatdan mustaqil; capture’ni faqat ochiq `payment` nizosi kechiktiradi.

| From → To | Buyruq | Actor | Guard | Side effect | Xato | AC |
|---|---|---|---|---|---|---|
| unpaid → reported_paid | `report_paid` | D yoki payer | Bron `onboard`/`picked_up` yoki keyingi; summa = `total_minor` (farq — izoh) | `cash_receipts` | `INVALID_STATE_TRANSITION` | AC26 |
| reported_paid → acknowledged | `acknowledge` | Qarshi tomon | — | — | `FORBIDDEN` | AC26 |
| reported_paid → contested | `contest` | Qarshi tomon | Izoh | `disputes_v2(type=payment)`; xizmat o‘zgarmaydi | `DISPUTE_ALREADY_OPEN` | AC26 |
| contested → acknowledged / unpaid | `resolve_paid` / `resolve_unpaid` | **admin+** (`ops.dispute_decide`, nizo qarori ichida — wave 3.1) | Nizo qarori `cash_outcome` (`paid`/`unpaid`) bilan; `contested` kvitansiyali payment nizosi natijasiz yopilmaydi | — | `VALIDATION_ERROR` (`cash_outcome`) | AC26 |

## 7. Commission (`bookings.commission_status` + bitta `wallet_holds` qatori + ledger)
Terminal: `exempt`, `released`, `reversed`.

| From → To | Buyruq | Actor | Guard | Side effect (A3) | Xato | AC |
|---|---|---|---|---|---|---|
| ∅ → exempt | `mark_exempt` | S (accept) | **Snapshot `fee_bps == 0`**, ya’ni faol 0 bps `campaign` policy (Q1). `wallet_required`dan hech qachon kelib chiqmaydi | Hold yo‘q, ledger yo‘q | — | §13, Q1 |
| ∅ → held | `hold_fee` | S (accept) | Snapshot `fee_bps > 0`; `balance_check_required(is_production, wallet_required)` True bo‘lsa `available ≥ commission`; production’da doim True; non-prod’da False bo‘lsa tekshiruv o‘tkaziladi, lekin real fee hisoblanadi va hold qilinadi (wallet `test_overdraft_allowed=true` seed’i talab) | Hold `active`, `held_minor += x`; posting yo‘q; outbox `wallet.hold.created` | `INSUFFICIENT_COMMISSION_BALANCE` | AC19, Q1 |
| held → held | `adjust_hold` | S (amendment accept, D10) | Yangi commission = `commission_minor(new_total, booking.fee_bps)` (snapshot bps o‘zgarmaydi); `delta = hold_adjustment_minor(...)`; `delta > 0` bo‘lsa balans tekshiruvi (yuqoridagi qoida); **ikkinchi hold yaratilmaydi** (`UNIQUE(booking_id, charge_kind)`) | `wallet_holds.amount_minor` va `held_minor` yangilanadi; outbox `wallet.hold.adjusted` | `INSUFFICIENT_COMMISSION_BALANCE`, `AMENDMENT_CONFLICT` | D10 |
| held → captured | `capture` | S (booking `completed`, jiddiy nizo yo‘q) | Hold `active`; ledger reference `commission:capture:<booking>` unique | Bitta tx: hold `captured` (`captured_minor`), `held −= x`, Dr driver liability / Cr commission revenue; outbox | takror → no-op | AC20 |
| held → released | `release` | S (cancel, confirm_no_show), O (`finalize_fee`) | — | Hold `released`, `held −= x` | — | AC21 |
| captured → partially_reversed; partially_reversed → partially_reversed | `reverse_partial` | O + `finance.adjustment` | Wallet lock ostida `validate_reversal(captured, reversed_sum, amount)` — yig‘indi ≤ captured (D4); sabab, dalil; chegaradan katta — ikkinchi xodim | Har reversal alohida ledger tx (`reversal_of` → capture tx, **unique emas**), `reversed_minor += amount` | `REVERSAL_EXCEEDS_CAPTURED`, `SECOND_APPROVER_REQUIRED`, `LEDGER_UNBALANCED` | AC25 |
| captured/partially_reversed → reversed | `reverse` | O + `finance.adjustment` | Qolgan summa to‘liq | Ledger teskari posting | same | AC25 |

Hold muddati o‘tishi avtomatik capture/release qilmaydi; 48 soatda eskalatsiya. Legacy v1 buyurtmalar bu mashinaga kirmaydi (§18.2, Q4).

## 8. Dispute (`disputes_v2`)
Boshlang‘ich `open`; terminal `resolved`, `rejected`.

| From → To | Buyruq | Actor | Guard | Side effect | Xato |
|---|---|---|---|---|---|
| ∅ → open | `open_dispute` | C, D, O | Ishtirokchi; booking+type uchun bitta faol case | **Booking/trip holati o‘zgarmaydi**; service/commission/payment/delivery turlari capture’ni kechiktiradi; 48 soat eskalatsiya; **safar xom GPS’i hold ostiga olinadi (M1, wave 3.1)** | `DISPUTE_ALREADY_OPEN`, `NOT_FOUND` |
| open → under_review | `start_review` | O | Mas’ul tayinlanadi | — | — |
| open/under_review → resolved | `resolve` | **admin+** (`ops.dispute_decide`; +moliyada `finance.adjustment`) — operator `start_review` va izoh bilan qoladi (wave 3.1, v1 Q13/Q38 pariteti) | `resolution_code`; kerakli **alohida** buyruqlar (`resolve_paid`, `reverse_partial`, `complete_with_evidence`, `require_return`…) har biri o‘z guard’i va lock tartibi bilan | Kechiktirilgan capture S tomonidan qayta baholanadi | `INVALID_STATE_TRANSITION` |
| open/under_review → rejected | `reject` | **admin+** (`ops.dispute_decide`) | Sabab; `contested` kvitansiyali payment nizosida `cash_outcome` majburiy | Kechiktirilgan capture davom etadi; nizo yopilgach bron `finance_review` navbatiga (`dispute_resolved`) | `VALIDATION_ERROR` |

v1 `previous_order_status` tiklash naqshi v2’da taqiq.

## 9. Qo‘shimcha mashinalar

- **Ledger adjustment request** (`ledger_adjustment_requests.status`, A3; Q17, Q49, 0047): `pending_second_approval → posted` (`approve`: `finance.adjustment_approve`, `approved_by ≠ requested_by`) • `pending_second_approval → rejected` (`reject`: `finance.adjustment_approve`, **`rejected_by ≠ requested_by`** — DB CHECK) • `pending_second_approval → withdrawn` (`withdraw`, W17a: `finance.adjustment`, **faqat so‘rovchi**; so‘rovchining `reject` urinishi `403 FORBIDDEN reason=requester_must_withdraw`). `posted`, `rejected`, `withdrawn` — terminal (DB guard; `enums.LEDGER_ADJUSTMENT_TERMINAL`). Xato: `INVALID_STATE_TRANSITION`, `SECOND_APPROVER_REQUIRED`, `FORBIDDEN`, `VERSION_CONFLICT`.
- **Kontakt ko‘rinishi (Q43–Q44, A4; holat mashinasi emas — booking holatidan hisoblanadi):** accept’dan oldin — hech kimga telefon/to‘liq ism/plate/aniq manzil yo‘q; `accepted`/`awaiting_pickup` (va `arrived_at_pickup`) — faqat chat, tracking oynasi, “keldim” signali; **start** (passenger: `onboard`; parcel: `picked_up`) — ishtirokchi telefonlari ochiladi; terminal holatdan **24 soat** keyin yana yashiriladi. Parcel qabul qiluvchi telefoni driverga faqat `picked_up`dan keyin; jo‘natuvchi telefoni driverga hech qachon. Support/SOS har holatda. Operator (staff) ko‘rinishi o‘zgarmaydi (audit bilan).
- **No-show review** (`pending → confirmed` `confirm_no_show`; `pending → rejected` `reject_no_show` | `system_close_boarded`) — §4.
- **Custody case** (`open → resolved`) — §5.
- **Amendment** (`proposed → accepted/rejected/withdrawn/expired`): lock trip → booking → amendment → wallet; sig‘im, oyna, D9 miqdor qayta tekshiruvi; fee — §7 `adjust_hold`. `AMENDMENT_CONFLICT`.
- **Top-up** (`pending → approved` ≤ chegara; `pending → awaiting_second_approval → approved`, ikkinchi approver boshqa xodim; `→ rejected`): lock wallet → topup; ledger Dr bank/kassa, Cr driver liability; reference unique. AC23, AC24.
- **Tracking session** (`active → superseded/closed`): trip uchun bitta `active`; eski sessiya batch’i `409 TRACKING_SESSION_SUPERSEDED` (AC29). Obligation capability — eligibility block uni to‘xtatmaydi (D16).
- **Tracking grant**: `valid_from` (passenger pickup − 30 daq; parcel pickup’dan), `valid_until`, `revoked_at`. Token ≥128 bit (`crypto.new_secret_token`), bazada hash. Freshness: `fresh ≤30 s`, `delayed 31–120 s`, `lost >120 s`, `no_data` (`tracking.freshness_for_age`). AC27, AC30, AC31, AC44.

## 10. Corridor rollout (`service_corridors.rollout_state`)
Kontrakt: `app/contracts/state_machines.py` `CORRIDOR_ROLLOUT`, enum `CorridorRolloutState` (integratsiya o‘tishi 1, A2 dan ko‘tarilgan). Boshlang‘ich `draft`; terminal `closed`. Buyruq — `PATCH /api/v2/admin/corridors/{id}` (`ops.corridor_manage`, `expected_version`, sabab majburiy, audit).

| From → To | Buyruq | Guard | Side effect |
|---|---|---|---|
| draft → internal | `start_internal` | Kamida bitta faol bekat | Faqat ichki akkauntlar/operatorlar (§18.1 M6) |
| internal → draft | `return_to_draft` | Faol bron yo‘q | — |
| internal → pilot | `start_pilot` | Tekshirilgan bekatlar — pilotda bekat yaratuvchisi verifier hisoblanadi, lekin **har faol bekatda meeting note yoki foto dalil** bo‘lishi shart (Q27); **kamida 2 faol bekat** (Q47 — `pilot`/`active` davomida **uzluksiz**: bekatni o‘chirish/faolsizlantirish yoki dalilni olib tashlash ham rad, DB deferred constraint trigger’i 0046; servis `409` `details.reason = needs_two_active_stops {active_stops}` yoki `stops_missing_meeting_evidence {stop_ids}`; mavjud qatorlar faqat keyingi o‘zgarishida tekshiriladi); flag’lar alohida yoqiladi (Q5) | Koridor ommaviy ro‘yxatda (`PUBLIC_ROLLOUT_STATES = pilot, active`) |
| pilot → internal | `return_to_internal` | Sabab | Yangi ommaviy listing to‘xtaydi; mavjud bronlar bajariladi (AC38) |
| pilot → active | `activate` | §20.4 kengayish mezonlari (operator qarori) | — |
| active → pilot | `return_to_pilot` | Sabab | — |
| draft/internal/pilot/active → closed | `close` | Sabab | Yangi e’lon/bron yo‘q; faol bronlar va trip’lar yakunlanadi (§20.3) |

Operatsion holatlar (`internal`, `pilot`, `active`) — `OPERABLE_ROLLOUT_STATES` (A2 servisi). **Wave 1.5 (A2):** `active` holatda ham kamida 2 faol bekat qoidasi saqlanadi; koridor yopish/qaytarish faol bronlar hisobini `geo.service.set_active_booking_counter` hook’i orqali oladi (A4 ro‘yxatdan o‘tkazadi; `bookings` jadvali bor, hook yo‘q bo‘lsa — fail-closed `503`). Rollout holati feature flag’larni almashtirmaydi: xizmat har koridorda flag bilan alohida yoqiladi.

## 11. Wave 2.1 o‘zgarishlari (15.09.2026, Q59–Q73, wave 2 BR) — yuqoridagi jadvallardan ustun
Kod kontrakti: `state_machines.py` (`TRIP_STATUSES_ALLOWING_SERVICE_START`, `service_start_allowed`, `PASSENGER_BLOCKS_TRIP_CANCEL`, `PARCEL_BLOCKS_TRIP_CANCEL`, `booking_blocks_trip_cancel`, `TRIP_CANCEL_REFUSED_WITH_PENDING_NO_SHOW_REVIEW`, `DELIVERED_OPERATOR_QUEUE_AFTER`), `proofs.py`, `disclosure.py`, `detour.py` (`DETOUR_NOT_AVAILABLE_REASON`).

| Joy | Oldingi qoida | Yangi qoida | Xato | Egasi / manba |
|---|---|---|---|---|
| §2 `accept` | detour quote’lar tekshiriladi | Versiyada detour quote bo‘lsa **barcha muhitlarda** rad; AC13 qayta tekshiruvi pilotdan tashqarida | `409 ROUTE_MISMATCH` `details.reason=detour_not_available` | A4, Q62 |
| §2 `accept` | vehicle holati tekshirilmagan | Trip vehicle’i `approved` (A1 `trips.service.assert_vehicle_eligible_for_new_booking`) — faqat yangi bron bloklanadi; mavjud bronlar majburiyat sifatida davom etadi | `409 VEHICLE_NOT_ELIGIBLE` | A4 + A1, Q61 |
| §2 `counter` | band faqat narx o‘zgarsa | Band narx **yoki** pickup/dropoff bekati o‘zgarsa qayta o‘qiladi (nuqtali uchda uchlar o‘zgarmaydi → faqat narx) | `warnings[PRICE_OUTSIDE_REFERENCE]`; `enforced` band bo‘lsa `400 PRICE_OUT_OF_BAND` | A1, Q67, Q90 |
| §3 T7 `PATCH /trips` | bronli trip marshruti `INVALID_STATE_TRANSITION` | Trip’da bironta allocation (inactive ham) bo‘lsa bekatlar o‘zgarmaydi (servis `bookings.service.trip_has_allocations` + DB 0054) | `409 TRIP_STOPS_LOCKED` | A1, Q63 |
| §3 `cancel` (har holatdan) | `boarding`/`interrupted`da onboard/custody tekshiruvi; pending no-show review avtomatik `rejected` | `booking_blocks_trip_cancel` bo‘lgan bron (passenger `onboard`/`arrived`, parcel `picked_up`/`in_transit`/`delivery_failed`/`return_required`) bo‘lsa **har qanday trip holatida** rad; pending no-show review bo‘lsa rad — operator avval review’ni hal qiladi, trip cancel review’ni **hech qachon** yopmaydi | `409 TRIP_HAS_UNRESOLVED_BOOKINGS` / `409 NO_SHOW_REVIEW_PENDING` (`details.bookings[]`) | A4, Q19, Q7, BR 4–5 |
| §4 `board`, §5 `pick_up` | trip holati tekshirilmagan (`planned`da ham mumkin edi) | Trip `boarding` yoki `in_progress` bo‘lishi shart (`service_start_allowed`) | `409 TRIP_NOT_STARTED` | A4, BR 4 |
| §4, §5 proof kodlar | 5 xato → abadiy qulf | Kod egasi o‘zi qayta chiqaradi (`proofs.reissue_decision`) yoki operator `reissue_proof_code`; rotation +1, eski kod yaroqsiz, audit + `booking.proof_code.reissued` | `429 PROOF_REISSUE_LIMITED` | A4, BR 3, ADR-0018 |
| §4 `arrived → completed`, §5 `delivered → completed` | operator yo‘li mashinada yo‘q edi | `complete_with_evidence` (O) o‘tishi qo‘shildi | — | A4 |
| §5 `deliver` | shu tx’da S `complete` + capture | `deliver` faqat `delivered`ga o‘tkazadi; jo‘natuvchi `complete` bilan tasdiqlaydi, 24 soatdan keyin `awaiting_confirmation` operator navbati → `complete_with_evidence`; B5 delivery kodi `WarningCode.DELIVERY_CODE_SHARE_WITH_RECEIVER_ONLY` bilan; chatda 6 xonali kodlar maskalanadi | — | A4 (+A7, A10a), Q65 |
| §4/§5 `complete` capture | A12 probe yo‘q + `disputes_v2` bor → `503` | **Q74:** A12 probe ro‘yxatdan o‘tmagan bo‘lsa (jadval bor-yo‘qligidan qat’i nazar) `bookings.service.dispute_state` → `unavailable`: xizmat yakunlanadi, commission `held` qoladi, `finance_review` navbati (`CommissionReviewReason.DISPUTE_MODULE_UNAVAILABLE`), staff event `commission.finance_review_required`; finance B13 `finalize_fee` bilan yopadi (pilotda har yakunlangan bron; AC20 bitta capture — `finalize_fee` orqali). Probe ro‘yxatdan o‘tgach (A12, wave 3): `clear` → shu tx’da capture; `open` → capture kechiktiriladi, finance navbatiga tushmaydi | — | A4, Q66, Q74 |
| §9 kontakt ko‘rinishi | to‘liq plate `awaiting_pickup`dan | Maskalangan plate + model + rang accept’dan; to‘liq plate trip `boarding` yoki pickup’ga ≤ 30 daqiqa (`disclosure.full_plate_visible`); admin ro‘yxatlarida telefon ko‘rsatilishi audit qatori bilan | — | A4, Q64 |
| §0.1 bron snapshot | 0048 guard butun snapshot’ni muzlatadi | Miqdor/narx/jami/komissiya/resurs faqat qabul qilingan amendment bilan; qolgani muzlatilgan (DB 0056) | `409 INTEGRITY_CONFLICT` (`booking_snapshot_frozen`) | A4, Q60 |
| §9 Top-up / adjustment | approver capability servisda | Approver faol `finance`/`super_admin` — DB’da; production’da Q48 gate o‘tmaguncha top-up tasdiqlash va kredit adjustment rad | `403 FORBIDDEN` / `503 PRODUCTION_INVARIANTS_FAILED` | A3, Q69, Q70 |

## 12. Wave 3 (16.09.2026) — tracking, communications, trust & support
Kod kontrakti: `state_machines.py` (`TRUST_REVIEW`, `SUPPORT_TICKET`), `tracking.py` (`tracking_window`, `point_rejection`, `is_trusted_for_live`), `communications.py` (`chat_writable`, `outbox_retry_delay`), `trust.py` (`BLOCKING_DISPUTE_TYPES`, strike qoidalari, probe protokollari).

### 12.1 Trust review (`trust_review_items.status`, A12, Q45)
Boshlang‘ich `open`; terminal `dismissed`, `actioned`. Avtomatik ban yoki jarima yo‘q.

| From → To | Buyruq | Actor | Guard | Side effect | Xato |
|---|---|---|---|---|---|
| ∅ → open | `open` (S) | S (consumer) | (subject, signal_type) uchun bitta ochiq/ko‘rib chiqilayotgan qator (partial unique) — takror signal mavjud qator evidence’ini yangilaydi | `trust.review.opened` (staff) | — |
| open → under_review | `start_review` | O (`ops.trust_review`) | `expected_version` | Mas’ul yoziladi, audit | `VERSION_CONFLICT` |
| open/under_review → dismissed | `dismiss` | O | `decision = no_violation`, izoh | audit | `INVALID_STATE_TRANSITION` |
| open/under_review → actioned | `action` | O | `decision ∈ {warning_issued, escalated_to_admin}`, izoh | `warning_issued` → `trust.warning_issued` (foydalanuvchiga); `escalated_to_admin` → admin I5 orqali alohida (avtomatik blok yo‘q) | `INVALID_STATE_TRANSITION` |

Signal manbalari (A12 outbox consumer’lari, `communications.EventConsumer`): `trust.contact_filter.hit` → oynadagi oldingi mosliklar `CONTACT_FILTER_FREE_HITS`dan ko‘p bo‘lsa strike (`contact_strikes`, `trust.contact_strike.recorded`), strike’lar `STRIKES_FOR_REVIEW`ga yetsa `contact_filter_strikes`; `booking.cancelled` → A7 `chat_activity_for_booking` bo‘yicha oxirgi chat filtr mosligidan `QUICK_CANCEL_AFTER_CHAT_WINDOW` ichida bekor → `quick_cancel_after_chat`; bir juftlikning oynadagi bekor qilishlari `REPEATED_PAIR_CANCEL_THRESHOLD`ga yetsa → `repeated_pair_cancellations`. Evidence faqat `trust.TRUST_REVIEW_EVIDENCE_KEYS`.

### 12.2 Support ticket / SOS (`support_tickets.status`, A12, §16)
Boshlang‘ich `open`; terminal `resolved`. `open → acknowledged` (`acknowledge`, O `ops.trust_review`), `open/acknowledged → resolved` (`resolve`, O, izoh). SOS har bron holatida ochiladi (obligation, D16); staff event `support.sos.raised` koordinatasiz; javob vaqti va’da qilinmaydi.

### 12.3 Dispute (§8 ga qo‘shimcha)
- `open_dispute` lock: `bookings.service.lock_booking` → `disputes_v2` insert (booking bolasi, ADR-0017). Yakunlash (`complete`) ham bronni lock qiladi — shuning uchun nizo ochish va capture ketma-ketlashadi.
- A12 `register_booking_hooks()` dan keyin `bookings.service.dispute_state`: `BLOCKING_DISPUTE_TYPES` turidagi `open|under_review` nizo bor → `open` (capture kechiktiriladi), yo‘q → `clear` (capture). `no_show`, `safety`, `other` capture’ni to‘xtatmaydi.
- B8 `contest` → `PaymentDisputeOpener` (`payment` turi, mavjud faol bo‘lsa uning id’si qaytadi).
- **Ochiq (U8):** nizo hal bo‘lgach kechiktirilgan capture’ni kim qayta baholaydi (§8 “S tomonidan”) — A4 funksiyasi yo‘q; pilotda finance B13 `finalize_fee` (B12 `hold_escalation`).

### 12.4 Tracking oynasi va sessiya (§9 ga qo‘shimcha, A6)
- Oyna o‘qish vaqtida: `tracking.tracking_window(service_type, service_status, trip_status, pickup_window_start, now)` — trip terminal → `trip_finished`; passenger `confirmed|awaiting_pickup` pickup − 30 daqiqadan, `onboard` har doim ochiq, `arrived`/terminal → yopiq; parcel `picked_up|in_transit|delivery_failed|return_required` ochiq, pickup’gacha `parcel_not_picked_up`, `delivered`/terminal → yopiq. Grant `valid_until`/`revoked_at` qo‘shimcha cheklaydi.
- Sessiya: `create` — trip `FOR SHARE` → oldingi `active` → `superseded` (`supersede`) → yangi `active`; `close` — egasi yoki S (trip terminal). Yopiq/eskirgan sessiya nuqtasi DB’da ham rad (`tracking_session_closed`, `tracking_session_superseded`).
- Faqat ishonchli nuqta (`is_trusted_for_live`) live marker va freshness’ni yangilaydi; `captured_at` bo‘yicha monoton (AC28).

### 12.5 Chat yozish qoidasi (A7)
Holat mashinasi emas — ota ob’ektdan hisoblanadi: `communications.chat_writable` (proposal chat faqat thread `open`; bron chat terminal vaqtdan `CHAT_WRITABLE_AFTER_TERMINAL` (24 soat) gacha) → aks holda `409 CHAT_CLOSED`. Xabar kontenti o‘zgarmas; faqat `moderation_status` (`visible → hidden_by_staff`, O `ops.trust_review`, sabab, audit).
