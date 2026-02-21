"""FastAPI entrypoint for the Conversational Insurance AI Platform."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from backend.auth import (  # noqa: E402
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    hash_password,
    security,
    verify_password,
)
from backend.chat_engine import InsuranceChatEngine  # noqa: E402
from backend.database import SessionLocal, bootstrap_database, get_db  # noqa: E402
from backend.models import User  # noqa: E402
from backend.policy_service import get_policy, serialize_policy  # noqa: E402
from backend.product_service import buy_policy, ensure_default_catalog, list_products  # noqa: E402
from backend.rag.rag_engine import RAGEngine  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"

rag_engine = RAGEngine(DATA_DIR)
chat_engine = InsuranceChatEngine(rag_engine)

app = FastAPI(
    title="Conversational Insurance AI Platform",
    version="1.0.0",
    description="Policy-aware insurance chatbot with authentication + RAG",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignupRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChatRequest(BaseModel):
    message: str
    policy_number: str | None = None


class BuyPolicyRequest(BaseModel):
    product_code: str = Field(min_length=3, max_length=64)
    addon_codes: list[str] = Field(default_factory=list)


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=6, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


def _clear_redis_chat_history(user_id: int) -> bool:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return False

    try:
        import redis  # Imported lazily to keep Redis optional.
    except Exception as exc:
        logger.warning("Redis package unavailable for logout cache clear: %s", exc)
        return False

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.delete(f"chat:history:{user_id}")
        return True
    except Exception as exc:
        logger.warning("Failed to clear Redis chat history for user %s: %s", user_id, exc)
        return False


@app.on_event("startup")
def startup_event() -> None:
    try:
        bootstrap_database(load_seed_data=True)
    except Exception as exc:
        logger.exception("Database bootstrap failed: %s", exc)
        raise

    db = SessionLocal()
    try:
        ensure_default_catalog(db)
    except Exception as exc:
        logger.exception("Product catalog initialization failed: %s", exc)
        raise
    finally:
        db.close()

    try:
        rag_engine.initialize_from_faq()
    except Exception as exc:
        logger.exception("RAG initialization failed. Continuing with empty context: %s", exc)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/frontend/style.css", include_in_schema=False)
def frontend_css() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "style.css")


@app.get("/frontend/script.js", include_in_schema=False)
def frontend_js() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "script.js")


@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        name=payload.name.strip(),
        email=payload.email.lower().strip(),
        password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.user_id), "email": user.email})
    return {
        "message": "Signup successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {"user_id": user.user_id, "name": user.name, "email": user.email},
    }


@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"sub": str(user.user_id), "email": user.email})
    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {"user_id": user.user_id, "name": user.name, "email": user.email},
    }


@app.post("/logout")
def logout(user: User = Depends(get_current_user)):
    cache_cleared = _clear_redis_chat_history(user.user_id)
    return {
        "message": "Logout successful",
        "chat_history_cleared": cache_cleared,
    }


@app.get("/profile")
def get_profile(user: User = Depends(get_current_user)):
    return {
        "user": {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
        }
    }


@app.put("/profile")
def update_profile(
    payload: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_email = payload.email.lower().strip()
    existing = (
        db.query(User)
        .filter(User.email == normalized_email, User.user_id != user.user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user.name = payload.name.strip()
    user.email = normalized_email
    db.commit()
    db.refresh(user)

    return {
        "message": "Profile updated successfully",
        "user": {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
        },
    }


@app.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=400,
            detail="New password must be different from current password",
        )

    user.password = hash_password(payload.new_password)
    db.commit()

    return {"message": "Password changed successfully"}


@app.get("/products")
def products(db: Session = Depends(get_db)):
    return {
        "products": list_products(db),
    }





@app.post("/buy-policy")
def buy_policy_endpoint(
    payload: BuyPolicyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        created_policy = buy_policy(
            db=db,
            user_id=user.user_id,
            product_code=payload.product_code,
            addon_codes=payload.addon_codes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "message": "Policy purchased successfully",
        "policy": created_policy,
    }


@app.get("/policy/{policy_number}")
def fetch_policy(
    policy_number: str,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    user = get_current_user_optional(credentials, db)
    policy = get_policy(db, policy_number)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    if user and policy.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Policy does not belong to this user")

    return serialize_policy(policy)


@app.post("/chat")
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    user = get_current_user_optional(credentials, db)
    result = chat_engine.respond(
        db=db,
        message=payload.message,
        user=user,
        policy_number=payload.policy_number,
    )
    return {
        "response": result.response,
        "policy_number": result.policy_number,
        "requires_policy": result.requires_policy,
        "booking_intent": result.booking_intent,
    }


@app.post("/upload-data")
async def upload_data(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    destination = upload_dir / f"{int(time.time())}_{safe_name}"

    with destination.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    indexed = rag_engine.ingest_csv(destination)
    return {
        "message": "Data uploaded and indexed",
        "file": destination.name,
        "documents_indexed": indexed,
    }
