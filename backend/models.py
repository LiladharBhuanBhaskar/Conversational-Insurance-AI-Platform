"""SQLAlchemy ORM models for users, policies, coverage, products, and add-ons."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)

    policies = relationship("Policy", back_populates="user", cascade="all, delete-orphan")


class Policy(Base):
    __tablename__ = "policies"

    policy_number = Column(String(50), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    insurance_type = Column(String(50), nullable=False)
    coverage_limit = Column(Float, nullable=False)
    premium = Column(Float, nullable=False)
    status = Column(String(30), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    user = relationship("User", back_populates="policies")
    coverage = relationship(
        "CoverageDetail",
        back_populates="policy",
        uselist=False,
        cascade="all, delete-orphan",
    )
    policy_addons = relationship(
        "PolicyAddon",
        back_populates="policy",
        cascade="all, delete-orphan",
    )


class CoverageDetail(Base):
    __tablename__ = "coverage"

    policy_number = Column(String(50), ForeignKey("policies.policy_number"), primary_key=True)
    coverage_items = Column(Text, nullable=False)
    exclusions = Column(Text, nullable=False)
    deductible = Column(Float, nullable=False)

    policy = relationship("Policy", back_populates="coverage")


class InsuranceProduct(Base):
    __tablename__ = "insurance_products"

    product_id = Column(Integer, primary_key=True, index=True)
    product_code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(140), nullable=False)
    insurance_type = Column(String(50), nullable=False, index=True)
    coverage_limit = Column(Float, nullable=False)
    premium = Column(Float, nullable=False)
    tenure_months = Column(Integer, nullable=False, default=12)
    description = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True)


class AddonPack(Base):
    __tablename__ = "addon_packs"

    addon_id = Column(Integer, primary_key=True, index=True)
    addon_code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(140), nullable=False)
    insurance_type = Column(String(50), nullable=False, index=True)
    addon_premium = Column(Float, nullable=False)
    coverage_boost = Column(Float, nullable=False, default=0.0)
    description = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True)

    policy_links = relationship("PolicyAddon", back_populates="addon")


class PolicyAddon(Base):
    __tablename__ = "policy_addons"
    __table_args__ = (
        UniqueConstraint("policy_number", "addon_id", name="uq_policy_addon"),
    )

    policy_addon_id = Column(Integer, primary_key=True, index=True)
    policy_number = Column(String(50), ForeignKey("policies.policy_number"), nullable=False, index=True)
    addon_id = Column(Integer, ForeignKey("addon_packs.addon_id"), nullable=False, index=True)
    addon_premium = Column(Float, nullable=False)
    added_on = Column(DateTime, default=datetime.utcnow, nullable=False)

    policy = relationship("Policy", back_populates="policy_addons")
    addon = relationship("AddonPack", back_populates="policy_links")
