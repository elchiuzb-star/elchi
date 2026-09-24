"""Referral stage 6 simulator (ADR-0023 §20) - SYNTHETIC scenarios, reproducible from this command.

    py scripts/promo_simulate.py                    # run docs/referral/simulation/scenarios.json -> results.json + REPORT.md
    py scripts/promo_simulate.py --check            # re-run; exit 1 when the committed results.json differs
    py scripts/promo_simulate.py --config other.json --out-dir some/dir

No database, no network, no settings: the scenario file, its seed and the code fingerprint printed in the report
fully determine the output. Nothing it prints is an approved value or a production tariff. This CLI is the dry-run
tool of A6.1; an HTTP dry-run endpoint is deferred (see REFERRAL_PLAN A6.1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.promotions.simulation.config import Scenario, load_scenarios
from app.modules.promotions.simulation.engine import (
    NOT_YET,
    UNUSED_REASONS,
    run_scenario,
)
from app.modules.promotions.simulation.report import (
    COMBINED_STRESS,
    PERTURBATIONS,
    cac,
    checks,
    combine,
    fmt,
    liability,
    lines,
    matched_control,
    perturb,
    programme,
    scale_incremental,
)

DEFAULT_CONFIG = ROOT / "docs/referral/simulation/scenarios.json"
CODE_FILES = sorted((ROOT / "app/modules/promotions/simulation").glob("*.py")) + [
    ROOT / "app/contracts/promo.py", ROOT / "app/contracts/money.py", ROOT / "app/contracts/enums.py"]
SEEDS = 20  # seed spread: model randomness only - never a market confidence interval
GRID = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 125, 150)  # incremental-users assumption, % of the scenario's


def code_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in CODE_FILES:
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


def summarize(scenario: Scenario, run: dict) -> dict:
    out = {"name": scenario.name, "title": scenario.title, "synthetic": scenario.synthetic, "seed": scenario.seed,
           "config_fingerprint": scenario.fingerprint, "referral_enabled": scenario.referral_enabled,
           "pilot_variant": scenario.pilot_variant, "experiment": scenario.experiment, "notes": list(scenario.notes),
           "snapshots": {}}
    for day, snap in sorted(run["snapshots"].items()):
        scopes = {key: lines(snap, scenario, key) for key in snap["money"] if key.split(":")[0] in ("total", "service", "corridor")}
        out["snapshots"][str(day)] = {
            "lines": scopes, "programme": programme(snap), "cac": cac(snap, scenario), "budgets": snap["budgets"],
            "users": snap["users"], "events": snap["events"], "enrollments": snap["enrollments"],
            "not_activated": snap["not_activated"], "avg_review_wait_days": snap["avg_review_wait_days"],
            "campaign_money": {k: v for k, v in snap["money"].items() if k.startswith("campaign:")},
            "cohorts": snap["cohorts"], "bonus_use": snap["bonus_use"],
            "checks": [{"name": name, "ok": ok} for name, ok in checks(snap, scenario)],
        }
    return out


def _last(summary: dict) -> dict:
    return summary["snapshots"][str(max(int(d) for d in summary["snapshots"]))]


def _scope(service: str | None) -> str:
    return "total:all" if service is None else f"service:{service}"


def margin_of(snap: dict, service: str | None = None) -> int:
    row = snap["lines"].get(_scope(service))
    return 0 if row is None else row["operational_margin"]


def stress_margin(snap: dict, service: str | None = None) -> int:
    """Operational margin if every outstanding promise and unspent bonus of the scope's campaigns is later spent in
    full (each tiyin of P/H spent lowers some future C_net by exactly that tiyin): never relies on bonuses going unused."""
    return margin_of(snap, service) - liability(snap, service)


def _twin(scenario: Scenario) -> tuple[Scenario, dict]:
    twin = matched_control(scenario)
    return twin, run_scenario(twin)


def control_view(summary: dict) -> dict:
    """What the report needs from a matched control: margins and users per snapshot and scope."""
    return {"name": summary["name"], "config_fingerprint": summary["config_fingerprint"], "snapshots": {
        day: {"lines": {scope: {k: L[k] for k in ("served", "operational_margin", "net_commission_kept", "variable_cost",
                                                  "unserved_orders")} for scope, L in snap["lines"].items()},
              "users": {svc: {"activated": u["activated"], "arrived": u["arrived"]} for svc, u in snap["users"].items()},
              "budgets": {}, "checks_ok": all(c["ok"] for c in snap["checks"])}
        for day, snap in summary["snapshots"].items()}}


def diff(ran: dict, twin: dict, service: str | None = None) -> dict:
    last, base = _last(ran), _last(twin)
    return {"margin_diff": margin_of(last, service) - margin_of(base, service),
            "stress_diff": stress_margin(last, service) - margin_of(base, service),
            "liability": liability(last, service), "incentive_consumed": last["programme"]["incentive_consumed"],
            "checks_ok": all(c["ok"] for snap in ran["snapshots"].values() for c in snap["checks"])}


def evaluate(scenario: Scenario, service: str | None = None) -> dict:
    ran = summarize(scenario, run_scenario(scenario))
    return diff(ran, summarize(*_twin(scenario)), service)


def sensitivity(scenario: Scenario, service: str | None) -> dict:
    """Each assumption change applied ALONE, then two joint runs: passing each alone is not passing them together."""
    single = {name: evaluate(perturb(scenario, name), service) for name in PERTURBATIONS}
    joint_names = {"joint_half_incremental": COMBINED_STRESS,
                   "joint_no_incremental": tuple(n if n != "half_incremental_users" else "no_incremental_users"
                                                 for n in COMBINED_STRESS)}
    joint = {key: {**evaluate(combine(scenario, names), service), "applied": list(names)}
             for key, names in joint_names.items()}
    return {"single": single, "joint": joint}


def breakeven(scenario: Scenario, service: str | None) -> dict:
    """Break-even of the incremental-users assumption found BY SIMULATION on a grid, next to the old ratio estimate.

    The ratio (cost / control margin per activated user) assumes every extra user earns the control average from day
    one and that cost grows linearly; the budget cap, qualification failures and late arrivals make both untrue, so
    the grid is the evidence and the ratio only a cross-check."""
    twin = summarize(*_twin(scenario))  # referral off: independent of the assumption
    rows = []
    for pct in GRID:
        ran = summarize(scale_incremental(scenario, pct), run_scenario(scale_incremental(scenario, pct)))
        last = _last(ran)
        rows.append({"factor_pct": pct, **diff(ran, twin, service),
                     "incremental_activated": sum(u["activated_incremental"] for u in last["users"].values()),
                     "budget_blocked": last["programme"]["budget_blocked_enrollments"]})
    ok = [r["stress_diff"] >= 0 for r in rows]
    first = next((i for i, v in enumerate(ok) if v), None)
    monotone = first is not None and all(ok[first:])
    full = next(r for r in rows if r["factor_pct"] == 100)
    base = _last(twin)
    activated = sum(u["activated"] for u in base["users"].values())
    per_user = margin_of(base) // activated if activated else None
    cost = full["incentive_consumed"] + full["liability"] + scenario.extra_marketing_minor
    need = math.ceil(cost / per_user) if per_user and per_user > 0 else None
    return {"rows": rows, "threshold_pct": None if first is None else GRID[first], "stable_above": monotone,
            "below": rows[first - 1] if first else None, "at": rows[first] if first is not None else None,
            "ratio_need_users": need, "ratio_have_users": full["incremental_activated"],
            "ratio_estimate_pct": None if not need or not full["incremental_activated"]
            else round(100 * need / full["incremental_activated"])}


def seed_spread(scenario: Scenario, service: str | None) -> dict:
    values = []
    for i in range(SEEDS):
        seeded = replace(scenario, seed=scenario.seed + i)
        values.append({"seed": seeded.seed, **evaluate(seeded, service)})
    stress = sorted(v["stress_diff"] for v in values)
    margin = sorted(v["margin_diff"] for v in values)

    def stats(xs: list[int]) -> dict:
        return {"min": xs[0], "p10": xs[len(xs) // 10], "median": xs[len(xs) // 2], "p90": xs[(len(xs) * 9) // 10],
                "max": xs[-1], "negative": sum(x < 0 for x in xs)}

    return {"seeds": [v["seed"] for v in values], "n": len(values), "stress_diff": stats(stress),
            "margin_diff": stats(margin), "checks_ok": all(v["checks_ok"] for v in values)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out-dir", default=str(DEFAULT_CONFIG.parent))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    scenarios, raw = load_scenarios(args.config)
    by_name = {s.name: s for s in scenarios}
    results = {"about": raw.get("about"), "code_fingerprint": code_fingerprint(),
               "command": "py scripts/promo_simulate.py" + ("" if Path(args.config) == DEFAULT_CONFIG else f" --config {args.config}"),
               "seeds_per_spread": SEEDS, "breakeven_grid_pct": list(GRID), "scenarios": {}, "analysis": {}}
    for scenario in scenarios:
        summary = summarize(scenario, run_scenario(scenario))
        if scenario.referral_enabled:  # each scenario against its own twin with referral off
            summary["matched_control"] = control_view(summarize(*_twin(scenario)))
        results["scenarios"][scenario.name] = summary
    for scenario in scenarios:
        parcel = (scenario.experiment or "").startswith("pochta")
        if not (scenario.pilot_variant or parcel):
            continue
        service = "parcel" if parcel else None
        entry = {"service": service, "breakeven": breakeven(scenario, service), "sensitivity": sensitivity(scenario, service)}
        if scenario.pilot_variant or scenario.name == "parcel_base":
            entry["seeds"] = seed_spread(scenario, service)
        results["analysis"][scenario.name] = entry

    out_dir = Path(args.out_dir)
    text = json.dumps(results, indent=1, sort_keys=True, ensure_ascii=False)
    if args.check:
        current = (out_dir / "results.json").read_text(encoding="utf-8") if (out_dir / "results.json").exists() else ""
        if current != text + "\n":
            print("results.json differs from a fresh run (seed/config/code changed?)")
            return 1
        print("results.json reproduced exactly")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(text + "\n", encoding="utf-8")
    (out_dir / "REPORT.md").write_text(render(results, by_name), encoding="utf-8")
    bad = [f"{name}: {c['name']}" for name, s in results["scenarios"].items()
           for snap in s["snapshots"].values() for c in snap["checks"] if not c["ok"]]
    bad += [f"analysis {name}" for name, a in results["analysis"].items()
            if not all(r["checks_ok"] for r in a["breakeven"]["rows"])]
    print(f"wrote {out_dir / 'results.json'} and REPORT.md; code {results['code_fingerprint']}; failed checks: {len(bad)}")
    for item in bad:
        print("  FAILED", item)
    return 1 if bad else 0


# --- the Markdown report -------------------------------------------------------------------------------------------


def _pct(num: int, den: int) -> str:
    return "—" if not den else f"{100 * num / den:.0f}%"


def _bps(value: int | None) -> str:
    return "—" if value is None else f"{value / 100:.1f}%"


def _twin_last(summary: dict) -> dict | None:
    twin = summary.get("matched_control")
    return _last(twin) if twin else None


def _twin_margin(summary: dict, scope: str = "total:all") -> int | None:
    twin = _twin_last(summary)
    row = twin["lines"].get(scope) if twin else None
    return None if row is None else row["operational_margin"]


def _metric_cell(m: dict) -> str:
    if m["status"] == NOT_YET:
        return f"hali baholab bo'lmaydi ({m['matured']} yetilgan / {m['immature']} yetilmagan; kamida {m['minimum']})"
    value = fmt(m["value_minor"]) + " so'm" if m["value_minor"] is not None else _bps(m["value_bps"])
    return f"{value} ({m['matured']} yetilgan / {m['immature']} yetilmagan)"


REASON_LABELS = {
    "not_matured": "lot hali yetilmagan (< yetilish kunlari)", "reserved_awaiting_capture": "bronda rezervda, capture kutilmoqda",
    "client_did_not_return": "egasi qayta buyurtma bermagan", "no_driver_found": "mos haydovchi topilmagan",
    "no_room_in_commission": "komissiyada chegirmaga joy yo'q (C_net − O ≥ M)", "receiver_pays": "qabul qiluvchi to'laydi",
    "client_did_not_choose": "mijoz bonusni tanlamagan", "order_cancelled": "buyurtma bekor qilingan",
    "reversed_fraud": "firibgarlik sababli qaytarilgan",
}
METRIC_LABELS = {
    "qualification_rate": "Qualification ulushi", "retention_d30": "D30 qaytish", "retention_d60": "D60 qaytish",
    "margin_d60": "D60 marja / kishi", "bonus_first_spend_d30": "Lot 30 kunda ishlatilgan",
    "bonus_value_spent_d30": "Bonus qiymati 30 kunda ishlatilgan",
}


def render(results: dict, scenarios: dict[str, Scenario]) -> str:  # noqa: C901 - one linear document
    S = results["scenarios"]
    out: list[str] = []
    w = out.append
    w("# Referral simulyatsiyasi (6-bosqich) — **SINTETIK SSENARIYLAR**\n")
    w("> Barcha kirish qiymatlari va natijalar **sintetik ssenariy**: haqiqiy ma'lumot yo'q, hech bir qiymat tasdiqlanmagan va "
      "production konfiguratsiyasiga ko'chirilmaydi. Natijalar faqat kiritilgan taxminlarning oqibati — foydalanuvchilar "
      "soni albatta oshishi yoki platforma zarar ko'rmasligi isboti **emas**. Operatsion (haqiqiy) ko'rsatkichlar bu yerda "
      "yo'q — ular admin hisobotida (`GET /api/v2/admin/promo/report`, `data_source = operational`).\n")
    w("## Takrorlash\n")
    w(f"- Buyruq: `{results['command']}` (tekshirish: `py scripts/promo_simulate.py --check`)")
    w(f"- Kod barmoq izi: `{results['code_fingerprint']}` (simulyator + `app/contracts/promo.py`, `money.py`, `enums.py`)")
    w("- Konfiguratsiya: `docs/referral/simulation/scenarios.json`; natijalar: `results.json`")
    w("- Seed va konfiguratsiya barmoq izi har ssenariy uchun:\n")
    w("| Ssenariy | Seed | Konfiguratsiya barmoq izi | Sintetik | Izoh |")
    w("|---|---|---|---|---|")
    for name, s in S.items():
        w(f"| {name} | {s['seed']} | `{s['config_fingerprint']}` | {'ha' if s['synthetic'] else 'YO‘Q'} | "
          f"{'; '.join(s['notes']) or ('tajriba: ' + s['experiment'] if s['experiment'] else '')} |")
    w("")

    w("## 1. Model nimani hisoblaydi\n")
    w("- Oqim: taklif kodi → attribution → enrollment (ikkala tomon maksimal majburiyati budjetdan rezerv) → qualification "
      "(48 soatlik risk oynasi, taklif qiluvchi xizmati hisoblanmaydi, pochtada 2 ta jo'natma) → grant (va'da → berilgan) → "
      "sarflash (keyingi buyurtmalarda P, haydovchi buyurtmalarida H).")
    w("- Birinchi va takroriy buyurtmalar; bekor qilish (Q129), nizo, fee release, reversal (Q127), kech capture, review, "
      "qisman sarf, expiry, grace, reinstate (Q122), haydovchi milestone'lari, P va H birga/alohida, haydovchi topilmasligi; "
      "past/o'rta/yuqori narx.")
    w("- **Formula bitta:** har bron shartlari `contracts.promo` dan (`choose_passenger_source`, `choose_driver_source`, "
      "`quote_at_accept`, `combined_margin_policy`); lot `LotBalance`, budjet `BudgetPosition`, qualification "
      "`evaluate_qualification`. PostgreSQL bilan solishtirilgan: `tests/pg/promotions/test_promo_simulation_pg.py`.")
    w("- **Ikki marta sanalmaydi:** `F_cash = F − P`, `C_net = C − P − H`; `C − P − H − reversal = saqlangan C_net` alohida "
      "tekshiriladi. F va F_cash — hajm, tushum emas; haydovchi top-up modelda yo'q. Doimiy xarajat va soliq **noma'lum** → "
      "biznes natijasi hisoblanmaydi.")
    w("- **Attribution ≠ sabab.** Qo'shimcha foydalanuvchilar (`incremental_new_per_day`) — ochiq taxmin; faqat va'da bera "
      "oladigan kampaniya bo'lsa keladi. Har ssenariy **juft nazorat** bilan (xuddi shu dunyo, referral o'chiq, `<nom>~control`); "
      "tasodifiy sonlar barqaror identifikator bo'yicha chiziladi.")
    w("- **Cohort langari (A6.2) — har ko'rsatkich o'z langari bilan, aralashtirilmaydi:**")
    w("  - *enrollment* → qualification ulushi (qualification oynasi + capture/review dumi o'tgan enrollment'lar);")
    w("  - *aktivlashish* (commission capture qilingan birinchi bronning xizmat kuni) → D30/D60 qaytish, D60 marja;")
    w(f"  - *grant* (`available_from`, bonus sarflanishi mumkin bo'lgan lahza) → "
      f"{next(iter(scenarios.values())).lot_maturity_days} kunlik bonus sarfi; yaqinda berilgan lot yetilmagan hisoblanadi.")
    w("  - Oynasi hali to'lmagan kuzatuv **yetilmagan** deb alohida sanaladi — \"qaytmadi\", \"nol daromad\" yoki \"ishlatilmadi\" "
      "hisoblanmaydi. Yetilgan kuzatuv minimaldan kam bo'lsa qiymat **\"hali baholab bo'lmaydi\"**, nol emas. Hisob sanasi — "
      "snapshot kuni (kuzatilgan oxirgi kun = kun − 1).\n")

    w("## 2. Asosiy natijalar (90 kun, so'm) — juft nazoratga nisbatan\n")
    w("Stress marja — qolgan majburiyat (va'da + sarflanmagan bonus) kelajakda to'liq sarflansa.\n")
    w("| Ssenariy | Xizmat ko'rsatilgan | C | P | H | Saqlangan C_net | Reversal | O | Operatsion marja | Nazoratdan farq | Qolgan majburiyat | Stress farq | Rad (budjet) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, s in S.items():
        last = _last(s)
        L, P = last["lines"]["total:all"], last["programme"]
        base = _twin_margin(s)
        w(f"| {name} | {L['served']} | {fmt(L['commission_gross'])} | {fmt(L['passenger_bonus'])} | {fmt(L['driver_credit'])} | "
          f"{fmt(L['net_commission_kept'])} | {fmt(L['commission_reversed'])} | {fmt(L['variable_cost'])} | "
          f"{fmt(L['operational_margin'])} | {'—' if base is None else fmt(L['operational_margin'] - base)} | "
          f"{fmt(P['outstanding_liability'])} | {'—' if base is None else fmt(stress_margin(last) - base)} | "
          f"{P['budget_blocked_enrollments']} |")
    w("\nBiznes natijasi (doimiy xarajat va soliqdan keyin): **noma'lum** — `fixed_costs_per_30_days_minor = null`.\n")

    w("## 3. 30 / 60 / 90 kun: pul va cohort ko'rsatkichlari\n")
    w("| Ssenariy | Kun | Operatsion marja | Sarflangan rag'bat (P+H) | Qolgan majburiyat | Rezerv (bronlarda) |")
    w("|---|---|---|---|---|---|")
    for name, s in S.items():
        for day, snap in sorted(s["snapshots"].items(), key=lambda item: int(item[0])):
            reserved = sum(b["reserved_on_bookings"] for b in snap["budgets"].values())
            w(f"| {name} | {day} | {fmt(snap['lines']['total:all']['operational_margin'])} | "
              f"{fmt(snap['programme']['incentive_consumed'])} | {fmt(snap['programme']['outstanding_liability'])} | {fmt(reserved)} |")
    w("")
    w("### Cohort ko'rsatkichlari (langar, yetilgan/yetilmagan)\n")
    w("Qiymat faqat yetilgan kuzatuvlardan; \"hali baholab bo'lmaydi\" — nol emas.\n")
    focus = [n for n in ("control", "variant_A", "variant_B", "parcel_base") if n in S]
    w("| Ssenariy | Xizmat | Ko'rsatkich | Langar | Guruh | Kun 30 | Kun 60 | Kun 90 |")
    w("|---|---|---|---|---|---|---|---|")
    for name in focus:
        snaps = S[name]["snapshots"]
        keys = [(m["service"], m["metric"], m["group"]) for m in snaps["90"]["cohorts"]]
        for service, metric, group in keys:
            if group == "all":
                continue
            found = [next(x for x in snaps[day]["cohorts"] if (x["service"], x["metric"], x["group"]) == (service, metric, group))
                     for day in ("30", "60", "90")]
            if not any(m["matured"] + m["immature"] for m in found):
                continue  # nobody in this cohort at all (e.g. referees in a control): nothing to show
            cells = [_metric_cell(m) for m in found]
            anchor = next(x for x in snaps["90"]["cohorts"] if (x["service"], x["metric"], x["group"]) == (service, metric, group))["anchor"]
            w(f"| {name} | {service} | {METRIC_LABELS.get(metric, metric)} | {anchor} | {group} | {' | '.join(cells)} |")
    w("")

    w("## 4. Xizmat va koridor bo'yicha (90 kun)\n")
    w("Pochta natijasi yo'lovchi zararini yashirmasligi uchun har xizmat alohida, o'z juft nazorati bilan.\n")
    w("| Ssenariy | Qamrov | Xizmat ko'rsatilgan | Chegirmali | P | H | Saqlangan C_net | O | Operatsion marja | Juft nazorat | Farq | Stress farq (xizmat) | Haydovchi topilmagan |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, s in S.items():
        last = _last(s)
        for scope, L in sorted(last["lines"].items()):
            if scope == "total:all":
                continue
            base = _twin_margin(s, scope)
            service = scope.split(":")[1] if scope.startswith("service:") else None
            stress = "—" if base is None or service is None else fmt(stress_margin(last, service) - base)
            w(f"| {name} | {scope} | {L['served']} | {L['discounted_bookings']} | {fmt(L['passenger_bonus'])} | "
              f"{fmt(L['driver_credit'])} | {fmt(L['net_commission_kept'])} | {fmt(L['variable_cost'])} | "
              f"{fmt(L['operational_margin'])} | {fmt(base)} | {'—' if base is None else fmt(L['operational_margin'] - base)} | "
              f"{stress} | {L['unserved_orders']} |")
    w("")

    w("## 5. Budjet: limit, majburiyat, mablag' bilan ta'minlanganlik (90 kun)\n")
    w("Majburiyat = va'da + berilgan (sarflanmagan) + sarflangan. Ta'minlangan = majburiyat − kamomad. Foydalanish cho'qqisi — "
      "**o'sha lahzadagi** limitga nisbatan. Budjet manbai — aniq parametr; kelajakdagi daromad mavjud mablag' emas.\n")
    w("| Ssenariy | Kampaniya | Xizmat | Boshlang'ich limit | Yakuniy limit | Majburiyat | Ta'minlangan | Kamomad | Kamaytirish: bajarildi / rad | Funding loss | Kamaytirish mumkin (B − S − L) | Foydalanish cho'qqisi | Rad (budjet) | Reinstate / bajarilmagan |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, s in S.items():
        last = _last(s)
        for cid, na in last["not_activated"].items():
            w(f"| {name} | {cid} | — | 0 | 0 | — | — | — | — | — | — | — | faollashtirilmadi ({na}) | — |")
        for cid, b in last["budgets"].items():
            w(f"| {name} | {cid} ({b['kind']}) | {b['service']} | {fmt(b['allocated_initial'])} | {fmt(b['allocated'])} | "
              f"{fmt(b['committed'])} | {fmt(b['funded_committed'])} | {fmt(b['shortfall'])} | "
              f"{fmt(b['reduce_applied'])} / {fmt(b['reduce_refused'])} | {fmt(b['funding_loss'])} | {fmt(b['reducible'])} | "
              f"{_bps(b['peak_utilization_bps'])} | {b['budget_blocked_enrollments']} | "
              f"{fmt(b['reinstated'])} / {fmt(b['reinstate_unfulfilled'])} |")
    w("")
    w("**Budjetni kamaytirish (G14, migratsiya 0090).** Oddiy `reduce_allocation` budjetni sarflangan summa va bajarilmagan "
      "majburiyatlar yig'indisidan pastga tushira olmaydi: `B ≥ S + L`, kamaytirish mumkin bo'lgan summa `max(0, B − S − L)`. "
      "B — tasdiqlangan jami ajratma, S — hisobga olingan sof sarf (hech bir ledger turi uni kamaytirmaydi), L — va'da rezervi + "
      "berilgan sarflanmagan bonus (bronda band qilingan qism uning ichida, bir marta) + budjet joyini kutayotgan tasdiqlangan "
      "tiklashlar. Review yoki kech capture kutayotgan majburiyatlar va'da/berilgan ichida qoladi. Servis va DB trigger (budjet "
      "qatori lock'i ostida) tekshiradi; vakolatli admin ham chetlab o'tolmaydi. `budget_cut` ssenariysi endi shu kontraktni "
      "ishlatadi: so'ralgan summaning faqat `B − S − L` qismi bajariladi, qolgani **rad etiladi** — kamomad paydo bo'lmaydi, "
      "joy qolmagani uchun yangi va'dalar to'xtaydi.\n")
    w("**Tashqi moliyalashtirish yo'qolishi — alohida holat (`funding_loss`).** Oddiy kamaytirish emas: dalil (`evidence_reference`) "
      "bilan qayd etiladi, finance va katta summada ikki turli xodim qoidasi bilan. U majburiyatdan pastga tushishi mumkin — bu "
      "haqiqiy kamomad: hech bir va'da, bonus yoki sarf bekor qilinmaydi, kampaniya o'sha tranzaksiyada pauzaga o'tadi, yangi "
      "va'dalar to'xtaydi, admin hisobotida `budget_shortfall` ogohlantirishi va audit yozuvi. Ssenariy: `funding_loss`. "
      "Avvalgi \"104%\" — cho'qqi majburiyat kesilgan yakuniy limitga bo'lingan edi (noto'g'ri solishtirish) va taqiqlanishi "
      "kerak bo'lgan kamaytirishni ruxsat etilgandek ko'rsatardi; ikkalasi ham tuzatilgan. Dalil: "
      "`tests/pg/promotions/test_promo_budget_floor_pg.py`, `tests/contracts/test_promo.py::test_g14_*`, "
      "`tests/contracts/test_promo_simulation.py`.\n")

    w("## 6. Pochta: amaliy foyda alohida (model natijasi, haqiqiy ma'lumot emas)\n")
    w("Lotlar, bonus egalari va bonus qiymati alohida; faqat **yetilgan** lotlar (sarflash mumkin bo'lgan kun ≥ yetilish kunlari yoki "
      "yopilgan) baholanadi. Ishlatilmagan lot sababi — egasi bonusni ishlatishga eng yaqin kelgan holat.\n")
    parcel_names = [n for n, s in S.items() if _last(s)["bonus_use"].get("parcel", {}).get("lots_granted")]
    w("| Ssenariy | Lot (yetilgan / yetilmagan) | Ishlatilgan lot (yetilgan) | Ishlatgan egalar | Qiymat ishlatilgan (yetilgan) | Muddati tugagan | Ochiq | Review'da (enrollment) |")
    w("|---|---|---|---|---|---|---|---|")
    for name in parcel_names:
        u = _last(S[name])["bonus_use"]["parcel"]
        w(f"| {name} | {u['lots_matured']} / {u['lots_immature']} | {u['lots_spent_any_matured']} ({_pct(u['lots_spent_any_matured'], u['lots_matured'])}) | "
          f"{u['holders_used_any']} / {u['holders_matured']} ({_pct(u['holders_used_any'], u['holders_matured'])}) | "
          f"{fmt(u['value_spent_matured_minor'])} / {fmt(u['value_granted_matured_minor'])} ({_pct(u['value_spent_matured_minor'], u['value_granted_matured_minor'])}) | "
          f"{fmt(u['value_expired_minor'])} | {fmt(u['value_open_minor'])} | {u['enrollments_in_review']} |")
    w("\n**Ishlatilmagan lotlar sababi (90 kun, lot soni; qavsda — shundan muddati tugaganlar):**\n")
    w("| Ssenariy | " + " | ".join(REASON_LABELS[r] for r in UNUSED_REASONS) + " |")
    w("|---|" + "---|" * len(UNUSED_REASONS))
    for name in parcel_names:
        u = _last(S[name])["bonus_use"]["parcel"]
        w(f"| {name} | " + " | ".join(f"{u['unused_reason_lots'][r]} ({u['unused_reason_lots_expired'][r]})" for r in UNUSED_REASONS) + " |")
    w("")
    w("**Pochta tajribalari (faqat sintetik; narx, haydovchi daromadi va M o'zgarmagan) — pochta qamrovi, o'z juft nazoratiga nisbatan:**\n")
    w("| Tajriba | Marja farqi | Stress farq | Zararsizlik (simulyatsiya to'ri) | Qo'shimcha foydalanuvchi yo'q (stress farq) | Hammasi birga, yarim qo'shimcha (stress farq) |")
    w("|---|---|---|---|---|---|")
    for name, a in results["analysis"].items():
        if a["service"] != "parcel":
            continue
        full = next(r for r in a["breakeven"]["rows"] if r["factor_pct"] == 100)
        be = a["breakeven"]
        th = "topilmadi (≤150%)" if be["threshold_pct"] is None else f"{be['threshold_pct']}% dan{' (barqaror)' if be['stable_above'] else ' (barqaror emas)'}"
        w(f"| {name} | {fmt(full['margin_diff'])} | {fmt(full['stress_diff'])} | {th} | "
          f"{fmt(a['sensitivity']['single']['no_incremental_users']['stress_diff'])} | "
          f"{fmt(a['sensitivity']['joint']['joint_half_incremental']['stress_diff'])} |")
    w("")

    w("## 7. Foydalanuvchi tomoni va CAC (90 kun)\n")
    w("| Ssenariy | Xizmat | Kelgan | Qo'shimcha (taxmin) | Kod bilan | Enrollment | Aktivlashgan referee | O'rtacha haqiqiy chegirma | Grant → birinchi sarf (kun) | O'rtacha review kutish (kun) | Haydovchi topilmagan referee |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, s in S.items():
        last = _last(s)
        for service, u in last["users"].items():
            w(f"| {name} | {service} | {u['arrived']} | {u['arrived_incremental']} | {u['attributed']} | {u['enrolled_referees']} | "
              f"{u['activated_referees']} | {fmt(u['avg_discount_minor'])} | "
              f"{u['avg_days_grant_to_first_spend'] if u['avg_days_grant_to_first_spend'] is not None else '—'} | "
              f"{last['avg_review_wait_days'] if last['avg_review_wait_days'] is not None else '—'} | {u['referees_with_unserved_orders']} |")
    w("\nCAC surati: sarflangan rag'bat + qolgan majburiyat + qo'shimcha marketing; maxrajlar aralashtirilmaydi.\n")
    w("| Ssenariy | Surat | / attribution | / enrollment | / aktivlashgan referee | / qo'shimcha aktivlashgan (TAXMIN) |")
    w("|---|---|---|---|---|---|")
    for name, s in S.items():
        c = _last(s)["cac"]
        if c["numerator"]["total"]:
            w(f"| {name} | {fmt(c['numerator']['total'])} | {fmt(c['per']['attributed'])} | {fmt(c['per']['enrolled_referees'])} | "
              f"{fmt(c['per']['activated_referees'])} | {fmt(c['per']['activated_incremental_ASSUMPTION'])} |")
    w("")

    w("## 8. Moliyaviy tengliklar va budjet invariantlari\n")
    for name, s in S.items():
        total = sum(len(snap["checks"]) for snap in s["snapshots"].values())
        failed = [c["name"] for snap in s["snapshots"].values() for c in snap["checks"] if not c["ok"]]
        w(f"- {name}: {total - len(failed)}/{total} ✓" + (f" — BUZILGAN: {failed}" if failed else ""))
    w("")

    w("## 9. Xulosa chegaralari: zararsizlik, stresslar, seed tarqalishi\n")
    w("**Zararsizlik qanday topiladi.** Avvalgi \"Kerak / Taxmin\" oddiy nisbat edi: (sarflangan rag'bat + qolgan majburiyat) / "
      "juft nazoratdagi bitta aktivlashgan foydalanuvchi marjasi. U har qo'shimcha foydalanuvchi birinchi kundan o'rtacha marja "
      "beradi va xarajat chiziqli o'sadi deb faraz qiladi — budjet limiti (limitga yetgach yangi va'da yo'q), qualification "
      "yiqilishlari va kech kelganlar buni buzadi. Endi chegara **simulyatsiya to'rida** topiladi: `incremental_new_per_day` "
      f"taxmini {', '.join(str(g) for g in results['breakeven_grid_pct'])} % ga ko'paytiriladi, har nuqta o'z juft nazoratiga "
      "solishtiriladi; chegara — stress farq ≥ 0 bo'lgan birinchi nuqta, \"barqaror\" — undan yuqori barcha nuqtalar ham ≥ 0.\n")
    w("**Stresslar:** \"alohida\" jadvalda har taxmin **yolg'iz** qo'llanadi. Bir nechta alohida stressdan o'tish ularning "
      f"birgalikdagi holatidan o'tish emas — shuning uchun ikki qo'shma qator bor: {', '.join(COMBINED_STRESS)} **birga**, "
      "va xuddi shu to'plam qo'shimcha foydalanuvchisiz.\n")
    w("**Seed tarqalishi** — model ichidagi tasodif (bir xil taxminlar, boshqa seed). Bu haqiqiy bozor ishonch oralig'i "
      "**emas**.\n")
    for name, a in results["analysis"].items():
        s = S[name]
        scope = "pochta qamrovi" if a["service"] == "parcel" else "jami"
        w(f"### {s['title']} (`{name}`, {scope})\n")
        be = a["breakeven"]
        w(f"- Nisbat bilan baho: kerak {be['ratio_need_users'] if be['ratio_need_users'] is not None else '—'} qo'shimcha "
          f"aktivlashgan, taxminda {be['ratio_have_users']} → taxminning ~{be['ratio_estimate_pct'] if be['ratio_estimate_pct'] is not None else '—'} % i.")
        if be["threshold_pct"] is None:
            w("- Simulyatsiya to'ri: **150 % gacha zararsizlik chegarasi topilmadi** (stress farq hamma nuqtada manfiy).")
        else:
            below = be["below"]
            w(f"- Simulyatsiya to'ri: chegara **{be['threshold_pct']} %** ({'barqaror' if be['stable_above'] else 'barqaror emas — yuqorida yana manfiy nuqta bor'}); "
              f"oldidagi nuqta {below['factor_pct'] if below else '—'} % → stress farq {fmt(below['stress_diff']) if below else '—'}, "
              f"chegarada → {fmt(be['at']['stress_diff'])}.")
        w("\n| Qo'shimcha foydalanuvchi taxmini | Marja farqi | Stress farq | Qo'shimcha aktivlashgan | Rad (budjet) |")
        w("|---|---|---|---|---|")
        for r in be["rows"]:
            w(f"| {r['factor_pct']} % | {fmt(r['margin_diff'])} | {fmt(r['stress_diff'])} | {r['incremental_activated']} | {r['budget_blocked']} |")
        w("\n| Taxmin o'zgarishi (ALOHIDA) | Marja farqi | Stress farq | Tengliklar |")
        w("|---|---|---|---|")
        breaks = []
        for pert, r in a["sensitivity"]["single"].items():
            if r["stress_diff"] < 0:
                breaks.append(PERTURBATIONS[pert])
            w(f"| {PERTURBATIONS[pert]} | {fmt(r['margin_diff'])} | {fmt(r['stress_diff'])} | {'✓' if r['checks_ok'] else 'BUZILGAN'} |")
        for key, r in a["sensitivity"]["joint"].items():
            if r["stress_diff"] < 0:
                breaks.append("BIRGA: " + " + ".join(r["applied"]))
            w(f"| **BIRGA:** {' + '.join(r['applied'])} | {fmt(r['margin_diff'])} | {fmt(r['stress_diff'])} | {'✓' if r['checks_ok'] else 'BUZILGAN'} |")
        if "seeds" in a:
            sp = a["seeds"]
            st, mg = sp["stress_diff"], sp["margin_diff"]
            w(f"\n- Seed tarqalishi ({sp['n']} seed, {sp['seeds'][0]}–{sp['seeds'][-1]}): stress farq min {fmt(st['min'])}, p10 "
              f"{fmt(st['p10'])}, mediana {fmt(st['median'])}, p90 {fmt(st['p90'])}, max {fmt(st['max'])}; manfiy — "
              f"{st['negative']}/{sp['n']}. Marja farqi mediana {fmt(mg['median'])} (min {fmt(mg['min'])}, max {fmt(mg['max'])}).")
        w("\n**Nimada ishlamay qoladi:** " + ("; ".join(breaks) if breaks else "sinalgan holatlarning hech birida stress farq manfiy emas") + ".\n")

    w("## 10. Variantlar bo'yicha qaror holati (foydalanuvchi, 24.09.2026)\n")
    w("- **A** — kelajakdagi yo'lovchi pilotini baholash uchun asosiy nomzod; summalar va 600 000 so'm budjet production uchun "
      "**tasdiqlanmagan**; yo'lovchi xizmatining huquqiy/texnik gate'lari (K7/Q5/Q89, Q48) saqlanadi.")
    w("- **B** — hozirgi ko'rinishida tasdiqlanmaydi; pochta qismi §6 da alohida.")
    w("- **C** — keyingi baholashga qoldirilgan.")
    w("- **Pochta bonusi (G20, 24.09.2026):** hozircha yoqilmaydi — **vaqtinchalik mahsulot qarori**, chunki haqiqiy qayta "
      "buyurtma va bonusdan foydalanish ma'lumotlari hali yo'q. §6 dagi ~9 % — **model natijasi**, pochta bonusining foydasizligi "
      "isboti emas. Mexanizm kodda saqlanadi, pochta kampaniyasi o'chiq.")
    w("- Bu qarorlar kampaniyani yoqish yoki mablag' ajratish ruxsati emas; mukofot, O, M, cap, muddat va budjet manbai "
      "haqiqiy pilot qarori bilan belgilanadi.\n")

    w("## 11. Simulyator tasdiqlamaydigan qarorlar\n")
    w("- **Q108 HMAC saqlash muddati** — huquqiy qaror; moliyaviy model bilan tanlanmaydi.")
    w("- **Rate-limit va review SLA** — trafik, bloklanish ehtimoli va operator ish hajmi bo'yicha alohida baho kerak.")
    w("- **48 soatlik risk oynasi** asosiy modelda o'zgarmagan; o'zgartiruvchi tajriba yo'q.")
    w("- Mukofot, budjet, O, M, cap'lar, muddatlar — **hammasi sintetik**.")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
