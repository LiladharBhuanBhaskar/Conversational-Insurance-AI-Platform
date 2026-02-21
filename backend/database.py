"""Database configuration and CSV seeding utilities for the insurance AI platform."""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from passlib.context import CryptContext
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "insurance.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH.as_posix()}")

engine_kwargs = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Imported lazily to avoid circular imports.
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def _parse_date(value: str):
    if not value:
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hash_if_needed(raw_password: str) -> str:
    if not raw_password:
        return pwd_context.hash("ChangeMe123!")
    raw_password = raw_password.strip()
    if raw_password.startswith("$2"):
        return raw_password
    return pwd_context.hash(raw_password)


def _iter_csv_rows(csv_path: Path):
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [
                (field_name or "").replace("\ufeff", "").strip()
                for field_name in reader.fieldnames
            ]

        for row in reader:
            normalized = {}
            for key, value in row.items():
                clean_key = (key or "").replace("\ufeff", "").strip()
                if isinstance(value, str):
                    normalized[clean_key] = value.strip()
                else:
                    normalized[clean_key] = value
            yield normalized


def seed_data_from_csv(data_dir: Path | None = None) -> None:
    from backend.models import CoverageDetail, Policy, User

    seed_dir = data_dir or (BASE_DIR / "data")
    users_file = seed_dir / "users.csv"
    policies_file = seed_dir / "policies.csv"
    coverage_file = seed_dir / "coverage_details.csv"

    if not users_file.exists() or not policies_file.exists() or not coverage_file.exists():
        return

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            for row in _iter_csv_rows(users_file):
                if not row.get("email"):
                    continue
                user = User(
                    user_id=int(row["user_id"]) if row.get("user_id") else None,
                    name=(row.get("name") or "Unknown User").strip(),
                    email=row["email"].strip().lower(),
                    password=_hash_if_needed(row.get("password", "")),
                )
                db.add(user)
            db.commit()

        if db.query(Policy).count() == 0:
            for row in _iter_csv_rows(policies_file):
                if not row.get("policy_number") or not row.get("user_id"):
                    continue
                policy = Policy(
                    policy_number=row["policy_number"].strip().upper(),
                    user_id=int(row["user_id"]),
                    insurance_type=(row.get("insurance_type") or "health").strip().lower(),
                    coverage_limit=_safe_float(row.get("coverage_limit")),
                    premium=_safe_float(row.get("premium")),
                    status=(row.get("status") or "active").strip().lower(),
                    start_date=_parse_date(row.get("start_date", "")),
                    end_date=_parse_date(row.get("end_date", "")),
                )
                db.add(policy)
            db.commit()

        if db.query(CoverageDetail).count() == 0:
            for row in _iter_csv_rows(coverage_file):
                if not row.get("policy_number"):
                    continue
                detail = CoverageDetail(
                    policy_number=row["policy_number"].strip().upper(),
                    coverage_items=(row.get("coverage_items") or "").strip(),
                    exclusions=(row.get("exclusions") or "").strip(),
                    deductible=_safe_float(row.get("deductible")),
                )
                db.add(detail)
            db.commit()
    finally:
        db.close()


def bootstrap_database(load_seed_data: bool = True) -> None:
    init_db()
    if load_seed_data:
        seed_data_from_csv()


if __name__ == "__main__":
    bootstrap_database(load_seed_data=True)
    print("Database initialized and sample data seeded.")
