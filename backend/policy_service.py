"""Policy lookup and serialization helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, joinedload

from backend.models import Policy, PolicyAddon


def get_policy(db: Session, policy_number: str) -> Policy | None:
    return (
        db.query(Policy)
        .options(
            joinedload(Policy.coverage),
            joinedload(Policy.user),
            joinedload(Policy.policy_addons).joinedload(PolicyAddon.addon),
        )
        .filter(Policy.policy_number == policy_number.upper().strip())
        .first()
    )


def get_user_policies(db: Session, user_id: int) -> list[Policy]:
    return (
        db.query(Policy)
        .options(
            joinedload(Policy.coverage),
            joinedload(Policy.policy_addons).joinedload(PolicyAddon.addon),
        )
        .filter(Policy.user_id == user_id)
        .order_by(Policy.policy_number.asc())
        .all()
    )


def get_user_active_policies(db: Session, user_id: int) -> list[Policy]:
    policies = get_user_policies(db, user_id)
    return [policy for policy in policies if not is_policy_expired(policy)]


def is_policy_expired(policy: Policy) -> bool:
    if policy.end_date is None:
        return False
    return policy.end_date < date.today() or policy.status.lower() == "expired"


def serialize_policy(policy: Policy) -> dict:
    coverage = policy.coverage
    addons = []
    for link in policy.policy_addons or []:
        addon = link.addon
        if not addon:
            continue
        addons.append(
            {
                "addon_code": addon.addon_code,
                "name": addon.name,
                "description": addon.description,
                "addon_premium": link.addon_premium,
                "coverage_boost": addon.coverage_boost,
            }
        )

    return {
        "policy_number": policy.policy_number,
        "user_id": policy.user_id,
        "user_name": policy.user.name if policy.user else None,
        "insurance_type": policy.insurance_type,
        "coverage_limit": policy.coverage_limit,
        "premium": policy.premium,
        "status": "expired" if is_policy_expired(policy) else policy.status,
        "start_date": policy.start_date.isoformat() if policy.start_date else None,
        "end_date": policy.end_date.isoformat() if policy.end_date else None,
        "is_expired": is_policy_expired(policy),
        "coverage_details": {
            "coverage_items": coverage.coverage_items if coverage else "",
            "exclusions": coverage.exclusions if coverage else "",
            "deductible": coverage.deductible if coverage else 0.0,
        },
        "addons": addons,
    }


def format_policy_for_prompt(policy_dict: dict) -> str:
    coverage = policy_dict.get("coverage_details", {})
    addon_items = policy_dict.get("addons", [])
    addons_text = (
        "; ".join(f"{item.get('name')} ({item.get('addon_code')})" for item in addon_items)
        if addon_items
        else "None"
    )

    return (
        f"Policy Number: {policy_dict.get('policy_number')}\n"
        f"Insurance Type: {policy_dict.get('insurance_type')}\n"
        f"Coverage Limit: {policy_dict.get('coverage_limit')}\n"
        f"Premium: {policy_dict.get('premium')}\n"
        f"Status: {policy_dict.get('status')}\n"
        f"Policy Start Date: {policy_dict.get('start_date')}\n"
        f"Policy End Date: {policy_dict.get('end_date')}\n"
        f"Coverage Items: {coverage.get('coverage_items')}\n"
        f"Exclusions: {coverage.get('exclusions')}\n"
        f"Deductible: {coverage.get('deductible')}\n"
        f"Add-on Packs: {addons_text}"
    )
