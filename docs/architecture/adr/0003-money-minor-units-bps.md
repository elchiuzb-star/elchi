# ADR-0003: Pul — BIGINT minor unit, bps, yagona `round_half_up`

**Holat:** Accepted (Q19, 13.09.2026) • **Sana:** 13.09.2026 • **Muallif:** A0a
**Spec:** §5.2, §9.3, §9.4, §14.1, §18.2 • **AC:** AC01, AC19, AC20, AC25, AC37, AC43
**Kontrakt:** `app/contracts/money.py`, `tests/contracts/test_money.py`

## Kontekst
v1: `Numeric(12,2)` so‘m (`app/models/order.py:36-41`, `bid.py:20`), stavka `Numeric(5,4)` (`order.py:39`), `Decimal` yaxlitlash `ROUND_HALF_UP` 0.01 gacha (`app/services/system_settings_service.py:12-25,46-55`). JSON’da float (`BASELINE_AUDIT.md` §2.8). Spec §9.4: BIGINT minimal birlik, 1 so‘m = 100 tiyin, float yo‘q, bps, bitta server funksiyasi.

## Qaror
1. **Saqlash:** barcha v2 pul ustunlari `BIGINT NOT NULL`, nomi `*_minor`, yonida `currency CHAR(3) NOT NULL DEFAULT 'UZS'` (CHECK `currency IN ('UZS')`). Musbatlik CHECK’lari DATA_MODEL’da.
2. **API:** `unit_price_minor`, `total_minor`, `commission_minor`… integer; `currency`. Klient formatlaydi. Float qabul qilinmaydi (`MoneyDTO.amount_minor: StrictInt`).
3. **Hisob:** `total_minor = unit_price_minor × quantity` (`per_seat`) yoki `total_minor = unit_price_minor` (`total`). Server hisoblaydi, klient qiymatiga ishonmaydi (§14.1).
4. **Komissiya:** `commission_minor = round_half_up(total_minor × fee_bps / 10000)` — faqat `money.commission_minor`. `round_half_up_div` — integer, yarimlar noldan uzoqqa (`Decimal ROUND_HALF_UP` bilan bir xil; testda ±2000 oralig‘ida solishtirilgan). Net: `total − commission` (“sof foyda” emas, §8.4).
5. **Stavka:** `fee_bps INTEGER CHECK (fee_bps BETWEEN 0 AND 10000)`.
6. **Legacy mapping:** `major_to_minor(Decimal)` — aniq, 2 xonadan ortig‘i xato; `legacy_rate_to_bps(Decimal('0.1500')) = 1500` — aniq bo‘lmasa xato (jim yaxlitlash yo‘q). Legacy `system_fee` faqat hisobot uchun `legacy_calculated_fee_minor` sifatida ko‘chiriladi, ledger’ga tushmaydi (§18.2).
7. **v1:** v1 javoblari o‘zgarmaydi (float so‘m) — muzlatilgan klientlar uchun. v1→v2 adapterlari `money` helper’larini ishlatadi.

## Muqobillar
- **Numeric(14,2) so‘m** — spec §9.4 ga zid; Python/JS float xatolariga yo‘l ochadi.
- **Butun so‘m (minor=1)** — UZS’da tiyin amalda ishlatilmaydi, lekin spec 100 tiyin deydi va karta provayderlari minor unit kutadi; spec ustun.
- **Banker’s rounding** — spec `round_half_up` deydi.

## Oqibatlar
- Tiyinli qiymatlar UI’da ko‘rsatilmasa ham saqlanadi; komissiya 1 tiyin aniqlikda.
- `9.2 × 10^18` limit — amaliy muammo yo‘q.
- JS tomonda `Number.MAX_SAFE_INTEGER` (9.0 × 10^15 tiyin = 90 trln so‘m) — pilot uchun yetarli; TS tip `number`.
