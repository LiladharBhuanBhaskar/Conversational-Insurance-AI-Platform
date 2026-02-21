"""Product catalog, add-on packs, and policy purchase operations."""

from __future__ import annotations

import secrets
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.models import AddonPack, CoverageDetail, InsuranceProduct, Policy, PolicyAddon
from backend.policy_service import serialize_policy

DEFAULT_PRODUCTS = [
    {
        "product_code": "HLT_CORE",
        "name": "Health Core",
        "insurance_type": "health",
        "coverage_limit": 500000.0,
        "premium": 12000.0,
        "tenure_months": 12,
        "description": "Comprehensive hospitalization and daycare cover for individuals.",
    },
    {
        "product_code": "HLT_FAMILY_PLUS",
        "name": "Health Family Plus",
        "insurance_type": "health",
        "coverage_limit": 1000000.0,
        "premium": 24000.0,
        "tenure_months": 12,
        "description": "Family floater plan with maternity and diagnostics benefits.",
    },
    {
        "product_code": "VEH_SMART_DRIVE",
        "name": "Vehicle Smart Drive",
        "insurance_type": "vehicle",
        "coverage_limit": 300000.0,
        "premium": 18000.0,
        "tenure_months": 12,
        "description": "Own damage and third-party liability with personal accident cover.",
    },
    {
        "product_code": "VEH_MAX_GUARD",
        "name": "Vehicle Max Guard",
        "insurance_type": "vehicle",
        "coverage_limit": 600000.0,
        "premium": 29000.0,
        "tenure_months": 12,
        "description": "Premium vehicle protection with wider claim assistance services.",
    },
    {
        "product_code": "LIF_GUARD_TERM",
        "name": "Life Guard Term",
        "insurance_type": "life",
        "coverage_limit": 1500000.0,
        "premium": 26000.0,
        "tenure_months": 12,
        "description": "Affordable life protection with annual renewal flexibility.",
    },
    {
        "product_code": "LIF_WEALTH_SHIELD",
        "name": "Life Wealth Shield",
        "insurance_type": "life",
        "coverage_limit": 2500000.0,
        "premium": 41000.0,
        "tenure_months": 12,
        "description": "Higher sum insured for long-term life and family security.",
    },
]

DEFAULT_ADDONS = [
    {
        "addon_code": "ADD_HEALTH_DENTAL",
        "name": "Dental Care Pack",
        "insurance_type": "health",
        "addon_premium": 1800.0,
        "coverage_boost": 50000.0,
        "description": "Extends coverage for consultations, cleaning, and selected procedures.",
    },
    {
        "addon_code": "ADD_HEALTH_CRITICAL",
        "name": "Critical Illness Pack",
        "insurance_type": "health",
        "addon_premium": 3600.0,
        "coverage_boost": 150000.0,
        "description": "Lump-sum support for listed major illnesses and prolonged treatment.",
    },
    {
        "addon_code": "ADD_VEH_ROADSIDE",
        "name": "Roadside Assistance",
        "insurance_type": "vehicle",
        "addon_premium": 1200.0,
        "coverage_boost": 0.0,
        "description": "24x7 towing, breakdown support, and emergency on-road help.",
    },
    {
        "addon_code": "ADD_VEH_ENGINE_PROTECT",
        "name": "Engine Protect Pack",
        "insurance_type": "vehicle",
        "addon_premium": 2200.0,
        "coverage_boost": 50000.0,
        "description": "Covers engine and gearbox repair costs due to water ingress damage.",
    },
    {
        "addon_code": "ADD_LIFE_ACCIDENT_RIDER",
        "name": "Accidental Death Rider",
        "insurance_type": "life",
        "addon_premium": 2600.0,
        "coverage_boost": 250000.0,
        "description": "Additional payout if death occurs due to covered accident.",
    },
    {
        "addon_code": "ADD_LIFE_WAIVER_PREMIUM",
        "name": "Waiver of Premium",
        "insurance_type": "life",
        "addon_premium": 2100.0,
        "coverage_boost": 0.0,
        "description": "Future premiums waived in qualifying disability scenarios.",
    },
]


def ensure_default_catalog(db: Session) -> None:
    if db.query(InsuranceProduct).count() == 0:
        for item in DEFAULT_PRODUCTS:
            db.add(InsuranceProduct(**item, is_active=True))

    if db.query(AddonPack).count() == 0:
        for item in DEFAULT_ADDONS:
            db.add(AddonPack(**item, is_active=True))

    db.commit()


