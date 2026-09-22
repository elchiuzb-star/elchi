"""Load the §5.2 prohibited-items list into the database as a **draft** policy version.

The *content* of the list was approved by the product owner on 17.09.2026
(``docs/ops/PARCEL_PROHIBITED_ITEMS_DRAFT.md``). That approval is not the same as activation:

* the version is created with status ``draft`` - nothing is shown to users and no rule is enforced;
* activation in production needs ``POST /api/v2/admin/parcel-policies/{id}/confirm`` by **another**
  super_admin, over an authenticated, audited request. This script will not do that for you;
* ``--confirm-as-user-id`` exists for development and staging only and refuses to run when the database is
  marked production, so the two-person control is never reduced to one person running one command.

Every ``prohibited`` row carries its legal basis, its source and the date that source was checked - the database
refuses the row otherwise (CHECK ``ck_parcel_policy_items_basis``).

Usage::

    ELCHI_DATABASE_URL=postgresql+psycopg://... py scripts/seed_parcel_policy_draft.py \
        --actor-user-id 1 --label pilot-2026-09
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SOURCE_CHECKED_ON = date(2026, 9, 17)
SOURCE_LAW_POSTAL = "Pochta aloqasi to'g'risida (O'RQ-777, 09.06.2022); Qoidalar 2219-son 18.04.2011, 3-ilova"
SOURCE_DANGEROUS = "Xavfli yuklarni avtomobil transportida tashish qoidalari (VM 35-son, 16.02.2011)"
SOURCE_WEAPONS = "Qurol to'g'risida (O'RQ-550, 29.07.2019)"
SOURCE_DRUGS = "Giyohvandlik vositalari va psixotrop moddalar to'g'risidagi qonunchilik"
SOURCE_BUSINESS = "Elchi pilot siyosati (huquqiy taqiq emas)"


@dataclass(frozen=True, slots=True)
class DraftItem:
    code: str
    category: str
    applies_to: str
    title_uz: str
    description_uz: str
    legal_basis: str | None
    source_ref: str | None
    source_checked_on: date | None
    display_order: int | None = None


# Mirrors docs/ops/PARCEL_PROHIBITED_ITEMS_DRAFT.md §3. Edit the document and this list together.
DRAFT_ITEMS: tuple[DraftItem, ...] = (
    DraftItem("weapons_ammunition", "prohibited", "all", "Qurol va o'q-dorilar",
              "Har qanday o'qotar, pnevmatik va sovuq qurol, o'q-dori, elektroshoker.",
              "Qurol muomalasi qonun bilan tartibga solingan; maxsus ruxsatsiz tashish taqiqlanadi.",
              SOURCE_WEAPONS, SOURCE_CHECKED_ON, 10),
    DraftItem("explosives_pyrotechnics", "prohibited", "all", "Portlovchi moddalar va pirotexnika",
              "Portlovchi moddalar, portlatish qurilmalari, mushakbozlik va pirotexnika mahsulotlari.",
              "Portlovchi moddalar xavfli yuk hisoblanadi; maxsus ruxsat va jihoz talab qilinadi.",
              SOURCE_DANGEROUS, SOURCE_CHECKED_ON, 20),
    DraftItem("narcotics_psychotropic", "prohibited", "all", "Giyohvandlik vositalari va psixotrop moddalar",
              "Nazorat ostidagi moddalar, ularning analoglari va prekursorlari.",
              "Nazorat ostidagi moddalar muomalasi qonun bilan taqiqlangan.",
              SOURCE_DRUGS, SOURCE_CHECKED_ON, 30),
    DraftItem("radioactive_toxic", "prohibited", "all", "Radioaktiv va zaharli moddalar",
              "Radioaktiv, zaharli va kuchli ta'sir qiluvchi kimyoviy moddalar.",
              "Xavfli yuk sinflari; maxsus tashish rejimi va ruxsatnoma talab qilinadi.",
              SOURCE_DANGEROUS, SOURCE_CHECKED_ON, 40),
    DraftItem("flammable_gas_fuel", "prohibited", "all", "Yonuvchi suyuqlik va gaz",
              "Benzin, dizel, gaz balloni, aerozol va o't oldiruvchi materiallar.",
              "Yonuvchi materiallar xavfli yuk; yengil avtomobilda oddiy tartibda tashilmaydi.",
              SOURCE_DANGEROUS, SOURCE_CHECKED_ON, 50),
    DraftItem("human_remains_biological", "prohibited", "all", "Biologik materiallar va tibbiy chiqindi",
              "Inson qoldiqlari, biologik namunalar, tibbiy chiqindi.",
              "Maxsus tartib, qadoq va ruxsat talab qilinadi.",
              SOURCE_LAW_POSTAL, SOURCE_CHECKED_ON, 60),
    DraftItem("live_animals", "restricted", "all", "Tirik hayvonlar",
              "Tirik hayvon va qushlar pilotda qabul qilinmaydi.",
              "Veterinariya hujjati va maxsus shart talab qilinadi.", SOURCE_LAW_POSTAL, SOURCE_CHECKED_ON, 70),
    DraftItem("alcohol_tobacco_excise", "restricted", "parcel", "Aksiz osti tovarlari",
              "Alkogol va tamaki mahsulotlari pilotda qabul qilinmaydi.",
              "Aksiz markasi va savdo qoidalari talab qilinadi (yurist tekshiruvi kerak).",
              SOURCE_LAW_POSTAL, SOURCE_CHECKED_ON, 80),
    DraftItem("medicines_prescription", "restricted", "parcel", "Retseptli dori vositalari",
              "Retsept bo'yicha beriladigan dorilar pilotda qabul qilinmaydi.",
              "Dori vositalari muomalasi litsenziyalangan faoliyat (yurist tekshiruvi kerak).",
              SOURCE_LAW_POSTAL, SOURCE_CHECKED_ON, 90),
    DraftItem("documents_originals_critical", "restricted", "parcel", "Asl hujjatlar",
              "Pasport, diplom va boshqa tiklab bo'lmaydigan asl hujjatlar.",
              "Yo'qolganda tiklash imkoni yo'q; pilotda qabul qilinmaydi.", SOURCE_BUSINESS, SOURCE_CHECKED_ON, 100),
    DraftItem("cash_bearer_valuables", "business_declined", "all", "Naqd pul va qimmatbaho buyumlar",
              "Naqd pul, bank kartalari, qimmatbaho metall va toshlar, zargarlik buyumlari.",
              "Elchi bu jo'natmalarni sug'urtalamaydi; e'lon qilingan qiymat kafolat emas.",
              SOURCE_BUSINESS, SOURCE_CHECKED_ON, 110),
    DraftItem("perishable_unpackaged", "business_declined", "parcel", "Tez buziladigan mahsulot",
              "Sovutish talab qiladigan yoki tez buziladigan oziq-ovqat.",
              "Sovutish zanjiri yo'q; sifat kafolatlanmaydi.", SOURCE_BUSINESS, SOURCE_CHECKED_ON, 120),
    DraftItem("oversized_over_pilot_limit", "business_declined", "parcel", "Pilot chegarasidan katta yuk",
              "50 kg dan og'ir, 150 sm dan uzun yoki 0,5 m3 dan katta jo'natma.",
              "Haydovchi yolg'iz yuklay olmaydi; alohida transport kerak.", SOURCE_BUSINESS, SOURCE_CHECKED_ON, 130),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-user-id", type=int, required=True, help="super_admin drafting the policy")
    parser.add_argument("--label", required=True, help="policy label, e.g. pilot-2026-09")
    parser.add_argument("--dry-run", action="store_true", help="print what would be created and exit")
    parser.add_argument(
        "--confirm-as-user-id",
        type=int,
        default=None,
        help="dev/staging only: a SECOND super_admin id that activates the draft; refused on a production database",
    )
    args = parser.parse_args(argv)

    if args.confirm_as_user_id is not None and args.confirm_as_user_id == args.actor_user_id:
        parser.error("the author of a policy cannot confirm it - that is the whole point of the second pair of eyes")

    if args.dry_run:
        for item in DRAFT_ITEMS:
            print(f"{item.category:18} {item.applies_to:18} {item.code:28} {item.title_uz}")
        print(f"\n{len(DRAFT_ITEMS)} draft item(s). Nothing was written; this list is NOT approved.")
        return 0

    from app.db.session import SessionLocal
    from app.modules.marketplace import service as marketplace_service
    from app.modules.platform import service as platform_service

    with SessionLocal() as session:
        if args.confirm_as_user_id is not None and platform_service.is_production(session):
            print(
                "refusing: this database is marked production. Activate the policy through "
                "POST /api/v2/admin/parcel-policies/{id}/confirm as a second super_admin, so the approval is "
                "authenticated and audited.",
                file=sys.stderr,
            )
            return 2
        version = marketplace_service.create_parcel_policy_version(
            session,
            actor_user_id=args.actor_user_id,
            label=args.label,
            source_note=(
                "docs/ops/PARCEL_PROHIBITED_ITEMS_DRAFT.md, content approved by the product owner 17.09.2026 "
                f"(sources checked {SOURCE_CHECKED_ON.isoformat()}). An external legal review is still an open "
                "item; a second super_admin must confirm before it applies."
            ),
            items=DRAFT_ITEMS,
        )
        session.commit()
        public_id = marketplace_service.parcel_policy_public_id(version)
        print(f"draft policy created: {public_id} ({len(DRAFT_ITEMS)} items, status=draft)")
        if args.confirm_as_user_id is None:
            print("It applies to nobody until another super_admin confirms it.")
            return 0

        marketplace_service.confirm_parcel_policy_version(
            session,
            actor_user_id=args.confirm_as_user_id,
            policy_public_id=public_id,
            expected_version=version.version,
        )
        session.commit()
        print(f"confirmed by user {args.confirm_as_user_id}: {public_id} is now the active policy (non-production).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
