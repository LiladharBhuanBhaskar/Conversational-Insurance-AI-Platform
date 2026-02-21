"""Conversational orchestration for policy-aware insurance responses."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import requests
from sqlalchemy.orm import Session

try:
    from groq import Groq
except Exception:
    Groq = None

from backend.models import User
from backend.policy_service import (
    format_policy_for_prompt,
    get_policy,
    get_user_active_policies,
    get_user_policies,
    is_policy_expired,
    serialize_policy,
)
from backend.product_service import buy_policy, get_recommended_addons, list_products
from backend.rag.rag_engine import RAGEngine

logger = logging.getLogger(__name__)

NO_POLICY_PATTERNS = [
    r"\bno policy\b",
    r"\bdon'?t have (a )?policy\b",
    r"\bhaven'?t (got )?(a )?policy\b",
    r"\bneed (a )?new policy\b",
    r"\bbook (a )?policy\b",
]

PLAN_DISCOVERY_PATTERNS = [
    r"\b(show|list|view).*(plans|products|policies)\b",
    r"\bavailable (plans|products|insurance)\b",
    r"\b(plan|product) options\b",
]

PURCHASE_PATTERNS = [
    r"\bbuy\b",
    r"\bpurchase\b",
    r"\bbook\b",
    r"\bget me\b",
]

ADDON_PATTERNS = [
    r"\badd[- ]?ons?\b",
    r"\briders?\b",
    r"\bupgrade\b",
    r"\bextra cover\b",
]


@dataclass
class ChatResult:
    response: str
    policy_number: str | None = None
    requires_policy: bool = False
    booking_intent: bool = False


class LLMClient:
    def __init__(self) -> None:
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")
        self.groq_client = None

        if Groq and self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception as exc:
                logger.warning("Failed to initialize Groq client: %s", exc)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.groq_client is not None:
            try:
                completion = self.groq_client.chat.completions.create(
                    model=self.groq_model,
                    temperature=0.2,
                    max_tokens=700,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                content = (completion.choices[0].message.content or "").strip()
                if content:
                    return content
            except Exception as exc:
                logger.warning("Groq generation failed: %s", exc)

        # Optional Ollama fallback.
        try:
            payload = {
                "model": self.ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
            }
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=60,
            )
            if response.ok:
                body = response.json()
                content = (body.get("response") or "").strip()
                if content:
                    return content
        except Exception as exc:
            logger.warning("Ollama fallback failed: %s", exc)

        return (
            "I can access your policy and knowledge context, but no LLM is currently available. "
            "Set GROQ_API_KEY (recommended) or start Ollama to generate full answers."
        )


class InsuranceChatEngine:
    def __init__(self, rag_engine: RAGEngine):
        self.rag_engine = rag_engine
        self.llm = LLMClient()

    def _is_booking_intent(self, message: str) -> bool:
        lowered = message.lower()
        return any(re.search(pattern, lowered) for pattern in NO_POLICY_PATTERNS)

    def _is_plan_discovery(self, message: str) -> bool:
        lowered = message.lower()
        return any(re.search(pattern, lowered) for pattern in PLAN_DISCOVERY_PATTERNS)

    def _is_purchase_intent(self, message: str) -> bool:
        lowered = message.lower()
        return any(re.search(pattern, lowered) for pattern in PURCHASE_PATTERNS)

    def _is_addon_query(self, message: str) -> bool:
        lowered = message.lower()
        return any(re.search(pattern, lowered) for pattern in ADDON_PATTERNS)

    def _extract_policy_from_message(self, message: str) -> str | None:
        match = re.search(r"\b[A-Za-z]{2,6}[0-9]{3,12}\b", message)
        if match:
            return match.group(0).upper()
        return None

    def _system_prompt(self) -> str:
        return (
            "You are InsureAssist, a specialized insurance AI assistant.\n"
            "Rules:\n"
            "1) You must ground policy-specific answers ONLY on POLICY_DATA.\n"
            "2) Never fabricate policy numbers, coverage limits, premiums, dates, exclusions, or claim outcomes.\n"
            "3) Use RAG_CONTEXT only for general insurance explanations and guidance.\n"
            "4) If information is missing, explicitly say it is unavailable and ask for the exact required detail.\n"
            "5) Keep tone professional, concise, and customer-friendly.\n"
            "6) If policy is expired, explain that renewal is needed before fresh claims can be processed."
        )

    def _build_user_prompt(self, user_message: str, policy_context: str, rag_chunks: list[str]) -> str:
        rag_context = "\n\n".join(rag_chunks) if rag_chunks else "No additional knowledge context found."
        return (
            f"USER_QUERY:\n{user_message}\n\n"
            f"POLICY_DATA:\n{policy_context}\n\n"
            f"RAG_CONTEXT (top 3 chunks):\n{rag_context}\n\n"
            "Generate an accurate response grounded in the above data."
        )

    def _format_products_for_chat(self, products: list[dict]) -> str:
        if not products:
            return "No plans are available right now."

        lines = ["Available insurance plans:"]
        for product in products:
            lines.append(
                f"- {product['product_code']} | {product['name']} | "
                f"Type: {product['insurance_type'].title()} | "
                f"Coverage: {product['coverage_limit']} | Premium: {product['premium']}"
            )
            addons = product.get("addons", [])
            if addons:
                addon_codes = ", ".join(item["addon_code"] for item in addons)
                lines.append(f"  Add-ons: {addon_codes}")

        lines.append(
            "To buy via chat, type: buy <PRODUCT_CODE> with <ADDON_CODE_1>,<ADDON_CODE_2>"
        )
        return "\n".join(lines)

    def _extract_catalog_codes(self, message: str, products: list[dict]) -> tuple[str | None, list[str]]:
        upper = message.upper()
        product_code = None
        addon_codes: list[str] = []

        for product in products:
            code = product["product_code"].upper()
            if code in upper:
                product_code = code

            for addon in product.get("addons", []):
                addon_code = addon["addon_code"].upper()
                if addon_code in upper and addon_code not in addon_codes:
                    addon_codes.append(addon_code)

        return product_code, addon_codes

    def respond(
        self,
        db: Session,
        message: str,
        user: User | None = None,
        policy_number: str | None = None,
    ) -> ChatResult:
        user_message = (message or "").strip()
        if not user_message:
            return ChatResult(response="Please type your question so I can help.")

        catalog = list_products(db)
        explicit_booking = self._is_booking_intent(user_message)
        plan_discovery = self._is_plan_discovery(user_message)
        purchase_intent = self._is_purchase_intent(user_message)

        if plan_discovery or explicit_booking:
            catalog_text = self._format_products_for_chat(catalog)
            return ChatResult(
                response=(
                    "I can help you buy a new policy.\n"
                    f"{catalog_text}"
                ),
                booking_intent=True,
            )

        if purchase_intent:
            product_code, addon_codes = self._extract_catalog_codes(user_message, catalog)
            if not product_code:
                return ChatResult(
                    response=(
                        "I detected purchase intent but couldn't find a valid product code in your message.\n"
                        f"{self._format_products_for_chat(catalog)}"
                    ),
                    booking_intent=True,
                )

            if not user:
                return ChatResult(
                    response="Please login first to buy a new policy.",
                    booking_intent=True,
                )

            try:
                purchased = buy_policy(
                    db=db,
                    user_id=user.user_id,
                    product_code=product_code,
                    addon_codes=addon_codes,
                )
            except ValueError as exc:
                return ChatResult(
                    response=f"Purchase failed: {exc}",
                    booking_intent=True,
                )

            addon_names = ", ".join(item["name"] for item in purchased.get("addons", []))
            addon_info = f" Add-ons applied: {addon_names}." if addon_names else ""
            return ChatResult(
                response=(
                    f"Policy purchase successful. Your new policy number is {purchased['policy_number']} "
                    f"for {purchased['insurance_type'].title()} insurance.{addon_info}"
                ),
                policy_number=purchased["policy_number"],
                booking_intent=True,
            )

        candidate_policy_number = (policy_number or "").strip().upper() if policy_number else None
        if not candidate_policy_number:
            candidate_policy_number = self._extract_policy_from_message(user_message)

        if not candidate_policy_number:
            if user:
                active_policies = get_user_active_policies(db, user.user_id)
                if len(active_policies) == 1:
                    candidate_policy_number = active_policies[0].policy_number
                elif len(active_policies) > 1:
                    insurance_types = ", ".join(
                        sorted({item.insurance_type.title() for item in active_policies})
                    )
                    options = ", ".join(item.policy_number for item in active_policies)
                    return ChatResult(
                        response=(
                            f"You have multiple active policies ({insurance_types}). "
                            f"Which one do you want details about? Share policy number: {options}"
                        ),
                        requires_policy=True,
                    )
                else:
                    total_policies = get_user_policies(db, user.user_id)
                    if total_policies:
                        return ChatResult(
                            response=(
                                "You currently have no active policy. You can renew an existing one "
                                "or buy a new plan. Say 'show available plans'."
                            ),
                            requires_policy=True,
                            booking_intent=True,
                        )

            if not candidate_policy_number:
                return ChatResult(
                    response=(
                        "Please provide your policy number to continue. "
                        "If you do not have one, say 'show available plans' to book policy."
                    ),
                    requires_policy=True,
                )

        policy = get_policy(db, candidate_policy_number)
        if not policy:
            return ChatResult(
                response=(
                    f"I could not find policy number {candidate_policy_number}. "
                    "Please verify the number or say 'show available plans'."
                ),
                requires_policy=True,
                policy_number=candidate_policy_number,
            )

        if user and policy.user_id != user.user_id:
            return ChatResult(
                response="This policy number is not linked to your account. Please provide your own policy number.",
                requires_policy=True,
            )

        policy_dict = serialize_policy(policy)
        policy_context = format_policy_for_prompt(policy_dict)

        if self._is_addon_query(user_message):
            recommendations = get_recommended_addons(db, policy.insurance_type, top_k=3)
            if recommendations:
                rec_text = "\n".join(
                    f"- {item['addon_code']} | {item['name']} | Premium: {item['addon_premium']} | {item['description']}"
                    for item in recommendations
                )
                return ChatResult(
                    response=(
                        f"Recommended add-on packs for your {policy.insurance_type.title()} policy:\n"
                        f"{rec_text}\n"
                        "To buy a new policy with add-ons, say: buy <PRODUCT_CODE> with <ADDON_CODE>."
                    ),
                    policy_number=policy.policy_number,
                )

        try:
            rag_chunks = self.rag_engine.retrieve(query=user_message, top_k=3)
        except Exception as exc:
            logger.warning("RAG retrieval failed: %s", exc)
            rag_chunks = []

        user_prompt = self._build_user_prompt(user_message, policy_context, rag_chunks)
        answer = self.llm.generate(self._system_prompt(), user_prompt)

        if is_policy_expired(policy) and policy.end_date and "expired" not in answer.lower():
            answer = (
                f"{answer}\n\nNote: policy {policy.policy_number} expired on "
                f"{policy.end_date.isoformat()}. Renewal is required before new claims can be processed."
            )

        return ChatResult(
            response=answer,
            policy_number=policy.policy_number,
            requires_policy=False,
        )