def list_products(db: Session) -> list[dict]:
    products = (
        db.query(InsuranceProduct)
        .filter(InsuranceProduct.is_active.is_(True))
        .order_by(InsuranceProduct.insurance_type.asc(), InsuranceProduct.premium.asc())
        .all()
    )
    addons = (
        db.query(AddonPack)
        .filter(AddonPack.is_active.is_(True))
        .order_by(AddonPack.insurance_type.asc(), AddonPack.addon_premium.asc())
        .all()
    )

    addons_by_type: dict[str, list[dict]] = {}
    for addon in addons:
        addons_by_type.setdefault(addon.insurance_type, []).append(
            {
                "addon_code": addon.addon_code,
                "name": addon.name,
                "addon_premium": addon.addon_premium,
                "coverage_boost": addon.coverage_boost,
                "description": addon.description,
            }
        )

    response = []
    for product in products:
        response.append(
            {
                "product_code": product.product_code,
                "name": product.name,
                "insurance_type": product.insurance_type,
                "coverage_limit": product.coverage_limit,
                "premium": product.premium,
                "tenure_months": product.tenure_months,
                "description": product.description,
                "addons": addons_by_type.get(product.insurance_type, []),
            }
        )
    return response


def get_recommended_addons(db: Session, insurance_type: str, top_k: int = 3) -> list[dict]:
    rows = (
        db.query(AddonPack)
        .filter(
            AddonPack.is_active.is_(True),
            AddonPack.insurance_type == insurance_type.lower().strip(),
        )
        .order_by(AddonPack.addon_premium.asc())
        .limit(top_k)
        .all()
    )

    return [
        {
            "addon_code": row.addon_code,
            "name": row.name,
            "description": row.description,
            "addon_premium": row.addon_premium,
            "coverage_boost": row.coverage_boost,
        }
        for row in rows
    ]


def _policy_prefix(insurance_type: str) -> str:
    mapping = {
        "health": "HLT",
        "vehicle": "VEH",
        "life": "LIF",
    }
    return mapping.get((insurance_type or "").lower(), "POL")


def _generate_policy_number(db: Session, insurance_type: str) -> str:
    prefix = _policy_prefix(insurance_type)
    for _ in range(100):
        candidate = f"{prefix}{100000 + secrets.randbelow(900000)}"
        exists = db.query(Policy).filter(Policy.policy_number == candidate).first()
        if not exists:
            return candidate
    raise ValueError("Unable to generate a unique policy number")


def _default_coverage_template(insurance_type: str) -> tuple[str, str, float]:
    insurance_type = (insurance_type or "").lower().strip()
    if insurance_type == "health":
        return (
            "Hospitalization; ICU; Diagnostics; Daycare procedures",
            "Cosmetic and experimental procedures",
            5000.0,
        )
    if insurance_type == "vehicle":
        return (
            "Own damage; Third-party liability; Personal accident",
            "Drunk driving; Illegal modifications",
            2000.0,
        )
    if insurance_type == "life":
        return (
            "Natural death; Accidental death support",
            "Fraud declaration; Suicide waiting period",
            0.0,
        )
    return ("Core insurance coverage", "Policy-specific exclusions", 0.0)


def buy_policy(
    db: Session,
    user_id: int,
    product_code: str,
    addon_codes: list[str] | None = None,
) -> dict:
    product = (
        db.query(InsuranceProduct)
        .filter(
            InsuranceProduct.product_code == product_code.upper().strip(),
            InsuranceProduct.is_active.is_(True),
        )
        .first()
    )
    if not product:
        raise ValueError("Invalid product code")

    requested_codes = [code.upper().strip() for code in (addon_codes or []) if code]
    selected_addons: list[AddonPack] = []
    if requested_codes:
        selected_addons = (
            db.query(AddonPack)
            .filter(
                AddonPack.addon_code.in_(requested_codes),
                AddonPack.insurance_type == product.insurance_type,
                AddonPack.is_active.is_(True),
            )
            .all()
        )

        selected_codes = {item.addon_code for item in selected_addons}
        missing = [code for code in requested_codes if code not in selected_codes]
        if missing:
            raise ValueError(f"Invalid add-on code(s): {', '.join(missing)}")

    coverage_boost = sum(item.coverage_boost for item in selected_addons)
    addon_premium_total = sum(item.addon_premium for item in selected_addons)

    start_date = date.today()
    end_date = start_date + timedelta(days=30 * max(1, product.tenure_months))

    policy_number = _generate_policy_number(db, product.insurance_type)
    policy = Policy(
        policy_number=policy_number,
        user_id=user_id,
        insurance_type=product.insurance_type,
        coverage_limit=product.coverage_limit + coverage_boost,
        premium=product.premium + addon_premium_total,
        status="active",
        start_date=start_date,
        end_date=end_date,
    )
    db.add(policy)

    coverage_items, exclusions, deductible = _default_coverage_template(product.insurance_type)
    if selected_addons:
        coverage_items = f"{coverage_items}; Add-ons: {', '.join(item.name for item in selected_addons)}"

    coverage_detail = CoverageDetail(
        policy_number=policy_number,
        coverage_items=coverage_items,
        exclusions=exclusions,
        deductible=deductible,
    )
    db.add(coverage_detail)

    for addon in selected_addons:
        db.add(
            PolicyAddon(
                policy_number=policy_number,
                addon_id=addon.addon_id,
                addon_premium=addon.addon_premium,
            )
        )

    db.commit()
    db.refresh(policy)

    created = (
        db.query(Policy)
        .filter(Policy.policy_number == policy_number)
        .first()
    )
    return serialize_policy(created)
